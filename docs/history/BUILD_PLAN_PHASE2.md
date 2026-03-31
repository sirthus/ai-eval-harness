# Phase 2 Implementation Blueprint — ai-eval-harness

> Archived planning document. Use [README](../../README.md) and [PROJECT.md](../../PROJECT.md)
> for the current project overview.

## Grounding Observations from Phase 1 Codebase

Three design facts that matter for every section below:

1. `score_correctness` in `score.py` calls `score_completeness(ratio)` as its base — correctness and completeness share the same input signal. This conflation must be fixed in Phase 2.
2. `RunManifest` has `total_requirements / parse_failures / total_evaluated` but no `pass_count`, `borderline_count`, `fail_count`, or `avg_weighted_score`. Those are required for trend reports.
3. `review_queue.py` writes `queue.jsonl` correctly and `ReviewRecord` already has `review_decision`, `reviewer_notes`, `final_scores`. The data model is right — the tooling (CLI to adjudicate) is missing.

---

## 1. Dataset Expansion (40 Requirements)

### Target: 40 requirements (REQ-001 through REQ-040)

- 10 existing requirements are reused unchanged
- 30 new requirements (REQ-011 through REQ-040)
- 40 balances gold annotation quality against statistical meaningfulness

### Difficulty distribution (40 total)

| Difficulty | Count | Notes |
|---|---|---|
| easy | 10 | Happy-path baselines; model should nearly always pass |
| medium | 18 | Validation, permissions, state transitions |
| hard | 12 | Ambiguous, underspecified, multi-condition, adversarial |

Existing 10 contribute: 4 easy, 4 medium, 2 hard. New 30 add: 6 easy, 14 medium, 10 hard.

### Domain coverage (40 total, 9 domains)

| Domain tag | Count | Description |
|---|---|---|
| `auth` | 7 | 5 existing + 2 new: MFA flow, session fixation prevention |
| `permissions` | 5 | 2 existing + 3 new: viewer vs editor, org-level vs project-level |
| `tasks` | 5 | 2 existing + 3 new: bulk operations, due date logic, subtasks |
| `search` | 3 | 1 existing + 2 new: pagination, combined filters |
| `notifications` | 3 | 1 existing + 2 new: digest mode, per-channel opt-out |
| `billing` | 3 | 1 existing + 2 new: downgrade flow, invoice generation |
| `api` | 7 | **New**: REST behavior — rate limiting, versioning, error shapes, pagination contracts |
| `data_export` | 4 | **New**: CSV/JSON export, large datasets, field inclusion, format validation |
| `onboarding` | 3 | **New**: welcome email, guided setup, skip behavior |

### Deliberate inclusions in the 30 new requirements

- **4+ multi-condition requirements**: "A and B shall happen only when C AND D" — tests full branch coverage
- **3+ state-dependent requirements**: outcome depends on preceding state (e.g. suspended account behavior)
- **3+ cross-domain requirements**: e.g. "When a project is deleted, billing for that project's premium plan shall be prorated"
- **3-4 severely underspecified requirements** (REQ-009 style): model gets no credit unless it documents gaps in `notes`
- **2-3 adversarial-input requirements**: SQL injection in API filter params, unicode in export filenames, concurrent bulk edits

### Gold dataset QA step (before running comparisons)

Expanding to 40 requirements makes gold annotation quality the primary risk. Before any Phase 2 comparison runs, spot-review 10 entries (at minimum: 3 easy, 4 medium, 3 hard) against this checklist:

- [ ] Each `required_coverage_points` entry is a distinct, observable behavior — not a paraphrase of the requirement text
- [ ] `disallowed_assumptions` are specific enough to be detectable; avoid single common words
- [ ] `difficulty` tag matches the actual cognitive load of writing good test cases for that requirement
- [ ] `domain_tag` is the primary domain; cross-domain requirements are tagged by their primary concern
- [ ] Underspecified requirements (REQ-009 style) have `review_notes` that say explicitly what is missing
- [ ] At least one `acceptable_variant` per coverage point that a well-prompted model might plausibly use instead

