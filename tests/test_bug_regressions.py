"""Regression tests for bugs found after Phase 3 implementation.

Bug 1: quality_gate_decision never persisted in run_eval.py
Bug 2: step-only evaluate.py ignores scorer: llm-judge
Bug 4: trend charts use fixed filenames, overwriting on successive runs
(Bug 3 regression tests live in test_llm_judge.py alongside the scorer tests.)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.schemas import DimensionScores, GoldAnnotation, ModelOutput, RunManifest, ScoredResult, TestCase
from harness.run_eval import _compute_quality_gate
from tests.factories import make_run_manifest, make_scored_result


# ---------------------------------------------------------------------------
def _make_scored_result(
    requirement_id: str,
    decision: str,
    weighted_score: float,
) -> ScoredResult:
    return make_scored_result(
        requirement_id=requirement_id,
        decision=decision,
        weighted_score=weighted_score,
        coverage_ratio=1.0,
    )


# ---------------------------------------------------------------------------
# Bug 1: quality_gate_decision must be persisted in manifest
# ---------------------------------------------------------------------------


class TestQualityGateDecisionPersisted:
    def test_manifest_schema_has_quality_gate_decision_field(self):
        m = make_run_manifest(quality_gate_decision="pass")
        assert m.quality_gate_decision == "pass"

    def test_quality_gate_decision_serialised_to_json(self):
        m = make_run_manifest(quality_gate_decision="fail")
        data = json.loads(m.model_dump_json())
        assert "quality_gate_decision" in data
        assert data["quality_gate_decision"] == "fail"

    def test_quality_gate_decision_round_trips_from_json(self):
        m = make_run_manifest(quality_gate_decision="needs_review")
        restored = RunManifest.model_validate(json.loads(m.model_dump_json()))
        assert restored.quality_gate_decision == "needs_review"

    def test_check_quality_gate_script_reads_field(self, tmp_path):
        """check_quality_gate.py must exit 1 when a recent manifest has quality_gate_decision='fail'."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        m = make_run_manifest(quality_gate_decision="fail")
        (runs_dir / f"{m.run_id}.json").write_text(m.model_dump_json(), encoding="utf-8")

        from scripts.check_quality_gate import check
        exit_code = check(runs_dir, last_n=5)
        assert exit_code == 1

    def test_check_quality_gate_exits_0_when_all_pass(self, tmp_path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        m = make_run_manifest(quality_gate_decision="pass")
        (runs_dir / f"{m.run_id}.json").write_text(m.model_dump_json(), encoding="utf-8")

        from scripts.check_quality_gate import check
        exit_code = check(runs_dir, last_n=5)
        assert exit_code == 0

    def test_check_quality_gate_exits_0_on_empty_dir(self, tmp_path):
        runs_dir = tmp_path / "empty_runs"
        from scripts.check_quality_gate import check
        exit_code = check(runs_dir, last_n=5)
        assert exit_code == 0

    def test_quality_gate_logic_pass(self):
        assert _compute_quality_gate(0.8, 2, 0) == "pass"

    def test_quality_gate_logic_fail_low_pass_rate_even_with_borderline(self):
        assert _compute_quality_gate(0.1, 1, 0) == "fail"

    def test_quality_gate_logic_needs_review_borderline(self):
        assert _compute_quality_gate(0.6, 3, 0) == "needs_review"

    def test_quality_gate_logic_needs_review_parse_failures(self):
        assert _compute_quality_gate(0.7, 0, 1) == "needs_review"

    def test_quality_gate_logic_fail_zero_evaluated(self):
        assert _compute_quality_gate(0.0, 0, 0) == "fail"

    def test_manifest_schema_has_is_dirty_field(self):
        m = make_run_manifest(is_dirty=True)
        assert m.is_dirty is True
        data = json.loads(m.model_dump_json())
        assert "is_dirty" in data
        assert data["is_dirty"] is True

    def test_manifest_is_dirty_defaults_false(self):
        m = make_run_manifest()
        assert m.is_dirty is False


# ---------------------------------------------------------------------------
# Bug 2: step-only evaluate.py must honour scorer: llm-judge from config
# ---------------------------------------------------------------------------


class TestEvaluateStepHonoursScorer:
    def _write_config(self, tmp_path: Path, scorer: str = "llm-judge") -> Path:
        gold = {
            "requirement_id": "REQ-001",
            "required_coverage_points": ["valid login grants access"],
            "acceptable_variants": {},
            "disallowed_assumptions": [],
            "review_notes": "",
            "gold_test_cases": [],
        }
        gold_path = tmp_path / "gold.jsonl"
        gold_path.write_text(json.dumps(gold) + "\n", encoding="utf-8")

        cfg = {
            "run_id": "run_test",
            "model_name": "claude",
            "model_version": "claude-sonnet-4-6",
            "prompt_version": "v2",
            "dataset_version": "mvp_v2",
            "scoring_version": "v2",
            "threshold_version": "v2",
            "dataset_path": str(gold_path),
            "gold_path": str(gold_path),
            "generated_dir": str(tmp_path / "generated"),
            "runs_dir": str(tmp_path / "runs"),
            "reviews_dir": str(tmp_path / "reviews"),
            "reports_dir": str(tmp_path / "reports"),
            "scorer": scorer,
            "thresholds": {
                "pass": 1.6, "borderline_low": 1.2,
                "weights": {"correctness": 0.35, "completeness": 0.30,
                            "hallucination_risk": 0.20, "reviewer_usefulness": 0.15},
                "floor": {"correctness": 1.0, "completeness": 1.0, "hallucination_risk": 1.0},
            },
        }
        import yaml
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
        return cfg_path

    def _write_generated_output(self, tmp_path: Path, run_id: str = "run_test") -> None:
        output = {
            "requirement_id": "REQ-001",
            "test_cases": [
                {
                    "title": "Valid login succeeds",
                    "preconditions": ["App is running"],
                    "steps": ["Enter credentials", "Click Submit"],
                    "expected_result": "User is redirected",
                    "priority": "high",
                    "type": "positive",
                },
                {
                    "title": "Invalid login fails",
                    "preconditions": ["App is running"],
                    "steps": ["Enter wrong password", "Click Submit"],
                    "expected_result": "Error message shown",
                    "priority": "high",
                    "type": "negative",
                },
            ],
            "assumptions": [],
            "notes": "",
        }
        out_dir = tmp_path / "generated" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "REQ-001.json").write_text(json.dumps(output), encoding="utf-8")

    def test_heuristic_scorer_used_when_config_omits_scorer(self, tmp_path):
        """When scorer field is absent from config, heuristic scorer is used — no import error."""
        cfg_path = self._write_config(tmp_path, scorer="heuristic")
        self._write_generated_output(tmp_path)

        # Patch the config to remove the 'scorer' key entirely
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        cfg.pop("scorer", None)
        cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")

        from harness import evaluate
        results = evaluate.run(str(cfg_path))
        assert len(results) == 1

    def test_llm_judge_scorer_constructed_when_config_specifies_it(self, tmp_path, mocker):
        """When scorer=llm-judge in config, evaluate.run() builds and uses LLMJudgeScorer."""
        cfg_path = self._write_config(tmp_path, scorer="llm-judge")
        self._write_generated_output(tmp_path)

        # Mock LLMJudgeScorer so no real API call is made
        mock_result = ScoredResult(
            requirement_id="REQ-001",
            scores=DimensionScores(correctness=2.0, completeness=2.0,
                                   hallucination_risk=2.0, reviewer_usefulness=2.0),
            weighted_score=2.0,
            decision="pass",
            coverage_ratio=1.0,
        )
        mock_scorer_instance = MagicMock()
        mock_scorer_instance.score.return_value = mock_result
        # LLMJudgeScorer is lazily imported inside evaluate.run(), so patch at source module
        mocker.patch("harness.llm_judge.LLMJudgeScorer", return_value=mock_scorer_instance)

        from harness import evaluate
        results = evaluate.run(str(cfg_path))
        # LLMJudgeScorer was instantiated
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Bug 4: trend chart filenames must include timestamp to avoid overwrites
# ---------------------------------------------------------------------------


