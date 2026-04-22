# Dataset Design

Related docs: [README](../README.md), [Architecture](architecture.md), [Review Workflow](review_workflow.md)

## Why The Dataset Exists

The dataset is intentionally small enough to inspect end-to-end and rich enough to make scoring and review do meaningful work.

The goal is a harness that can:

- measure structured QA-test generation against explicit expectations
- distinguish strong outputs from merely plausible ones
- surface ambiguity and underspecification instead of hiding them

## Current Dataset Pairs

| Dataset | Gold | Size | Purpose |
|---|---|---|---|
| `mvp_dataset.jsonl` | `gold_test_cases.jsonl` | 10 requirements | Small baseline run |
| `mvp_dataset_v2.jsonl` | `gold_test_cases_v2.jsonl` | 40 requirements | Main comparison, review, and trend workflow |

`mvp_dataset_v2.jsonl` is the primary working dataset for the current system.

## What Makes The Dataset Meaningful

The dataset deliberately includes:

- multi-condition requirements such as scope boundaries and downgrade flows
- state-dependent requirements such as sessions, overdue logic, or async exports
- underspecified requirements where reviewer judgment matters
- adversarial or tricky inputs such as SQL-like strings and filename edge cases
- cross-domain requirements where one feature affects another

That mix forces the scoring logic and review queue to do real work. A dataset made only of happy-path requirements would make the harness look stronger than it really is.

## Domain Distribution (mvp_dataset_v2)

| Domain | Count | Notes |
|---|---|---|
| `auth` | 7 | Login, MFA, session handling, OAuth |
| `permissions` | 5 | Role boundaries, removal, scope |
| `tasks` | 5 | Bulk ops, due dates, subtasks, transitions |
| `search` | 3 | Filtering, pagination, query behavior |
| `notifications` | 3 | Delivery and preference behavior |
| `billing` | 3 | Subscription and invoice behavior |
| `api` | 7 | Error shape, auth, validation, rate limiting, pagination |
| `data_export` | 4 | CSV and JSON export, async exports, filename handling |
| `onboarding` | 3 | Welcome flows, wizard behavior, skip behavior |

## Difficulty Distribution (mvp_dataset_v2)

| Difficulty | Count | Notes |
|---|---|---|
| `easy` | 11 | Straightforward validation and happy-path cases |
| `medium` | 18 | Multi-step flows and richer state transitions |
| `hard` | 11 | Ambiguous, adversarial, or highly stateful requirements |

The point of the difficulty labels is not to rank requirements abstractly. It is to make trend and comparison outputs more informative.

## Gold Annotation Model

Each gold record contains:

| Field | Purpose |
|---|---|
| `required_coverage_points` | Observable behaviors the generated test cases should cover |
| `acceptable_variants` | Alternate wording that still counts as coverage for a specific point |
| `disallowed_assumptions` | Unsupported behavior the model should not invent |
| `review_notes` | Reviewer context for underspecified or tricky requirements |
| `gold_test_cases` | Optional example cases for reference |

This structure lets the harness evaluate meaningfully without depending on exact string matches.

## Why This Supports Evaluation Better Than Literal Matching

- coverage points focus on behavior, not phrasing
- acceptable variants let good alternate wording count when it is still faithful
- disallowed assumptions let the harness penalize confident invention
- review notes create a place to document ambiguity that scoring alone cannot settle

In other words, the gold data is designed for evaluation, not for brittle answer-key matching.

## Maintenance Checklist

Use this checklist when revising or expanding the gold files:

- each `required_coverage_points` entry is a distinct observable behavior
- `acceptable_variants` are realistic alternate phrasing, not a second copy of the same point
- `disallowed_assumptions` are specific enough to detect and meaningful enough to penalize
- `difficulty` reflects actual QA reasoning difficulty, not just requirement length
- `domain_tag` reflects the primary concern even when a requirement crosses domains
- underspecified requirements include `review_notes` that explain what judgment a reviewer may need to apply

## Versioning And Comparability

Changing gold annotations after runs have been recorded weakens comparison value. If the gold needs to change materially, treat that as a new dataset version instead of silently mutating the old ground truth.

That rule matters because compare and trend reports only stay honest when the underlying evaluation target is stable.
