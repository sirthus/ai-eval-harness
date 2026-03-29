# AI QA Evaluation Harness

A Python evaluation harness for AI-generated QA test cases. Given a requirement snippet, an LLM generates structured JSON test cases; the harness validates that output, scores it against a gold dataset, routes borderline cases to human review, and produces reports for per-run analysis, side-by-side prompt comparison, and multi-run trends.

---

## What This Repo Does

The current repo supports two evaluation tracks:

| Track | Dataset | Gold | Prompt(s) | Purpose |
|---|---|---|---|---|
| Phase 1 baseline | `mvp_dataset.jsonl` (10 requirements) | `gold_test_cases.jsonl` | `v1` | Small baseline run |
| Phase 2 current workflow | `mvp_dataset_v2.jsonl` (40 requirements) | `gold_test_cases_v2.jsonl` | `v1`, `v2` | Prompt comparison, human review, trend analysis |

A full run:

1. Loads requirements from JSONL
2. Prompts Claude for structured JSON test cases
3. Validates the response against the schema
4. Scores the output across four dimensions
5. Writes generated outputs, scored results, a review queue, a run manifest, and a report

`run_eval.py` creates timestamped run IDs such as `run_v2_prompt_v2_20260329T143022Z`, so each invocation writes to an isolated output directory.

---

## Evaluation Method

### Scoring dimensions (0–2 scale each)

| Dimension | Weight | What it measures |
|---|---|---|
| Correctness | 0.35 | Are the generated test cases materially correct relative to the requirement? Phase 2 uses a structural proxy: disallowed hits plus minimum test-case count. |
| Completeness | 0.30 | Are required coverage points addressed? |
| Hallucination risk | 0.20 | Does the output invent unsupported behavior or assumptions? |
| Reviewer usefulness | 0.15 | Are the test cases clear, concrete, and reviewable? |

### Decision bands

| Band | Condition |
|---|---|
| **Pass** | Weighted average ≥ 1.6 and all floor dimensions meet threshold |
| **Borderline** | Weighted average 1.2–1.59 and floor dimensions met |
| **Fail** | Weighted average < 1.2, or any floor dimension below threshold |

A floor violation always fails, even if the weighted average is otherwise high.

### Gold dataset philosophy

Each requirement defines:

- `required_coverage_points`
- `acceptable_variants`
- `disallowed_assumptions`
- optional `review_notes`
- optional example `gold_test_cases`

Coverage is phrase-based, not semantic reasoning. `acceptable_variants` are keyed to specific coverage points, so a synonym only credits the point it belongs to.

---

## Human Review Semantics

Auto-scored artifacts are canonical and immutable:

- `data/generated/{run_id}/scored_results.json`
- `data/runs/{run_id}.json`

Human review is a separate overlay built from:

- `data/reviews/{run_id}/queue.jsonl`
- `data/reviews/{run_id}/adjudicated.jsonl`

When `--use-human-review` is enabled:

- `report.py` keeps auto decisions visible and adds a post-review aggregate plus post-review quality-gate view for adjudicated borderline items only
- `compare_report.py` shows human decisions alongside auto decisions when adjudications exist
- `trend_report.py` stays auto-based for pass rates, consistency, borderline detection, and domain trends; human review is added as markdown annotations and an optional `human_decision` CSV column

Only parse/schema validation failures create persistent `{requirement_id}.fail.json` markers and append to `parse_failures.jsonl`. Transient model/API failures abort generation so incomplete runs are not silently treated as valid evaluation artifacts.

See [docs/review_workflow.md](docs/review_workflow.md) for the full review workflow.

---

## How to Run

### Prerequisites

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=your_key_here
```

### Phase 2 prompt comparison

```bash
python -m harness.run_eval --config configs/run_v2_prompt_v1.yaml
python -m harness.run_eval --config configs/run_v2_prompt_v2.yaml
```

### Review borderline cases from one run

```bash
python -m harness.review_cli --run-id run_v2_prompt_v2_TIMESTAMP
```

Optional review CLI flags:

- `--gold-path` to point directly at a gold file
- `--runs-dir` if manifests are stored outside `data/runs`

### Generate a per-run report

```bash
python -m harness.report \
    --config configs/run_v2_prompt_v2.yaml \
    --run-id run_v2_prompt_v2_TIMESTAMP
