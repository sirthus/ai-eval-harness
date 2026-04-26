"""Unit tests for harness.loaders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.loaders import load_config, load_manifest, load_requirements, load_scored_results
from tests.factories import make_run_manifest, make_scored_result, make_small_requirements_list

# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_returns_run_manifest_for_valid_file(self, tmp_path):
        manifest = make_run_manifest(run_id="run_abc")
        (tmp_path / "run_abc.json").write_text(manifest.model_dump_json(), encoding="utf-8")

        result = load_manifest(str(tmp_path), "run_abc")

        assert result.run_id == "run_abc"

    def test_raises_file_not_found_when_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Run manifest not found"):
            load_manifest(str(tmp_path), "nonexistent")

    def test_uses_manifest_path_helper_for_filename(self, tmp_path):
        """load_manifest constructs path as {runs_dir}/{run_id}.json."""
        manifest = make_run_manifest(run_id="my_run")
        # Write to the expected location; if the helper diverges the read would fail
        (tmp_path / "my_run.json").write_text(manifest.model_dump_json(), encoding="utf-8")

        result = load_manifest(str(tmp_path), "my_run")
        assert result.run_id == "my_run"


# ---------------------------------------------------------------------------
# load_scored_results
# ---------------------------------------------------------------------------


class TestLoadScoredResults:
    def _write_scored_results(self, tmp_path, run_id: str, results: list) -> None:
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = [r.model_dump() for r in results]
        (run_dir / "scored_results.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_returns_dict_for_valid_file(self, tmp_path):
        result = make_scored_result(requirement_id="REQ-001")
        self._write_scored_results(tmp_path, "run_abc", [result])

        loaded = load_scored_results(str(tmp_path), "run_abc")

        assert "REQ-001" in loaded
        assert loaded["REQ-001"].requirement_id == "REQ-001"

    def test_raises_file_not_found_by_default(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Scored results not found"):
            load_scored_results(str(tmp_path), "missing_run")

    def test_returns_empty_dict_when_raise_on_missing_false(self, tmp_path):
        result = load_scored_results(str(tmp_path), "missing_run", raise_on_missing=False)
        assert result == {}

    def test_malformed_json_raises(self, tmp_path):
        run_dir = tmp_path / "bad_run"
        run_dir.mkdir()
        (run_dir / "scored_results.json").write_text("not json", encoding="utf-8")

        with pytest.raises((json.JSONDecodeError, ValueError)):
            load_scored_results(str(tmp_path), "bad_run")

    def test_multiple_results_keyed_by_requirement_id(self, tmp_path):
        results = [
            make_scored_result(requirement_id="REQ-001"),
            make_scored_result(requirement_id="REQ-002"),
        ]
        self._write_scored_results(tmp_path, "run_multi", results)

        loaded = load_scored_results(str(tmp_path), "run_multi")

        assert set(loaded.keys()) == {"REQ-001", "REQ-002"}

    def test_missing_scorer_provenance_fields_use_defaults(self, tmp_path):
        run_dir = tmp_path / "run_legacy"
        run_dir.mkdir(parents=True)
        payload = [
            {
                "requirement_id": "REQ-001",
                "scores": {
                    "correctness": 2.0,
                    "completeness": 2.0,
                    "hallucination_risk": 2.0,
                    "reviewer_usefulness": 1.0,
                },
                "weighted_score": 1.8,
                "decision": "pass",
                "coverage_ratio": 1.0,
            }
        ]
        (run_dir / "scored_results.json").write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_scored_results(str(tmp_path), "run_legacy")

        assert loaded["REQ-001"].scorer_source == "heuristic"
        assert loaded["REQ-001"].scorer_error == ""


# ---------------------------------------------------------------------------
# load_requirements
# ---------------------------------------------------------------------------


class TestLoadRequirements:
    def test_empty_jsonl_returns_empty_list(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("\n\n", encoding="utf-8")

        assert load_requirements(str(f)) == []

    def test_valid_jsonl_parses_all_rows(self, tmp_path):
        reqs = make_small_requirements_list()
        lines = "\n".join(
            json.dumps({
                "requirement_id": r.requirement_id,
                "requirement_text": r.requirement_text,
                "domain_tag": r.domain_tag,
                "difficulty": r.difficulty,
            })
            for r in reqs
        )
        f = tmp_path / "reqs.jsonl"
        f.write_text(lines, encoding="utf-8")

        loaded = load_requirements(str(f))

        assert len(loaded) == 3
        assert loaded[0].requirement_id == "REQ-001"

    def test_skips_blank_lines(self, tmp_path):
        req = make_small_requirements_list()[0]
        row = json.dumps({
            "requirement_id": req.requirement_id,
            "requirement_text": req.requirement_text,
            "domain_tag": req.domain_tag,
            "difficulty": req.difficulty,
        })
        f = tmp_path / "gaps.jsonl"
        f.write_text(f"\n{row}\n\n", encoding="utf-8")

        loaded = load_requirements(str(f))
        assert len(loaded) == 1


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """Regression for P2: empty YAML must not return None."""
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")

        result = load_config(str(f))

        assert result == {}
        assert result is not None

    def test_whitespace_only_yaml_returns_empty_dict(self, tmp_path):
        f = tmp_path / "ws.yaml"
        f.write_text("   \n\n", encoding="utf-8")

        assert load_config(str(f)) == {}

    def test_valid_yaml_parsed_correctly(self, tmp_path):
        f = tmp_path / "cfg.yaml"
        f.write_text("run_id: test_run\nmodel_version: claude-sonnet-4-6\n", encoding="utf-8")

        cfg = load_config(str(f))

        assert cfg["run_id"] == "test_run"
        assert cfg["model_version"] == "claude-sonnet-4-6"

    def test_repo_config_paths_resolve_from_repo_root_when_cwd_differs(self, tmp_path, monkeypatch):
        repo_root = Path(__file__).resolve().parents[1]
        config_path = repo_root / "configs" / "run_v1.yaml"
        monkeypatch.chdir(tmp_path)

        cfg = load_config(config_path)

        assert cfg["dataset_path"] == str(repo_root / "data" / "requirements" / "mvp_dataset.jsonl")
        assert cfg["generated_dir"] == str(repo_root / "data" / "generated")
        assert cfg["reports_dir"] == str(repo_root / "reports")

    def test_absolute_config_paths_remain_absolute(self, tmp_path):
        dataset_path = tmp_path / "requirements.jsonl"
        f = tmp_path / "cfg.yaml"
        f.write_text(f"dataset_path: {dataset_path}\nreports_dir: reports\n", encoding="utf-8")

        cfg = load_config(str(f))

        assert cfg["dataset_path"] == str(dataset_path)
        assert cfg["reports_dir"] == str(tmp_path / "reports")
