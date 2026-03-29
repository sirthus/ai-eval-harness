# AI QA Evaluation Harness

A Python evaluation harness for AI-generated QA test cases. Given a requirement snippet, an LLM generates structured JSON test cases; this system scores that output against a gold dataset across four dimensions, routes borderline cases to human review, and produces versioned markdown reports for model and prompt comparison.

---

## The Problem

LLMs can generate test cases from requirements, but their output is variable. Some outputs are excellent; others miss critical coverage points, invent unsupported behaviors, or produce vague steps a reviewer cannot use. You cannot trust LLM-generated QA artifacts without measurement.

This project answers: **Is this model/prompt combination reliable enough to assist QA test design, and where does it still require human review?**

---

## MVP

Given a requirement snippet, the harness:

1. Sends it to an LLM (Claude) with a structured prompt
2. Validates the response as JSON matching a defined test case schema
3. Scores the output against a gold dataset across four dimensions
4. Routes borderline outputs to a human review queue
5. Produces a scored markdown report with a quality gate recommendation

---

## Evaluation Method

### Scoring dimensions (0–2 scale each)

| Dimension | Weight | What it measures |
|---|---|---|
| Correctness | 0.35 | Are the test cases materially correct and on-target? |
| Completeness | 0.30 | Are all required coverage points addressed? |
| Hallucination risk | 0.20 | Does the output invent unsupported behaviors or assumptions? |
| Reviewer usefulness | 0.15 | Are the test cases clear, specific, and time-saving? |

### Decision bands

| Band | Condition |
|---|---|
| **Pass** | Weighted average ≥ 1.6 AND correctness, completeness, hallucination_risk each ≥ 1 |
| **Borderline** | Weighted 1.2–1.59 → routed to human review queue |
| **Fail** | Weighted < 1.2, or any floor dimension < 1 |

### Gold dataset philosophy

Each requirement defines required coverage points, acceptable variant phrases, and disallowed assumptions — not a single correct answer. Scoring matches coverage by keyword/phrase presence, not exact string matching.

---

## Why This Matters

This repo demonstrates:

- **Reproducibility**: every run records model, prompt, dataset, scoring, threshold, git commit, and timestamp
- **Measurement over hype**: outputs are scored against a rubric with explicit pass/fail criteria
- **Controlled experiments**: versioned prompts and model IDs make comparisons traceable
- **Human-in-the-loop**: borderline cases are routed to review rather than auto-decided
- **Failure analysis**: reports surface common coverage gaps and hallucinated assumptions

---

## How to Run

### Prerequisites

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=your_key_here
```

### Full evaluation pipeline

```bash
python -m harness.run_eval --config configs/run_v1.yaml
```

This runs all steps in sequence: generate → evaluate → review queue → report → manifest.

### Individual steps (development)

```bash
python -m harness.generate --config configs/run_v1.yaml
python -m harness.evaluate --config configs/run_v1.yaml
```

### Tests

```bash
pytest
```

---

## Sample Report Output

```
## Run Summary

| Field     | Value                        |
|-----------|------------------------------|
| Run ID    | run_v1                       |
| Model     | claude-3-5-sonnet-20241022   |
| Prompt    | v1                           |
| Dataset   | mvp_v1 (10 requirements)     |

### Aggregate Scores

| Metric             | Value  |
|--------------------|--------|
| Pass               | 6 (60%) |
| Borderline         | 3 (30%) |
| Fail               | 1 (10%) |
| Avg weighted score | 1.58 / 2.00 |

## Quality Gate Recommendation

Recommended for assisted internal use with reviewer oversight. Pass rate: 60%.
Borderline rate (30%) requires human review before production use.
```

---

## Project Structure

```
src/harness/
  run_eval.py        orchestrates full pipeline
  generate.py        calls model API, writes generated/ output
  evaluate.py        scores generated output against gold
  score.py           scoring logic (4 dimensions, weights, thresholds)
  report.py          produces CSV + markdown report
  review_queue.py    routes borderline samples to data/reviews/
  schemas.py         pydantic models for requirements and LLM output
  model_adapter.py   abstraction over Anthropic API
  prompts/v1.txt     first prompt version

data/requirements/   input requirement snippets (JSONL, committed)
data/gold/           gold annotations (JSONL, committed)
data/generated/      raw model outputs per run (gitignored)
data/runs/           run manifests (gitignored)
data/reviews/        borderline review records (gitignored)
reports/             markdown + CSV reports (gitignored)
configs/             YAML run configs
tests/               pytest tests for scoring, parsing, thresholds
```

---

## Known Limitations

- **Keyword-based coverage scoring**: semantic equivalence is not detected. A test case that covers a point in different words may not be credited unless included in `acceptable_variants`.
- **Heuristic hallucination scoring**: the scorer checks for disallowed assumption phrases and large assumption lists. It cannot detect subtle invented behaviors.
- **Narrow dataset**: Phase 1 uses 10 requirement snippets from a single fictional SaaS domain (TaskFlow). Coverage of edge domains and real-world requirement styles is limited.
- **Gold subjectivity**: coverage points and disallowed assumptions reflect one annotator's judgment. Different annotators may disagree.
- **Phase 1 scope**: no UI, no RAG, no vector DBs, no dashboards. This is intentionally a small, serious evaluation system.
