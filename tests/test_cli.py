"""Tests for the unified CLI entry point (cli.py)."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from harness.cli import make_parser, print_results_table, print_run_summary
from harness.schemas import RunManifest, ScoredResult
from tests.factories import make_run_manifest, make_scored_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manifest(
    run_id: str = "run_test_20260329T120000Z",
    pass_count: int = 7,
    borderline_count: int = 2,
    fail_count: int = 1,
    avg_score: float = 1.72,
    parse_failures: int = 0,
    scorer_type: str = "heuristic",
) -> RunManifest:
    total = pass_count + borderline_count + fail_count
    return make_run_manifest(
        run_id=run_id,
        config_file="configs/run_v2_prompt_v2.yaml",
        total_requirements=total,
        parse_failures=parse_failures,
        total_evaluated=total,
        pass_count=pass_count,
        borderline_count=borderline_count,
        fail_count=fail_count,
        avg_weighted_score=avg_score,
        scorer_type=scorer_type,
    )


def _make_result(req_id: str, decision: str = "pass", score: float = 1.8) -> ScoredResult:
    return make_scored_result(requirement_id=req_id, decision=decision, weighted_score=score, coverage_ratio=1.0)


def _capture_console() -> tuple[Console, StringIO]:
    """Create a Console that writes to a StringIO buffer."""
    buffer = StringIO()
    console = Console(file=buffer, highlight=False, markup=True, force_terminal=True)
    return console, buffer


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestMakeParser:
    def test_run_subcommand_requires_config(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])  # missing --config

    def test_run_subcommand_accepts_config(self):
        parser = make_parser()
        args = parser.parse_args(["run", "--config", "configs/run_v1.yaml"])
        assert args.config == "configs/run_v1.yaml"
        assert args.subcommand == "run"

    def test_review_subcommand_requires_run_id(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["review"])  # missing --run-id

    def test_review_subcommand_accepts_run_id(self):
        parser = make_parser()
        args = parser.parse_args(["review", "--run-id", "run_test_123"])
        assert args.run_id == "run_test_123"

    def test_compare_requires_run_a(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["compare", "--run-b", "run_b", "--dataset-path", "data/d.jsonl"])

    def test_compare_requires_run_b(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["compare", "--run-a", "run_a", "--dataset-path", "data/d.jsonl"])

    def test_compare_requires_dataset_path(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["compare", "--run-a", "run_a", "--run-b", "run_b"])

    def test_compare_accepts_all_required_args(self):
        parser = make_parser()
        args = parser.parse_args([
            "compare", "--run-a", "run_a", "--run-b", "run_b",
            "--dataset-path", "data/reqs.jsonl",
        ])
        assert args.run_a == "run_a"
        assert args.run_b == "run_b"

    def test_trend_requires_dataset_path(self):
        parser = make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["trend"])

    def test_unknown_subcommand_exits_nonzero(self):
        parser = make_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["nonexistent"])
        assert exc_info.value.code != 0

    def test_report_charts_flag_defaults_false(self):
        parser = make_parser()
        args = parser.parse_args(["report", "--config", "configs/run.yaml"])
        assert args.charts is False

    def test_report_charts_flag_set_true(self):
        parser = make_parser()
        args = parser.parse_args(["report", "--config", "configs/run.yaml", "--charts"])
        assert args.charts is True


# ---------------------------------------------------------------------------
# print_run_summary tests
# ---------------------------------------------------------------------------


class TestPrintRunSummary:
    def test_pass_gate_renders_run_id(self):
        manifest = _make_manifest(pass_count=8, borderline_count=1, fail_count=1)
        console, buf = _capture_console()
        print_run_summary(manifest, console)
        output = buf.getvalue()
        assert "run_test_20260329T120000Z" in output

    def test_shows_pass_borderline_fail_counts(self):
        manifest = _make_manifest(pass_count=7, borderline_count=2, fail_count=1)
        console, buf = _capture_console()
        print_run_summary(manifest, console)
        output = buf.getvalue()
        assert "7" in output
        assert "2" in output
        assert "1" in output

    def test_shows_scorer_type(self):
        manifest = _make_manifest(scorer_type="llm-judge")
        console, buf = _capture_console()
        print_run_summary(manifest, console)
        output = buf.getvalue()
        assert "llm-judge" in output

    def test_shows_avg_score(self):
        manifest = _make_manifest(avg_score=1.72)
        console, buf = _capture_console()
        print_run_summary(manifest, console)
        output = buf.getvalue()
        assert "1.72" in output

    def test_panel_text_includes_run_complete(self):
        manifest = _make_manifest()
        console, buf = _capture_console()
        print_run_summary(manifest, console)
        output = buf.getvalue()
        assert "Run Complete" in output


# ---------------------------------------------------------------------------
# print_results_table tests
# ---------------------------------------------------------------------------


class TestPrintResultsTable:
    def test_table_contains_all_requirement_ids(self):
        results = [
            _make_result("REQ-001", "pass"),
            _make_result("REQ-002", "borderline"),
            _make_result("REQ-003", "fail"),
        ]
        console, buf = _capture_console()
        print_results_table(results, console)
        output = buf.getvalue()
        assert "REQ-001" in output
        assert "REQ-002" in output
        assert "REQ-003" in output

    def test_table_shows_decision_labels(self):
        results = [
            _make_result("REQ-001", "pass"),
            _make_result("REQ-002", "fail"),
        ]
        console, buf = _capture_console()
        print_results_table(results, console)
        output = buf.getvalue()
        assert "pass" in output
        assert "fail" in output

    def test_human_decision_column_absent_without_adjudicated(self):
        results = [_make_result("REQ-001", "pass")]
        console, buf = _capture_console()
        print_results_table(results, console)
        output = buf.getvalue()
        assert "Human" not in output

    def test_human_decision_column_present_with_adjudicated(self):
        results = [_make_result("REQ-001", "borderline")]
        console, buf = _capture_console()
        print_results_table(results, console, adjudicated={})
        output = buf.getvalue()
        assert "Human" in output

    def test_empty_results_does_not_raise(self):
        console, buf = _capture_console()
        print_results_table([], console)
        # Should produce a (potentially empty) table without error

    def test_results_sorted_by_requirement_id(self):
        results = [
            _make_result("REQ-010", "pass"),
            _make_result("REQ-001", "pass"),
            _make_result("REQ-005", "fail"),
        ]
        console, buf = _capture_console()
        print_results_table(results, console)
        output = buf.getvalue()
        pos_001 = output.index("REQ-001")
        pos_005 = output.index("REQ-005")
        pos_010 = output.index("REQ-010")
        assert pos_001 < pos_005 < pos_010
