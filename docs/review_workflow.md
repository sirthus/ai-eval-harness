# Human Review Workflow

Related docs: [README](../README.md), [Architecture](architecture.md), [Report Examples](report_examples.md)

## Why Human Review Exists

The harness is designed to answer a practical question, not an abstract benchmark question:

> Is this output strong enough to assist QA test design, or does it still need reviewer judgment?

That is why borderline results are a first-class feature. The repo does not pretend that every low-confidence case can be fully settled by automation.

## Canonical Artifacts

Automated run artifacts remain the source of truth for the automated evaluation:

- `data/generated/{run_id}/scored_results.json`
- `data/runs/{run_id}.json`

Human-review artifacts live separately:

- `data/reviews/{run_id}/queue.jsonl`
- `data/reviews/{run_id}/adjudicated.jsonl`

This separation is deliberate. Review is an overlay, not a rewrite of the auto-scored run.

## Review Session Flow

Run the CLI:

```bash
python -m harness review --run-id run_v2_prompt_v2_20260402T130000Z
```

Optional flags:

- `--gold-path`
- `--runs-dir`
- `--generated-dir`
- `--reviews-dir`

If `--gold-path` is omitted, the CLI resolves the gold annotations through this chain:

1. `data/runs/{run_id}.json`
2. `manifest.config_file`
3. config `gold_path`

If that chain fails, the command exits clearly rather than guessing.

## What The Reviewer Sees

For each borderline sample, the review CLI loads:

1. the queued `ReviewRecord`
2. the generated `ModelOutput`
3. the matching `ScoredResult`
4. `GoldAnnotation.review_notes` when present

Controls:

| Key | Action |
|---|---|
| `p` | Mark as pass |
| `f` | Mark as fail |
| `s` | Skip and leave pending |
| `q` | Quit and save progress |

After the session:

- `queue.jsonl` is rewritten with updated decisions
- `adjudicated.jsonl` is rewritten with only non-pending records

## Reporting Semantics

The reporting commands support `--use-human-review`:

```bash
python -m harness report --config configs/run_v2_prompt_v2.yaml --run-id <run_id> --use-human-review
python -m harness compare --run-a <run_a> --run-b <run_b> --dataset-path data/requirements/mvp_dataset_v2.jsonl --use-human-review
python -m harness trend --dataset-path data/requirements/mvp_dataset_v2.jsonl --use-human-review
```

When enabled:

- per-run reports show both auto and human decisions
- per-run reports keep the persisted auto quality gate and add a separate post-review outlook
- compare reports show human decisions alongside the auto decisions when available
- trend reports keep the math auto-based and add human-review annotations for context
- trend CSV output can include `human_decision`

What does not change:

- auto-scored weighted scores
- canonical run manifests
- `scored_results.json`

## Review Decision Meanings

| Decision | Meaning |
|---|---|
| `pass` | Reviewer judges the generated test cases usable despite the borderline auto score |
| `fail` | Reviewer judges the generated test cases inadequate |
| `pending` | Not yet reviewed |

Each adjudicated record can also include:

- `reviewed_at`
- `reviewer_notes`

## What This Workflow Demonstrates

From an engineering perspective, this review layer shows that the repo:

- models uncertainty explicitly
- separates automation from human judgment cleanly
- preserves a readable audit trail
- gives reports a practical “what now?” path when automation is not decisive

## Run Integrity Rules

- only parse or schema validation failures create persistent `{requirement_id}.fail.json` markers
- transient model or API failures abort generation rather than becoming silent exclusions
- reviewer decisions do not mutate the canonical auto-scored artifacts

Those rules keep the evaluation history trustworthy even when the model output is not.
