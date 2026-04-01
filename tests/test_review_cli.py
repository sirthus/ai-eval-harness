"""Tests for the interactive review CLI."""

from __future__ import annotations

import json


from harness.review_cli import adjudicate, _load_model_output, _load_scored_result
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
