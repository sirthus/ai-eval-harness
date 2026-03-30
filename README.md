# AI QA Evaluation Harness

A Python evaluation harness for AI-generated QA test cases. Given a requirement snippet, an LLM generates structured JSON test cases; the harness validates the output, scores it against a gold dataset, routes borderline cases to human review, and produces per-run, comparison, and trend reports.

## Current Status

Phase 3 is implemented. The repo now includes:

- a unified `python -m harness` CLI
- optional chart generation for reports
- an optional LLM-as-judge scorer
- persisted run-level quality gates
- a second prompt/model configuration path for comparison work
- CI checks for tests and recent evaluation quality

## Install

Core development install:

```bash
pip install -e ".[dev]"
```

Install chart support too:

```bash
pip install -e ".[dev,charts]"
```

Set the Anthropic API key before generation or LLM-judge runs:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

## Recommended CLI

Phase 3 adds a unified CLI. This is the preferred entry point:

```bash
python -m harness <subcommand> ...
```

Available subcommands:

- `run` — full pipeline
- `generate` — generation only
- `evaluate` — scoring only
- `report` — per-run report
- `review` — human adjudication of borderline items
- `compare` — side-by-side comparison of two runs
- `trend` — multi-run history report

Legacy module entry points still exist, but the unified CLI is what the current docs use.

## Common Workflows

Run the full pipeline:

```bash
python -m harness run --config configs/run_v2_prompt_v2.yaml
```

Run the Phase 3 alternate model/prompt config:

```bash
python -m harness run --config configs/run_v3_haiku.yaml
```

Run individual development steps:

```bash
python -m harness generate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
python -m harness evaluate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
```

Generate a per-run report:

```bash
python -m harness report \
    --config configs/run_v2_prompt_v2.yaml \
    --run-id run_v2_prompt_v2_20260329T143022Z
```

Generate a per-run report with human-review overlay and charts:

```bash
python -m harness report \
    --config configs/run_v2_prompt_v2.yaml \
    --run-id run_v2_prompt_v2_20260329T143022Z \
    --use-human-review \
    --charts
```

Review borderline cases:

```bash
python -m harness review --run-id run_v2_prompt_v2_20260329T143022Z
```

Compare two runs:

```bash
python -m harness compare \
    --run-a run_v2_prompt_v1_20260329T120000Z \
    --run-b run_v2_prompt_v2_20260329T143022Z \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl \
    --charts
```

Build a trend report:

```bash
python -m harness trend \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl \
    --charts
```

## Datasets and Tracks

The current repo supports these main evaluation tracks:

| Track | Dataset | Gold | Prompt / Config | Purpose |
|---|---|---|---|---|
| Phase 1 baseline | `mvp_dataset.jsonl` (10 requirements) | `gold_test_cases.jsonl` | `run_v1.yaml`, prompt `v1` | Small baseline run |
| Phase 2 workflow | `mvp_dataset_v2.jsonl` (40 requirements) | `gold_test_cases_v2.jsonl` | `run_v2_prompt_v1.yaml`, `run_v2_prompt_v2.yaml` | Prompt comparison, review workflow, trend analysis |
| Phase 3 comparison path | `mvp_dataset_v2.jsonl` (40 requirements) | `gold_test_cases_v2.jsonl` | `run_v3_haiku.yaml`, prompt `v3` | Second model/prompt path for comparison |

## Scoring Model

### Dimensions

Scores are on a `0.0-2.0` scale:

| Dimension | Weight | Purpose |
|---|---|---|
| Correctness | 0.35 | Whether the generated tests are materially valid |
| Completeness | 0.30 | Whether required coverage points are addressed |
| Hallucination risk | 0.20 | Whether the output invents unsupported behavior |
| Reviewer usefulness | 0.15 | Whether the tests are clear and reviewable |

### Sample decision bands

| Band | Condition |
|---|---|
| Pass | Weighted average `>= 1.6` and all floor dimensions meet threshold |
| Borderline | Weighted average `1.2-1.59` with floor dimensions met |
| Fail | Weighted average `< 1.2` or any floor dimension below threshold |

Floors currently require `correctness >= 1.0`, `completeness >= 1.0`, and `hallucination_risk >= 1.0`.

### Scorer modes

The harness supports two scorer modes:

- `heuristic` — default rule-based scorer
- `llm-judge` — judge-model scorer in [llm_judge.py](/mnt/c/Users/dalli/github/ai-eval-harness/src/harness/llm_judge.py)

