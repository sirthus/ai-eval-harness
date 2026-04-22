"""Tests for trend_report.py: trend data aggregation and filtering."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from harness.charts import inject_chart_markdown
from harness.review_queue import write_adjudicated
from harness.schemas import (
    DimensionScores,
    Requirement,
    ReviewRecord,
    RunManifest,
    RunSummary,
    ScoredResult,
    TrendReport,
)
from harness.trend_report import (
    build_trend_data,
    consistently_borderline_requirements,
    domain_pass_rates,
    render_trend_markdown,
)
from harness.trend_report import (
    run as run_trend_report,
)
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


# ---------------------------------------------------------------------------
# Human-review semantics and run grouping
# ---------------------------------------------------------------------------


def _trend_requirement(req_id: str = "REQ-001") -> Requirement:
    return Requirement(
        requirement_id=req_id,
        requirement_text=f"Requirement for {req_id}",
        domain_tag="auth",
        difficulty="easy",
    )


def _trend_result(req_id: str, decision: str, score: float) -> ScoredResult:
    return ScoredResult(
        requirement_id=req_id,
        scores=DimensionScores(
            correctness=1.5,
            completeness=1.5,
            hallucination_risk=1.5,
            reviewer_usefulness=1.5,
        ),
        weighted_score=score,
        decision=decision,
        coverage_ratio=0.67,
        disallowed_hits=[],
        scoring_notes="",
        diagnostic_notes="",
    )


def _trend_manifest(
    run_id: str,
    timestamp: str,
    prompt_version: str = "v2",
    pass_count: int = 0,
    borderline_count: int = 1,
    fail_count: int = 0,
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        model_name="claude",
        model_version="claude-3-5-sonnet-20241022",
        prompt_version=prompt_version,
        dataset_version="mvp_v2",
        scoring_version="v2",
        threshold_version="v2",
        timestamp=timestamp,
        git_commit_hash="abc1234",
        config_file="configs/run.yaml",
        total_requirements=1,
        parse_failures=0,
        total_evaluated=1,
        pass_count=pass_count,
        borderline_count=borderline_count,
        fail_count=fail_count,
        avg_weighted_score=1.35,
    )


def _write_trend_requirements(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(_trend_requirement().model_dump_json() + "\n")


def _write_trend_run_artifacts(base: Path, manifest: RunManifest, result: ScoredResult) -> None:
    runs_dir = base / "runs"
    generated_dir = base / "generated" / manifest.run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{manifest.run_id}.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (generated_dir / "scored_results.json").write_text(
        json.dumps([result.model_dump()]),
        encoding="utf-8",
    )


class TestTrendFollowups:
    def test_use_human_review_adds_annotations_but_keeps_auto_math(self, tmp_path):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_trend_requirements(dataset_path)

        base = tmp_path / "data"
        reviews_dir = base / "reviews"
        reports_dir = tmp_path / "reports"

        run_a = _trend_manifest("run_prompt_v2_20260401T120000Z", "2026-04-01T12:00:00+00:00")
        run_b = _trend_manifest("run_prompt_v2_20260402T120000Z", "2026-04-02T12:00:00+00:00")
        _write_trend_run_artifacts(base, run_a, _trend_result("REQ-001", "borderline", 1.35))
        _write_trend_run_artifacts(base, run_b, _trend_result("REQ-001", "borderline", 1.30))

        write_adjudicated(
            [
                ReviewRecord(
                    run_id=run_a.run_id,
                    requirement_id="REQ-001",
                    weighted_score=1.35,
                    scores=DimensionScores(
                        correctness=1.0,
                        completeness=1.0,
                        hallucination_risk=1.0,
                        reviewer_usefulness=2.0,
                    ),
                    review_decision="pass",
                    reviewer_notes="accepted by reviewer",
                )
            ],
            run_id=run_a.run_id,
            reviews_dir=str(reviews_dir),
        )

        md_path, csv_path = run_trend_report(
            dataset_path=str(dataset_path),
            runs_dir=str(base / "runs"),
            generated_dir=str(base / "generated"),
            reviews_dir=str(reviews_dir),
            reports_dir=str(reports_dir),
            filter_dataset="mvp_v2",
            use_human_review=True,
        )

        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert "human_decision" in rows[0]
        annotated_row = next(row for row in rows if row["run_id"] == run_a.run_id)
        assert annotated_row["decision"] == "borderline"
        assert annotated_row["human_decision"] == "pass"

        markdown = md_path.read_text(encoding="utf-8")
        assert "## Human Review Annotations" in markdown
        consistently_borderline = (
            markdown.split("## Consistently Borderline Requirements", 1)[1].split("## Domain Trends", 1)[0]
        )
        assert "- REQ-001" in consistently_borderline

    def test_run_distribution_keeps_prompt_families_separate(self, tmp_path):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_trend_requirements(dataset_path)

        base = tmp_path / "data"
        reports_dir = tmp_path / "reports"
        run_v1 = _trend_manifest(
            "run_v2_prompt_v1_20260401T120000Z",
            "2026-04-01T12:00:00+00:00",
            prompt_version="v1",
            pass_count=1,
            borderline_count=0,
        )
        run_v2 = _trend_manifest(
            "run_v2_prompt_v2_20260402T120000Z",
            "2026-04-02T12:00:00+00:00",
            prompt_version="v2",
            pass_count=1,
            borderline_count=0,
        )
        _write_trend_run_artifacts(base, run_v1, _trend_result("REQ-001", "pass", 1.8))
        _write_trend_run_artifacts(base, run_v2, _trend_result("REQ-001", "pass", 1.85))

        md_path, csv_path = run_trend_report(
            dataset_path=str(dataset_path),
            runs_dir=str(base / "runs"),
            generated_dir=str(base / "generated"),
            reviews_dir=str(base / "reviews"),
            reports_dir=str(reports_dir),
            filter_dataset="mvp_v2",
            use_human_review=False,
        )

        markdown = md_path.read_text(encoding="utf-8")
        assert "run_v2_prompt_v1 ×1" in markdown
        assert "run_v2_prompt_v2 ×1" in markdown

        with open(csv_path, encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert "human_decision" not in header
