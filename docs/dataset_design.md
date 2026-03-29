# Dataset Design

## Overview

The repo contains two requirement/gold pairs:

| Dataset | Gold | Size | Purpose |
|---|---|---|---|
| `mvp_dataset.jsonl` | `gold_test_cases.jsonl` | 10 requirements | Phase 1 baseline |
| `mvp_dataset_v2.jsonl` | `gold_test_cases_v2.jsonl` | 40 requirements | Current comparison, review, and trend workflow |

`mvp_dataset_v2.jsonl` is the primary working dataset for the current system.

## Phase 2 Domain Distribution

| Domain | Count | Notes |
|---|---|---|
| `auth` | 7 | Login, MFA, session handling, OAuth |
| `permissions` | 5 | Role boundaries, removal, scope |
| `tasks` | 5 | Bulk ops, due dates, subtasks, transitions |
| `search` | 3 | Filtering, pagination, query behavior |
| `notifications` | 3 | Delivery and preference behavior |
| `billing` | 3 | Subscription and invoice behavior |
| `api` | 7 | Error shape, auth, validation, rate limiting, pagination |
| `data_export` | 4 | CSV/JSON export, async exports, filename handling |
| `onboarding` | 3 | Welcome flows, wizard behavior, skip behavior |

## Phase 2 Difficulty Distribution

| Difficulty | Count | Notes |
|---|---|---|
| `easy` | 11 | Happy-path and straightforward validation cases |
| `medium` | 18 | Multi-step flows, validation, and state transitions |
| `hard` | 11 | Ambiguous, stateful, adversarial, or multi-condition requirements |

## Design Characteristics

The dataset deliberately includes:

- multi-condition requirements such as role-scope boundaries and downgrade flows
- state-dependent requirements such as session changes and overdue logic
- underspecified requirements where reviewer judgment matters
- adversarial inputs such as SQL-like strings and unicode filename handling
- cross-domain requirements where one feature affects another

This mix makes the scorer and human review queue do real work instead of only validating happy paths.

## Gold Annotation Structure

Each gold record contains:

- `required_coverage_points`: observable behaviors the generated tests should cover
- `acceptable_variants`: per-point synonym phrases that still count as coverage
- `disallowed_assumptions`: assumptions that should not be invented by the model
- `review_notes`: optional context for reviewers
- `gold_test_cases`: optional example test cases for reference

`acceptable_variants` are keyed by coverage point. A variant only credits the point it belongs to.

## Dataset Maintenance Checklist

Use this checklist when auditing or revising a gold file:

- Each `required_coverage_points` entry is a distinct observable behavior, not a paraphrase of the requirement text
- `acceptable_variants` reflect realistic alternate phrasing a good model might use
- `disallowed_assumptions` are specific enough to be detectable and not just common words
- `difficulty` reflects the actual cognitive load of writing strong test cases
- `domain_tag` reflects the primary concern even when a requirement crosses domains
- Underspecified requirements include `review_notes` explaining what is missing or ambiguous

## Versioning Policy

- `mvp_dataset.jsonl` / `gold_test_cases.jsonl` are the Phase 1 baseline
- `mvp_dataset_v2.jsonl` / `gold_test_cases_v2.jsonl` are the current Phase 2 working pair

Changing gold annotations after runs have been recorded invalidates comparisons with earlier reports. If the gold must change, treat that as a new dataset version.