This QA step is a manual checklist pass, not automated. It surfaces annotation inconsistencies before they cause inexplicable score patterns in the comparison.

### File layout

- `data/requirements/mvp_dataset_v2.jsonl` — all 40 requirements (new file; `mvp_dataset.jsonl` stays for Phase 1 config)
- `data/gold/gold_test_cases_v2.jsonl` — gold for all 40 (new file; existing file stays)
- Both files use unchanged `Requirement` and `GoldAnnotation` schemas

---

## 2. Prompt/Model Comparison

### Decision: one model, two prompts

Keep `claude-3-5-sonnet-20241022`. Adding a second model creates a confound — if results differ you cannot attribute it to prompt vs model. Phase 2 story: "same model, different prompt; here is what changed." Phase 3 adds haiku as cost/quality tradeoff.

### v2 prompt design (src/harness/prompts/v2.txt)

v1 is structurally correct but lacks explicit coverage planning, targeted role framing, and an ambiguity gate. v2 differs in four concrete ways. Note: the model should not emit intermediate reasoning — the output remains only the schema-valid JSON. The intent of the changes below is **explicit behavior enumeration and coverage discipline**, not chain-of-thought in the response.

**1. Role with seniority signal**
- v1: "You are a QA test case generator."
- v2: "You are a senior QA engineer with experience in API testing, security testing, and requirements analysis."

**2. Explicit behavior enumeration step**
Add: "Before writing test cases, identify the distinct testable behaviors in the requirement. Write at least one test case per behavior. Do not include this enumeration in your output — it is a planning step only."

This explicitly directs the model to enumerate behaviors internally, without producing any extra output text. The JSON is still the only output.

**3. Ambiguity gate**
Add: "If the requirement does not specify a concrete observable outcome, write your uncertainty in 'notes' and keep test steps generic rather than assuming implementation details."

**4. Explicit negative/permission case instruction**
- v1: "Cover at minimum: the happy path and at least one failure/error case."
- v2: "For each behavior, include both a success case and at least one failure/error case. For permission-related requirements, include at least one test case for an unauthorized actor."

Placeholders unchanged: `{requirement_id}`, `{requirement_text}`. Adapter does not change.

### Run config structure

```
configs/
  run_v1.yaml                # existing — unchanged (Phase 1 baseline)
  run_v2_prompt_v1.yaml      # sonnet + prompt v1 + mvp_v2 dataset (40 reqs)
  run_v2_prompt_v2.yaml      # sonnet + prompt v2 + mvp_v2 dataset (40 reqs)
```

Both v2 configs are structurally identical to `run_v1.yaml` with:
- `dataset_version: mvp_v2`
- `dataset_path: data/requirements/mvp_dataset_v2.jsonl`
- `gold_path: data/gold/gold_test_cases_v2.jsonl`
- `prompt_version: v1` or `v2`
- `run_id: run_v2_prompt_v1` or `run_v2_prompt_v2`

No new config schema needed.

### Comparison report contents

New file: `src/harness/compare_report.py`

Accepts `(results_a, manifest_a, results_b, manifest_b, dataset_path)` as arguments — **not** a config file. This makes it fully testable without file I/O.

**Dataset consistency guard**: `compare_report` must fail fast if `manifest_a.dataset_version != manifest_b.dataset_version`. Comparing runs on different datasets produces meaningless deltas. If the two runs cover different requirement sets (e.g. one had parse failures), report only the intersection and state explicitly how many requirements were excluded and why.

