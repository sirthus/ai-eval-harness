"""Tests for LLM-as-judge scorer. All API calls are mocked — no live API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from harness.llm_judge import LLMJudgeScorer, LLMJudgeScorerError
from harness.schemas import GoldAnnotation, ModelOutput, TestCase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_case(
    title: str = "Test login with valid credentials",
    steps: list[str] | None = None,
    expected_result: str = "User is redirected to dashboard",
    tc_type: str = "positive",
    priority: str = "high",
    preconditions: list[str] | None = None,
) -> TestCase:
    return TestCase(
        title=title,
        preconditions=preconditions or ["Application is running"],
        steps=steps or ["Enter username", "Enter password", "Click Submit"],
        expected_result=expected_result,
        priority=priority,
        type=tc_type,
    )


def _make_output(
    requirement_id: str = "REQ-001",
    test_cases: list[TestCase] | None = None,
) -> ModelOutput:
    return ModelOutput(
        requirement_id=requirement_id,
        test_cases=test_cases or [
            _make_test_case(title="Valid login succeeds"),
            _make_test_case(title="Invalid password is rejected", tc_type="negative"),
        ],
        assumptions=[],
        notes="",
    )


def _make_gold(
    requirement_id: str = "REQ-001",
    coverage_points: list[str] | None = None,
    disallowed: list[str] | None = None,
) -> GoldAnnotation:
    return GoldAnnotation(
        requirement_id=requirement_id,
        required_coverage_points=coverage_points or [
            "valid credentials grant access",
            "invalid credentials are rejected",
        ],
        disallowed_assumptions=disallowed or ["assumes admin bypass route exists"],
        review_notes="",
    )


def _make_valid_verdict(
    coverage_points: list[str] | None = None,
    covered: list[bool] | None = None,
) -> dict:
    points = coverage_points or ["valid credentials grant access", "invalid credentials are rejected"]
    covereds = covered or [True, True]
    return {
        "coverage_assessment": [
            {"point": p, "covered": c, "evidence": "test case title mentions it" if c else ""}
            for p, c in zip(points, covereds)
        ],
        "correctness_score": 2.0,
        "correctness_rationale": "No disallowed assumptions found.",
        "hallucination_risk_score": 2.0,
        "hallucination_risk_rationale": "No invented behaviors detected.",
        "reviewer_usefulness_score": 2.0,
        "reviewer_usefulness_rationale": "Test cases are specific and actionable.",
    }


def _make_scorer(mocker, verdict_dict: dict, tmp_path: Path | None = None) -> LLMJudgeScorer:
    """Create a scorer with mocked Anthropic client returning the given verdict."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(verdict_dict))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    mocker.patch("harness.llm_judge.anthropic.Anthropic", return_value=mock_client)
    mocker.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    return LLMJudgeScorer(sidecar_dir=tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_valid_verdict_parses_successfully(self):
        scorer = LLMJudgeScorer()
        verdict = _make_valid_verdict()
        result = scorer._parse_verdict(json.dumps(verdict), "REQ-001")
        assert result.requirement_id == "REQ-001"
        assert len(result.coverage_assessments) == 2
        assert result.correctness_score == 2.0
        assert result.judge_model == scorer.judge_model
        assert result.judge_prompt_version == scorer.judge_prompt_version

    def test_malformed_json_raises_llm_judge_scorer_error(self):
        scorer = LLMJudgeScorer()
        with pytest.raises(LLMJudgeScorerError, match="not valid JSON"):
            scorer._parse_verdict("this is not json {{{", "REQ-001")

    def test_verdict_missing_required_field_raises_error(self):
        scorer = LLMJudgeScorer()
        incomplete = {"coverage_assessment": [], "correctness_score": 2.0}
        with pytest.raises(LLMJudgeScorerError, match="failed schema validation"):
            scorer._parse_verdict(json.dumps(incomplete), "REQ-001")

    def test_markdown_fences_stripped_before_parsing(self):
        scorer = LLMJudgeScorer()
        verdict = _make_valid_verdict()
        raw = f"```json\n{json.dumps(verdict)}\n```"
        result = scorer._parse_verdict(raw, "REQ-001")
        assert result.requirement_id == "REQ-001"

    def test_markdown_fences_extracted_even_with_leading_prose(self):
        scorer = LLMJudgeScorer()
        verdict = _make_valid_verdict()
        raw = f"Here is the evaluation:\n```json\n{json.dumps(verdict)}\n```"
        result = scorer._parse_verdict(raw, "REQ-001")
        assert result.requirement_id == "REQ-001"

    def test_coverage_assessment_key_remapped(self):
        """coverage_assessment (prompt key) → coverage_assessments (schema field)."""
        scorer = LLMJudgeScorer()
        verdict = _make_valid_verdict()
        assert "coverage_assessment" in verdict
        result = scorer._parse_verdict(json.dumps(verdict), "REQ-001")
        assert len(result.coverage_assessments) == 2


class TestBuildJudgePrompt:
    def test_judge_prompt_contains_coverage_points(self):
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold(coverage_points=["valid credentials grant access", "invalid credentials are rejected"])
        prompt = scorer._build_judge_prompt(output, gold)
        assert "valid credentials grant access" in prompt
        assert "invalid credentials are rejected" in prompt

    def test_judge_prompt_does_not_contain_raw_requirement_text(self):
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold()
        prompt = scorer._build_judge_prompt(output, gold)
        # The prompt contains the requirement_id but NOT a separate requirement_text field
        assert "REQ-001" in prompt
        # Verify the generated output (JSON) is embedded, not a hypothetical requirement description
        assert '"requirement_id"' in prompt  # from the generated JSON
        assert "requirement_text" not in prompt  # raw requirement is NOT included

    def test_judge_prompt_contains_disallowed_assumptions(self):
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold(disallowed=["assumes admin bypass route exists"])
        prompt = scorer._build_judge_prompt(output, gold)
        assert "assumes admin bypass route exists" in prompt

    def test_judge_prompt_contains_generated_output(self):
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold()
        prompt = scorer._build_judge_prompt(output, gold)
        assert "Valid login succeeds" in prompt  # test case title from the output


class TestScore:
    def test_valid_verdict_produces_correct_scored_result(self, mocker):
        verdict = _make_valid_verdict(covered=[True, True])
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert result.requirement_id == "REQ-001"
        assert result.scores.correctness == 2.0
        assert result.scores.hallucination_risk == 2.0
        assert result.scores.reviewer_usefulness == 2.0
        assert result.coverage_ratio == 1.0
        assert result.scores.completeness == 2.0  # 100% coverage → 2.0

    def test_partial_coverage_drives_completeness_score(self, mocker):
        """One of two coverage points covered → coverage_ratio=0.5 → completeness=1.0."""
        verdict = _make_valid_verdict(covered=[True, False])
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert result.coverage_ratio == 0.5
        assert result.scores.completeness == 1.0

    def test_zero_coverage_drives_fail(self, mocker):
        """No coverage points covered → completeness=0.0 → floor violation → fail."""
        verdict = _make_valid_verdict(covered=[False, False])
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert result.scores.completeness == 0.0
        assert result.decision == "fail"

    def test_api_error_triggers_fallback_to_heuristic(self, mocker):
        """Anthropic APIError causes fallback to heuristic scorer."""
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        api_error = anthropic.APIError("API timeout", request, body=None)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = api_error
        mocker.patch("harness.llm_judge.anthropic.Anthropic", return_value=mock_client)
        mocker.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold()
        # Should not raise — returns a valid ScoredResult from heuristic fallback
        result = scorer.score(output, gold)
        assert result.requirement_id == "REQ-001"

    def test_anthropic_client_is_created_once_per_scorer(self, mocker):
        verdict = _make_valid_verdict()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(verdict))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        anthropic_ctor = mocker.patch(
            "harness.llm_judge.anthropic.Anthropic",
            return_value=mock_client,
        )
        mocker.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold()

        scorer.score(output, gold)
        scorer.score(output, gold)

        assert anthropic_ctor.call_count == 1

    def test_unexpected_internal_error_is_not_swallowed(self, mocker):
        verdict = _make_valid_verdict()
        scorer = _make_scorer(mocker, verdict)
        mocker.patch.object(scorer, "_to_scored_result", side_effect=ValueError("broken mapping"))
        output = _make_output()
        gold = _make_gold()

        with pytest.raises(ValueError, match="broken mapping"):
            scorer.score(output, gold)

    def test_missing_api_key_triggers_fallback(self, mocker):
        """EnvironmentError from missing key causes fallback."""
        mocker.patch.dict("os.environ", {}, clear=True)
        # Remove ANTHROPIC_API_KEY if present
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        scorer = LLMJudgeScorer()
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert result.requirement_id == "REQ-001"

    def test_scored_result_fields_map_from_verdict(self, mocker):
        verdict = _make_valid_verdict()
        verdict["correctness_score"] = 1.0
        verdict["hallucination_risk_score"] = 1.0
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert result.scores.correctness == 1.0
        assert result.scores.hallucination_risk == 1.0

    def test_weighted_score_computed_from_dimensions(self, mocker):
        verdict = _make_valid_verdict()  # all 2.0
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        # All dims 2.0, weights sum to 1.0 → weighted = 2.0
        assert result.weighted_score == 2.0

    def test_sidecar_written_to_disk(self, mocker, tmp_path):
        verdict = _make_valid_verdict()
        scorer = _make_scorer(mocker, verdict, tmp_path=tmp_path)
        output = _make_output()
        gold = _make_gold()
        scorer.score(output, gold)
        sidecar = tmp_path / "REQ-001.judge.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert data["requirement_id"] == "REQ-001"
        assert "coverage_assessments" in data

    def test_no_sidecar_when_sidecar_dir_is_none(self, mocker, tmp_path):
        verdict = _make_valid_verdict()
        scorer = _make_scorer(mocker, verdict, tmp_path=None)
        output = _make_output()
        gold = _make_gold()
        scorer.score(output, gold)
        # Nothing should have been written to tmp_path
        assert list(tmp_path.iterdir()) == []

    def test_scoring_notes_include_judge_rationales(self, mocker):
        verdict = _make_valid_verdict()
        verdict["correctness_rationale"] = "All test cases are correct."
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        gold = _make_gold()
        result = scorer.score(output, gold)
        assert "All test cases are correct." in result.scoring_notes

    # ------------------------------------------------------------------
    # Regression: Bug 3 — judge trusting its own coverage list length
    # ------------------------------------------------------------------

    def test_omitted_coverage_points_count_as_not_covered(self, mocker):
        """Judge returning only 1 of 3 gold points must not inflate ratio to 1/1=100%.

        Before the fix, len(verdict.coverage_assessments) was used as the denominator.
        If the judge only assessed the one point it covered, ratio would be 1/1 = 100%
        instead of 1/3 = 33%.
        """
        gold = _make_gold(coverage_points=[
            "valid credentials grant access",
            "invalid credentials are rejected",
            "account lockout after N failures",
        ])
        # Judge only returns an assessment for the first point
        verdict = {
            "coverage_assessment": [
                {"point": "valid credentials grant access", "covered": True, "evidence": "title"},
                # second and third points are omitted entirely
            ],
            "correctness_score": 2.0,
            "correctness_rationale": "No issues.",
            "hallucination_risk_score": 2.0,
            "hallucination_risk_rationale": "No invented behavior.",
            "reviewer_usefulness_score": 2.0,
            "reviewer_usefulness_rationale": "Actionable.",
        }
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        result = scorer.score(output, gold)
        # 1 covered out of 3 gold points → ratio = 1/3 ≈ 0.33 → completeness = 0.0
        assert abs(result.coverage_ratio - 1 / 3) < 0.01
        assert result.scores.completeness == 0.0

    def test_extra_assessed_points_beyond_gold_are_ignored(self, mocker):
        """Judge assessing points not in gold must not increase covered count."""
        gold = _make_gold(coverage_points=["valid credentials grant access"])
        verdict = {
            "coverage_assessment": [
                {"point": "valid credentials grant access", "covered": True, "evidence": "yes"},
                {"point": "invented point not in gold", "covered": True, "evidence": "yes"},
            ],
            "correctness_score": 2.0,
            "correctness_rationale": "Fine.",
            "hallucination_risk_score": 2.0,
            "hallucination_risk_rationale": "Fine.",
            "reviewer_usefulness_score": 2.0,
            "reviewer_usefulness_rationale": "Fine.",
        }
        scorer = _make_scorer(mocker, verdict)
        output = _make_output()
        result = scorer.score(output, gold)
        # Only 1 gold point; it was covered → ratio = 1/1 = 1.0
        assert result.coverage_ratio == 1.0
