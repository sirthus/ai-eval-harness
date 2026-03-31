"""Shared test factory functions for ai-eval-harness tests.

Plain module-level factories — import directly: ``from tests.factories import ...``
Pytest fixtures that need scope or teardown should live in a conftest.py file.
"""

from __future__ import annotations

from harness.schemas import (
    DimensionScores,
    GoldAnnotation,
    ModelOutput,
    Requirement,
    RunManifest,
    ScoredResult,
    TestCase,
)


def make_test_case(
    title: str = "Login succeeds",
    preconditions: list[str] | None = None,
    steps: list[str] | None = None,
    expected_result: str = "User is redirected to dashboard",
    priority: str = "high",
    tc_type: str = "positive",
) -> TestCase:
    return TestCase(
        title=title,
        preconditions=preconditions if preconditions is not None else ["Application is running"],
        steps=steps if steps is not None else ["Open login page", "Enter credentials", "Submit"],
        expected_result=expected_result,
        priority=priority,
        type=tc_type,
    )


def make_model_output(
    requirement_id: str = "REQ-001",
    test_cases: list[TestCase] | None = None,
    assumptions: list[str] | None = None,
    notes: str = "",
) -> ModelOutput:
    return ModelOutput(
        requirement_id=requirement_id,
        test_cases=test_cases if test_cases is not None else [make_test_case()],
        assumptions=assumptions if assumptions is not None else [],
        notes=notes,
    )


def make_gold_annotation(
    requirement_id: str = "REQ-001",
    coverage_points: list[str] | None = None,
    variants: dict[str, list[str]] | None = None,
    disallowed: list[str] | None = None,
) -> GoldAnnotation:
    return GoldAnnotation(
        requirement_id=requirement_id,
        required_coverage_points=coverage_points if coverage_points is not None else [
            "valid credentials grant access",
            "invalid credentials are rejected",
        ],
        acceptable_variants=variants if variants is not None else {},
        disallowed_assumptions=disallowed if disallowed is not None else [],
    )


def make_run_manifest(
    run_id: str = "run_test_20260329T120000Z",
    model_name: str = "claude",
    model_version: str = "claude-sonnet-4-6",
    prompt_version: str = "v2",
    dataset_version: str = "mvp_v2",
    scoring_version: str = "v2",
    threshold_version: str = "v2",
    timestamp: str = "2026-03-29T12:00:00+00:00",
    git_commit_hash: str = "abc1234",
    config_file: str = "configs/run_v2.yaml",
    total_requirements: int = 10,
    parse_failures: int = 0,
    total_evaluated: int = 10,
    pass_count: int = 8,
    borderline_count: int = 1,
    fail_count: int = 1,
    avg_weighted_score: float = 1.72,
    scorer_type: str = "heuristic",
    quality_gate_decision: str = "needs_review",
    **extra,
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        model_name=model_name,
        model_version=model_version,
        prompt_version=prompt_version,
        dataset_version=dataset_version,
        scoring_version=scoring_version,
        threshold_version=threshold_version,
        timestamp=timestamp,
        git_commit_hash=git_commit_hash,
        config_file=config_file,
        total_requirements=total_requirements,
        parse_failures=parse_failures,
        total_evaluated=total_evaluated,
        pass_count=pass_count,
        borderline_count=borderline_count,
        fail_count=fail_count,
        avg_weighted_score=avg_weighted_score,
        scorer_type=scorer_type,
        quality_gate_decision=quality_gate_decision,
        **extra,
    )


def make_scored_result(
    requirement_id: str = "REQ-001",
    decision: str = "pass",
    weighted_score: float = 1.8,
    coverage_ratio: float = 0.8,
    correctness: float = 2.0,
    completeness: float = 2.0,
    hallucination_risk: float = 2.0,
    reviewer_usefulness: float = 1.0,
) -> ScoredResult:
    return ScoredResult(
        requirement_id=requirement_id,
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


def make_small_requirements_list() -> list[Requirement]:
    return [
        Requirement(
            requirement_id="REQ-001",
            requirement_text="Auth login",
            domain_tag="auth",
            difficulty="easy",
        ),
        Requirement(
            requirement_id="REQ-002",
            requirement_text="Task creation",
            domain_tag="tasks",
            difficulty="medium",
        ),
        Requirement(
            requirement_id="REQ-003",
            requirement_text="Search filters",
            domain_tag="search",
            difficulty="hard",
        ),
    ]