Sections:
1. **Header**: run IDs, models, prompts, dataset version, comparison timestamp; intersection size if < total
2. **Aggregate delta table**: pass/borderline/fail rates for both runs + delta; avg weighted score + delta; parse failures
3. **Per-dimension averages**: correctness, completeness, hallucination_risk, reviewer_usefulness — both runs + delta
4. **Per-requirement delta table**: for each requirement in the intersection, decision in both runs, weighted score both runs, delta. Sorted by largest absolute delta. Regressions (v2 worse than v1) visually distinct.
5. **Domain breakdown**: per `domain_tag`, pass rate in both runs across all 9 domains
6. **Difficulty breakdown**: easy/medium/hard pass rates in both runs — did v2 help on hard reqs (the intended target)?
7. **Notable changes**: top 5 improvements (fail→pass), top 5 regressions (pass→fail), with scores
8. **Conclusion sentence**: generated from data (e.g. "Prompt v2 improved hard requirement pass rate by X% while introducing Y regressions on easy requirements.")

CLI: `python -m harness.compare_report --run-a {run_id} --run-b {run_id} --dataset-path data/requirements/mvp_dataset_v2.jsonl`

---

## 3. Human Review Workflow

### Current state

`review_queue.py` writes correct `queue.jsonl` with `review_decision="pending"`. `ReviewRecord` schema already has `review_decision`, `reviewer_notes`, `final_scores`. The gap is entirely tooling: nothing reads a completed queue and writes back decisions.

### Canonical decision source: immutable auto-run artifacts

**The run manifest and `scored_results.json` are immutable once written.** They record what the automated pipeline produced and are never overwritten by human review. Human adjudication is a separate layer that report/compare/trend tools may optionally merge.

This means:
- `data/runs/{run_id}.json` — auto-scored manifest; never modified post-run
- `data/generated/{run_id}/scored_results.json` — auto-scored results; never modified post-run
- `data/reviews/{run_id}/adjudicated.jsonl` — human review layer; optional, queried on demand

When `report.py`, `compare_report.py`, or `trend_report.py` merge adjudicated reviews, they show both the auto decision and the human decision side by side. They do not silently replace one with the other.

`--use-human-review` is an explicit flag on each reporting tool, defaulting to `false`. When not passed, all reports reflect auto-scored results only. This makes reports reproducible: the same command with the same run ID always produces the same output unless `--use-human-review` is added.

### New file: src/harness/review_cli.py

Entry point: `python -m harness.review_cli --run-id {run_id}`

Interactive terminal tool. Plain `input()` calls — no UI framework.

**What the CLI loads for each item:**
1. The `ReviewRecord` from `queue.jsonl` (weighted score, auto decision)
2. The `ModelOutput` from `data/generated/{run_id}/{requirement_id}.json` (full generated test cases)
3. The `ScoredResult` from `data/generated/{run_id}/scored_results.json` (all four dimension scores, coverage ratio, disallowed hits)
4. The `GoldAnnotation.review_notes` from `gold_test_cases_v2.jsonl` (optional; omit if empty)

This is the minimum context a reviewer needs to make a meaningful decision. The `ReviewRecord` alone does not contain the generated test cases or the gold guidance — those must be loaded separately.

**Per-item display:**
```
=== Review 2 of 5 ===
Run:          run_v2_prompt_v1_20260402T130000Z
Requirement:  REQ-023
Gold notes:   Flag if model invents specific notification channels not stated in requirement.

Auto scores:  correctness=1.0  completeness=1.0  hallucination=1.0  usefulness=0.0
              Weighted: 1.35 (borderline) | Coverage: 67% | Disallowed hits: none

Generated test cases:
  [1] "User receives email when project is deleted" (positive, high)
      Preconditions: user is a project member
      Steps: delete project, check inbox
      Expected: email received within 5 minutes
  ...

Decision [p=pass / f=fail / s=skip / q=quit]:
Notes (optional):
```

**Controls:**
- `p` → `review_decision = "pass"`
- `f` → `review_decision = "fail"`
- `s` → leave as pending, move to next
- `q` → save all decisions made so far, exit

**Output on session end:**
- Rewrites `queue.jsonl` in place with updated decisions and `reviewed_at` timestamp
- Writes `data/reviews/{run_id}/adjudicated.jsonl` (only items where `review_decision != "pending"`)

