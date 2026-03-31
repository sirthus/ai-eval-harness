# Engineering Brief

This repository evaluates AI-generated QA test cases from requirement snippets.

Its core claim is:

> A compact, disciplined harness can measure whether an LLM produces useful QA test cases by combining structured generation, explicit scoring, human review, and repeatable reporting.

## Architecture Summary

The system is intentionally pipeline-shaped.

1. `generate.py` calls the model and writes structured JSON outputs per requirement.
2. `evaluate.py` validates and scores those outputs against gold annotations.
3. `review_queue.py` routes borderline results into a separate human-review path.
4. `report.py`, `compare_report.py`, and `trend_report.py` turn run artifacts into decision-support outputs.
5. `run_eval.py` coordinates the full flow and persists a run manifest with traceability metadata.

This design keeps each concern narrow:

- generation is separate from scoring
- automated scoring is separate from human review
- report generation is separate from artifact creation
- experiment metadata is separate from display-only summaries

## Major Design Choices

| Choice | Why it matters |
|---|---|
| Schema-first model output | Keeps generation measurable and parseable instead of relying on prose evaluation |
| Gold annotations instead of exact-string matching | Lets the scorer reason about coverage points and disallowed assumptions rather than brittle literal matches |
| Borderline review queue | Acknowledges that some samples need human judgment instead of pretending automation is fully reliable |
| Immutable auto-scored artifacts | Preserves a clean audit trail and keeps adjudication as an overlay |
| Explicit scorer mode | Makes heuristic vs judge-model runs comparable and traceable |
| Run-level quality gates | Turns report findings into an operational recommendation artifact |
| Same-dataset comparison rule | Prevents misleading deltas between runs evaluated on different ground truth |

## Why This Design Matters

This repo emphasizes:

- evaluation thinking rather than prompt-only iteration
- careful data and artifact modeling
- human-in-the-loop workflow design
- traceability and experiment hygiene
- concise CLI tooling around a composable core

## Current Boundaries

This is not a general QA platform.

It intentionally does not include:

- a UI
- a dashboard layer
- RAG or vector search
- autonomous agent workflows
- production-scale orchestration

The project is strongest as a focused evaluation harness, not as an end-user product.

## What To Read Next

- [README.md](README.md) for the project overview
- [docs/architecture.md](docs/architecture.md) for the system flow and artifact lifecycle
- [docs/report_examples.md](docs/report_examples.md) for the reporting outputs and how to interpret them
- [docs/dataset_design.md](docs/dataset_design.md) for dataset and annotation design
- [docs/review_workflow.md](docs/review_workflow.md) for the human-review layer
- [docs/history/README.md](docs/history/README.md) for archived implementation plans
