# Architecture

Related docs: [README](../README.md), [PROJECT.md](../PROJECT.md), [Report Examples](report_examples.md), [Dataset Design](dataset_design.md), [Review Workflow](review_workflow.md)

## Overview

The harness evaluates AI-generated QA test cases as a pipeline of persisted artifacts.

That design choice matters. Instead of producing a one-off score in memory, the repo writes each step to disk so a reviewer can inspect what was generated, what failed, how it was scored, what was escalated to human review, and what recommendation the run produced.

## End-To-End Flow

1. A requirement dataset is loaded from `data/requirements/`.
2. `generate.py` calls the model and writes one structured JSON file per requirement.
3. Parse or schema failures are written as explicit failure artifacts instead of being silently dropped.
4. `evaluate.py` scores each valid output against gold annotations from `data/gold/`.
5. Borderline results are written to a separate review queue.
6. `report.py` writes a per-run markdown and CSV report.
7. `compare_report.py` compares two compatible runs.
8. `trend_report.py` aggregates multiple runs into a historical view.
9. `run_eval.py` persists a run manifest with model, prompt, dataset, thresholds, scorer mode, git metadata, and quality-gate outcome.

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `generate.py` | Model invocation orchestration and output artifact writing |
| `loaders.py` | Shared config, dataset, manifest, and scored-result loading helpers |
| `paths.py` | Canonical artifact-path helpers for generated outputs and run manifests |
| `model_adapter.py` | Anthropic client integration, prompt loading, retries, and response parsing |
| `schemas.py` | Shared data contracts for datasets, outputs, scores, reviews, and manifests |
| `heuristic_scorer.py` | Heuristic scorer implementation and score computation |
| `scorer_base.py` | Stable `Scorer` protocol shared by heuristic and judge scorers |
| `llm_judge.py` | Optional scorer that uses a second model as a semantic judge |
| `evaluate.py` | Gold loading, generated-output loading, config-driven scorer selection, and scored-result persistence |
| `review_queue.py` | Borderline queue and adjudication persistence |
| `review_cli.py` | Human adjudication workflow in the terminal |
| `report.py` | Per-run reporting |
| `compare_report.py` | Side-by-side comparison reporting |
| `trend_report.py` | Multi-run historical reporting |
| `run_eval.py` | Full-pipeline orchestration, review/report sequencing, and run-manifest creation |

## Persisted Artifacts

| Artifact | Purpose |
|---|---|
| `data/generated/{run_id}/{requirement_id}.json` | Canonical valid generated output |
| `data/generated/{run_id}/{requirement_id}.fail.json` | Canonical parse or schema failure marker |
| `data/generated/{run_id}/parse_failures.jsonl` | Aggregated parse-failure log |
| `data/generated/{run_id}/{requirement_id}.judge.json` | Optional LLM-judge sidecar audit record |
| `data/generated/{run_id}/scored_results.json` | Canonical scored results for the run |
| `data/reviews/{run_id}/queue.jsonl` | Borderline samples awaiting review |
| `data/reviews/{run_id}/adjudicated.jsonl` | Completed review decisions |
| `data/runs/{run_id}.json` | Run manifest and quality-gate summary |
| `reports/*.md` and `reports/*.csv` | Human-readable per-run, compare, and trend outputs |

Artifact locations are centralized through shared path helpers so the canonical layout stays consistent across pipeline steps.

## Scoring Model

The harness supports two scorer modes:

- `heuristic`: rule-based scoring against coverage points, floor thresholds, and structural signals
- `llm-judge`: a second model evaluates semantic coverage and scoring rationales, with heuristic fallback on expected judge failures

`evaluate.py` resolves scorer choice from config in both standalone and full-pipeline runs, and both scorer implementations share the same stable interface.

Both modes converge on the same persisted `ScoredResult` shape so reporting and comparison stay stable.

The four scoring dimensions are:

- correctness
- completeness
- hallucination risk
- reviewer usefulness

Weighted scores determine `pass`, `borderline`, or `fail`, but floor rules prevent a sample from passing when key quality dimensions fall below minimum thresholds.

## Quality Gate Semantics

Each run persists a `quality_gate_decision` in its manifest:

- `pass`
- `needs_review`
- `fail`

This is a policy artifact, not just display text. It is used in the CLI summary, markdown reporting, and the CI advisory quality check. That gives the repo a clear answer to the operational question, “Is this run good enough to recommend, or does it still need review?”

## Human Review Layer

Human review is intentionally designed as an overlay.

- automated scoring writes the canonical run artifacts
- only borderline samples are routed to review
- reviewer decisions live in `data/reviews/`, not in the generated or scored artifacts
- reports can optionally show human-review context without rewriting auto-scored history

This separation keeps the audit trail clean and makes it obvious which conclusions came from automation versus a reviewer.

## Compare And Trend Reporting

The repo has three levels of reporting:

- per-run: “What happened in this evaluation?”
- compare: “How did run B differ from run A on the same dataset?”
- trend: “How is behavior changing over time across runs?”

Comparison reporting is only meaningful when both runs use the same dataset version. Trend reporting keeps auto-scored math stable even when human-review annotations are present, which avoids mixing adjudicated context into the historical baseline.

## Design Choices

- **Small datasets by design**: the harness demonstrates evaluation discipline, not scale for its own sake.
- **Persist everything important**: generation, scoring, review, and manifests are all inspectable after the run.
- **Separate artifacts by role**: generated outputs, scored outputs, reviews, and reports each live in a distinct path.
- **Keep the CLI thin**: business logic lives in independently testable modules; the CLI only dispatches and formats.

## Architectural Rationale

- ambiguity is modeled explicitly rather than collapsed into a single pass/fail
- evaluation is treated as a system design problem, with artifact lifecycle and traceability as first-class concerns
- automation and human review are kept clearly separated so it is always obvious which conclusions came from which source
