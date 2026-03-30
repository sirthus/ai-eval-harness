# CLAUDE.md — ai-eval-harness

## Project summary

A Python evaluation harness for AI-generated QA test cases. Given a requirement snippet, an LLM generates structured JSON test cases; this system validates the output, scores it against a gold dataset across four dimensions, routes borderline cases to human review, and produces per-run, comparison, and trend reports.

**One-sentence pitch**: Built a Python evaluation harness for AI-generated QA test cases, using a gold dataset, rubric-based scoring, optional LLM-as-judge evaluation, human review for borderline outputs, and trend reporting across prompt/model versions.

**Status**: Implemented through Phase 3. Current scope includes charts, unified CLI support, CI quality checks, and a second model/prompt path.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Install chart support too
pip install -e ".[dev,charts]"

# Run a full evaluation
python -m harness run --config configs/run_v1.yaml

# Run individual steps
python -m harness generate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
python -m harness evaluate --config configs/run_v2_prompt_v2.yaml --run-id local_dev_run
python -m harness report   --config configs/run_v2_prompt_v2.yaml --run-id <run_id>
python -m harness review   --run-id <run_id>
python -m harness compare  --run-a <run_a> --run-b <run_b> --dataset-path data/requirements/mvp_dataset_v2.jsonl
python -m harness trend    --dataset-path data/requirements/mvp_dataset_v2.jsonl

# Tests
pytest
pytest tests/test_llm_judge.py
pytest tests/test_cli.py
pytest tests/test_charts.py
```

## Package manager

`pip` with `pyproject.toml`. Use `pip install -e ".[dev]"` for development installs and `pip install -e ".[dev,charts]"` when working on chart output.

## Current architecture

```text
src/harness/
  __main__.py       # unified python -m harness entry point
  cli.py            # rich CLI wrapper
  run_eval.py       # orchestrates full pipeline
  generate.py       # calls model API, writes generated output
  evaluate.py       # scores generated output against gold
  score.py          # heuristic scoring logic
  llm_judge.py      # optional LLM-as-judge scorer
  report.py         # per-run CSV + markdown report
  compare_report.py # side-by-side run comparison
  trend_report.py   # multi-run history and trend reporting
  charts.py         # optional PNG charts
  review_queue.py   # borderline queue persistence
  review_cli.py     # human adjudication workflow
  schemas.py        # pydantic models for datasets and artifacts
  model_adapter.py  # Anthropic abstraction
  prompts/
    v1.txt
    v2.txt
    v3.txt
    judge_v1.txt
```

## Key data directories

- `data/requirements/` — input requirement snippets (JSONL)
- `data/gold/` — gold test cases and coverage annotations (JSONL)
- `data/generated/` — raw model outputs per run and judge sidecars (do not hand-edit)
- `data/runs/` — run manifests (JSON, one per run)
- `data/reviews/` — human review records for borderline cases
- `reports/` — markdown, CSV, and optional chart outputs
- `configs/` — YAML run configs

**Do not commit API keys or credentials to any of these directories.**

## Scoring model

Dimensions (0–2 scale each):

- **Correctness** (weight 0.35)
- **Completeness** (weight 0.30)
- **Hallucination risk** (weight 0.20)
- **Reviewer usefulness** (weight 0.15)

Decision bands:

- Pass: weighted average `>= 1.6`
- Borderline: `1.2-1.59` with floor dimensions met
- Fail: `< 1.2`, or any floor dimension below threshold

A sample passes only if `correctness >= 1`, `completeness >= 1`, and `hallucination_risk >= 1`.

## Rules that are always true

- All model output must be valid JSON matching the schema in `schemas.py`.
- Every run records model, prompt, dataset, scoring, threshold, timestamp, git hash, config path, scorer type, and quality-gate decision.
- Gold data supports scoring, not exact string matching.
- Borderline routing is a first-class feature.
- Human review is an overlay, not a rewrite of auto-scored artifacts.
- MVP scope remains intentionally narrow: no UI, no RAG, no vector DBs, no dashboards.

## Sensitive directories

- `data/` — may contain proprietary requirement snippets; do not log contents
- `data/generated/` — raw LLM outputs; never treat as ground truth
- `data/reviews/` — human adjudication records; handle with care
- `.env` / any secrets file — never commit

## Implementation phases

- **Phase 1**: 10 requirements, 1 prompt, 1 model, basic scoring, markdown report
- **Phase 2**: 30–50 snippets, all 4 dimensions, review queue, run metadata, comparison report
- **Phase 3**: charts, unified CLI, CI checks, second model/prompt, optional LLM judge