Scorer choice is configured in YAML and persisted to the run manifest as `scorer_type`.

When `llm-judge` is enabled:

- the judge sees generated output plus gold coverage criteria
- the judge does not see the raw requirement text
- per-sample judge sidecars are written as `{requirement_id}.judge.json`
- expected operational failures fall back to heuristic scoring

## Quality Gate

Each run manifest stores a `quality_gate_decision`:

- `pass`
- `needs_review`
- `fail`

Current gate policy:

- `pass` if pass rate is at least `70%`, borderline count is at most `2`, and parse failures are `0`
- `fail` if pass rate is below `40%`
- `needs_review` if the run is not a pass or fail but still has borderlines or parse failures
- `fail` otherwise

This gate is used in the rich CLI summary, persisted run manifests, markdown reporting, and the CI advisory check.

## Human Review Model

Borderline samples are routed to `data/reviews/{run_id}/queue.jsonl`. Human adjudication is a separate overlay, not a rewrite of automated artifacts.

Canonical automated artifacts:

- `data/generated/{run_id}/scored_results.json`
- `data/runs/{run_id}.json`

Human review artifacts:

- `data/reviews/{run_id}/queue.jsonl`
- `data/reviews/{run_id}/adjudicated.jsonl`

When `--use-human-review` is enabled in report commands:

- per-run reports show both the persisted auto gate and a separate post-review outlook
- compare reports show human decisions alongside auto decisions when available
- trend reports keep run math auto-based and add human-review context only

See [docs/review_workflow.md](/mnt/c/Users/dalli/github/ai-eval-harness/docs/review_workflow.md) for the full review workflow.

## Output Artifacts

A typical run writes:

- `data/generated/{run_id}/REQ-*.json` for valid model outputs
- `data/generated/{run_id}/{requirement_id}.fail.json` for parse or schema failures
- `data/generated/{run_id}/parse_failures.jsonl` for aggregated parse failure records
- `data/generated/{run_id}/{requirement_id}.judge.json` when LLM-judge scoring is active
- `data/generated/{run_id}/scored_results.json` for scored samples
- `data/reviews/{run_id}/queue.jsonl` for borderline items
- `data/reviews/{run_id}/adjudicated.jsonl` for completed review decisions
- `data/runs/{run_id}.json` for the run manifest
- `reports/{run_id}_scores.csv` and `reports/{run_id}_report.md` for per-run reporting
- timestamped compare and trend markdown and CSV artifacts under `reports/`
- optional PNG charts written alongside the corresponding markdown report

## CI Quality Check

Phase 3 adds an advisory quality-gate checker:

```bash
python scripts/check_quality_gate.py --runs-dir data/runs --last 5
```

It reads recent manifests and exits non-zero if any recent run has `quality_gate_decision == "fail"`.

## Tests

Run the full suite:

```bash
pytest
```

Useful focused suites:

```bash
pytest tests/test_llm_judge.py
pytest tests/test_cli.py
pytest tests/test_charts.py
pytest tests/test_compare_report.py
pytest tests/test_trend_report.py
pytest tests/test_report_followups.py
```

## Repository Map

```text
src/harness/
  __main__.py         unified `python -m harness` entry point
  cli.py              unified rich CLI
  run_eval.py         full pipeline orchestration
  generate.py         model generation step
  evaluate.py         scoring step
  score.py            heuristic scoring logic
  llm_judge.py        optional LLM-as-judge scorer
  review_queue.py     review queue persistence
  review_cli.py       interactive review workflow
  report.py           per-run CSV + markdown reporting
  compare_report.py   side-by-side run comparison
  trend_report.py     multi-run trend reporting
  charts.py           optional PNG chart generation
  schemas.py          Pydantic models for datasets and artifacts
  model_adapter.py    Anthropic model adapter
  prompts/
    v1.txt
    v2.txt
    v3.txt
    judge_v1.txt

configs/
  run_v1.yaml
  run_v2_prompt_v1.yaml
  run_v2_prompt_v2.yaml
  run_v3_haiku.yaml

scripts/
  check_quality_gate.py

docs/
  dataset_design.md
  review_workflow.md
```

## Boundaries

This repo is intentionally narrow:

- no UI
- no RAG or vector search
- no autonomous agent workflows
- no dashboard product layer
- no attempt to treat raw model output as ground truth
