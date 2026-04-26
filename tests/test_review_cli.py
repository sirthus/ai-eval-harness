"""Tests for the interactive review CLI and gold-path resolution."""

from __future__ import annotations

import json

from harness.review_cli import _load_model_output, _load_scored_result, _resolve_repo_relative_path, adjudicate
from harness.review_queue import load_queue, write_queue
from harness.schemas import DimensionScores, ModelOutput, ReviewRecord, ScoredResult, TestCase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(req_id: str, run_id: str = "run_test") -> ReviewRecord:
    return ReviewRecord(
        run_id=run_id,
        requirement_id=req_id,
        weighted_score=1.35,
        scores=DimensionScores(
            correctness=1.0,
            completeness=1.0,
            hallucination_risk=1.0,
            reviewer_usefulness=2.0,
        ),
        review_decision="pending",
    )


def _make_output(req_id: str) -> ModelOutput:
    return ModelOutput(
        requirement_id=req_id,
        test_cases=[
            TestCase(
                title=f"Happy path for {req_id}",
                preconditions=["system is running"],
                steps=["navigate to feature", "perform action", "verify result"],
                expected_result="System behaves as expected",
                priority="high",
                type="positive",
            ),
            TestCase(
                title=f"Error path for {req_id}",
                preconditions=["system is running"],
                steps=["trigger error condition"],
                expected_result="Error is handled gracefully",
                priority="medium",
                type="negative",
            ),
        ],
        assumptions=[],
        notes="",
    )


def _make_scored(req_id: str, decision: str = "borderline") -> ScoredResult:
    return ScoredResult(
        requirement_id=req_id,
        scores=DimensionScores(
            correctness=1.0,
            completeness=1.0,
            hallucination_risk=1.0,
            reviewer_usefulness=2.0,
        ),
        weighted_score=1.35,
        decision=decision,
        coverage_ratio=0.67,
        disallowed_hits=[],
        scoring_notes="",
    )


# ---------------------------------------------------------------------------
# adjudicate() with simulated inputs
# ---------------------------------------------------------------------------


class TestAdjudicate:
    def test_pass_decision_recorded(self, tmp_path):
        records = [_make_record("REQ-001")]
        inputs = iter(["p", ""])  # decision=pass, notes=empty

        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )
        assert updated[0].review_decision == "pass"
        assert updated[0].reviewed_at is not None

    def test_fail_decision_with_notes(self, tmp_path):
        records = [_make_record("REQ-001")]
        inputs = iter(["f", "wrong scores are bad"])

        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )
        assert updated[0].review_decision == "fail"
        assert updated[0].reviewer_notes == "wrong scores are bad"

    def test_skip_leaves_item_pending(self, tmp_path):
        records = [_make_record("REQ-001"), _make_record("REQ-002")]
        inputs = iter(["s", "p", ""])  # skip first, pass second

        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )
        # First item was skipped → stays pending
        assert updated[0].review_decision == "pending"
        # Second item was passed
        assert updated[1].review_decision == "pass"

    def test_quit_saves_decisions_made_so_far(self, tmp_path):
        records = [_make_record("REQ-001"), _make_record("REQ-002"), _make_record("REQ-003")]
        inputs = iter(["p", "", "q"])  # pass first, quit before second

        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )
        assert updated[0].review_decision == "pass"
        # Remaining items stay pending after quit
        assert updated[1].review_decision == "pending"
        assert updated[2].review_decision == "pending"

    def test_empty_queue_returns_early(self, tmp_path, capsys):
        # No pending items
        records = [
            ReviewRecord(
                run_id="run_test",
                requirement_id="REQ-001",
                weighted_score=1.35,
                scores=DimensionScores(correctness=1.0, completeness=1.0,
                                       hallucination_risk=1.0, reviewer_usefulness=2.0),
                review_decision="pass",
            )
        ]
        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: "p",
        )
        out = capsys.readouterr().out
        assert "No pending" in out
        assert updated[0].review_decision == "pass"  # unchanged

    def test_invalid_input_reprompts(self, tmp_path):
        records = [_make_record("REQ-001")]
        inputs = iter(["x", "z", "p", ""])  # two bad inputs then pass

        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )
        assert updated[0].review_decision == "pass"


# ---------------------------------------------------------------------------
# queue.jsonl rewritten correctly after session
# ---------------------------------------------------------------------------


class TestQueuePersistence:
    def test_queue_rewritten_with_updated_decisions(self, tmp_path):
        # Write a queue, adjudicate it, verify file is updated
        results = [_make_scored("REQ-001"), _make_scored("REQ-002")]
        run_id = "run_persist_test"
        reviews_dir = str(tmp_path / "reviews")

        queue_path = write_queue(results, run_id=run_id, reviews_dir=reviews_dir)
        records = load_queue(queue_path)

        inputs = iter(["p", "reviewed carefully", "f", "not good enough"])
        updated = adjudicate(
            records,
            generated_dir=str(tmp_path / "generated"),
            gold_path=str(tmp_path / "gold.jsonl"),
            input_fn=lambda _: next(inputs),
        )

        # Rewrite queue
        with open(queue_path, "w", encoding="utf-8") as f:
            for record in updated:
                f.write(record.model_dump_json() + "\n")

        reloaded = load_queue(queue_path)
        assert reloaded[0].review_decision == "pass"
        assert reloaded[1].review_decision == "fail"


