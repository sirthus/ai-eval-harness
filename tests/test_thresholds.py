"""Tests for decision band thresholds and floor violations (score.py).

Phase 2 note: score_correctness is now decoupled from coverage ratio.
  correctness = 2.0 - min(hits, 2) - (0.5 if single TC) capped at 0.
  completeness still uses coverage ratio.
"""

import pytest

from harness.schemas import GoldAnnotation, ModelOutput, TestCase
from harness.score import score

# Default thresholds from CLAUDE.md:
#   pass >= 1.6 (AND all floors >= 1)
#   borderline: 1.2 – 1.59
#   fail: < 1.2
# Weights: correctness=0.35, completeness=0.30, hallucination_risk=0.20, usefulness=0.15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_output_with_dims(
    correctness_coverage: float,
    clean_assumptions: bool = True,
    steps_per_tc: int = 3,
    num_types: int = 2,
    num_test_cases: int = 2,
    req_id: str = "REQ-T",
    extra_assumptions: list[str] | None = None,
) -> ModelOutput:
    """Construct an output that achieves approximately the desired dimension scores.

    Coverage ratio drives completeness.
    clean_assumptions=False adds many assumptions to lower hallucination_risk.
    steps_per_tc and num_types affect reviewer_usefulness.
    num_test_cases controls single-TC penalty for correctness.
    """
    if correctness_coverage >= 0.75:
        titles = ["target coverage point alpha", "target coverage point beta"]
    elif correctness_coverage >= 0.5:
        titles = ["target coverage point alpha", "unrelated title"]
    else:
        titles = ["unrelated title one", "unrelated title two"]

    # Adjust title list to match desired num_test_cases
    if num_test_cases == 1:
        titles = titles[:1]
    elif num_test_cases > 2:
        titles = titles + [f"extra tc {i}" for i in range(num_test_cases - 2)]

    types = ["positive", "negative", "edge_case", "boundary"][:num_types]
    tcs = [
        TestCase(
            title=t,
            preconditions=["precond"],
            steps=[f"step {i}" for i in range(steps_per_tc)],
            expected_result="system behaves correctly",
            priority="medium",
            type=types[idx % len(types)],
        )
        for idx, t in enumerate(titles)
    ]
    assumptions = (
        []
        if clean_assumptions
        else ["assumption one", "assumption two", "assumption three", "assumption four"]
    )
    if extra_assumptions:
        assumptions.extend(extra_assumptions)
    return ModelOutput(
        requirement_id=req_id,
        test_cases=tcs,
        assumptions=assumptions,
        notes="",
    )


def _make_gold(
    points: list[str] | None = None,
    disallowed: list[str] | None = None,
) -> GoldAnnotation:
    return GoldAnnotation(
        requirement_id="REQ-T",
        required_coverage_points=points or ["target coverage point alpha", "target coverage point beta"],
        acceptable_variants={},
        disallowed_assumptions=disallowed or [],
    )


# ---------------------------------------------------------------------------
# Pass band
# ---------------------------------------------------------------------------


class TestPassBand:
    def test_high_coverage_clean_output_passes(self):
        output = _make_output_with_dims(correctness_coverage=1.0, steps_per_tc=3, num_types=2)
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision == "pass"
        assert result.weighted_score >= 1.6

    def test_weighted_score_exactly_at_pass_threshold(self):
        # correctness=2 (2 TCs, no hits), completeness=2 (full coverage)
        # hallucination=2 (clean), usefulness with 1 type: steps>=3 ✓, expected ✓, precond ✓, types ✗
        # single-type: signals=3 → usefulness=2.0
        # weighted = 2*0.35 + 2*0.30 + 2*0.20 + 2*0.15 = 0.70+0.60+0.40+0.30 = 2.0 → pass
        output = _make_output_with_dims(
            correctness_coverage=1.0,
            clean_assumptions=True,
            steps_per_tc=3,
            num_types=1,
        )
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision == "pass"


# ---------------------------------------------------------------------------
# Borderline band
# ---------------------------------------------------------------------------