### Fields the reviewer fills in

| Field | Source |
|---|---|
| `review_decision` | CLI input (p/f) |
| `reviewer_notes` | CLI free text (optional) |
| `reviewed_at` | `datetime.now(timezone.utc).isoformat()` — set by tool |
| `final_scores` | Not set in Phase 2 (Phase 3 feature) |

Add `reviewed_at: str | None = None` to `ReviewRecord` schema.

### How adjudicated reviews feed into reports

`report.py`, `compare_report.py`, and `trend_report.py` each accept `--use-human-review` (default: false).

When active, each tool calls `_load_adjudicated_reviews(run_id, reviews_dir) -> dict[str, ReviewRecord]` and merges the result into display only — not into the underlying scored data.

In `report.py` when active:
- Per-sample table gains `Auto Decision` and `Human Decision` columns
- Aggregate stats show both "auto" and "after human review" rows in separate sections
- Quality gate recommendation is shown for both
- New section: "Human Review Summary" with reviewer notes

CSV always writes `auto_decision`; `human_decision` column is added when `--use-human-review` is passed.

In `compare_report.py` when active: the comparison operates on auto scores for the delta table, but the per-requirement table shows a third column for human decision where adjudicated.

In `trend_report.py` when active: the per-requirement history shows `auto_decision` and, where available, `human_decision`. Aggregate pass rates are computed from auto scores only (consistent baseline).

### New helper in review_queue.py

`write_adjudicated(records: list[ReviewRecord], run_id: str, reviews_dir: str) -> Path`

Called by `review_cli` after each adjudication session.

---

## 4. Trend Report

### Unit of analysis

Trend treats **every run independently** (not grouped or de-duplicated). Rationale: if a config is run three times and another only once, that is meaningful signal — the repeated config may reflect active iteration. Suppressing repeats would hide that.

To prevent analytical noise from dataset mixing, the default behavior is:

- **`--filter-dataset` defaults to the most recent `dataset_version` seen in `runs_dir`**, not to "all runs." This means a `trend_report` run without flags always produces a coherent same-dataset view.
- `--filter-dataset all` must be passed explicitly to include all dataset versions, and the output adds a "⚠ Mixed datasets" warning header.
- Runs on different dataset versions are never included in the same domain or per-requirement breakdown row, even when `--filter-dataset all` is used. Mixed-dataset rows are rendered separately.

A single-config run count note is included in the report header: "run_v2_prompt_v1: 3 runs, run_v2_prompt_v2: 1 run" — so the reader knows the distribution.

### Schema additions to schemas.py

**`RunSummary`** (new):
```python
class RunSummary(BaseModel):
    run_id: str
    timestamp: str
    model_version: str
    prompt_version: str
    dataset_version: str
    pass_count: int
    borderline_count: int
    fail_count: int
    total_evaluated: int
    parse_failures: int
    avg_weighted_score: float
```

**`TrendReport`** (new):
```python
class TrendReport(BaseModel):
    generated_at: str
    runs: list[RunSummary]
    per_requirement_history: dict[str, list[dict]]  # req_id → [{run_id, decision, weighted_score}]
    consistently_borderline: list[str]               # req_ids borderline in >50% of runs
    domain_pass_rates: dict[str, dict[str, float]]   # domain → {run_id → pass_rate}
```

Note: `RunManifest` needs four new fields to support `RunSummary` construction (see section 6).

### Trend report content

