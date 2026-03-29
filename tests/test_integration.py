"""End-to-end smoke test using synthetic fixtures. No API calls required.

Tests the full pipeline:
1. evaluate.run() equivalent (direct scoring)
2. review_queue.write_queue()
3. report.write_report()
4. trend_report.build_trend_data() with two synthetic runs
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from harness.evaluate import _write_scored_results
from harness.report import write_report
from harness.review_queue import write_queue
from harness.schemas import (
    DimensionScores,
    GoldAnnotation,
    ModelOutput,
    Requirement,
    RunManifest,
    ScoredResult,
    TestCase,
)
from harness.score import score
from harness.trend_report import build_trend_data


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------


def _tc(title: str, tc_type: str = "positive", steps: int = 3) -> TestCase:
    return TestCase(
        title=title,
        preconditions=["system is available"],
        steps=[f"step {i}" for i in range(steps)],
        expected_result="System behaves as expected",
        priority="high",
        type=tc_type,
    )


def _output(req_id: str, high_quality: bool = True) -> ModelOutput:
    if high_quality:
        return ModelOutput(
            requirement_id=req_id,
            test_cases=[
                _tc(f"Happy path {req_id}", tc_type="positive"),
                _tc(f"Error path {req_id}", tc_type="negative"),
                _tc(f"Edge case {req_id}", tc_type="edge_case"),
            ],
            assumptions=[],
            notes="",
        )
    else:
        return ModelOutput(
            requirement_id=req_id,
            test_cases=[_tc(f"Minimal {req_id}")],
            assumptions=["assumption A", "assumption B", "assumption C", "assumption D"],
            notes="under-specified requirement, coverage gaps documented",
        )


def _gold(req_id: str) -> GoldAnnotation:
    return GoldAnnotation(
        requirement_id=req_id,
        required_coverage_points=["system behaves", "error path"],
        acceptable_variants={"system behaves": ["expected"], "error path": ["failure"]},
        disallowed_assumptions=[],
        review_notes="",
    )


def _manifest(run_id: str, pass_count: int, borderline_count: int, fail_count: int) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        model_name="claude",
        model_version="claude-3-5-sonnet-20241022",
        prompt_version="v1",
        dataset_version="mvp_v2",
        scoring_version="v2",
        threshold_version="v2",
        timestamp="2026-04-01T12:00:00+00:00",
        git_commit_hash="abc1234",
        config_file="configs/run_v2_prompt_v1.yaml",
        total_requirements=40,
        parse_failures=0,
        total_evaluated=40,
        pass_count=pass_count,
        borderline_count=borderline_count,
        fail_count=fail_count,
        avg_weighted_score=1.65,
    )


def _requirements(n: int = 40) -> list[Requirement]:
    domains = ["auth", "tasks", "search", "permissions", "notifications",
               "billing", "api", "data_export", "onboarding"]
    difficulties = ["easy", "medium", "hard"]
    return [
        Requirement(
            requirement_id=f"REQ-{i:03d}",
            requirement_text=f"Requirement {i} text",
            domain_tag=domains[i % len(domains)],
            difficulty=difficulties[i % len(difficulties)],
        )
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_score_40_synthetic_outputs(self):
        """Score 40 synthetic outputs and verify distribution."""
        req_ids = [f"REQ-{i:03d}" for i in range(1, 41)]
        outputs = [_output(rid, high_quality=(i % 5 != 0)) for i, rid in enumerate(req_ids)]
        golds = [_gold(rid) for rid in req_ids]

        results = [score(o, g) for o, g in zip(outputs, golds)]

        passes = sum(1 for r in results if r.decision == "pass")
        fails = sum(1 for r in results if r.decision == "fail")

        assert len(results) == 40
        assert passes >= 20, f"Expected at least 50% pass, got {passes}/40"
        assert fails <= 12, f"Expected at most 30% fail, got {fails}/40"
        assert all(r.requirement_id.startswith("REQ-") for r in results)

    def test_write_queue_produces_borderline_items(self, tmp_path):
        """Borderline results are written to the review queue."""
        req_ids = [f"REQ-{i:03d}" for i in range(1, 11)]
        outputs = [_output(rid, high_quality=False) for rid in req_ids]
        golds = [_gold(rid) for rid in req_ids]
        results = [score(o, g) for o, g in zip(outputs, golds)]

        borderlines = [r for r in results if r.decision == "borderline"]
        if borderlines:
            queue_path = write_queue(results, run_id="run_integ_test", reviews_dir=str(tmp_path))
            assert queue_path.exists()
            lines = [l for l in queue_path.read_text().splitlines() if l.strip()]
            assert len(lines) == len(borderlines)

    def test_write_report_produces_well_formed_markdown_and_csv(self, tmp_path):
        """write_report produces non-empty, well-formed markdown and CSV."""
        req_ids = [f"REQ-{i:03d}" for i in range(1, 11)]
        results = [
            ScoredResult(
                requirement_id=rid,
                scores=DimensionScores(correctness=2.0, completeness=2.0,
                                       hallucination_risk=2.0, reviewer_usefulness=2.0),
                weighted_score=2.0,
                decision="pass",
                coverage_ratio=1.0,
            )
            for rid in req_ids
        ]
        manifest = _manifest("run_integ_test", pass_count=10, borderline_count=0, fail_count=0)
        csv_path, md_path = write_report(results, manifest, str(tmp_path))

        assert md_path.exists()
        md_content = md_path.read_text(encoding="utf-8")
        assert "# Evaluation Report" in md_content
        assert "run_integ_test" in md_content
        assert len(md_content) > 500

        assert csv_path.exists()
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 10
        assert "auto_decision" in rows[0]

    def test_trend_report_with_two_synthetic_runs(self, tmp_path):
        """trend_report.build_trend_data works with two synthetic runs on same dataset."""
        gen_dir = tmp_path / "generated"
        req_ids = [f"REQ-{i:03d}" for i in range(1, 11)]
        requirements = [
            Requirement(
                requirement_id=rid,
                requirement_text=f"Req {rid}",
                domain_tag=["auth", "tasks"][i % 2],
                difficulty=["easy", "medium", "hard"][i % 3],
            )
            for i, rid in enumerate(req_ids)
        ]

        # Write two runs
        manifests = []
        for run_num, (timestamp, decision) in enumerate(
            [("2026-04-01T12:00:00+00:00", "pass"), ("2026-04-02T12:00:00+00:00", "borderline")],
            1,
        ):
            run_id = f"run_{run_num:03d}"
            run_dir = gen_dir / run_id
            run_dir.mkdir(parents=True)
            scored = [
                ScoredResult(
                    requirement_id=rid,
                    scores=DimensionScores(correctness=1.5, completeness=1.5,
                                           hallucination_risk=2.0, reviewer_usefulness=1.5),
                    weighted_score=1.65,
                    decision=decision,
                    coverage_ratio=0.75,
                )
                for rid in req_ids
            ]
            (run_dir / "scored_results.json").write_text(
                json.dumps([r.model_dump() for r in scored]), encoding="utf-8"
            )
            manifests.append(_manifest(run_id, pass_count=5, borderline_count=3, fail_count=2))
            manifests[-1].timestamp = timestamp

        trend = build_trend_data(
            manifests,
            generated_dir=str(gen_dir),
            requirements=requirements,
            filter_dataset="mvp_v2",
        )

        assert len(trend.runs) == 2
        assert len(trend.per_requirement_history) == len(req_ids)
        for req_id in req_ids:
            assert len(trend.per_requirement_history[req_id]) == 2
        # All same dataset, so domain rates should be populated
        assert "auth" in trend.domain_pass_rates or "tasks" in trend.domain_pass_rates