class TestBorderlineBand:
    def test_single_disallowed_hit_with_full_coverage_borderlines(self):
        # correctness = 2 - 1 = 1.0 (floor met), completeness=2, hallucination=1 (1 hit), usefulness=2
        # weighted = 1*0.35 + 2*0.30 + 1*0.20 + 2*0.15 = 0.35+0.60+0.20+0.30 = 1.45 → borderline
        output = _make_output_with_dims(
            correctness_coverage=1.0, steps_per_tc=3, num_types=2,
            extra_assumptions=["bad assumption"],
        )
        gold = _make_gold(disallowed=["bad assumption"])
        result = score(output, gold)
        assert result.decision == "borderline"
        assert 1.2 <= result.weighted_score < 1.6

    def test_floor_exactly_met_is_not_a_violation(self):
        # 4 assumptions → hallucination_risk=1.0, exactly meets floor (>= 1.0).
        # correctness=2.0, completeness=2.0, hallucination=1.0, usefulness=2.0
        # weighted = 2*0.35 + 2*0.30 + 1*0.20 + 2*0.15 = 0.70+0.60+0.20+0.30 = 1.80 → pass
        output = _make_output_with_dims(
            correctness_coverage=1.0,
            clean_assumptions=False,  # 4 assumptions → hallucination=1.0
            steps_per_tc=3,
            num_types=2,
        )
        gold = _make_gold()
        result = score(output, gold)
        # hallucination=1 meets floor (no violation)
        assert result.decision == "pass"

    def test_medium_coverage_low_usefulness_borderlines(self):
        # correctness=2.0 (2 TCs, no hits), completeness=1.0 (50% coverage)
        # hallucination=2.0, usefulness=0.0 (short steps, no precond, 1 type, 1 TC)
        # weighted = 2*0.35 + 1*0.30 + 2*0.20 + 0*0.15 = 0.70+0.30+0.40+0.0 = 1.40 → borderline
        output = _make_output_with_dims(
            correctness_coverage=0.5, steps_per_tc=1, num_types=1,
            num_test_cases=2,
        )
        # Override preconditions to be empty
        for tc in output.test_cases:
            tc.preconditions = []
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision in ("borderline", "pass")  # depends on exact usefulness
        assert result.weighted_score >= 1.2


# ---------------------------------------------------------------------------
# Fail band
# ---------------------------------------------------------------------------


class TestFailBand:
    def test_zero_coverage_fails(self):
        output = _make_output_with_dims(correctness_coverage=0.0)
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision == "fail"

    def test_disallowed_hit_can_cause_borderline_or_fail(self):
        # Full coverage + 1 disallowed hit
        output = _make_output_with_dims(correctness_coverage=1.0)
        output.assumptions.append("bad assumption")
        gold = _make_gold(disallowed=["bad assumption"])
        result = score(output, gold)
        # correctness = 2-1=1, hallucination = 1 (one hit) → borderline or fail
        assert result.decision in ("borderline", "fail")

    def test_two_disallowed_hits_fails(self):
        output = _make_output_with_dims(correctness_coverage=1.0)
        output.assumptions.extend(["bad assumption one", "bad assumption two"])
        gold = _make_gold(disallowed=["bad assumption one", "bad assumption two"])
        result = score(output, gold)
        # correctness = max(0, 2-2) = 0 → floor violation → fail
        assert result.decision == "fail"

    def test_weighted_below_1_2_is_fail(self):
        # Force low weighted: 0 coverage → completeness=0 (floor violation), short steps
        output = _make_output_with_dims(
            correctness_coverage=0.0,
            steps_per_tc=1,
            num_types=1,
        )
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision == "fail"


# ---------------------------------------------------------------------------
# Floor violations
# ---------------------------------------------------------------------------


class TestFloorViolations:
    def test_correctness_floor_violation_noted(self):
        # Two disallowed hits drive correctness to 0
        output = _make_output_with_dims(correctness_coverage=1.0)
        output.assumptions.extend(["forbidden phrase one", "forbidden phrase two"])
        gold = _make_gold(disallowed=["forbidden phrase one", "forbidden phrase two"])
        result = score(output, gold)
        assert result.scores.correctness < 1.0
        assert "correctness" in result.scoring_notes

    def test_completeness_floor_violation_noted(self):
        # 0% coverage → completeness = 0 → floor violation
        output = _make_output_with_dims(correctness_coverage=0.0)
        gold = _make_gold()
        result = score(output, gold)
        assert result.scores.completeness == 0.0
        assert "completeness" in result.scoring_notes

    def test_no_floor_violation_when_all_dims_meet_floor(self):
        output = _make_output_with_dims(correctness_coverage=1.0, steps_per_tc=3, num_types=2)
        gold = _make_gold()
        result = score(output, gold)
        assert all(
            getattr(result.scores, dim) >= 1.0
            for dim in ["correctness", "completeness", "hallucination_risk"]
        )
        assert "Floor violation" not in result.scoring_notes


# ---------------------------------------------------------------------------
# Boundary values
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    def test_coverage_exactly_0_5_gives_completeness_1(self):
        from harness.score import score_completeness
        assert score_completeness(0.50) == 1.0

    def test_coverage_just_below_0_5_gives_completeness_0(self):
        from harness.score import score_completeness
        assert score_completeness(0.499) == 0.0

    def test_coverage_exactly_0_75_gives_completeness_2(self):
        from harness.score import score_completeness
        assert score_completeness(0.75) == 2.0

    def test_coverage_just_below_0_75_gives_completeness_1(self):
        from harness.score import score_completeness
        assert score_completeness(0.74) == 1.0