```markdown
# Trend Report — {N} runs ({date range})
⚠ Filtered to dataset_version: mvp_v2 | Run distribution: run_v2_prompt_v1 ×3, run_v2_prompt_v2 ×1

## Runs Included
| Run ID | Timestamp | Model | Prompt | Dataset | Pass% | Avg Score |

## Pass Rate Over Time
[Table sorted by timestamp]

## Per-Requirement Pass Rate (all runs, same dataset)
| Req ID | Domain | Difficulty | Run1 | Run2 | Run3 | Run4 | Consistency |
(sorted by consistency ascending — most consistently problematic first)

## Consistently Borderline Requirements
(borderline in >50% of included runs — prime candidates for gold annotation review or prompt improvement)

## Domain Trends (9 domains)
| Domain | Avg Pass Rate (earliest run) | Avg Pass Rate (latest run) | Delta |

## Quality Gate Evolution
| Run | Decision | Pass% | Notes |
```

### CLI: src/harness/trend_report.py

```
python -m harness.trend_report
  --runs-dir data/runs                                 (default)
  --reports-dir reports                                (default)
  --dataset-path data/requirements/mvp_dataset_v2.jsonl
  --filter-dataset mvp_v2                              (default: most recent version seen)
  --filter-prompt v2                                   (optional)
  --use-human-review                                   (optional, default false)
```

Loads all `*.json` manifests from `--runs-dir`, loads corresponding `scored_results.json` from `data/generated/{run_id}/`. Does not call API. Output: `reports/trend_{timestamp}.md` and `reports/trend_{timestamp}.csv`.

---

## 5. Scoring Improvements

### Fix 1 — Decouple score_correctness (required for Phase 2)

**The semantic distinction:**

- **Completeness** answers: "How much of the required ground was covered?"
- **Correctness** answers: "Are the claims and test cases that were generated valid relative to the requirement and gold guidance?"

These are independent properties. A model can cover 90% of required points but write incorrect expected results. A model can cover 40% of required points but what it wrote is accurate. Phase 1 makes them the same signal, which means the correctness floor check is not measuring correctness at all — it is measuring coverage twice.

**Phase 2 correctness is still heuristic.** Semantic validity cannot be fully measured without embeddings or human review. The heuristic chosen for Phase 2 is:

> A generated output is likely correct if it avoids stating things explicitly prohibited by the gold annotations (no disallowed hits) and if it produces enough test cases to cover at least both a success and a failure scenario (minimum 2 test cases). Outputs that fail either condition are penalized proportionally.

This is a proxy, not a semantic judge. The scoring notes in `ScoredResult` must record what the heuristic measured so human reviewers know what "correctness" means in context.

**Proposed implementation:**
```python
def score_correctness(output: ModelOutput, hits: list[str]) -> float:
    """
    Measures validity of generated content relative to gold guidance.
    Proxy: penalizes disallowed assumptions and outputs too thin to cover
    both positive and negative cases.
    Does NOT measure coverage breadth — that is completeness.
    """
    score = 2.0
    score -= min(len(hits), 2)        # 1.0 per disallowed hit, capped at 2 deductions
    if len(output.test_cases) < 2:
        score -= 0.5                   # can't cover +/- with a single test case
    return max(0.0, score)
```

Signature change: `ratio: float` → `output: ModelOutput`. All callers in `score.py` updated. Completeness unchanged.

**Threshold calibration required:** Before shipping Phase 2, run the new scorer against all 10 Phase 1 requirements with their actual model outputs (if available) or synthetic stand-ins. Verify the pass/borderline/fail distribution stays reasonable. Recalibrate `thresholds.pass` or `thresholds.borderline_low` in `run_v2_*.yaml` if needed. `run_v1.yaml` stays frozen.

### Fix 2 — Optional scoring heuristics: diagnostic signals first

The proposed hallucination and reviewer usefulness heuristics carry false-penalty risk:

- `expected_result > 15 words` would penalize perfectly valid API or data export assertions that are inherently verbose
- `avg words-per-step < 5` would penalize concise but accurate steps

**Phase 2 approach: introduce as diagnostic report signals, not scoring inputs.**

Both heuristics are computed and written to a new `diagnostic_notes` field on `ScoredResult`, visible in the per-run report, but they do **not** change the score values. After observing real Phase 2 outputs, the decision to promote them to scoring factors can be made with evidence rather than guesswork.

