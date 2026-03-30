# Project Snapshot

## Summary

This repository evaluates AI-generated QA test cases from requirement snippets.

The core claim it demonstrates is:

**A small, disciplined harness can measure whether an LLM produces useful QA test cases, using a gold dataset, explicit scoring, human review, and repeatable reporting.**

## Current Capabilities

The current implementation includes:

- structured test-case generation through Anthropic models
- schema validation of model output
- heuristic scoring across four dimensions
- optional LLM-as-judge scoring with per-sample sidecars
- a human review queue for borderline samples
- per-run CSV and markdown reporting
- optional PNG charts for per-run, compare, and trend reports
- side-by-side comparison of two runs on the same dataset
- multi-run trend reporting with domain and consistency views
- a unified rich CLI through `python -m harness`
- timestamped run IDs and run manifests for traceability
- persisted run-level quality gates plus a CI advisory checker

## Current Boundaries

This project is intentionally not a broad QA platform.

It does not include:

- a UI
- RAG or vector search
- autonomous defect generation
- workflow agents
- dashboards
- large-scale distributed evaluation infrastructure

## Main Question It Answers

**Is this model/prompt combination reliable enough to assist QA test design, and where does it still require human review?**

## Current Datasets and Config Paths

- `mvp_dataset.jsonl` / `gold_test_cases.jsonl`: 10-requirement Phase 1 baseline
- `mvp_dataset_v2.jsonl` / `gold_test_cases_v2.jsonl`: 40-requirement Phase 2 and Phase 3 dataset
- `configs/run_v2_prompt_v1.yaml` and `configs/run_v2_prompt_v2.yaml`: prompt comparison path
- `configs/run_v3_haiku.yaml`: alternate model/prompt comparison path added in Phase 3

## Key Artifacts

A full run produces:

- generated model outputs under `data/generated/{run_id}/`
- parse/schema failure markers and `parse_failures.jsonl` when applicable
- optional `{requirement_id}.judge.json` sidecars when LLM-judge scoring is used
- `scored_results.json` for evaluation output
- a review queue under `data/reviews/{run_id}/`
- a run manifest under `data/runs/{run_id}.json`
- report files under `reports/`
- optional chart PNGs beside the markdown reports

## Core Design Principles

- Auto-scored artifacts are immutable once written.
- Human review is an overlay, not a rewrite of automated results.
- Parse/schema failures are first-class artifacts.
- Transient generation failures abort runs rather than becoming permanent sample-level exclusions.
- Scorer choice is explicit and persisted in the run manifest.
- Run-level quality gates are policy artifacts, not just display text.
- Comparison and trend views are only meaningful when dataset consistency is preserved.

## Where To Start

- [README.md](/mnt/c/Users/dalli/github/ai-eval-harness/README.md) for setup, commands, and artifact layout
- [docs/dataset_design.md](/mnt/c/Users/dalli/github/ai-eval-harness/docs/dataset_design.md) for dataset structure and annotation guidance
- [docs/review_workflow.md](/mnt/c/Users/dalli/github/ai-eval-harness/docs/review_workflow.md) for review semantics and reporting behavior
- [BUILD_PLAN_PHASE3.md](/mnt/c/Users/dalli/github/ai-eval-harness/BUILD_PLAN_PHASE3.md) for the Phase 3 implementation plan and delivered scope
