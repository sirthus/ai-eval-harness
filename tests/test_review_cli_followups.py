"""Regression tests for review CLI gold-path resolution."""

from __future__ import annotations


import pytest
import yaml

from harness.review_cli import _resolve_gold_path, run as review_run
from harness.review_queue import write_queue
from harness.schemas import DimensionScores, RunManifest, ScoredResult


def _manifest(config_file: str) -> RunManifest:
    return RunManifest(
        run_id="run_case",
        model_name="claude",
        model_version="claude-3-5-sonnet-20241022",
        prompt_version="v2",
        dataset_version="mvp_v2",
        scoring_version="v2",
        threshold_version="v2",
        timestamp="2026-04-01T12:00:00+00:00",
        git_commit_hash="abc1234",
        config_file=config_file,
        total_requirements=1,
        parse_failures=0,
        total_evaluated=1,
        pass_count=0,
        borderline_count=1,
        fail_count=0,
        avg_weighted_score=1.35,
    )


def _borderline_result(req_id: str = "REQ-001") -> ScoredResult:
    return ScoredResult(
        requirement_id=req_id,
        scores=DimensionScores(
            correctness=1.0,
            completeness=1.0,
            hallucination_risk=1.0,
            reviewer_usefulness=2.0,
        ),
        weighted_score=1.35,
        decision="borderline",
        coverage_ratio=0.67,
        disallowed_hits=[],
        scoring_notes="",
    )


class TestGoldPathResolution:
    def test_resolves_gold_path_from_manifest_and_config(self, tmp_path):
        runs_dir = tmp_path / "data" / "runs"
        runs_dir.mkdir(parents=True)
        gold_path = tmp_path / "data" / "gold" / "gold.jsonl"
        gold_path.parent.mkdir(parents=True)
        gold_path.write_text("", encoding="utf-8")

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        config_path = config_dir / "run.yaml"
        config_path.write_text(yaml.safe_dump({"gold_path": "data/gold/gold.jsonl"}), encoding="utf-8")

        manifest = _manifest(config_file="configs/run.yaml")
        (runs_dir / "run_case.json").write_text(manifest.model_dump_json(), encoding="utf-8")

        resolved = _resolve_gold_path(None, run_id="run_case", runs_dir=str(runs_dir))
        assert resolved == gold_path

    def test_run_fails_clearly_when_manifest_cannot_resolve_gold(self, tmp_path):
        reviews_dir = tmp_path / "reviews"
        write_queue([_borderline_result()], run_id="run_case", reviews_dir=str(reviews_dir))

        with pytest.raises(FileNotFoundError, match="Pass --gold-path explicitly"):
            review_run(
                run_id="run_case",
                reviews_dir=str(reviews_dir),
                generated_dir=str(tmp_path / "generated"),
                runs_dir=str(tmp_path / "data" / "runs"),
                gold_path=None,
            )

    def test_run_exits_nonzero_when_queue_is_missing(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            review_run(
                run_id="run_case",
                reviews_dir=str(tmp_path / "reviews"),
                generated_dir=str(tmp_path / "generated"),
                runs_dir=str(tmp_path / "data" / "runs"),
                gold_path=None,
            )
        assert exc_info.value.code == 1

    def test_run_returns_cleanly_when_queue_is_empty(self, tmp_path, capsys):
        queue_dir = tmp_path / "reviews" / "run_case"
        queue_dir.mkdir(parents=True)
        (queue_dir / "queue.jsonl").write_text("", encoding="utf-8")

        review_run(
            run_id="run_case",
            reviews_dir=str(tmp_path / "reviews"),
            generated_dir=str(tmp_path / "generated"),
            runs_dir=str(tmp_path / "data" / "runs"),
            gold_path=None,
        )

        out = capsys.readouterr().out
        assert "Review queue is empty" in out
        assert not (queue_dir / "adjudicated.jsonl").exists()