```

### Generate a per-run report with human review overlay

```bash
python -m harness.report \
    --config configs/run_v2_prompt_v2.yaml \
    --run-id run_v2_prompt_v2_TIMESTAMP \
    --use-human-review
```

### Compare two runs

```bash
python -m harness.compare_report \
    --run-a run_v2_prompt_v1_TIMESTAMP \
    --run-b run_v2_prompt_v2_TIMESTAMP \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl
```

### Compare two runs with human decisions shown

```bash
python -m harness.compare_report \
    --run-a run_v2_prompt_v1_TIMESTAMP \
    --run-b run_v2_prompt_v2_TIMESTAMP \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl \
    --use-human-review
```

### Trend report across multiple runs

```bash
python -m harness.trend_report \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl
```

### Trend report with human-review annotations

```bash
python -m harness.trend_report \
    --dataset-path data/requirements/mvp_dataset_v2.jsonl \
    --use-human-review
```

### Phase 1 baseline

```bash
python -m harness.run_eval --config configs/run_v1.yaml
```

### Individual development steps

```bash
python -m harness.generate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
python -m harness.evaluate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
```

---

## Output Artifacts

A typical full run writes:

- `data/generated/{run_id}/REQ-*.json` for successful model outputs
- `data/generated/{run_id}/{requirement_id}.fail.json` for parse/schema failures
- `data/generated/{run_id}/parse_failures.jsonl` for aggregated parse/schema failure records
- `data/generated/{run_id}/scored_results.json` for scored samples
- `data/reviews/{run_id}/queue.jsonl` for borderline items
- `data/reviews/{run_id}/adjudicated.jsonl` for completed human decisions
- `data/runs/{run_id}.json` for the run manifest
- `reports/{run_id}_scores.csv` and `reports/{run_id}_report.md` for per-run reporting
- timestamped comparison and trend reports under `reports/`

---

## Tests

```bash
pytest                            # all tests (no API key needed)
pytest tests/test_scoring.py
pytest tests/test_scoring_v2.py
pytest tests/test_review_cli.py
pytest tests/test_compare_report.py
pytest tests/test_trend_report.py
pytest tests/test_generate_followups.py
pytest tests/test_report_followups.py
pytest tests/test_trend_followups.py
pytest tests/test_integration.py
```

---

## Repository Map

```text
src/harness/
  run_eval.py         orchestrates full pipeline
  generate.py         calls the model and writes generated outputs
  evaluate.py         scores generated output against gold
  score.py            scoring logic, thresholds, diagnostics
  report.py           per-run CSV + markdown reporting
  review_queue.py     review queue persistence
  review_cli.py       interactive adjudication tool
  compare_report.py   side-by-side run comparison
  trend_report.py     multi-run trend reporting
  schemas.py          pydantic models for datasets and artifacts
  model_adapter.py    Anthropic adapter
  prompts/
    v1.txt            Phase 1 prompt
    v2.txt            Phase 2 prompt

data/
  requirements/
    mvp_dataset.jsonl
    mvp_dataset_v2.jsonl
  gold/
    gold_test_cases.jsonl
    gold_test_cases_v2.jsonl
  generated/
  runs/
  reviews/

configs/
  run_v1.yaml
  run_v2_prompt_v1.yaml
  run_v2_prompt_v2.yaml

docs/
  dataset_design.md
  review_workflow.md
```

---

## Known Limitations

- Coverage scoring is phrase-based. Semantic equivalence is not detected unless it is represented in `acceptable_variants`.
- Correctness is still a heuristic proxy, not a semantic judge of whether a test case is truly valid.
- Hallucination scoring is heuristic and best used together with human review of borderline results.
- Human adjudication changes reporting overlays, not the underlying auto-scored artifacts.
- This repo is intentionally narrow: no UI, no dashboards, no RAG, no autonomous agent workflows.