```yaml
# run_v2_*.yaml
diagnostics:
  flag_long_expected_result: true    # words > 15 logged to diagnostic_notes, not penalized
  flag_low_step_verbosity: true      # avg words/step < 5 logged, not penalized
```

The `diagnostic_notes: str = ""` field is added to `ScoredResult` in `schemas.py`.

### Fix 3 — Reviewer usefulness: two safe new heuristics

Two heuristics with low false-penalty risk are appropriate for scoring (not just diagnostics) in Phase 2:

- **Duplicate title detection**: subtract 1 signal if any two test cases share an identical title. Zero false-penalty risk — duplicate titles are always a generation quality failure.
- **Test case count signal**: subtract 1 signal if `len(test_cases) == 1`. This is already enforced by the correctness scorer's 0.5 penalty; adding it to usefulness reinforces the signal and is unlikely to penalize valid outputs.

The third proposed heuristic (average words-per-step) is deferred to diagnostics as described above.

---

## 6. Files Changed

### New files

| File | Purpose |
|---|---|
| `data/requirements/mvp_dataset_v2.jsonl` | 40-requirement dataset |
| `data/gold/gold_test_cases_v2.jsonl` | Gold annotations for all 40 |
| `src/harness/prompts/v2.txt` | Behavior-enumeration prompt (v2) |
| `src/harness/review_cli.py` | Interactive terminal review tool |
| `src/harness/trend_report.py` | Trend report generator |
| `src/harness/compare_report.py` | Side-by-side run comparison |
| `configs/run_v2_prompt_v1.yaml` | v2 dataset + prompt v1 |
| `configs/run_v2_prompt_v2.yaml` | v2 dataset + prompt v2 |
| `tests/test_review_cli.py` | Tests for review CLI |
| `tests/test_trend_report.py` | Tests for trend aggregation |
| `tests/test_compare_report.py` | Tests for comparison/delta logic |
| `tests/test_scoring_v2.py` | Tests for decoupled correctness and new heuristics |
| `tests/test_integration.py` | End-to-end smoke test with synthetic fixtures |
| `docs/dataset_design.md` | Documents domain mix, difficulty rationale, gold QA checklist |
| `docs/review_workflow.md` | Documents human review process and `--use-human-review` semantics |

### Modified files

| File | Change | Breaking? |
|---|---|---|
| `schemas.py` | Add `pass_count`, `borderline_count`, `fail_count`, `avg_weighted_score` to `RunManifest` (default=0/0.0); add `reviewed_at: str \| None = None` and diagnostic fields to `ReviewRecord`; add `diagnostic_notes: str = ""` to `ScoredResult`; add `RunSummary` and `TrendReport` models | Soft — old records deserialize with defaults |
| `score.py` | Decouple `score_correctness` (new signature); add diagnostic heuristics; add safe usefulness heuristics | **Breaking to test assertions** |
| `run_eval.py` | Populate new `RunManifest` fields after evaluate step | None |
| `report.py` | Add `_load_adjudicated_reviews()`; add `--use-human-review` support; add `diagnostic_notes` column; add "Human Review Summary" section | None — backward compat when no review file |
| `evaluate.py` | Compute diagnostic heuristics and write to `ScoredResult.diagnostic_notes` | None |
| `review_queue.py` | Add `write_adjudicated()` function | None |
| `tests/test_scoring.py` | Update `TestScoreCorrectness` for new signature | Required |
| `tests/test_thresholds.py` | Re-verify boundary values with new correctness scorer | Required |
| `README.md` | Phase 2 commands, comparison report example, review workflow, `--use-human-review` flag | None |

### Critical breaking change: score_correctness signature

Before: `score_correctness(ratio: float, hits: list[str]) -> float`
After: `score_correctness(output: ModelOutput, hits: list[str]) -> float`

All callers in `score.py` and all tests in `test_scoring.py` must be updated. Existing scored results on disk are historical artifacts — they are not invalidated but the values will differ on re-run.

