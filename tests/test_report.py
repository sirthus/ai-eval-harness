"""Tests for report human-review overlays."""

from __future__ import annotations

from harness.report import write_report
from harness.schemas import DimensionScores, ReviewRecord, RunManifest, ScoredResult


def _result(
    req_id: str,
    decision: str,
    scoring_notes: str = "",
    diagnostic_notes: str = "",
) -> ScoredResult:
    return ScoredResult(
        requirement_id=req_id,
        scores=DimensionScores(
            correctness=1.5,
            completeness=1.5,
            hallucination_risk=1.5,
            reviewer_usefulness=1.5,
        ),
        weighted_score={"pass": 1.8, "borderline": 1.35, "fail": 0.9}[decision],
        decision=decision,
        coverage_ratio={"pass": 1.0, "borderline": 0.67, "fail": 0.33}[decision],
        disallowed_hits=[],
        scoring_notes=scoring_notes,
        diagnostic_notes=diagnostic_notes,
    )


def _review(req_id: str, decision: str, notes: str = "") -> ReviewRecord:
    return ReviewRecord(
        run_id="run_case",
        requirement_id=req_id,
        weighted_score=1.35,
        scores=DimensionScores(
            correctness=1.0,
            completeness=1.0,
            hallucination_risk=1.0,
            reviewer_usefulness=2.0,
        ),
        review_decision=decision,
        reviewer_notes=notes,
    )


def _manifest(run_id: str = "run_case") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        model_name="claude",
        model_version="claude-3-5-sonnet-20241022",
        prompt_version="v2",
        dataset_version="mvp_v2",
        scoring_version="v2",
        threshold_version="v2",
        timestamp="2026-04-01T12:00:00+00:00",
        git_commit_hash="abc1234",
        config_file="configs/run.yaml",
        total_requirements=4,
        parse_failures=0,
        total_evaluated=4,
        pass_count=1,
        borderline_count=2,
        fail_count=1,
        avg_weighted_score=1.35,
        quality_gate_decision="needs_review",
    )


def _section(content: str, start: str, end: str) -> str:
    return content.split(start, 1)[1].split(end, 1)[0]


class TestReportHumanReviewOverlay:
    def test_post_review_aggregate_rewrites_only_adjudicated_borderlines(self, tmp_path):
        results = [
            _result("REQ-001", "pass"),
            _result("REQ-002", "borderline"),
            _result("REQ-003", "borderline"),
            _result("REQ-004", "fail"),
        ]
        adjudicated = {
            "REQ-002": _review("REQ-002", "pass"),
            "REQ-003": _review("REQ-003", "fail"),
        }

        _, md_path = write_report(results, _manifest(), str(tmp_path), adjudicated=adjudicated)
        post_review = _section(
            md_path.read_text(encoding="utf-8"),
            "### Aggregate Scores (Post-review)",
            "## Quality Gate Recommendation",
        )

        assert "| Pass | 2 (50%) |" in post_review
        assert "| Borderline | 0 (0%) |" in post_review
        assert "| Fail | 2 (50%) |" in post_review

    def test_unresolved_borderlines_remain_borderline_post_review(self, tmp_path):
        results = [
            _result("REQ-001", "borderline"),
            _result("REQ-002", "borderline"),
        ]
        adjudicated = {
            "REQ-002": _review("REQ-002", "pass"),
        }
        manifest = _manifest()
        manifest.total_requirements = 2
        manifest.total_evaluated = 2
        manifest.pass_count = 0
        manifest.borderline_count = 2
        manifest.fail_count = 0

        _, md_path = write_report(results, manifest, str(tmp_path), adjudicated=adjudicated)
        post_review = _section(
            md_path.read_text(encoding="utf-8"),
            "### Aggregate Scores (Post-review)",
            "## Quality Gate Recommendation",
        )

        assert "| Pass | 1 (50%) |" in post_review
        assert "| Borderline | 1 (50%) |" in post_review
        assert "| Fail | 0 (0%) |" in post_review

    def test_quality_gate_uses_persisted_manifest_gate_for_auto_view(self, tmp_path):
        results = [
            _result("REQ-001", "pass"),
            _result("REQ-002", "pass"),
            _result("REQ-003", "borderline"),
            _result("REQ-004", "borderline"),
        ]
        manifest = _manifest()
        manifest.pass_count = 2
        manifest.borderline_count = 2
        manifest.fail_count = 0
        manifest.parse_failures = 1
        manifest.quality_gate_decision = "fail"

        _, md_path = write_report(results, manifest, str(tmp_path))
        quality_gate = _section(
            md_path.read_text(encoding="utf-8"),
            "## Quality Gate Recommendation",
            "## Per-Sample Results",
        )

        assert "Auto gate: ✗ Not recommended" in quality_gate
        assert "persisted manifest gate" in quality_gate
        assert "parse failures 1" in quality_gate
        assert "Recommended for assisted internal use" not in quality_gate

    def test_quality_gate_shows_auto_and_post_review_recommendations(self, tmp_path):
        results = [
            _result("REQ-001", "pass"),
            _result("REQ-002", "pass"),
            _result("REQ-003", "borderline"),
            _result("REQ-004", "borderline"),
        ]
        adjudicated = {
            "REQ-003": _review("REQ-003", "pass", notes="good enough"),
            "REQ-004": _review("REQ-004", "pass"),
        }
        manifest = _manifest()
        manifest.pass_count = 2
        manifest.borderline_count = 2
        manifest.fail_count = 0
        manifest.quality_gate_decision = "needs_review"

        _, md_path = write_report(results, manifest, str(tmp_path), adjudicated=adjudicated)
        quality_gate = _section(
            md_path.read_text(encoding="utf-8"),
            "## Quality Gate Recommendation",
            "## Per-Sample Results",
        )

        assert "| Auto (persisted gate) | ~ Needs review |" in quality_gate
        assert "| Post-review outlook |" in quality_gate
        assert "Recommended for assisted internal use with reviewer oversight" in quality_gate
        assert "not persisted to the manifest" in quality_gate

    def test_per_sample_markdown_table_escapes_pipes_and_newlines(self, tmp_path):
        results = [
            _result(
                "REQ-001",
                "fail",
                scoring_notes="judge | rationale\nsecond line",
                diagnostic_notes="diagnostic | detail\nnext line",
            )
        ]

        _, md_path = write_report(results, _manifest(), str(tmp_path))
        markdown = md_path.read_text(encoding="utf-8")

        assert "judge \\| rationale<br>second line" in markdown
        assert "diagnostic \\| detail<br>next line" in markdown

    def test_run_summary_shows_missing_requirements_and_scorer_fallbacks(self, tmp_path):
        manifest = _manifest()
        manifest.missing_requirements = 1
        manifest.scorer_fallback_count = 2

        _, md_path = write_report([_result("REQ-001", "pass")], manifest, str(tmp_path))
        markdown = md_path.read_text(encoding="utf-8")

        assert "| Missing requirements | 1 |" in markdown
        assert "| Scorer fallbacks | 2 |" in markdown
