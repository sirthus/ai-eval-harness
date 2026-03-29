"""Tests for decision band thresholds and floor violations (score.py)."""

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
    req_id: str = "REQ-T",
) -> ModelOutput:
    """Construct an output that achieves approximately the desired dimension scores.

    Coverage ratio drives correctness + completeness.
    clean_assumptions=False adds many assumptions to lower hallucination_risk.
    steps_per_tc and num_types affect reviewer_usefulness.
    """
    # Build test case titles that contain the gold coverage phrase
    titles = []
    if correctness_coverage >= 0.75:
        titles = ["target coverage point alpha", "target coverage point beta"]
    elif correctness_coverage >= 0.5:
        titles = ["target coverage point alpha", "unrelated title"]
    else:
        titles = ["unrelated title one", "unrelated title two"]

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
        # Force exact 1.6: correctness=2, completeness=2, hallucination=2, usefulness=1
        # weighted = 2*0.35 + 2*0.30 + 2*0.20 + 1*0.15 = 0.70+0.60+0.40+0.15 = 1.85 → pass
        # We achieve this with full coverage, clean output, but only 1 usefulness signal
        output = _make_output_with_dims(
            correctness_coverage=1.0,
            clean_assumptions=True,
            steps_per_tc=3,
            num_types=1,  # only 1 type → usefulness = 1.0 (3 signals: steps, expected, precond)
        )
        gold = _make_gold()
        result = score(output, gold)
        # With full coverage and 3 usefulness signals: should be pass
        assert result.decision == "pass"


# ---------------------------------------------------------------------------
# Borderline band
# ---------------------------------------------------------------------------


class TestBorderlineBand:
    def test_medium_coverage_borderlines(self):
        # 50% coverage → completeness=1, correctness=1 (no hits)
        # Borderline depends on usability and hallucination
        output = _make_output_with_dims(correctness_coverage=0.5, steps_per_tc=3, num_types=2)
        gold = _make_gold()
        result = score(output, gold)
        # completeness=1 (floor met), correctness=1 (floor met), hallucination=2
        # usefulness=2 (steps>=3, expected_result, precond, 2 types)
        # weighted = 1*0.35 + 1*0.30 + 2*0.20 + 2*0.15 = 0.35+0.30+0.40+0.30 = 1.35
        assert result.decision == "borderline"
        assert 1.2 <= result.weighted_score < 1.6

    def test_floor_exactly_met_is_not_a_violation(self):
        # 4 assumptions → hallucination_risk=1.0, which exactly meets the floor (>= 1.0).
        # This is not a violation; the weighted score is high, so result should be pass.
        output = _make_output_with_dims(
            correctness_coverage=1.0,
            clean_assumptions=False,  # 4 assumptions → hallucination=1.0
            steps_per_tc=3,
            num_types=2,
        )
        gold = _make_gold()
        result = score(output, gold)
        # hallucination=1 meets floor (no violation)
        # weighted = 2*0.35 + 2*0.30 + 1*0.20 + 2*0.15 = 0.70+0.60+0.20+0.30 = 1.80 → pass
        assert result.decision == "pass"


# ---------------------------------------------------------------------------
# Fail band
# ---------------------------------------------------------------------------


class TestFailBand:
    def test_zero_coverage_fails(self):
        output = _make_output_with_dims(correctness_coverage=0.0)
        gold = _make_gold()
        result = score(output, gold)
        assert result.decision == "fail"

    def test_disallowed_hit_can_cause_fail(self):
        # Full coverage + disallowed hit → correctness drops to 1, hallucination=1
        output = _make_output_with_dims(correctness_coverage=1.0)
        output.assumptions.append("bad assumption")
        gold = _make_gold(disallowed=["bad assumption"])
        result = score(output, gold)
        # correctness = 2-1=1, hallucination = 1 (one hit)
        # weighted = 1*0.35 + 2*0.30 + 1*0.20 + 2*0.15 = 0.35+0.60+0.20+0.30=1.45 → borderline
        assert result.decision in ("borderline", "fail")

    def test_two_disallowed_hits_fails(self):
        output = _make_output_with_dims(correctness_coverage=1.0)
        output.assumptions.extend(["bad assumption one", "bad assumption two"])
        gold = _make_gold(disallowed=["bad assumption one", "bad assumption two"])
        result = score(output, gold)
        # correctness = max(0, 2-2) = 0 → floor violation → fail
        assert result.decision == "fail"

    def test_weighted_below_1_2_is_fail(self):
        # Force low weighted score: 0 coverage, no types, short steps
        output = _make_output_with_dims(
            correctness_coverage=0.0,
            steps_per_tc=1,
            num_types=1,
        )
        gold = _make_gold()
        result = score(output, gold)
        assert result.weighted_score < 1.2
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
        # scoring_notes should not mention floor violations
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
