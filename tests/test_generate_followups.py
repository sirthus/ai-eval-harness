"""Regression tests for generation failure handling."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
import pytest

from harness import generate
from harness.schemas import ModelOutput, Requirement, TestCase


def _requirement(req_id: str) -> Requirement:
    return Requirement(
        requirement_id=req_id,
        requirement_text=f"Requirement text for {req_id}",
        domain_tag="auth",
        difficulty="easy",
    )


def _output(req_id: str) -> ModelOutput:
    return ModelOutput(
        requirement_id=req_id,
        test_cases=[
            TestCase(
                title=f"Happy path {req_id}",
                preconditions=["system is running"],
                steps=["open page", "submit form"],
                expected_result="Request succeeds",
                priority="high",
                type="positive",
            )
        ],
        assumptions=[],
        notes="",
    )


def _write_dataset(path: Path, req_ids: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for req_id in req_ids:
            f.write(_requirement(req_id).model_dump_json() + "\n")


def _write_config(tmp_path: Path, dataset_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config = {
        "run_id": "run_from_config",
        "model_version": "claude-test",
        "prompt_version": "v2",
        "dataset_path": str(dataset_path),
        "generated_dir": str(tmp_path / "generated"),
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


class TestGenerateFailureHandling:
    def test_parse_failure_writes_marker_and_log(self, tmp_path, monkeypatch):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_dataset(dataset_path, ["REQ-001", "REQ-002"])
        config_path = _write_config(tmp_path, dataset_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        def fake_generate(*, requirement_id: str, **_: str) -> ModelOutput:
            if requirement_id == "REQ-002":
                raise ValueError("invalid JSON")
            return _output(requirement_id)

        monkeypatch.setattr(generate.model_adapter, "generate", fake_generate)

        generated_dir, failures = generate.run(str(config_path), run_id="run_case")

        assert failures == ["REQ-002"]
        assert (generated_dir / "REQ-001.json").exists()

        marker_path = generated_dir / "REQ-002.fail.json"
        assert marker_path.exists()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        assert marker["requirement_id"] == "REQ-002"
        assert marker["error"] == "invalid JSON"

        failures_log = generated_dir / "parse_failures.jsonl"
        lines = [json.loads(line) for line in failures_log.read_text(encoding="utf-8").splitlines() if line]
        assert len(lines) == 1
        assert lines[0]["requirement_id"] == "REQ-002"

    def test_non_value_error_raises_without_failure_marker(self, tmp_path, monkeypatch):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_dataset(dataset_path, ["REQ-001", "REQ-002"])
        config_path = _write_config(tmp_path, dataset_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        def fake_generate(*, requirement_id: str, **_: str) -> ModelOutput:
            if requirement_id == "REQ-002":
                raise RuntimeError("rate limited")
            return _output(requirement_id)

        monkeypatch.setattr(generate.model_adapter, "generate", fake_generate)

        with pytest.raises(RuntimeError, match="rate limited"):
            generate.run(str(config_path), run_id="run_case")

        run_dir = tmp_path / "generated" / "run_case"
        assert (run_dir / "REQ-001.json").exists()
        assert not (run_dir / "REQ-002.fail.json").exists()
        assert not (run_dir / "parse_failures.jsonl").exists()

    def test_rerun_skips_success_and_parse_failure_markers(self, tmp_path, monkeypatch):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_dataset(dataset_path, ["REQ-001", "REQ-002", "REQ-003"])
        config_path = _write_config(tmp_path, dataset_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        run_dir = tmp_path / "generated" / "run_case"
        run_dir.mkdir(parents=True)
        (run_dir / "REQ-001.json").write_text(_output("REQ-001").model_dump_json(), encoding="utf-8")
        (run_dir / "REQ-002.fail.json").write_text(
            json.dumps({"requirement_id": "REQ-002", "error": "invalid JSON"}),
            encoding="utf-8",
        )

        calls: list[str] = []

        def fake_generate(*, requirement_id: str, **_: str) -> ModelOutput:
            calls.append(requirement_id)
            return _output(requirement_id)

        monkeypatch.setattr(generate.model_adapter, "generate", fake_generate)

        generated_dir, failures = generate.run(str(config_path), run_id="run_case")

        assert generated_dir == run_dir
        assert failures == ["REQ-002"]
        assert calls == ["REQ-003"]
        assert (run_dir / "REQ-003.json").exists()
