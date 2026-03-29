# CLAUDE.md — ai-eval-harness

## Project summary

A Python evaluation harness for AI-generated QA test cases. Given a requirement snippet, an LLM generates structured JSON test cases; this system scores that output against a gold dataset across four dimensions, routes borderline cases to human review, and produces versioned markdown reports for model/prompt comparison.

**One-sentence pitch**: Built a Python evaluation harness for AI-generated QA test cases, using a gold dataset, rubric-based scoring, human review for borderline outputs, and trend reporting across prompt/model versions.

**Status**: Blueprint phase. Only `PROJECT.md` exists. No code has been written yet.

## Commands

```bash
# Install (once pyproject.toml exists)
pip install -e ".[dev]"

# Run a full evaluation
python -m harness.run_eval --config configs/run_v1.yaml

# Run individual steps (dev convenience)
python -m harness.generate --config configs/run_v1.yaml
python -m harness.evaluate --config configs/run_v1.yaml
python -m harness.report    --config configs/run_v1.yaml

# Tests
pytest
pytest tests/test_scoring.py
pytest tests/test_parsing.py
pytest tests/test_thresholds.py
```

## Package manager

`pip` with `pyproject.toml`. Use `pip install -e ".[dev]"` for development installs. Do not use conda or poetry unless the user says otherwise.

## Planned architecture

```
src/harness/
  run_eval.py       # orchestrates full pipeline
  generate.py       # calls model API, writes generated/ output
  evaluate.py       # scores generated output against gold
  score.py          # scoring logic (4 dimensions, weights, thresholds)
  report.py         # produces CSV + markdown report
  review_queue.py   # routes borderline samples to data/reviews/
  schemas.py        # pydantic models for requirements and LLM output
  model_adapter.py  # abstraction over model API calls
  prompts/
    v1.txt          # first prompt version
```

## Key data directories

- `data/requirements/` — input requirement snippets (JSONL)
- `data/gold/` — gold test cases and coverage annotations (JSONL)
- `data/generated/` — raw model outputs per run (do not hand-edit)
- `data/runs/` — run manifests (JSON, one per run)
- `data/reviews/` — human review records for borderline cases
- `reports/` — final markdown + CSV reports
- `configs/` — YAML run configs (select model, prompt, dataset, thresholds)

**Do not commit API keys or credentials to any of these directories.**

## Scoring model (always true)

Dimensions (0–2 scale each):
- **Correctness** (weight 0.35)
- **Completeness** (weight 0.30)
- **Hallucination risk** (weight 0.20)
- **Reviewer usefulness** (weight 0.15)

Decision bands:
- Pass: weighted average ≥ 1.6
- Borderline: 1.2–1.59 → route to human review queue
- Fail: < 1.2

A sample passes only if correctness ≥ 1, completeness ≥ 1, and hallucination_risk ≥ 1 (in addition to the weighted threshold).

## Rules that are always true

- All model output must be valid JSON matching the schema in `schemas.py`. Reject freeform prose.
- Every run must record: model_name, model_version, prompt_version, dataset_version, scoring_version, threshold_version, timestamp, git_commit_hash, config_file.
- Gold dataset supports scoring, not exact string matching — each requirement defines required coverage points, acceptable variants, disallowed assumptions, and review notes.
- Borderline routing is a first-class feature, not an afterthought.
- MVP scope: no UI, no RAG, no agent workflows, no vector DBs, no dashboards. Keep it a small, serious evaluation system.

## Sensitive directories

- `data/` — may contain proprietary requirement snippets; do not log contents
- `data/generated/` — raw LLM outputs; never treat as ground truth
- `data/reviews/` — human adjudication records; handle with care
- `.env` / any secrets file — never commit

## Implementation phases

- **Phase 1** (foundation): 10 requirements, 1 prompt, 1 model, basic scoring, markdown report
- **Phase 2** (real MVP): 30–50 snippets, all 4 dimensions, review queue, run metadata, comparison report
- **Phase 3** (polish): charts, better CLI, CI checks, second model/prompt

**First milestone**: Evaluate 10 requirement snippets with one prompt and one model, produce a scored markdown report.