Do **not** change `thresholds.pass` or `thresholds.borderline_low` in `run_v1.yaml`. The Phase 1 run config stays frozen as a stable baseline. Any threshold recalibration goes in `run_v2_*.yaml` only.

---

## 7. Test Strategy

### test_review_cli.py

Use `monkeypatch` to replace `input()`. Key tests:
- `adjudicate()` with simulated inputs `["p", "", "f", "wrong scores are bad", "s", "q"]` → correct updated `ReviewRecord` objects
- CLI loads all four context sources (ReviewRecord, ModelOutput, ScoredResult, gold notes) before prompting
- `queue.jsonl` rewritten correctly after session (`tmp_path`)
- `adjudicated.jsonl` contains only non-pending records
- `q` mid-session saves all decisions made so far; remaining items stay pending
- Empty queue: message shown, no error, clean exit

### test_trend_report.py

Use `tmp_path` with synthetic manifest and `scored_results.json` files. No API calls.
- `build_trend_data()` with N=3 runs on same dataset → correct `TrendReport` structure
- Default `--filter-dataset` selects most recent dataset_version found in runs_dir
- `--filter-dataset all` includes mixed datasets and adds warning header
- Per-requirement rows are never mixed across dataset versions even with `--filter-dataset all`
- `consistently_borderline_requirements()`: req borderline in 2 of 3 runs → included
- `domain_pass_rates()`: correct grouping from dataset domain_tags
- Trend CSV shape: one row per (requirement × run)
- Run count note appears in report header

### test_compare_report.py

Two synthetic result lists and manifests. No file I/O.
- **Fails fast if `dataset_version` differs** between the two manifests
- When one run has parse failures: reports intersection size and excluded requirements
- Delta: score 1.4 → 1.7 → delta +0.3, regression=False
- Regression: decision pass → fail → regression=True, flagged distinctly
- Domain breakdown covers all 9 domains
- `--use-human-review`: auto decisions used for delta table; human decisions shown as separate column

### test_scoring_v2.py

With decoupled correctness scorer:
- `score_correctness(output_2tc, hits=[])` → 2.0
- `score_correctness(output_1tc, hits=[])` → 1.5 (single-TC penalty)
- `score_correctness(output_2tc, hits=["x"])` → 1.0
- `score_correctness(output_2tc, hits=["x", "y"])` → 0.0
- Correctness is independent of coverage ratio: same result for ratio=0.1 and ratio=1.0 with same hits
- Diagnostic flags written to `diagnostic_notes` when enabled; scores unchanged
- Reviewer usefulness: duplicate titles reduce signal count
- Reviewer usefulness: single test case reduces signal count

### test_integration.py

Synthetic fixtures (40 `ModelOutput` objects, 40 `GoldAnnotation` objects). No API.
1. Calls `evaluate.run()` directly with synthetic data
2. Verifies decision distribution within expected bounds (≥ 50% pass, ≤ 20% fail)
3. Calls `review_queue.write_queue()` → verifies borderline items written
4. Calls `report.write_report()` → verifies markdown and CSV are well-formed and non-empty
5. Calls `trend_report` with two runs' worth of synthetic data on same dataset version

This is the CI smoke test that runs without an API key.

---

## 8. Implementation Order

### Dependency graph

