"""Regression tests for trend report human-review semantics and run grouping."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from harness.review_queue import write_adjudicated
from harness.schemas import DimensionScores, Requirement, ReviewRecord, RunManifest, ScoredResult
from harness.trend_report import run as run_trend_report


def _requirement(req_id: str = "REQ-001") -> Requirement:
    return Requirement(
        requirement_id=req_id,
        requirement_text=f"Requirement for {req_id}",
        domain_tag="auth",
        difficulty="easy",
    )


def _result(req_id: str, decision: str, score: float) -> ScoredResult:
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


def _manifest(
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


def _write_requirements(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(_requirement().model_dump_json() + "\n")


def _write_run_artifacts(base: Path, manifest: RunManifest, result: ScoredResult) -> None:
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
        _write_requirements(dataset_path)

        base = tmp_path / "data"
        reviews_dir = base / "reviews"
        reports_dir = tmp_path / "reports"

        run_a = _manifest("run_prompt_v2_20260401T120000Z", "2026-04-01T12:00:00+00:00")
        run_b = _manifest("run_prompt_v2_20260402T120000Z", "2026-04-02T12:00:00+00:00")
        _write_run_artifacts(base, run_a, _result("REQ-001", "borderline", 1.35))
        _write_run_artifacts(base, run_b, _result("REQ-001", "borderline", 1.30))

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
        consistently_borderline = markdown.split("## Consistently Borderline Requirements", 1)[1].split("## Domain Trends", 1)[0]
        assert "- REQ-001" in consistently_borderline

    def test_run_distribution_keeps_prompt_families_separate(self, tmp_path):
        dataset_path = tmp_path / "requirements.jsonl"
        _write_requirements(dataset_path)

        base = tmp_path / "data"
        reports_dir = tmp_path / "reports"
        run_v1 = _manifest(
            "run_v2_prompt_v1_20260401T120000Z",
            "2026-04-01T12:00:00+00:00",
            prompt_version="v1",
            pass_count=1,
            borderline_count=0,
        )
        run_v2 = _manifest(
            "run_v2_prompt_v2_20260402T120000Z",
            "2026-04-02T12:00:00+00:00",
            prompt_version="v2",
            pass_count=1,
            borderline_count=0,
        )
        _write_run_artifacts(base, run_v1, _result("REQ-001", "pass", 1.8))
        _write_run_artifacts(base, run_v2, _result("REQ-001", "pass", 1.85))

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
