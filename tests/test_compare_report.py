"""Tests for compare_report.py: delta computation, dataset consistency guard."""

from __future__ import annotations

import pytest

from harness.charts import inject_chart_markdown
from harness.compare_report import _compute_deltas, build_compare_report
from harness.schemas import (
    DimensionScores,
    Requirement,
    ReviewRecord,
    RunManifest,
    ScoredResult,
)
from tests.factories import make_run_manifest, make_scored_result, make_small_requirements_list

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _result(req_id: str, decision: str, score: float) -> ScoredResult:
    return make_scored_result(requirement_id=req_id, decision=decision, weighted_score=score)


def _manifest(
    run_id: str,
    prompt_version: str = "v1",
    dataset_version: str = "mvp_v2",
    parse_failures: int = 0,
) -> RunManifest:
    return make_run_manifest(
        run_id=run_id,
        model_version="claude-3-5-sonnet-20241022",
        prompt_version=prompt_version,
        dataset_version=dataset_version,
        timestamp="2026-04-02T13:00:00+00:00",
        total_requirements=3,
        parse_failures=parse_failures,
        total_evaluated=3,
        pass_count=2,
        borderline_count=1,
        fail_count=0,
        avg_weighted_score=1.7,
    )


def _requirements():
    return make_small_requirements_list()


# ---------------------------------------------------------------------------
# _compute_deltas
# ---------------------------------------------------------------------------


class TestComputeDeltas:
    def test_positive_delta(self):
        results_a = {"REQ-001": _result("REQ-001", "fail", 1.1)}
        results_b = {"REQ-001": _result("REQ-001", "pass", 1.7)}
        deltas = _compute_deltas(results_a, results_b)
        assert deltas["REQ-001"]["delta"] == pytest.approx(0.6)
        assert deltas["REQ-001"]["improvement"] is True
        assert deltas["REQ-001"]["regression"] is False

    def test_negative_delta_is_regression(self):
        results_a = {"REQ-001": _result("REQ-001", "pass", 1.8)}
        results_b = {"REQ-001": _result("REQ-001", "fail", 1.1)}
        deltas = _compute_deltas(results_a, results_b)
        assert deltas["REQ-001"]["delta"] == pytest.approx(-0.7)
        assert deltas["REQ-001"]["regression"] is True
        assert deltas["REQ-001"]["improvement"] is False

    def test_borderline_to_pass_is_improvement(self):
        results_a = {"REQ-001": _result("REQ-001", "borderline", 1.4)}
        results_b = {"REQ-001": _result("REQ-001", "pass", 1.7)}
        deltas = _compute_deltas(results_a, results_b)
        assert deltas["REQ-001"]["improvement"] is True

    def test_only_intersection_included(self):
        results_a = {"REQ-001": _result("REQ-001", "pass", 1.7), "REQ-002": _result("REQ-002", "fail", 1.0)}
        results_b = {"REQ-001": _result("REQ-001", "pass", 1.7)}
        deltas = _compute_deltas(results_a, results_b)
        assert "REQ-001" in deltas
        assert "REQ-002" not in deltas


# ---------------------------------------------------------------------------
# build_compare_report — dataset consistency guard
# ---------------------------------------------------------------------------


