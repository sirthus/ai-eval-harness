# Evaluation Report — run_v1

## Run Summary

| Field | Value |
|---|---|
| Run ID | run_v1 |
| Model | claude-sonnet-4-6 |
| Prompt version | v1 |
| Dataset version | mvp_v1 |
| Scoring version | v1 |
| Scorer | heuristic |
| Timestamp | 2026-04-21T12:00:00+00:00 |
| Git commit | 2c0c256 |
| Config | configs/run_v1.yaml |
| Total requirements | 10 |
| Evaluated requirements | 10 |
| Parse failures | 0 |
| Missing requirements | 0 |

### Aggregate Scores (Auto)

| Metric | Value |
|---|---|
| Total samples | 10 |
| Pass | 8 (80%) |
| Borderline | 2 (20%) |
| Fail | 0 (0%) |
| Avg weighted score | 1.85 / 2.00 |
| Avg coverage ratio | 89% |

## Quality Gate Recommendation

Auto gate: ✓ Recommended
Basis: persisted manifest gate. Pass 8 (80%), borderline 2 (20%), fail 0 (0%), parse failures 0, missing requirements 0.

## Per-Sample Results

| ID | Decision | Weighted | Correct | Complete | Halluc Risk | Reviewer Use | Coverage | Notes | Diagnostics |
|---|---|---|---|---|---|---|---|---|---|
| REQ-001 | ✓ pass | 2.00 | 2.0 | 2.0 | 2.0 | 2.0 | 100% | — | — |
| REQ-002 | ✓ pass | 1.85 | 2.0 | 2.0 | 2.0 | 1.0 | 100% | — | — |
| REQ-003 | ✓ pass | 2.00 | 2.0 | 2.0 | 2.0 | 2.0 | 100% | — | — |
| REQ-004 | ✓ pass | 2.00 | 2.0 | 2.0 | 2.0 | 2.0 | 100% | — | — |
| REQ-005 | ✓ pass | 2.00 | 2.0 | 2.0 | 2.0 | 2.0 | 100% | — | — |
| REQ-006 | ✓ pass | 2.00 | 2.0 | 2.0 | 2.0 | 2.0 | 100% | — | — |
| REQ-007 | ✓ pass | 1.85 | 2.0 | 2.0 | 2.0 | 1.0 | 75% | — | — |
| REQ-008 | ✓ pass | 1.85 | 2.0 | 2.0 | 2.0 | 1.0 | 80% | — | — |
| REQ-009 | ~ borderline | 1.38 | 1.5 | 1.0 | 2.0 | 1.0 | 67% | — | — |
| REQ-010 | ~ borderline | 1.55 | 2.0 | 1.0 | 2.0 | 1.0 | 67% | — | — |

## Failure Analysis

**Borderline samples (auto-routed to human review queue):**

- REQ-009: weighted=1.38, coverage=67%
- REQ-010: weighted=1.55, coverage=67%

## Known Limitations

- Gold coverage scoring uses keyword/phrase matching — semantic equivalence is not detected.
- Hallucination risk scoring is heuristic-based; human review of borderline cases is required.
- Correctness scoring is a proxy (disallowed hits + minimum TC count) not a semantic judge.
- Reviewer usefulness scoring uses structural proxies, not semantic judgment.
