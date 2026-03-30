# Human Review Workflow

## Overview

Borderline results are routed to a human review queue. Human adjudication is a separate layer from auto-scoring and never rewrites the canonical auto-scored artifacts.

## Canonical Artifacts

Auto-scored artifacts remain the source of truth for the automated run:

- `data/generated/{run_id}/scored_results.json`
- `data/runs/{run_id}.json`

Human review artifacts are stored separately:

- `data/reviews/{run_id}/queue.jsonl`
- `data/reviews/{run_id}/adjudicated.jsonl`

## Running the Review CLI

```bash
python -m harness review --run-id run_v2_prompt_v2_20260402T130000Z
```

Optional flags:

- `--gold-path` to point directly at a gold file
- `--runs-dir` to resolve manifests from a non-default location
- `--generated-dir` and `--reviews-dir` for non-default artifact roots

If `--gold-path` is not provided, the CLI resolves gold annotations in this order:

1. `data/runs/{run_id}.json`
2. `manifest.config_file`
3. config `gold_path`

If that chain cannot be resolved, the CLI fails clearly instead of silently using the wrong gold file.

If `queue.jsonl` is missing for the run, the command exits non-zero. If the queue exists but is empty, the CLI prints a clear no-op message and exits successfully.

## What the Reviewer Sees

For each borderline item, the CLI loads:

1. The `ReviewRecord` from `queue.jsonl`
2. The generated `ModelOutput`
3. The matching `ScoredResult`
4. `GoldAnnotation.review_notes` for reviewer context

### Controls

| Key | Action |
|---|---|
| `p` | Mark as pass |
| `f` | Mark as fail |
| `s` | Skip and leave pending |
| `q` | Quit and save progress |

After a session, `queue.jsonl` is rewritten with updated decisions and `adjudicated.jsonl` is rewritten with only non-pending decisions.

## Reporting Semantics

The `--use-human-review` flag is available on reporting tools:

```bash
python -m harness report --config configs/run_v2_prompt_v2.yaml --run-id <run_id> --use-human-review
python -m harness compare --run-a <run_a> --run-b <run_b> --dataset-path data/requirements/mvp_dataset_v2.jsonl --use-human-review
python -m harness trend --dataset-path data/requirements/mvp_dataset_v2.jsonl --use-human-review
```

When `--use-human-review` is active:

- the per-run report shows both auto and human decisions per sample
- the per-run report keeps the persisted auto quality gate visible and adds a separate post-review outlook for adjudicated borderline items only
- the compare report shows human decisions alongside each run when adjudications exist
- the trend report keeps all run math auto-based and adds human-review annotations for context
- trend CSV output gains an optional `human_decision` column
- auto-scored weighted scores and stored run artifacts are never modified

Without `--use-human-review`, reports reflect auto-scored results only.

## Review Decision Meanings

| Decision | Meaning |
|---|---|
| `pass` | Reviewer judges the generated test cases adequate despite the borderline auto score |
| `fail` | Reviewer judges the generated test cases inadequate |
| `pending` | Not yet reviewed |

## Audit Trail

Every adjudicated record keeps:

- `reviewed_at` as an ISO timestamp
- `reviewer_notes` as optional free text

Those fields remain visible in `adjudicated.jsonl` and in report outputs that include human review.

## Run Integrity

Only parse/schema validation failures create persistent `{requirement_id}.fail.json` markers and append to `parse_failures.jsonl`. Transient model/API failures abort generation so incomplete runs are not recorded as if they were valid evaluation artifacts.
