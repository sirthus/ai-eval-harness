"""Scorer Protocol — defines the interface for all harness scorers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from harness.schemas import GoldAnnotation, ModelOutput, ScoredResult


@runtime_checkable
class Scorer(Protocol):
    """Protocol implemented by HeuristicScorer and LLMJudgeScorer."""

    def score(
        self,
        output: ModelOutput,
        gold: GoldAnnotation,
        weights: dict[str, float] | None = None,
        thresholds: dict[str, Any] | None = None,
        diagnostics: dict[str, bool] | None = None,
    ) -> ScoredResult: ...