class TestTrendChartFilenames:
    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_trend_pass_rate_filename_includes_timestamp(self, tmp_path):
        from harness.charts import plot_trend_pass_rate

        trend_data = [
            {"run_id": "run_a", "pass_rate": 0.7, "borderline_rate": 0.1},
            {"run_id": "run_b", "pass_rate": 0.8, "borderline_rate": 0.1},
        ]
        path = plot_trend_pass_rate(trend_data, tmp_path, timestamp="20260329T120000Z")
        assert path is not None
        assert "20260329T120000Z" in path.name

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_domain_heatmap_filename_includes_timestamp(self, tmp_path):
        from harness.charts import plot_domain_heatmap

        domain_data = {"auth": {"run_a": 0.8, "run_b": 0.9}}
        path = plot_domain_heatmap(domain_data, ["run_a", "run_b"], tmp_path, timestamp="20260329T120000Z")
        assert path is not None
        assert "20260329T120000Z" in path.name

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_two_trend_runs_produce_distinct_chart_files(self, tmp_path):
        from harness.charts import plot_trend_pass_rate

        trend_data = [{"run_id": "run_a", "pass_rate": 0.7, "borderline_rate": 0.1}]
        path1 = plot_trend_pass_rate(trend_data, tmp_path, timestamp="20260329T120000Z")
        path2 = plot_trend_pass_rate(trend_data, tmp_path, timestamp="20260329T130000Z")
        assert path1 is not None
        assert path2 is not None
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_trend_pass_rate_no_timestamp_uses_bare_filename(self, tmp_path):
        """Backward compat: omitting timestamp falls back to the old bare filename."""
        pytest.importorskip("matplotlib")
        from harness.charts import plot_trend_pass_rate

        trend_data = [{"run_id": "run_a", "pass_rate": 0.7, "borderline_rate": 0.1}]
        path = plot_trend_pass_rate(trend_data, tmp_path)
        assert path is not None
        assert path.name == "trend_pass_rate.png"


