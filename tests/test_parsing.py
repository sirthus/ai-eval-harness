"""Tests for schema validation (schemas.py) and model output parsing (model_adapter.py)."""

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from harness.model_adapter import _parse_output, split_prompt
from harness.schemas import (
    GoldAnnotation,
    ModelOutput,
    Requirement,
    TestCase,
)

# ---------------------------------------------------------------------------
# _split_prompt (from model_adapter)
# ---------------------------------------------------------------------------


class TestSplitPrompt:
    def test_splits_system_and_user_sections(self):
        template = "### SYSTEM ###\nYou are an assistant.\n### USER ###\nHello {name}."
        system, user = split_prompt(template)
        assert system == "You are an assistant."
        assert user == "Hello {name}."

    def test_no_markers_returns_flat_as_user(self):
        template = "Just a flat prompt with {placeholder}."
        system, user = split_prompt(template)
        assert system == ""
        assert user == template

    def test_marker_lines_stripped_from_output(self):
        template = "### SYSTEM ###\nsystem content\n### USER ###\nuser content"
        system, user = split_prompt(template)
        assert "### SYSTEM ###" not in system
        assert "### USER ###" not in user
        assert "### SYSTEM ###" not in user

    def test_multiline_sections_preserved(self):
        template = "### SYSTEM ###\nLine one.\nLine two.\n### USER ###\nReq: {req}\nText: {text}"
        system, user = split_prompt(template)
        assert "Line one." in system
        assert "Line two." in system
        assert "Req: {req}" in user


# ---------------------------------------------------------------------------
# TestCase validation
# ---------------------------------------------------------------------------


class TestTestCaseSchema:
    def test_valid_test_case(self):
        tc = TestCase(
            title="Login succeeds",
            preconditions=["User exists"],
            steps=["Open login page", "Submit credentials"],
            expected_result="User is redirected to dashboard",
            priority="high",
            type="positive",
        )
        assert tc.priority == "high"
        assert tc.type == "positive"

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                title="x",
                preconditions=[],
                steps=["step"],
                expected_result="result",
                priority="critical",  # not in enum
                type="positive",
            )

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                title="x",
                preconditions=[],
                steps=["step"],
                expected_result="result",
                priority="high",
                type="happy_path",  # not in enum
            )

    def test_security_type_accepted(self):
        tc = TestCase(
            title="x",
            preconditions=[],
            steps=["step"],
            expected_result="result",
            priority="high",
            type="security",
        )
        assert tc.type == "security"

    def test_performance_type_accepted(self):
        tc = TestCase(
            title="x",
            preconditions=[],
            steps=["step"],
            expected_result="result",
            priority="high",
            type="performance",
        )
        assert tc.type == "performance"


# ---------------------------------------------------------------------------
# ModelOutput validation
# ---------------------------------------------------------------------------


class TestModelOutputSchema:
    def test_valid_output(self):
        data = {
            "requirement_id": "REQ-001",
            "test_cases": [
                {
                    "title": "Test",
                    "preconditions": [],
                    "steps": ["step 1"],
                    "expected_result": "OK",
                    "priority": "medium",
                    "type": "positive",
                }
            ],
            "assumptions": [],
            "notes": "",
        }
        output = ModelOutput.model_validate(data)
        assert output.requirement_id == "REQ-001"
        assert len(output.test_cases) == 1

    def test_defaults_for_optional_fields(self):
        data = {
            "requirement_id": "REQ-002",
            "test_cases": [
                {
                    "title": "Default test",
                    "preconditions": [],
                    "steps": ["step"],
                    "expected_result": "OK",
                    "priority": "low",
                    "type": "positive",
                }
            ],
        }
        output = ModelOutput.model_validate(data)
        assert output.assumptions == []
        assert output.notes == ""

    def test_empty_test_cases_rejected(self):
        with pytest.raises(ValidationError):
            ModelOutput.model_validate({"requirement_id": "REQ-002", "test_cases": []})

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            ModelOutput.model_validate({"test_cases": []})  # no requirement_id

    def test_invalid_test_case_inside_output_rejected(self):
        data = {
            "requirement_id": "REQ-001",
            "test_cases": [
                {
                    "title": "Test",
                    "preconditions": [],
                    "steps": [],
                    "expected_result": "OK",
                    "priority": "urgent",  # invalid
                    "type": "positive",
                }
            ],
        }
        with pytest.raises(ValidationError):
            ModelOutput.model_validate(data)


# ---------------------------------------------------------------------------
# _parse_output (from model_adapter)
# ---------------------------------------------------------------------------


