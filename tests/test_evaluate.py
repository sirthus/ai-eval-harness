"""Tests for evaluator artifact loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.evaluate import _load_generated


def _model_output(requirement_id: str) -> dict:
    return {
        "requirement_id": requirement_id,
        "test_cases": [
            {
                "title": f"Test for {requirement_id}",
                "preconditions": ["system is running"],
                "steps": ["perform action"],
                "expected_result": "Action succeeds",
                "priority": "high",
                "type": "positive",
            }
        ],
        "assumptions": [],
        "notes": "",
    }


class TestLoadGenerated:
    def test_loads_non_req_requirement_ids_and_ignores_sidecars(self, tmp_path: Path):
        (tmp_path / "AUTH-001.json").write_text(
            json.dumps(_model_output("AUTH-001")),
            encoding="utf-8",
        )
        (tmp_path / "REQ-001.judge.json").write_text(
            json.dumps(
                {
                    "requirement_id": "REQ-001",
                    "coverage_assessments": [],
                    "correctness_score": 2.0,
                    "correctness_rationale": "ok",
                    "hallucination_risk_score": 2.0,
                    "hallucination_risk_rationale": "ok",
                    "reviewer_usefulness_score": 2.0,
                    "reviewer_usefulness_rationale": "ok",
                    "judge_model": "judge",
                    "judge_prompt_version": "judge_v1",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "REQ-002.fail.json").write_text(
            json.dumps({"requirement_id": "REQ-002", "error": "invalid JSON"}),
            encoding="utf-8",
        )
        (tmp_path / "scored_results.json").write_text("[]", encoding="utf-8")

        outputs = _load_generated(tmp_path)

        assert list(outputs) == ["AUTH-001"]
        assert outputs["AUTH-001"].requirement_id == "AUTH-001"

    def test_invalid_generated_output_still_raises_validation_error(self, tmp_path: Path):
        (tmp_path / "AUTH-001.json").write_text(
            json.dumps({"requirement_id": "AUTH-001"}),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError):
            _load_generated(tmp_path)

    def test_filename_payload_requirement_id_mismatch_raises(self, tmp_path: Path):
        (tmp_path / "REQ-001.json").write_text(
            json.dumps(_model_output("REQ-999")),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="requirement_id mismatch"):
            _load_generated(tmp_path)

    def test_duplicate_payload_requirement_id_raises(self, tmp_path: Path):
        (tmp_path / "REQ-001.json").write_text(
            json.dumps(_model_output("REQ-001")),
            encoding="utf-8",
        )
        (tmp_path / "REQ-002.json").write_text(
            json.dumps(_model_output("REQ-001")),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Duplicate generated output"):
            _load_generated(tmp_path)