class TestCompareChartFilenames:
    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_compare_distribution_filename_includes_timestamp(self, tmp_path):
        from harness.charts import plot_compare_distribution

        results_a = [_make_scored_result("REQ-001", "pass", 1.8)]
        results_b = [_make_scored_result("REQ-001", "pass", 1.9)]
        path = plot_compare_distribution(
            results_a,
            results_b,
            "run_family_20260329T120000Z",
            "run_family_20260329T130000Z",
            tmp_path,
            timestamp="20260329T140000Z",
        )
        assert path is not None
        assert "20260329T140000Z" in path.name

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_compare_delta_filename_includes_timestamp(self, tmp_path):
        from harness.charts import plot_compare_delta

        results_a = {"REQ-001": _make_scored_result("REQ-001", "pass", 1.8)}
        results_b = {"REQ-001": _make_scored_result("REQ-001", "pass", 1.9)}
        path = plot_compare_delta(
            results_a,
            results_b,
            "run_family_20260329T120000Z",
            "run_family_20260329T130000Z",
            tmp_path,
            timestamp="20260329T140000Z",
        )
        assert path is not None
        assert "20260329T140000Z" in path.name

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("matplotlib"),
        reason="matplotlib not installed",
    )
    def test_two_compare_runs_produce_distinct_chart_files(self, tmp_path):
        from harness.charts import plot_compare_distribution

        results_a = [_make_scored_result("REQ-001", "pass", 1.8)]
        results_b = [_make_scored_result("REQ-001", "pass", 1.9)]
        path1 = plot_compare_distribution(
            results_a,
            results_b,
            "run_family_20260329T120000Z",
            "run_family_20260329T130000Z",
            tmp_path,
            timestamp="20260329T140000Z",
        )
        path2 = plot_compare_distribution(
            results_a,
            results_b,
            "run_family_20260329T120000Z",
            "run_family_20260329T130000Z",
            tmp_path,
            timestamp="20260329T150000Z",
        )
        assert path1 is not None
        assert path2 is not None
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_compare_distribution_no_timestamp_uses_bare_filename(self, tmp_path):
        """Backward compat: omitting timestamp falls back to the old bare filename."""
        pytest.importorskip("matplotlib")
        from harness.charts import plot_compare_distribution

        results_a = [_make_scored_result("REQ-001", "pass", 1.8)]
        results_b = [_make_scored_result("REQ-001", "pass", 1.9)]
        path = plot_compare_distribution(
            results_a,
            results_b,
            "run_family_20260329T120000Z",
            "run_family_20260329T130000Z",
            tmp_path,
        )
        assert path is not None
        assert path.name == "compare_run_family_20260329T_vs_run_family_20260329T_distribution.png"
