# Project Snapshot

## Summary

This repository evaluates AI-generated QA test cases from requirement snippets.

The core claim it demonstrates is:

**A small, disciplined harness can measure whether an LLM produces useful QA test cases, using a gold dataset, explicit scoring, human review, and repeatable reporting.**

## Current Capabilities

The current implementation includes:

- structured test-case generation through Claude
- schema validation of model output
- gold-based scoring across four dimensions
- a human review queue for borderline samples
- per-run CSV and markdown reporting
- side-by-side comparison of two runs on the same dataset
- multi-run trend reporting with domain and consistency views
- timestamped run IDs and run manifests for traceability

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

## Current Datasets

- `mvp_dataset.jsonl` / `gold_test_cases.jsonl`: 10-requirement Phase 1 baseline
- `mvp_dataset_v2.jsonl` / `gold_test_cases_v2.jsonl`: 40-requirement Phase 2 dataset used for prompt comparison, human review, and trend reporting

## Key Artifacts

A full run produces:

- generated model outputs under `data/generated/{run_id}/`
- parse/schema failure markers and `parse_failures.jsonl` when applicable
- `scored_results.json` for evaluation output
- a review queue under `data/reviews/{run_id}/`
- a run manifest under `data/runs/{run_id}.json`
- report files under `reports/`

## Core Design Principles

- Auto-scored artifacts are immutable once written.
- Human review is an overlay, not a rewrite of automated results.
- Parse/schema failures are first-class artifacts.
- Transient generation failures abort runs rather than becoming permanent sample-level exclusions.
- Comparison and trend views are only meaningful when dataset consistency is preserved.

## Where To Start

- [README.md](README.md) for setup, commands, and artifact layout
- [docs/dataset_design.md](docs/dataset_design.md) for dataset structure and annotation guidance
- [docs/review_workflow.md](docs/review_workflow.md) for review semantics and reporting behavior
