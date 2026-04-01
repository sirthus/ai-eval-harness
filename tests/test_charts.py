"""Tests for chart generation. All tests require matplotlib — skipped if not installed."""

from __future__ import annotations


import pytest

pytest.importorskip("matplotlib", reason="matplotlib not installed; run pip install -e '.[charts]'")

from harness import charts
from harness.schemas import DimensionScores, ScoredResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    req_id: str = "REQ-001",
    decision: str = "pass",
    weighted_score: float = 1.8,
    correctness: float = 2.0,
    completeness: float = 2.0,
    hallucination_risk: float = 2.0,
    reviewer_usefulness: float = 1.0,
    coverage_ratio: float = 1.0,
) -> ScoredResult:
    return ScoredResult(
        requirement_id=req_id,
        scores=DimensionScores(
            correctness=correctness,
            completeness=completeness,
            hallucination_risk=hallucination_risk,
            reviewer_usefulness=reviewer_usefulness,
        ),
        weighted_score=weighted_score,
        decision=decision,
        coverage_ratio=coverage_ratio,
    )


def _sample_results() -> list[ScoredResult]:
    return [
        _make_result("REQ-001", "pass", 1.8),
        _make_result("REQ-002", "borderline", 1.4, correctness=1.0, completeness=1.0),
        _make_result("REQ-003", "fail", 0.8, correctness=0.0, completeness=0.0),
        _make_result("REQ-004", "pass", 1.9),
        _make_result("REQ-005", "pass", 2.0),
    ]


# ---------------------------------------------------------------------------
# Per-run charts
# ---------------------------------------------------------------------------


class TestPlotScoreDistribution:
    def test_creates_png_file(self, tmp_path):
        results = _sample_results()
        path = charts.plot_score_distribution(results, "run_test", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
        assert path.stat().st_size > 500

    def test_filename_contains_run_id(self, tmp_path):
        results = _sample_results()
        path = charts.plot_score_distribution(results, "my_run_id", tmp_path)
        assert "my_run_id" in path.name

    def test_empty_results_does_not_raise(self, tmp_path):
        path = charts.plot_score_distribution([], "run_empty", tmp_path)
        assert path is not None
        assert path.exists()


class TestPlotDimensionScores:
    def test_creates_png_file(self, tmp_path):
        results = _sample_results()
        path = charts.plot_dimension_scores(results, "run_test", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500

    def test_empty_results_does_not_raise(self, tmp_path):
        path = charts.plot_dimension_scores([], "run_empty", tmp_path)
        assert path is not None
        assert path.exists()


class TestPlotPerRequirementScores:
    def test_creates_png_file(self, tmp_path):
        results = _sample_results()
        path = charts.plot_per_requirement_scores(results, "run_test", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500

    def test_single_result_does_not_raise(self, tmp_path):
        path = charts.plot_per_requirement_scores(
            [_make_result("REQ-001", "pass", 1.8)], "run_single", tmp_path
        )
        assert path is not None
        assert path.exists()


# ---------------------------------------------------------------------------
# Compare report charts
# ---------------------------------------------------------------------------


class TestPlotCompareDistribution:
    def test_creates_png_file(self, tmp_path):
        results_a = _sample_results()
        results_b = [_make_result(r.requirement_id, "pass", 1.9) for r in results_a]
        path = charts.plot_compare_distribution(
            results_a, results_b, "run_a", "run_b", tmp_path
        )
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500


class TestPlotCompareDelta:
    def test_creates_png_file(self, tmp_path):
        results_a = {r.requirement_id: r for r in _sample_results()}
        results_b = {
            req_id: _make_result(req_id, "pass", 1.9)
            for req_id in results_a
        }
        path = charts.plot_compare_delta(results_a, results_b, "run_a", "run_b", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500

    def test_returns_none_for_empty_intersection(self, tmp_path):
        path = charts.plot_compare_delta({}, {}, "run_a", "run_b", tmp_path)
        assert path is None


# ---------------------------------------------------------------------------
# Trend report charts
# ---------------------------------------------------------------------------


class TestPlotTrendPassRate:
    def test_creates_png_file(self, tmp_path):
        trend_data = [
            {"run_id": "run_v2_20260301T120000Z", "pass_rate": 0.6, "borderline_rate": 0.2},
            {"run_id": "run_v2_20260302T120000Z", "pass_rate": 0.7, "borderline_rate": 0.1},
            {"run_id": "run_v2_20260303T120000Z", "pass_rate": 0.8, "borderline_rate": 0.1},
        ]
        path = charts.plot_trend_pass_rate(trend_data, tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500

    def test_returns_none_for_empty_data(self, tmp_path):
        path = charts.plot_trend_pass_rate([], tmp_path)
        assert path is None


class TestPlotDomainHeatmap:
    def test_creates_png_file(self, tmp_path):
        domain_data = {
            "auth": {"run_a": 0.8, "run_b": 0.9},
            "billing": {"run_a": 0.5, "run_b": 0.7},
            "search": {"run_a": 0.6, "run_b": 0.6},
        }
        run_ids = ["run_a", "run_b"]
        path = charts.plot_domain_heatmap(domain_data, run_ids, tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 500

    def test_returns_none_for_empty_data(self, tmp_path):
        path = charts.plot_domain_heatmap({}, [], tmp_path)
        assert path is None


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_returns_none_when_matplotlib_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(charts, "_MATPLOTLIB_AVAILABLE", False)
        path = charts.plot_score_distribution(_sample_results(), "run_test", tmp_path)
        assert path is None

    def test_dimension_scores_returns_none_when_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(charts, "_MATPLOTLIB_AVAILABLE", False)
        path = charts.plot_dimension_scores(_sample_results(), "run_test", tmp_path)
        assert path is None
