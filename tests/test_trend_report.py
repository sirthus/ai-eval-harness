"""Tests for trend_report.py: trend data aggregation and filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.charts import inject_chart_markdown
from harness.trend_report import (
    build_trend_data,
    consistently_borderline_requirements,
    domain_pass_rates,
    render_trend_markdown,
)
from harness.schemas import Requirement, RunManifest, RunSummary, ScoredResult, TrendReport
from tests.factories import make_run_manifest, make_scored_result, make_small_requirements_list


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _result(req_id: str, decision: str, score: float) -> ScoredResult:
    return make_scored_result(requirement_id=req_id, decision=decision, weighted_score=score)


def _manifest(
    run_id: str,
    dataset_version: str = "mvp_v2",
    prompt_version: str = "v1",
    timestamp: str = "2026-04-01T12:00:00+00:00",
    pass_count: int = 2,
    borderline_count: int = 1,
    fail_count: int = 0,
    quality_gate_decision: str = "needs_review",
) -> RunManifest:
    return make_run_manifest(
        run_id=run_id,
        model_version="claude-3-5-sonnet-20241022",
        prompt_version=prompt_version,
        dataset_version=dataset_version,
        timestamp=timestamp,
        config_file="configs/run.yaml",
        total_requirements=3,
        total_evaluated=3,
        pass_count=pass_count,
        borderline_count=borderline_count,
        fail_count=fail_count,
        avg_weighted_score=1.65,
        quality_gate_decision=quality_gate_decision,
    )


def _write_results(tmp_path: Path, run_id: str, results: list[ScoredResult]) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scored_results.json").write_text(
        json.dumps([r.model_dump() for r in results]), encoding="utf-8"
    )


def _requirements() -> list[Requirement]:
    return make_small_requirements_list()


# ---------------------------------------------------------------------------
# build_trend_data
# ---------------------------------------------------------------------------


class TestBuildTrendData:
    def test_three_runs_same_dataset_builds_correct_structure(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifests = [
            _manifest("run_001", timestamp="2026-04-01T12:00:00+00:00"),
            _manifest("run_002", timestamp="2026-04-02T12:00:00+00:00"),
            _manifest("run_003", timestamp="2026-04-03T12:00:00+00:00"),
        ]
        for m in manifests:
            _write_results(gen_dir, m.run_id, [
                _result("REQ-001", "pass", 1.8),
                _result("REQ-002", "borderline", 1.4),
                _result("REQ-003", "fail", 1.0),
            ])

        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset="mvp_v2",
        )

        assert len(trend.runs) == 3
        assert "REQ-001" in trend.per_requirement_history
        assert len(trend.per_requirement_history["REQ-001"]) == 3
        assert all(h["run_id"] in {"run_001", "run_002", "run_003"}
                   for h in trend.per_requirement_history["REQ-001"])

    def test_default_filter_selects_most_recent_dataset_version(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifests = [
            _manifest("run_old", dataset_version="mvp_v1", timestamp="2026-03-01T12:00:00+00:00"),
            _manifest("run_new", dataset_version="mvp_v2", timestamp="2026-04-01T12:00:00+00:00"),
        ]
        for m in manifests:
            _write_results(gen_dir, m.run_id, [_result("REQ-001", "pass", 1.8)])

        # No filter_dataset specified → should use most recent
        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset=None,
        )
        # Only the mvp_v2 run should be included
        assert len(trend.runs) == 1
        assert trend.runs[0].run_id == "run_new"

    def test_filter_dataset_all_includes_mixed(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifests = [
            _manifest("run_v1", dataset_version="mvp_v1", timestamp="2026-03-01T12:00:00+00:00"),
            _manifest("run_v2", dataset_version="mvp_v2", timestamp="2026-04-01T12:00:00+00:00"),
        ]
        for m in manifests:
            _write_results(gen_dir, m.run_id, [_result("REQ-001", "pass", 1.8)])

        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset="all",
        )
        assert len(trend.runs) == 2

    def test_filter_prompt_restricts_runs(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifests = [
            _manifest("run_p1", prompt_version="v1"),
            _manifest("run_p2", prompt_version="v2"),
        ]
        for m in manifests:
            _write_results(gen_dir, m.run_id, [_result("REQ-001", "pass", 1.8)])

        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset="mvp_v2",
            filter_prompt="v2",
        )
        assert len(trend.runs) == 1
        assert trend.runs[0].run_id == "run_p2"

    def test_trend_csv_shape(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifests = [_manifest("run_001"), _manifest("run_002", timestamp="2026-04-02T12:00:00+00:00")]
        for m in manifests:
            _write_results(gen_dir, m.run_id, [
                _result("REQ-001", "pass", 1.8),
                _result("REQ-002", "fail", 1.0),
            ])

        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset="mvp_v2",
        )
        # Expect 2 reqs × 2 runs = 4 entries
        total_entries = sum(len(v) for v in trend.per_requirement_history.values())
        assert total_entries == 4

    def test_run_summary_includes_quality_gate_decision(self, tmp_path):
        gen_dir = tmp_path / "generated"
        manifest = _manifest("run_001", quality_gate_decision="fail")
        _write_results(gen_dir, manifest.run_id, [_result("REQ-001", "pass", 1.8)])

        trend = build_trend_data(
            [manifest],
            generated_dir=str(gen_dir),
            requirements=_requirements(),
            filter_dataset="mvp_v2",
        )

        assert trend.runs[0].quality_gate_decision == "fail"


# ---------------------------------------------------------------------------
# consistently_borderline_requirements
# ---------------------------------------------------------------------------


class TestConsistentlyBorderline:
    def test_req_borderline_in_majority_of_runs_included(self):
        history = {
            "REQ-001": [
                {"run_id": "run_1", "decision": "borderline", "weighted_score": 1.4},
                {"run_id": "run_2", "decision": "borderline", "weighted_score": 1.3},
                {"run_id": "run_3", "decision": "pass", "weighted_score": 1.7},
            ],
            "REQ-002": [
                {"run_id": "run_1", "decision": "pass", "weighted_score": 1.8},
                {"run_id": "run_2", "decision": "pass", "weighted_score": 1.9},
            ],
        }
        result = consistently_borderline_requirements(history, threshold=0.5)
        assert "REQ-001" in result
        assert "REQ-002" not in result

    def test_exactly_half_borderline_not_included(self):
        history = {
            "REQ-001": [
                {"run_id": "run_1", "decision": "borderline", "weighted_score": 1.4},
                {"run_id": "run_2", "decision": "pass", "weighted_score": 1.8},
            ]
        }
        result = consistently_borderline_requirements(history, threshold=0.5)
        # exactly 50% is not > 50%
        assert "REQ-001" not in result


# ---------------------------------------------------------------------------
# domain_pass_rates
# ---------------------------------------------------------------------------


class TestDomainPassRates:
    def test_correct_grouping_from_domain_tags(self):
        history = {
            "REQ-001": [{"run_id": "run_1", "decision": "pass", "weighted_score": 1.8}],
            "REQ-002": [{"run_id": "run_1", "decision": "fail", "weighted_score": 1.0}],
            "REQ-003": [{"run_id": "run_1", "decision": "pass", "weighted_score": 1.7}],
        }
        requirements = _requirements()  # REQ-001=auth, REQ-002=tasks, REQ-003=search
        rates = domain_pass_rates(history, requirements, run_ids=["run_1"])
        assert rates["auth"]["run_1"] == pytest.approx(1.0)
        assert rates["tasks"]["run_1"] == pytest.approx(0.0)
        assert rates["search"]["run_1"] == pytest.approx(1.0)

    def test_multi_run_domain_rates(self):
        history = {
            "REQ-001": [
                {"run_id": "run_1", "decision": "fail", "weighted_score": 1.0},
                {"run_id": "run_2", "decision": "pass", "weighted_score": 1.8},
            ],
        }
        requirements = [
            Requirement(requirement_id="REQ-001", requirement_text="t", domain_tag="auth", difficulty="easy"),
        ]
        rates = domain_pass_rates(history, requirements, run_ids=["run_1", "run_2"])
        assert rates["auth"]["run_1"] == pytest.approx(0.0)
        assert rates["auth"]["run_2"] == pytest.approx(1.0)


class TestChartInjection:
    def test_injects_before_marker_when_present(self):
        md = "# Trend\n\n## Runs Included\n\nBody\n"
        updated = inject_chart_markdown(
            md,
            ["![Pass Rate Over Time](trend.png)"],
            "## Runs Included",
        )
        assert updated.index("## Charts") < updated.index("## Runs Included")
        assert "![Pass Rate Over Time](trend.png)" in updated

    def test_appends_fallback_section_when_marker_missing(self, caplog):
        md = "# Trend\n\nNo expected section.\n"
        with caplog.at_level("WARNING"):
            updated = inject_chart_markdown(
                md,
                ["![Pass Rate Over Time](trend.png)"],
                "## Runs Included",
            )
        assert "## Charts" in updated
        assert updated.rstrip().endswith("![Pass Rate Over Time](trend.png)")
        assert "not found" in caplog.text


class TestQualityGateEvolution:
    def test_render_uses_persisted_quality_gate_labels(self):
        trend = TrendReport(
            generated_at="2026-04-03T12:00:00+00:00",
            runs=[
                RunSummary(
                    run_id="run_pass",
                    timestamp="2026-04-01T12:00:00+00:00",
                    model_version="claude",
                    prompt_version="v1",
                    dataset_version="mvp_v2",
                    quality_gate_decision="pass",
                    pass_count=3,
                    borderline_count=0,
                    fail_count=0,
                    total_evaluated=3,
                    parse_failures=0,
                    avg_weighted_score=1.9,
                ),
                RunSummary(
                    run_id="run_review",
                    timestamp="2026-04-02T12:00:00+00:00",
                    model_version="claude",
                    prompt_version="v1",
                    dataset_version="mvp_v2",
                    quality_gate_decision="needs_review",
                    pass_count=3,
                    borderline_count=0,
                    fail_count=0,
                    total_evaluated=3,
                    parse_failures=2,
                    avg_weighted_score=1.9,
                ),
                RunSummary(
                    run_id="run_fail",
                    timestamp="2026-04-03T12:00:00+00:00",
                    model_version="claude",
                    prompt_version="v1",
                    dataset_version="mvp_v2",
                    quality_gate_decision="fail",
                    pass_count=1,
                    borderline_count=0,
                    fail_count=2,
                    total_evaluated=3,
                    parse_failures=0,
                    avg_weighted_score=1.0,
                ),
            ],
            per_requirement_history={},
            consistently_borderline=[],
            domain_pass_rates={},
        )

        markdown = render_trend_markdown(
            trend,
            filter_dataset="mvp_v2",
            run_counts={"run_fail": 1, "run_pass": 1, "run_review": 1},
        )

        assert "| `run_pass` | 100% | ✓ Recommended |" in markdown
        assert "| `run_review` | 100% | ~ Needs review |" in markdown
        assert "| `run_fail` | 33% | ✗ Not recommended |" in markdown
