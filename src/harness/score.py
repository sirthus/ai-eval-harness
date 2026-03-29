"""Scoring logic for evaluated model outputs.

Dimensions (0–2 scale each):
  correctness        weight 0.35
  completeness       weight 0.30
  hallucination_risk weight 0.20
  reviewer_usefulness weight 0.15

Decision bands (configurable via thresholds dict):
  pass:        weighted >= 1.6  AND no floor violations
  borderline:  weighted 1.2–1.59 AND no floor violations
  fail:        weighted < 1.2 OR any floor dimension < its minimum (floor always fails)
"""

from __future__ import annotations

import re
from typing import Any

from harness.schemas import (
    DimensionScores,
    GoldAnnotation,
    ModelOutput,
    ScoredResult,
)

_DEFAULT_WEIGHTS: dict[str, float] = {
    "correctness": 0.35,
    "completeness": 0.30,
    "hallucination_risk": 0.20,
    "reviewer_usefulness": 0.15,
}
_DEFAULT_THRESHOLDS = {
    "pass": 1.6,
    "borderline_low": 1.2,
    "floor": {
        "correctness": 1.0,
        "completeness": 1.0,
        "hallucination_risk": 1.0,
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _full_text(output: ModelOutput) -> str:
    """Concatenate all text in a ModelOutput for keyword matching."""
    parts: list[str] = []
    for tc in output.test_cases:
        parts.append(tc.title)
        parts.extend(tc.preconditions)
        parts.extend(tc.steps)
        parts.append(tc.expected_result)
    parts.extend(output.assumptions)
    parts.append(output.notes)
    return " ".join(parts).lower()


def _keyword_match(phrase: str, text: str) -> bool:
    """Return True if every word in `phrase` appears in `text`."""
    words = re.findall(r"\w+", phrase.lower())
    return all(word in text for word in words) if words else False


def _coverage_ratio(output: ModelOutput, gold: GoldAnnotation) -> float:
    """Fraction of required coverage points matched.

    A point is matched if its primary phrase appears in the output text OR if
    any of its acceptable_variants (keyed to that specific point) appears.
    Variants only credit the point they are bound to — they cannot substitute
    for an arbitrary uncovered point.
    """
    text = _full_text(output)
    matched = 0
    for point in gold.required_coverage_points:
        if _keyword_match(point, text):
            matched += 1
            continue
        variants = gold.acceptable_variants.get(point, [])
        if any(_keyword_match(v, text) for v in variants):
            matched += 1
    total = len(gold.required_coverage_points)
    return matched / total if total else 1.0


def _phrase_match(phrase: str, text: str) -> bool:
    """Return True if `phrase` appears as a literal substring in `text`.

    Uses exact substring matching rather than bag-of-words so that negated
    sentences ("account is NOT locked permanently") do not trigger a match
    against the disallowed phrase ("account locked permanently").
    Coverage-point matching uses the looser _keyword_match because it is
    checking for concept presence, not verbatim violations.
    """
    return phrase.lower() in text


def _disallowed_hits(output: ModelOutput, gold: GoldAnnotation) -> list[str]:
    """Return disallowed assumption phrases found verbatim in model output.

    Uses exact substring matching to avoid false positives when the model
    correctly negates a disallowed assumption (e.g. "must NOT be locked").
    """
    text = _full_text(output)
    return [d for d in gold.disallowed_assumptions if _phrase_match(d, text)]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def score_completeness(ratio: float) -> float:
    if ratio >= 0.75:
        return 2.0
    if ratio >= 0.5:
        return 1.0
    return 0.0


def score_correctness(ratio: float, hits: list[str]) -> float:
    """Completeness-based with penalty for disallowed assumptions."""
    base = score_completeness(ratio)
    penalty = min(len(hits), 2)  # cap penalty at 2
    return max(0.0, base - penalty)


def score_hallucination_risk(output: ModelOutput, hits: list[str]) -> float:
    """Check model's assumptions field and disallowed hits."""
    if hits:
        # Substantial if many hits, minor if one
        return 0.0 if len(hits) >= 2 else 1.0

    # Check for suspiciously large assumptions list (>3 items = noisy)
    if len(output.assumptions) > 3:
        return 1.0
    return 2.0


def score_reviewer_usefulness(output: ModelOutput) -> float:
    """Heuristic based on structural quality signals."""
    signals = 0

    if output.test_cases:
        avg_steps = sum(len(tc.steps) for tc in output.test_cases) / len(
            output.test_cases
        )
        if avg_steps >= 3:
            signals += 1

        if all(tc.expected_result.strip() for tc in output.test_cases):
            signals += 1

        if all(tc.preconditions for tc in output.test_cases):
            signals += 1

        types_used = {tc.type for tc in output.test_cases}
        if len(types_used) >= 2:
            signals += 1

    if signals >= 3:
        return 2.0
    if signals >= 2:
        return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def score(
    output: ModelOutput,
    gold: GoldAnnotation,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> ScoredResult:
    w = weights or _DEFAULT_WEIGHTS
    t = thresholds or _DEFAULT_THRESHOLDS

    ratio = _coverage_ratio(output, gold)
    hits = _disallowed_hits(output, gold)

    completeness = score_completeness(ratio)
    correctness = score_correctness(ratio, hits)
    hallucination_risk = score_hallucination_risk(output, hits)
    reviewer_usefulness = score_reviewer_usefulness(output)

    dims = DimensionScores(
        correctness=correctness,
        completeness=completeness,
        hallucination_risk=hallucination_risk,
        reviewer_usefulness=reviewer_usefulness,
    )

    weighted = (
        correctness * w["correctness"]
        + completeness * w["completeness"]
        + hallucination_risk * w["hallucination_risk"]
        + reviewer_usefulness * w["reviewer_usefulness"]
    )

    floor = t.get("floor", {})
    floor_violations = [
        dim
        for dim, minimum in floor.items()
        if getattr(dims, dim) < minimum
    ]

    if floor_violations:
        # Any floor violation is an unconditional fail regardless of weighted score.
        decision = "fail"
        notes = f"Floor violation(s): {', '.join(floor_violations)}"
    elif weighted >= t["pass"]:
        decision = "pass"
        notes = ""
    elif weighted >= t["borderline_low"]:
        decision = "borderline"
        notes = ""
    else:
        decision = "fail"
        notes = ""

    if hits:
        hit_note = f"Disallowed assumption(s) found: {hits}"
        notes = f"{notes}; {hit_note}".strip("; ")

    return ScoredResult(
        requirement_id=output.requirement_id,
        scores=dims,
        weighted_score=round(weighted, 4),
        decision=decision,
        coverage_ratio=round(ratio, 4),
        disallowed_hits=hits,
        scoring_notes=notes,
    )