class TestParseOutput:
    def _valid_json(self) -> str:
        return json.dumps(
            {
                "requirement_id": "REQ-001",
                "test_cases": [
                    {
                        "title": "Login test",
                        "preconditions": ["User exists"],
                        "steps": ["Open page", "Submit"],
                        "expected_result": "Redirect to dashboard",
                        "priority": "high",
                        "type": "positive",
                    }
                ],
                "assumptions": [],
                "notes": "",
            }
        )

    def test_valid_json_parsed(self):
        output = _parse_output(self._valid_json(), "REQ-001")
        assert output.requirement_id == "REQ-001"

    def test_strips_markdown_code_fence(self):
        fenced = f"```json\n{self._valid_json()}\n```"
        output = _parse_output(fenced, "REQ-001")
        assert output.requirement_id == "REQ-001"

    def test_strips_bare_code_fence(self):
        fenced = f"```\n{self._valid_json()}\n```"
        output = _parse_output(fenced, "REQ-001")
        assert output.requirement_id == "REQ-001"

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output("not json at all", "REQ-001")

    def test_valid_json_invalid_schema_raises_value_error(self):
        bad_schema = json.dumps({"requirement_id": "REQ-001", "test_cases": "not a list"})
        with pytest.raises(ValueError, match="schema validation"):
            _parse_output(bad_schema, "REQ-001")

    def test_requirement_id_mismatch_raises_value_error(self):
        data = json.loads(self._valid_json())
        data["requirement_id"] = "REQ-999"

        with pytest.raises(ValueError, match="requirement_id mismatch"):
            _parse_output(json.dumps(data), "REQ-001")

    def test_extra_top_level_field_rejected(self):
        data = json.loads(self._valid_json())
        data["debug"] = "not part of the output contract"

        with pytest.raises(ValueError, match="schema validation"):
            _parse_output(json.dumps(data), "REQ-001")

    def test_extra_test_case_field_rejected(self):
        data = json.loads(self._valid_json())
        data["test_cases"][0]["extra"] = "not part of the test case contract"

        with pytest.raises(ValueError, match="schema validation"):
            _parse_output(json.dumps(data), "REQ-001")

    def test_freeform_prose_raises_value_error(self):
        prose = "Here are some test cases: 1. Test login. 2. Test logout."
        with pytest.raises(ValueError, match="not valid JSON"):
            _parse_output(prose, "REQ-001")


# ---------------------------------------------------------------------------
# GoldAnnotation validation
# ---------------------------------------------------------------------------


class TestGoldAnnotationSchema:
    def test_valid_gold_annotation(self):
        ann = GoldAnnotation(
            requirement_id="REQ-001",
            required_coverage_points=["redirected to dashboard"],
            acceptable_variants={"redirected to dashboard": ["redirect"]},
            disallowed_assumptions=["auto-approve"],
            review_notes="test",
        )
        assert ann.requirement_id == "REQ-001"

    def test_defaults(self):
        ann = GoldAnnotation(
            requirement_id="REQ-001",
            required_coverage_points=[],
        )
        assert ann.acceptable_variants == {}
        assert ann.disallowed_assumptions == []
        assert ann.gold_test_cases == []


# ---------------------------------------------------------------------------
# Requirement validation
# ---------------------------------------------------------------------------


class TestRequirementSchema:
    def test_valid_requirement(self):
        req = Requirement(
            requirement_id="REQ-001",
            requirement_text="Users can log in.",
            domain_tag="auth",
            difficulty="easy",
        )
        assert req.difficulty == "easy"

    def test_invalid_difficulty(self):
        with pytest.raises(ValidationError):
            Requirement(
                requirement_id="REQ-001",
                requirement_text="text",
                domain_tag="auth",
                difficulty="trivial",  # not in enum
            )

    def test_ambiguous_difficulty_accepted(self):
        req = Requirement(
            requirement_id="REQ-009",
            requirement_text="The system should send notifications.",
            domain_tag="notifications",
            difficulty="ambiguous",
        )
        assert req.difficulty == "ambiguous"


class TestPromptSchemaParity:
    def test_all_generator_prompts_list_all_test_case_types(self):
        prompt_dir = Path(__file__).resolve().parents[1] / "src" / "harness" / "prompts"
        allowed_types = get_args(TestCase.model_fields["type"].annotation)

        for prompt_name in ("v1.txt", "v2.txt", "v3.txt"):
            prompt_text = (prompt_dir / prompt_name).read_text(encoding="utf-8")
            type_line = next(line for line in prompt_text.splitlines() if '"type":' in line)

            for allowed_type in allowed_types:
                assert allowed_type in type_line
