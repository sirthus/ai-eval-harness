# AI QA Evaluation Harness

A Python evaluation harness that measures whether an LLM can turn requirement snippets into useful QA test cases, using schema validation, rubric-based scoring, human review, and repeatable reporting.

Implemented through Phase 3. The current system includes:

- structured test-case generation through Anthropic models
- heuristic scoring and optional LLM-as-judge scoring
- a human review queue for borderline samples
- per-run, compare, and trend reporting
- persisted run manifests, quality gates, and optional charts

The core question this project answers is:

> Is this model and prompt combination reliable enough to assist QA test design, and where does it still require human review?

This is an evaluation problem, not a generation problem. Every run produces auditable artifacts, explicit pass/fail/review outcomes, and experiment history — not a single anecdotal headline score.

## Evaluation Design

- schema-first generation and validation for structured QA artifacts
- rubric-based scoring with weighted dimensions and floor rules
- human-in-the-loop review for borderline cases
- experiment traceability through run IDs, manifests, persisted scorer choice, and quality gates
- side-by-side comparison and trend reporting across prompt or model variants

## What It Accomplishes

| Area | Implemented |
|---|---|
| Generation | Requirement snippet -> structured JSON test cases |
| Validation | Pydantic schema validation plus parse-failure artifacts |
| Evaluation | Four-dimension scoring with `heuristic` and `llm-judge` modes |
| Review | Borderline routing, adjudication records, and report overlays |
| Reporting | Per-run markdown and CSV, compare reports, trend reports, optional PNG charts |
| Traceability | Timestamped run IDs, git metadata, config capture, and quality-gate decisions |

Current evaluation tracks:

| Track | Dataset | Gold | Configs | Purpose |
|---|---|---|---|---|
| Baseline | `mvp_dataset.jsonl` | `gold_test_cases.jsonl` | `configs/run_v1.yaml` | Small Phase 1 baseline |
| Prompt comparison | `mvp_dataset_v2.jsonl` | `gold_test_cases_v2.jsonl` | `configs/run_v2_prompt_v1.yaml`, `configs/run_v2_prompt_v2.yaml` | Prompt comparison on the primary working dataset |
| Alternate model path | `mvp_dataset_v2.jsonl` | `gold_test_cases_v2.jsonl` | `configs/run_v3_haiku.yaml` | Second model or prompt comparison path |

## System At A Glance

```mermaid
flowchart LR
    A["Requirement snippets"] --> B["Generate structured JSON test cases"]
    B --> C["Schema validation and parse-failure artifacts"]
    C --> D["Heuristic or LLM-judge scoring"]
    D --> E["Borderline review queue"]
    D --> F["Run manifest and per-run report"]
    E --> G["Human adjudication overlay"]
    F --> H["Compare and trend reports"]
    G --> H
```

![Synthetic CLI run summary](docs/assets/cli_run_summary.svg)

## Quickstart

Install the project:

```bash
pip install -e ".[dev]"
```

Install chart support too:

```bash
pip install -e ".[dev,charts]"
```

Set `ANTHROPIC_API_KEY` in your shell or a local `.env` file before generation or `llm-judge` runs.

Run the full pipeline:

```bash
python -m harness run --config configs/run_v2_prompt_v2.yaml
```

Useful follow-up commands:

```bash
python -m harness report  --config configs/run_v2_prompt_v2.yaml --run-id <run_id> --charts
python -m harness review  --run-id <run_id>
python -m harness compare --run-a <run_a> --run-b <run_b> --dataset-path data/requirements/mvp_dataset_v2.jsonl --charts
python -m harness trend   --dataset-path data/requirements/mvp_dataset_v2.jsonl --charts
```

The unified CLI is the recommended entry point:

```bash
python -m harness <subcommand>
```

Available subcommands:

- `run`
- `generate`
- `evaluate`
- `report`
- `review`
- `compare`
- `trend`

## How To Explore This Repo

1. Read this README for the project claim, scope, and quickstart.
2. Read [PROJECT.md](PROJECT.md) for the engineering brief and major design choices.
3. Read [docs/architecture.md](docs/architecture.md) for the end-to-end system flow and artifact model.
4. Read [docs/report_examples.md](docs/report_examples.md) for synthetic examples of the outputs this harness produces.
5. Read [docs/dataset_design.md](docs/dataset_design.md) and [docs/review_workflow.md](docs/review_workflow.md) for the dataset and human-review details.
6. Read [docs/history/README.md](docs/history/README.md) only if you want the implementation-history planning documents.

## Audit Trail

Each run writes a full set of inspectable artifacts rather than a single headline number.

- valid generations are written as `{requirement_id}.json`
- parse or schema failures are written as `{requirement_id}.fail.json` and aggregated in `parse_failures.jsonl`
- scored results are persisted in `scored_results.json`
- each run writes a manifest containing model, prompt, dataset, scorer, thresholds, timestamp, git hash, and quality gate
- optional judge-model verdicts are written as `{requirement_id}.judge.json`
- borderline review happens in a separate `data/reviews/{run_id}/` artifact path

That separation is intentional: automated artifacts stay immutable, while human review remains an overlay.

## Deliberate Boundaries

The scope is intentionally narrow:

- no UI or dashboard product layer
- no RAG or vector search
- no autonomous agent workflows
- no attempt to treat raw model output as ground truth
- no large-scale distributed evaluation infrastructure

Those are design choices that keep the evaluation problem crisp and inspectable, not missing polish.

## Historical Design Records

The original implementation plans are preserved under [docs/history/README.md](docs/history/README.md). They show how the project was built through staged phases, but they are intentionally out of the main reader path so the primary docs stay focused on current behavior.
