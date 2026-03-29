"""Pydantic v2 schemas for the evaluation harness."""

from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class TestCase(BaseModel):
    title: str
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    priority: Literal["high", "medium", "low"]
    type: Literal["positive", "negative", "edge_case", "boundary", "permission"]


class ModelOutput(BaseModel):
    requirement_id: str
    test_cases: Annotated[list[TestCase], Field(min_length=1)]
    assumptions: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Dataset schemas
# ---------------------------------------------------------------------------


class Requirement(BaseModel):
    requirement_id: str
    requirement_text: str
    domain_tag: str
    difficulty: Literal["easy", "medium", "hard"]


class GoldAnnotation(BaseModel):
    requirement_id: str
    required_coverage_points: list[str]
    # Per-point variant phrases: key = coverage point, value = list of alternative phrases
    # A variant credits its specific coverage point, not an arbitrary uncovered one.
    acceptable_variants: dict[str, list[str]] = Field(default_factory=dict)
    disallowed_assumptions: list[str] = Field(default_factory=list)
    review_notes: str = ""
    gold_test_cases: list[TestCase] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring schemas
# ---------------------------------------------------------------------------


class DimensionScores(BaseModel):
    correctness: Annotated[float, Field(ge=0.0, le=2.0)]
    completeness: Annotated[float, Field(ge=0.0, le=2.0)]
    hallucination_risk: Annotated[float, Field(ge=0.0, le=2.0)]
    reviewer_usefulness: Annotated[float, Field(ge=0.0, le=2.0)]


class ScoredResult(BaseModel):
    requirement_id: str
    scores: DimensionScores
    weighted_score: float
    decision: Literal["pass", "borderline", "fail"]
    coverage_ratio: float
    disallowed_hits: list[str] = Field(default_factory=list)
    scoring_notes: str = ""
    diagnostic_notes: str = ""


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------


class RunManifest(BaseModel):
    run_id: str
    model_name: str
    model_version: str
    prompt_version: str
    dataset_version: str
    scoring_version: str
    threshold_version: str
    timestamp: str
    git_commit_hash: str
    config_file: str
    total_requirements: int = 0
    parse_failures: int = 0
    total_evaluated: int = 0
    pass_count: int = 0
    borderline_count: int = 0
    fail_count: int = 0
    avg_weighted_score: float = 0.0


# ---------------------------------------------------------------------------
# Review record
# ---------------------------------------------------------------------------


class ReviewRecord(BaseModel):
    run_id: str
    requirement_id: str
    weighted_score: float
    scores: DimensionScores
    review_decision: Literal["pending", "pass", "fail", "escalate"] = "pending"
    reviewer_notes: str = ""
    reviewed_at: str | None = None
    final_scores: DimensionScores | None = None


# ---------------------------------------------------------------------------
# Trend schemas
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    run_id: str
    timestamp: str
    model_version: str
    prompt_version: str
    dataset_version: str
    pass_count: int
    borderline_count: int
    fail_count: int
    total_evaluated: int
    parse_failures: int
    avg_weighted_score: float


class TrendReport(BaseModel):
    generated_at: str
    runs: list[RunSummary]
    per_requirement_history: dict[str, list[dict]]  # req_id → [{run_id, decision, weighted_score}]
    consistently_borderline: list[str]              # req_ids borderline in >50% of runs
    domain_pass_rates: dict[str, dict[str, float]]  # domain → {run_id → pass_rate}
