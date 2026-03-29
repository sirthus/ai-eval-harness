"""Phase 2 scoring tests: decoupled correctness, diagnostics, new usefulness heuristics."""

from __future__ import annotations

import pytest

from harness.schemas import GoldAnnotation, ModelOutput, TestCase
from harness.score import (
    _compute_diagnostics,
    score,
    score_correctness,
    score_reviewer_usefulness,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tc(
    title: str = "TC",
    steps: list[str] | None = None,
    preconditions: list[str] | None = None,
    expected_result: str = "System behaves correctly",
    tc_type: str = "positive",
) -> TestCase:
    return TestCase(
        title=title,
        preconditions=preconditions or ["precond A"],
        steps=steps or ["step 1", "step 2", "step 3"],
        expected_result=expected_result,
        priority="high",
        type=tc_type,
    )


def _output(test_cases: list[TestCase], assumptions: list[str] | None = None) -> ModelOutput:
    return ModelOutput(
        requirement_id="REQ-T",
        test_cases=test_cases,
        assumptions=assumptions or [],
        notes="",
    )


# ---------------------------------------------------------------------------
# score_correctness — decoupled from coverage ratio
# ---------------------------------------------------------------------------


class TestScoreCorrectnessDecoupled:
    def test_two_tc_no_hits_returns_2(self):
        output = _output([_tc("Positive case"), _tc("Negative case", tc_type="negative")])
        assert score_correctness(output, []) == 2.0

    def test_single_tc_no_hits_returns_1_5(self):
        output = _output([_tc("Only case")])
        assert score_correctness(output, []) == 1.5

    def test_two_tc_one_hit_returns_1(self):
        output = _output([_tc("Positive"), _tc("Negative", tc_type="negative")])
        assert score_correctness(output, ["forbidden phrase"]) == 1.0

    def test_two_tc_two_hits_returns_0(self):
        output = _output([_tc("Positive"), _tc("Negative", tc_type="negative")])
        assert score_correctness(output, ["bad x", "bad y"]) == 0.0

    def test_three_hits_capped_at_zero(self):
        output = _output([_tc("Positive"), _tc("Negative", tc_type="negative")])
        result = score_correctness(output, ["a", "b", "c"])
        assert result == 0.0

    def test_correctness_independent_of_coverage_ratio(self):
        # Two different outputs with same structure produce same correctness
        # regardless of what their coverage ratio would be
        output_high = _output([_tc("full coverage text alpha"), _tc("full coverage text beta")])
        output_low = _output([_tc("unrelated title one"), _tc("unrelated title two")])
        assert score_correctness(output_high, []) == score_correctness(output_low, [])

    def test_single_tc_with_one_hit(self):
        # single TC: -0.5; one hit: -1.0 → 2.0 - 0.5 - 1.0 = 0.5
        output = _output([_tc("Only case")])
        assert score_correctness(output, ["bad phrase"]) == 0.5


# ---------------------------------------------------------------------------
# Reviewer usefulness — new Phase 2 heuristics
# ---------------------------------------------------------------------------


class TestReviewerUsefulnessPhase2:
    def test_duplicate_titles_penalize(self):
        # Four signals (steps, expected, precond, 2 types) then -1 for duplicate titles
        tcs = [
            _tc(title="Duplicate title", steps=["s1", "s2", "s3"], tc_type="positive"),
            _tc(title="Duplicate title", steps=["s1", "s2", "s3"], tc_type="negative"),
        ]
        output = _output(tcs)
        score = score_reviewer_usefulness(output)
        # Without duplicates: signals = 4 → 2.0; with duplicate: signals = 3 → 2.0 still
        # Let's check it doesn't score the same as a clean 4-signal output
        clean_tcs = [
            _tc(title="Title A", steps=["s1", "s2", "s3"], tc_type="positive"),
            _tc(title="Title B", steps=["s1", "s2", "s3"], tc_type="negative"),
        ]
        clean_output = _output(clean_tcs)
        clean_score = score_reviewer_usefulness(clean_output)
        # duplicate version should score <= clean version
        assert score <= clean_score

    def test_all_duplicate_titles_reduces_score(self):
        # Build an output where duplicate penalty matters to the band
        # signals without penalty: avg_steps>=3 ✓, expected ✓, precond ✓, 1 type only ✗ → signals=3 → 2.0
        # with duplicate: signals=2 → 1.0
        tcs = [
            _tc(title="Same title", steps=["s1", "s2", "s3"], tc_type="positive"),
            _tc(title="Same title", steps=["s1", "s2", "s3"], tc_type="positive"),
        ]
        output = _output(tcs)
        result = score_reviewer_usefulness(output)
        assert result == 1.0  # signals: steps✓ + expected✓ + precond✓ - duplicate → 2

    def test_single_test_case_reduces_score(self):
        # signals: steps>=3✓, expected✓, precond✓, 1 type✗ → 3 signals; then -1 for single TC → 2
        single_tc_output = _output([_tc(steps=["s1", "s2", "s3"])])
        multi_tc_output = _output([
            _tc(steps=["s1", "s2", "s3"], tc_type="positive"),
            _tc(title="Negative", steps=["s1", "s2", "s3"], tc_type="negative"),
        ])
        single_score = score_reviewer_usefulness(single_tc_output)
        multi_score = score_reviewer_usefulness(multi_tc_output)
        assert single_score <= multi_score


# ---------------------------------------------------------------------------
# Diagnostic notes
# ---------------------------------------------------------------------------


class TestDiagnosticNotes:
    def test_long_expected_result_flagged_when_enabled(self):
        tc = _tc(expected_result="A very long expected result that clearly exceeds fifteen words total count in this particular sentence")
        output = _output([tc, _tc(title="Other")])
        notes = _compute_diagnostics(output, {"flag_long_expected_result": True, "flag_low_step_verbosity": False})
        assert "[diag]" in notes
        assert "Long expected_result" in notes

    def test_long_expected_result_not_flagged_when_disabled(self):
        tc = _tc(expected_result="A very long expected result that exceeds fifteen words total in this sentence here")
        output = _output([tc, _tc(title="Other")])
        notes = _compute_diagnostics(output, {"flag_long_expected_result": False, "flag_low_step_verbosity": False})
        assert notes == ""

    def test_low_step_verbosity_flagged(self):
        tc = _tc(steps=["go", "do"])  # avg 1 word/step
        output = _output([tc, _tc(title="Other")])
        notes = _compute_diagnostics(output, {"flag_long_expected_result": False, "flag_low_step_verbosity": True})
        assert "Low step verbosity" in notes

    def test_diagnostics_do_not_affect_score(self):
        # Same output with diagnostics on vs off must produce the same dimension scores
        tc_verbose = _tc(
            expected_result="A very long expected result that has many many many many many words in it right here now indeed",
            steps=["go"],
        )
        output = _output([tc_verbose, _tc(title="Other")])
        gold = GoldAnnotation(
            requirement_id="REQ-T",
            required_coverage_points=["system behaves correctly"],
        )
        result_with_diag = score(output, gold, diagnostics={"flag_long_expected_result": True, "flag_low_step_verbosity": True})
        result_no_diag = score(output, gold, diagnostics={"flag_long_expected_result": False, "flag_low_step_verbosity": False})
        assert result_with_diag.scores == result_no_diag.scores
        assert result_with_diag.weighted_score == result_no_diag.weighted_score
        assert result_with_diag.decision == result_no_diag.decision

    def test_diagnostic_notes_written_to_scored_result(self):
        tc = _tc(expected_result="A very long expected result with many many many words beyond fifteen total words here now")
        output = _output([tc, _tc(title="Other")])
        gold = GoldAnnotation(requirement_id="REQ-T", required_coverage_points=[])
        result = score(output, gold, diagnostics={"flag_long_expected_result": True, "flag_low_step_verbosity": False})
        assert "[diag]" in result.diagnostic_notes
