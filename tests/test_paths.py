"""Unit tests for harness.paths and the Scorer protocol (harness.scoring)."""

from __future__ import annotations

from pathlib import Path

from harness.heuristic_scorer import HeuristicScorer
from harness.paths import ArtifactPaths, manifest_path
from harness.scorer_base import Scorer

# ---------------------------------------------------------------------------
# ArtifactPaths
# ---------------------------------------------------------------------------


class TestArtifactPaths:
    def test_run_dir(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.run_dir == Path("/data/run_abc")

    def test_scored_results(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.scored_results == Path("/data/run_abc/scored_results.json")

    def test_parse_failures(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.parse_failures == Path("/data/run_abc/parse_failures.jsonl")

    def test_output_file(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.output_file("REQ-001") == Path("/data/run_abc/REQ-001.json")

    def test_failure_marker(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.failure_marker("REQ-002") == Path("/data/run_abc/REQ-002.fail.json")

    def test_judge_sidecar(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.judge_sidecar("REQ-003") == Path("/data/run_abc/REQ-003.judge.json")

    def test_run_dir_with_nested_generated_dir(self):
        p = ArtifactPaths("/a/b/c", "run_xyz")
        assert p.run_dir == Path("/a/b/c/run_xyz")

    def test_scored_results_consistent_with_run_dir(self):
        p = ArtifactPaths("/data", "run_abc")
        assert p.scored_results.parent == p.run_dir


# ---------------------------------------------------------------------------
# manifest_path
# ---------------------------------------------------------------------------


class TestManifestPath:
    def test_manifest_path_construction(self):
        result = manifest_path("/runs", "run_xyz")
        assert result == Path("/runs/run_xyz.json")

    def test_manifest_path_with_different_run_id(self):
        result = manifest_path("/runs", "run_v2_20260329T120000Z")
        assert result == Path("/runs/run_v2_20260329T120000Z.json")

    def test_manifest_path_is_path_object(self):
        result = manifest_path("/runs", "run_xyz")
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Scorer Protocol (harness.scoring)
# ---------------------------------------------------------------------------


class TestScorerProtocol:
    def test_heuristic_scorer_satisfies_protocol(self):
        assert isinstance(HeuristicScorer(), Scorer)

    def test_llm_judge_scorer_satisfies_protocol(self):
        from harness.llm_judge import LLMJudgeScorer
        # Constructing LLMJudgeScorer() sets attributes only — no API call
        assert isinstance(LLMJudgeScorer(), Scorer)

    def test_matching_local_class_satisfies_protocol(self):
        from typing import Any

        from harness.schemas import GoldAnnotation, ModelOutput, ScoredResult

        class LocalScorer:
            def score(
                self,
                output: ModelOutput,
                gold: GoldAnnotation,
                weights: dict[str, float] | None = None,
                thresholds: dict[str, Any] | None = None,
                diagnostics: dict[str, bool] | None = None,
            ) -> ScoredResult: ...

        assert isinstance(LocalScorer(), Scorer)

    def test_object_without_score_method_is_not_scorer(self):
        assert not isinstance(object(), Scorer)

    def test_plain_function_is_not_scorer(self):
        def fn(): ...
        assert not isinstance(fn, Scorer)