class TestBuildCompareReport:
    def test_fails_fast_on_dataset_version_mismatch(self):
        manifest_a = _manifest("run_a", dataset_version="mvp_v1")
        manifest_b = _manifest("run_b", dataset_version="mvp_v2")
        results_a = {"REQ-001": _result("REQ-001", "pass", 1.7)}
        results_b = {"REQ-001": _result("REQ-001", "pass", 1.7)}

        with pytest.raises(ValueError, match="Dataset version mismatch"):
            build_compare_report(
                results_a, manifest_a, results_b, manifest_b, _requirements()
            )

    def test_intersection_size_noted_when_one_run_has_parse_failures(self):
        manifest_a = _manifest("run_a", parse_failures=1)
        manifest_b = _manifest("run_b", parse_failures=0)
        # run_a missing REQ-003
        results_a = {
            "REQ-001": _result("REQ-001", "pass", 1.7),
            "REQ-002": _result("REQ-002", "borderline", 1.4),
        }
        results_b = {
            "REQ-001": _result("REQ-001", "pass", 1.7),
            "REQ-002": _result("REQ-002", "pass", 1.6),
            "REQ-003": _result("REQ-003", "fail", 1.1),
        }
        md = build_compare_report(results_a, manifest_a, results_b, manifest_b, _requirements())
        assert "excluded" in md.lower() or "REQ-003" in md

    def test_report_contains_required_sections(self):
        manifest_a = _manifest("run_a", prompt_version="v1")
        manifest_b = _manifest("run_b", prompt_version="v2")
        results_a = {
            "REQ-001": _result("REQ-001", "pass", 1.7),
            "REQ-002": _result("REQ-002", "borderline", 1.4),
            "REQ-003": _result("REQ-003", "fail", 1.1),
        }
        results_b = {
            "REQ-001": _result("REQ-001", "pass", 1.8),
            "REQ-002": _result("REQ-002", "pass", 1.6),
            "REQ-003": _result("REQ-003", "borderline", 1.3),
        }
        md = build_compare_report(results_a, manifest_a, results_b, manifest_b, _requirements())
        assert "## Aggregate Delta" in md
        assert "## Per-Dimension Averages" in md
        assert "## Per-Requirement Delta" in md
        assert "## Domain Breakdown" in md
        assert "## Difficulty Breakdown" in md
        assert "## Notable Changes" in md
        assert "## Conclusion" in md

    def test_regression_flagged_in_per_requirement_table(self):
        manifest_a = _manifest("run_a")
        manifest_b = _manifest("run_b")
        results_a = {"REQ-001": _result("REQ-001", "pass", 1.8)}
        results_b = {"REQ-001": _result("REQ-001", "fail", 1.0)}
        md = build_compare_report(
            results_a, manifest_a, results_b, manifest_b,
            [Requirement(requirement_id="REQ-001", requirement_text="t", domain_tag="auth", difficulty="easy")],
        )
        assert "⚠" in md

    def test_improvement_flagged_in_per_requirement_table(self):
        manifest_a = _manifest("run_a")
        manifest_b = _manifest("run_b")
        results_a = {"REQ-001": _result("REQ-001", "fail", 1.1)}
        results_b = {"REQ-001": _result("REQ-001", "pass", 1.7)}
        md = build_compare_report(
            results_a, manifest_a, results_b, manifest_b,
            [Requirement(requirement_id="REQ-001", requirement_text="t", domain_tag="auth", difficulty="easy")],
        )
        assert "✓" in md

    def test_human_review_column_shown_when_adjudicated(self):
        manifest_a = _manifest("run_a")
        manifest_b = _manifest("run_b")
        results_a = {"REQ-001": _result("REQ-001", "borderline", 1.4)}
        results_b = {"REQ-001": _result("REQ-001", "borderline", 1.4)}
        adj_dims = DimensionScores(correctness=1.0, completeness=1.0, hallucination_risk=1.0, reviewer_usefulness=2.0)
        adjudicated_a = {
            "REQ-001": ReviewRecord(
                run_id="run_a", requirement_id="REQ-001", weighted_score=1.4,
                scores=adj_dims, review_decision="pass",
            )
        }
        md = build_compare_report(
            results_a, manifest_a, results_b, manifest_b,
            [Requirement(requirement_id="REQ-001", requirement_text="t", domain_tag="auth", difficulty="easy")],
            adjudicated_a=adjudicated_a,
        )
        assert "Human" in md
        assert "pass" in md

    def test_domain_breakdown_covers_all_domains(self):
        manifest_a = _manifest("run_a")
        manifest_b = _manifest("run_b")
        results_a = {
            "REQ-001": _result("REQ-001", "pass", 1.7),
            "REQ-002": _result("REQ-002", "pass", 1.6),
            "REQ-003": _result("REQ-003", "pass", 1.8),
        }
        results_b = results_a.copy()
        md = build_compare_report(results_a, manifest_a, results_b, manifest_b, _requirements())
        assert "auth" in md
        assert "tasks" in md
        assert "search" in md

    def test_difficulty_breakdown_includes_ambiguous_row(self):
        manifest_a = _manifest("run_a")
        manifest_b = _manifest("run_b")
        requirements = [
            Requirement(requirement_id="REQ-001", requirement_text="t", domain_tag="auth", difficulty="easy"),
            Requirement(requirement_id="REQ-002", requirement_text="t", domain_tag="tasks", difficulty="ambiguous"),
        ]
        results_a = {
            "REQ-001": _result("REQ-001", "pass", 1.7),
            "REQ-002": _result("REQ-002", "borderline", 1.4),
        }
        results_b = {
            "REQ-001": _result("REQ-001", "pass", 1.8),
            "REQ-002": _result("REQ-002", "fail", 1.0),
        }

        md = build_compare_report(results_a, manifest_a, results_b, manifest_b, requirements)

        assert "| ambiguous |" in md


class TestChartInjection:
    def test_injects_before_marker_when_present(self):
        md = "# Report\n\n## Aggregate Delta\n\nBody\n"
        updated = inject_chart_markdown(
            md,
            ["![Distribution Comparison](compare.png)"],
            "## Aggregate Delta",
        )
        assert updated.index("## Charts") < updated.index("## Aggregate Delta")
        assert "![Distribution Comparison](compare.png)" in updated

    def test_appends_fallback_section_when_marker_missing(self, caplog):
        md = "# Report\n\nNo expected section.\n"
        with caplog.at_level("WARNING"):
            updated = inject_chart_markdown(
                md,
                ["![Distribution Comparison](compare.png)"],
                "## Aggregate Delta",
            )
        assert "## Charts" in updated
        assert updated.rstrip().endswith("![Distribution Comparison](compare.png)")
        assert "not found" in caplog.text