```
[Stage 1] Data files + gold QA (no code)
  mvp_dataset_v2.jsonl
  gold_test_cases_v2.jsonl  ← gold QA checklist applied before moving to Stage 2
  prompts/v2.txt
  run_v2_*.yaml

[Stage 2] Schema + scoring changes
  schemas.py (RunManifest new fields, RunSummary, TrendReport, ReviewRecord.reviewed_at,
              ScoredResult.diagnostic_notes)
  score.py (decouple correctness, diagnostic heuristics, safe usefulness heuristics)
  run_eval.py (populate new manifest fields)
  tests/test_scoring.py (update)
  tests/test_thresholds.py (update)
  tests/test_scoring_v2.py (new)
  ← Calibrate thresholds against 10 Phase 1 reqs before proceeding

[Stage 3] Human review (parallel-trackable after Stage 2)
  review_cli.py (new — loads ReviewRecord + ModelOutput + ScoredResult + gold notes)
  review_queue.py (add write_adjudicated)
  report.py (add --use-human-review support)
  tests/test_review_cli.py (new)

[Stage 4] Comparison + trend (parallel-trackable after Stage 2)
  compare_report.py (new — dataset consistency guard required)
  trend_report.py (new — dataset-version filtering and run-count note required)
  tests/test_compare_report.py (new)
  tests/test_trend_report.py (new)

[Stage 5] Integration + first real runs
  tests/test_integration.py (new)
  Run both v2 configs end-to-end
  Tune v2 prompt based on observed outputs
  Calibrate diagnostic heuristics for potential promotion to scoring in Phase 3

[Stage 6] Documentation
  README.md update
  docs/dataset_design.md (include gold QA checklist)
  docs/review_workflow.md (include --use-human-review semantics)
```

Stages 3 and 4 can proceed in parallel after Stage 2 is complete. Stage 1 has no code dependencies but the gold QA checklist must pass before Stage 5 runs begin.

### Phase 2 "done" milestone

```bash
# Two parallel runs on 40 requirements, 9 domains
python -m harness.run_eval --config configs/run_v2_prompt_v1.yaml
python -m harness.run_eval --config configs/run_v2_prompt_v2.yaml

# Review borderline cases from prompt v2 run
python -m harness.review_cli --run-id run_v2_prompt_v2_TIMESTAMP

# Comparison report (same dataset_version required)
python -m harness.compare_report \
  --run-a run_v2_prompt_v1_TIMESTAMP \
  --run-b run_v2_prompt_v2_TIMESTAMP \
  --dataset-path data/requirements/mvp_dataset_v2.jsonl \
  --use-human-review
```

Output: a comparison report answering "which prompt performs better on each of the 40 requirements across all 9 domains, and where does human review change the picture?" That is the primary Phase 2 deliverable.

---

## Key Decisions Summary

| Decision | Recommendation | Rationale |
|---|---|---|
| Dataset size | 40 requirements | 50 risks rushed gold; 40 gives meaningful distributions |
| New domains | `api`, `data_export`, `onboarding` | Credible beyond SaaS CRUD; naturally rich edge cases |
| Model comparison | One model, two prompts | Cleaner signal; haiku deferred to Phase 3 |
| v2 prompt changes | Role + behavior enumeration + ambiguity gate | Addresses Phase 1 scoring weaknesses; output stays JSON-only |
| Correctness decoupling | Yes, heuristic proxy (Phase 2) | Semantic distinction defined; proxy is explicit and documented |
| Canonical decision source | Auto-scored manifests immutable; reviews merged on demand via `--use-human-review` | Reports are reproducible; human decisions are auditable, not silently applied |
| review_cli context | Loads ReviewRecord + ModelOutput + ScoredResult + gold notes | Minimum viable reviewer context; ReviewRecord alone is insufficient |
| Dataset consistency guards | compare_report fails fast on mismatched datasets; trend defaults to most recent dataset_version | Prevents analytically misleading comparisons |
| Trend unit of analysis | Every run independently; run counts shown in header | Repeated configs are signal, not noise; reader judges weight |
| New scoring heuristics | Diagnostic signals first; promote to scoring in Phase 3 with calibration evidence | Avoids false penalties on verbose-but-valid assertions |
| Gold dataset QA | Manual checklist on 10 entries before Phase 2 runs | Gold quality is the primary Phase 2 risk |
| Integration test | Synthetic fixtures only | Avoids API dependency in CI |
| Threshold config | Freeze `run_v1.yaml`; recalibrate in `run_v2_*.yaml` only | Phase 1 baseline stays comparable |