# ---------------------------------------------------------------------------
# adjudicated.jsonl contains only non-pending records
# ---------------------------------------------------------------------------


class TestAdjudicatedFile:
    def test_adjudicated_jsonl_contains_only_decided(self, tmp_path):
        from harness.review_queue import write_adjudicated

        records = [
            _make_record("REQ-001"),
            _make_record("REQ-002"),
        ]
        # Manually set one as decided
        records[0].review_decision = "pass"

        path = write_adjudicated(records, run_id="run_adj_test", reviews_dir=str(tmp_path))
        lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        # Only the decided one should be written
        assert len(lines) == 1
        assert lines[0]["requirement_id"] == "REQ-001"
        assert lines[0]["review_decision"] == "pass"


# ---------------------------------------------------------------------------
# Context loaders
# ---------------------------------------------------------------------------


class TestContextLoaders:
    def test_load_model_output_returns_none_when_missing(self, tmp_path):
        result = _load_model_output(str(tmp_path / "generated"), "run_x", "REQ-001")
        assert result is None

    def test_load_model_output_reads_correctly(self, tmp_path):
        run_dir = tmp_path / "generated" / "run_x"
        run_dir.mkdir(parents=True)
        output = _make_output("REQ-001")
        (run_dir / "REQ-001.json").write_text(output.model_dump_json(), encoding="utf-8")

        loaded = _load_model_output(str(tmp_path / "generated"), "run_x", "REQ-001")
        assert loaded is not None
        assert loaded.requirement_id == "REQ-001"
        assert len(loaded.test_cases) == 2

    def test_load_scored_result_reads_correctly(self, tmp_path):
        run_dir = tmp_path / "generated" / "run_x"
        run_dir.mkdir(parents=True)
        scored = _make_scored("REQ-001")
        scored2 = _make_scored("REQ-002")
        (run_dir / "scored_results.json").write_text(
            json.dumps([scored.model_dump(), scored2.model_dump()]), encoding="utf-8"
        )

        result = _load_scored_result(str(tmp_path / "generated"), "run_x", "REQ-001")
        assert result is not None
        assert result.requirement_id == "REQ-001"


# ---------------------------------------------------------------------------
# Gold-path resolution
# ---------------------------------------------------------------------------


import pytest  # noqa: E402
import yaml  # noqa: E402

from harness.review_cli import _resolve_gold_path  # noqa: E402
from harness.review_cli import run as review_run  # noqa: E402


def _make_manifest_for_config(config_file: str):
    from harness.schemas import RunManifest as _RunManifest
    return _RunManifest(
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


def _borderline_result(req_id: str = "REQ-001"):
    return _make_scored(req_id, "borderline")


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

        manifest = _make_manifest_for_config(config_file="configs/run.yaml")
        (runs_dir / "run_case.json").write_text(manifest.model_dump_json(), encoding="utf-8")

        resolved = _resolve_gold_path(None, run_id="run_case", runs_dir=str(runs_dir))
        assert resolved == gold_path

    def test_run_fails_clearly_when_manifest_cannot_resolve_gold(self, tmp_path):
        reviews_dir = tmp_path / "reviews"
        write_queue([_make_scored("REQ-001", "borderline")], run_id="run_case", reviews_dir=str(reviews_dir))

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


# ---------------------------------------------------------------------------
# _resolve_repo_relative_path
# ---------------------------------------------------------------------------


class TestResolveRepoRelativePath:
    def test_absolute_path_returned_as_is(self, tmp_path):
        target = tmp_path / "gold.jsonl"
        target.touch()
        config_path = tmp_path / "configs" / "run.yaml"
        result = _resolve_repo_relative_path(str(target), config_path)
        assert result == target

    def test_relative_path_found_via_config_parent(self, tmp_path):
        # Layout: tmp_path/configs/run.yaml, tmp_path/configs/gold.jsonl
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        gold = config_dir / "gold.jsonl"
        gold.touch()
        config_path = config_dir / "run.yaml"
        result = _resolve_repo_relative_path("gold.jsonl", config_path)
        assert result == gold

    def test_relative_path_found_via_config_grandparent(self, tmp_path):
        # Layout: tmp_path/configs/run.yaml, tmp_path/gold.jsonl
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        gold = tmp_path / "gold.jsonl"
        gold.touch()
        config_path = config_dir / "run.yaml"
        result = _resolve_repo_relative_path("gold.jsonl", config_path)
        assert result == gold

    def test_no_candidate_exists_returns_first(self, tmp_path):
        config_path = tmp_path / "configs" / "run.yaml"
        result = _resolve_repo_relative_path("missing.jsonl", config_path)
        # Falls back to the raw path (first candidate) — no error raised
        from pathlib import Path
        assert result == Path("missing.jsonl")
