"""LLM-as-judge scorer for evaluation harness.

Replaces heuristic substring matching with a second LLM call that assesses
coverage, correctness, hallucination risk, and reviewer usefulness semantically.

Drop-in replacement for score.score():
    judge = LLMJudgeScorer()
    result = judge.score(output, gold, weights=..., thresholds=..., diagnostics=...)

The judge sees the generated output and gold criteria. It does NOT see the raw
requirement text — this prevents the judge from scoring against its own mental
re-generation of test cases rather than the actual generated output.

A sidecar {requirement_id}.judge.json is written to sidecar_dir when provided.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from harness import score as heuristic_scoring
from harness.model_adapter import (
    _get_anthropic_api_key,
    _split_prompt,
    extract_text_content,
)
from harness.schemas import (
    CoveragePointAssessment,
    DimensionScores,
    GoldAnnotation,
    LLMJudgeVerdict,
    ModelOutput,
    ScoredResult,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class LLMJudgeScorerError(Exception):
    """Raised when the judge model returns a malformed or invalid verdict."""


class LLMJudgeScorer:
    """Score a ModelOutput against GoldAnnotation using a second LLM call.

    Falls back to the heuristic scorer on API failure and logs a warning.
    """

    def __init__(
        self,
        judge_model: str = "claude-sonnet-4-6",
        judge_prompt_version: str = "judge_v1",
        max_tokens: int = 1024,
        sidecar_dir: Path | None = None,
    ) -> None:
        self.judge_model = judge_model
        self.judge_prompt_version = judge_prompt_version
        self.max_tokens = max_tokens
        self.sidecar_dir = sidecar_dir
        self._client: anthropic.Anthropic | None = None

    def score(
        self,
        output: ModelOutput,
        gold: GoldAnnotation,
        weights: dict[str, float] | None = None,
        thresholds: dict[str, Any] | None = None,
        diagnostics: dict[str, bool] | None = None,
    ) -> ScoredResult:
        """Score output against gold using LLM judge. Falls back to heuristic on failure."""
        try:
            prompt = self._build_judge_prompt(output, gold)
            raw = self._call_judge(prompt, output.requirement_id)
            verdict = self._parse_verdict(raw, output.requirement_id)
            result = self._to_scored_result(verdict, output, gold, weights, thresholds, diagnostics)
            if self.sidecar_dir:
                self._write_sidecar(verdict)
            return result
        except (EnvironmentError, anthropic.APIError, LLMJudgeScorerError) as exc:
            logger.warning(
                "LLM judge failed for %s (%s: %s) — falling back to heuristic scorer",
                output.requirement_id,
                type(exc).__name__,
                exc,
            )
            return heuristic_scoring.score(
                output, gold, weights=weights, thresholds=thresholds, diagnostics=diagnostics
            )

    def _get_client(self) -> anthropic.Anthropic:
        """Create and cache the Anthropic client for this scorer instance."""
        if self._client is None:
            api_key = _get_anthropic_api_key()
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _build_judge_prompt(self, output: ModelOutput, gold: GoldAnnotation) -> str:
        """Build judge prompt from template. Does NOT include raw requirement text."""
        template_path = _PROMPTS_DIR / f"{self.judge_prompt_version}.txt"
        template = template_path.read_text(encoding="utf-8")

        coverage_points = "\n".join(
            f"- {point}" for point in gold.required_coverage_points
        ) or "- (none specified)"

        disallowed = "\n".join(
            f"- {assumption}" for assumption in gold.disallowed_assumptions
        ) or "- (none specified)"

        generated_output = json.dumps(output.model_dump(), indent=2)

        # Use explicit replace instead of str.format() — the prompt template
        # contains JSON examples with literal braces that would confuse .format().
        return (
            template
            .replace("{requirement_id}", output.requirement_id)
            .replace("{coverage_points}", coverage_points)
            .replace("{disallowed_assumptions}", disallowed)
            .replace("{generated_output}", generated_output)
        )

    def _call_judge(self, prompt: str, requirement_id: str) -> str:
        """Call judge model API. Raises on API failure (no retry — caller handles fallback)."""
        has_system_marker = "### SYSTEM ###" in prompt
        has_user_marker = "### USER ###" in prompt
        if has_system_marker != has_user_marker:
            raise LLMJudgeScorerError(
                "Judge prompt for "
                f"{requirement_id} must contain both ### SYSTEM ### and ### USER ### markers or neither"
            )

        system_text, user_text = _split_prompt(prompt)
        if has_system_marker and not user_text:
            raise LLMJudgeScorerError(
                f"Judge prompt for {requirement_id} has an empty ### USER ### section"
            )

        client = self._get_client()
        logger.info(
            "LLM judge scoring %s with model %s (prompt %s)",
            requirement_id,
            self.judge_model,
            self.judge_prompt_version,
        )

        create_kwargs: dict = dict(
            model=self.judge_model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": user_text}],
        )
        if system_text:
            create_kwargs["system"] = system_text

        message = client.messages.create(**create_kwargs)
        try:
            return extract_text_content(
                message,
                requirement_id=requirement_id,
                source="Judge response",
            )
        except ValueError as exc:
            raise LLMJudgeScorerError(str(exc)) from exc

    def _parse_verdict(self, raw: str, requirement_id: str) -> LLMJudgeVerdict:
        """Parse judge JSON verdict. Raises LLMJudgeScorerError on malformed output."""
        text = raw
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMJudgeScorerError(
                f"Judge output for {requirement_id} is not valid JSON: {exc}"
            ) from exc

        # Remap the key from the prompt schema ("coverage_assessment") to the
        # LLMJudgeVerdict field name ("coverage_assessments").
        if "coverage_assessment" in data and "coverage_assessments" not in data:
            data["coverage_assessments"] = data.pop("coverage_assessment")

        try:
            verdict = LLMJudgeVerdict.model_validate({
                **data,
                "requirement_id": requirement_id,
                "judge_model": self.judge_model,
                "judge_prompt_version": self.judge_prompt_version,
            })
        except ValidationError as exc:
            raise LLMJudgeScorerError(
                f"Judge verdict for {requirement_id} failed schema validation: {exc}"
            ) from exc

        return verdict

    def _to_scored_result(
        self,
        verdict: LLMJudgeVerdict,
        output: ModelOutput,
        gold: GoldAnnotation,
        weights: dict[str, float] | None,
        thresholds: dict[str, Any] | None,
        diagnostics: dict[str, bool] | None,
    ) -> ScoredResult:
        """Map LLMJudgeVerdict to ScoredResult using existing scoring framework."""
        w = weights or heuristic_scoring._DEFAULT_WEIGHTS
        t = thresholds or heuristic_scoring._DEFAULT_THRESHOLDS
        diag_cfg = diagnostics or heuristic_scoring._DEFAULT_DIAGNOSTICS

        # Completeness derived from gold's required_coverage_points as the authoritative
        # denominator. The judge may return fewer assessments than there are gold points
        # (e.g., if it omits uncovered points), so counting only assessed points would
        # inflate the ratio. Unassessed gold points count as not covered.
        total_points = len(gold.required_coverage_points)
        assessed_covered = {a.point: a.covered for a in verdict.coverage_assessments}
        covered_count = sum(
            1 for point in gold.required_coverage_points
            if assessed_covered.get(point, False)
        )
        coverage_ratio = covered_count / total_points if total_points else 1.0
        completeness = heuristic_scoring.score_completeness(coverage_ratio)

        dims = DimensionScores(
            correctness=verdict.correctness_score,
            completeness=completeness,
            hallucination_risk=verdict.hallucination_risk_score,
            reviewer_usefulness=verdict.reviewer_usefulness_score,
        )

        weighted = (
            dims.correctness * w["correctness"]
            + dims.completeness * w["completeness"]
            + dims.hallucination_risk * w["hallucination_risk"]
            + dims.reviewer_usefulness * w["reviewer_usefulness"]
        )

        floor = t.get("floor", {})
        floor_violations = [
            dim for dim, minimum in floor.items() if getattr(dims, dim) < minimum
        ]

        if floor_violations:
            decision = "fail"
            scoring_notes = f"Floor violation(s): {', '.join(floor_violations)}"
        elif weighted >= t["pass"]:
            decision = "pass"
            scoring_notes = ""
        elif weighted >= t["borderline_low"]:
            decision = "borderline"
            scoring_notes = ""
        else:
            decision = "fail"
            scoring_notes = ""

        judge_notes = (
            f"Judge: correctness={verdict.correctness_score:.1f} ({verdict.correctness_rationale}); "
            f"hallucination={verdict.hallucination_risk_score:.1f} ({verdict.hallucination_risk_rationale}); "
            f"usefulness={verdict.reviewer_usefulness_score:.1f} ({verdict.reviewer_usefulness_rationale}); "
            f"coverage {covered_count}/{total_points} points."
        )
        if scoring_notes:
            scoring_notes = f"{scoring_notes}; {judge_notes}"
        else:
            scoring_notes = judge_notes

        # Disallowed hits: re-compute heuristically for audit consistency in reports
        disallowed_hits = heuristic_scoring._disallowed_hits(output, gold)
        diagnostic_notes = heuristic_scoring._compute_diagnostics(output, diag_cfg)

        return ScoredResult(
            requirement_id=output.requirement_id,
            scores=dims,
            weighted_score=round(weighted, 4),
            decision=decision,
            coverage_ratio=round(coverage_ratio, 4),
            disallowed_hits=disallowed_hits,
            scoring_notes=scoring_notes,
            diagnostic_notes=diagnostic_notes,
        )

    def _write_sidecar(self, verdict: LLMJudgeVerdict) -> None:
        """Write audit sidecar JSON next to the generated output."""
        if self.sidecar_dir is None:
            return
        sidecar_dir = Path(self.sidecar_dir)
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        sidecar_path = sidecar_dir / f"{verdict.requirement_id}.judge.json"
        sidecar_path.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
        logger.debug("Judge verdict sidecar written: %s", sidecar_path)
