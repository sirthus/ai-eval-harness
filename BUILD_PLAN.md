# AI Eval Harness — Build Plan

> Companion to PROJECT.md. Contains implementation strategy, schema design, data formats,
> config structure, and a Phase 1 file-by-file checklist.

---

## 1. Build Order

The dependency graph flows in one direction: data shapes define everything else.
Build from the inside out.

**Layer 1 — Schema and config (no dependencies; everything else depends on these)**

1. `pyproject.toml` — add missing dependencies first so the environment is correct
2. `src/harness/schemas.py` — all Pydantic models; every other module imports from here
3. `configs/run_v1.yaml` — write before the code that reads it; forces a concrete contract
4. `data/requirements/mvp_dataset.jsonl` + `data/gold/gold_test_cases.jsonl` — real data
   before scoring logic forces you to confront edge cases early

**Layer 2 — Core logic (depends on schemas; no inter-module dependencies)**

5. `score.py` — pure scoring logic, no I/O, no API calls; most testable module
6. `src/harness/prompts/v1.txt` — prompt template with `{requirement}` placeholder;
   treat as data, not code
7. `model_adapter.py` — wraps Anthropic SDK; keeps API logic out of generate.py

**Layer 3 — Tests (write before the pipeline)**

8. `tests/conftest.py` — shared fixtures; must exist before any test file
9. `tests/test_scoring.py` + `tests/test_thresholds.py` — test score.py before wiring

**Layer 4 — Pipeline steps (depend on Layers 1–2)**

10. `generate.py` — calls model_adapter, writes raw outputs to `data/generated/`
11. `evaluate.py` — loads generated output and gold, calls score.py, writes scored results
12. `review_queue.py` — routes borderline/pass/fail from scored results
13. `report.py` — reads scored results and run manifest, writes markdown + CSV

**Layer 5 — Orchestration and remaining tests**

14. `run_eval.py` — calls all pipeline steps in sequence; writes run manifest
15. `tests/test_parsing.py`
16. Supporting files: `README.md`, `.env.example`, `data/.gitignore`,
    `src/harness/__init__.py`, `tests/__init__.py`

---

## 2. Dependency Stack

```toml
# pyproject.toml — dependencies
anthropic>=0.40          # model API
pydantic>=2.0            # schema validation
pyyaml>=6.0              # config loading
pandas>=2.0              # report generation only (report.py)
python-dotenv>=1.0       # API key loading from .env  ← ADD THIS

# pyproject.toml — [project.optional-dependencies] dev
pytest>=8.0
pytest-cov
pytest-mock>=3.0         # mock API calls in test_parsing.py  ← ADD THIS
```

**Scope rules:**
- `pandas` stays in `report.py` only — never imported in score.py or evaluate.py
- `pydantic` is the validation layer for all I/O boundaries
- `python-dotenv` loaded once at the top of `model_adapter.py` via `load_dotenv()`
- `rich` deferred to Phase 3 — do not add now

---

## 3. Schema Design (schemas.py)

Build in this order within the file: input → gold → model output → scoring → review → manifest.

### A. Input

```python
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field

Score = Annotated[float, Field(ge=0.0, le=2.0)]  # reused across scoring models

class Requirement(BaseModel):
    requirement_id: str           # "REQ-001"
    requirement_text: str
    domain_tag: str               # "auth", "validation", "permissions", "edge-case"
    difficulty: Literal["easy", "medium", "hard", "ambiguous"]
```

### B. Gold Dataset

```python
class GoldTestCase(BaseModel):
    title: str
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    priority: Literal["high", "medium", "low"]
    type: Literal["positive", "negative", "edge-case", "security", "performance"]

class GoldEntry(BaseModel):
    requirement_id: str
    gold_test_cases: list[GoldTestCase]
    required_coverage_points: list[str]
    # acceptable_variants: paraphrases that still satisfy a coverage point.
    # compute_correctness() checks these as fallback when a coverage point
    # does not match directly — see score.py notes below.
    acceptable_variants: dict[str, list[str]]
    # key = coverage point text, value = list of acceptable paraphrases for that point
    disallowed_assumptions: list[str]
    review_notes: str
```

**`acceptable_variants` design note**: keyed by coverage point so `compute_correctness`
can attempt a secondary match per point. Example:
```json
"acceptable_variants": {
  "empty username triggers validation": [
    "blank username shows error",
    "username field required message displayed"
  ]
}
```
This makes the matching logic explicit and testable rather than a flat list that
floats unanchored.

### C. Model Output

```python
class GeneratedTestCase(BaseModel):
    title: str
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    priority: Literal["high", "medium", "low"]
    type: Literal["positive", "negative", "edge-case", "security", "performance"]

class ModelOutput(BaseModel):
    requirement_id: str
    test_cases: list[GeneratedTestCase]
    assumptions: list[str]   # explicit model assumptions — used for hallucination scoring
    notes: str
```

### D. Scoring

```python
class DimensionScores(BaseModel):
    correctness: Score
    completeness: Score
    hallucination_risk: Score
    reviewer_usefulness: Score

class ScoredResult(BaseModel):
    requirement_id: str
    run_id: str
    weighted_score: float
    dimension_scores: DimensionScores
    decision: Literal["pass", "borderline", "fail"]
    coverage_hit_count: int
    coverage_miss_count: int
    disallowed_assumption_triggered: bool
    # scoring_notes is populated by score_sample() — one sentence per dimension
    # explaining the rationale. Example: "Correctness: 2/2 — all 3 coverage points hit."
    scoring_notes: str
```

### E. Parse Failure

```python
class ParseFailureRecord(BaseModel):
    run_id: str
    requirement_id: str
    raw_response: str
    error_message: str
    timestamp: str
```

Parse failures are **hard failures**, not borderline. They are written to
`data/generated/{run_id}/parse_failures.jsonl` and counted in `RunManifest.parse_failure_count`.
They do **not** appear in scored results. For pass rate calculation:
`effective_total = requirement_count - parse_failure_count`.

### F. Review

```python
class ReviewRecord(BaseModel):
    run_id: str
    requirement_id: str
    auto_scores: DimensionScores
    auto_weighted_score: float
    review_decision: Optional[Literal["pass", "fail"]] = None
    reviewer_notes: str = ""
    final_scores: Optional[DimensionScores] = None
    reviewed_at: Optional[str] = None
```

### G. Run Manifest

```python
class RunManifest(BaseModel):
    run_id: str                   # "run_20260328_143022" — timestamp-based, sortable
    model_id: str                 # full API model identifier: "claude-3-5-sonnet-20241022"
                                  # NOTE: model_name + model_version collapsed into model_id
                                  # version is already embedded in the Anthropic model string
    prompt_version: str           # "v1"
    dataset_version: str          # "mvp_v1"
    scoring_version: str          # "v1.0"
    threshold_version: str        # "v1.0"
    timestamp: str                # ISO 8601
    git_commit_hash: str
    is_dirty: bool                # True if working tree had uncommitted changes at run time
    config_file: str
    requirement_count: int
    pass_count: int
    borderline_count: int
    fail_count: int
    parse_failure_count: int      # hard failures excluded from scored totals
    mean_weighted_score: float    # computed over scored (non-parse-failure) samples only
    quality_gate_decision: Literal["pass", "fail", "needs_review"]
    # pass_count + borderline_count + fail_count + parse_failure_count == requirement_count
```

**`quality_gate_decision` logic** (applied in `run_eval.py` after report is built):
- `"pass"` if pass_rate ≥ 0.70 and borderline_count ≤ 2 and parse_failure_count == 0
- `"needs_review"` if borderline_count > 0 or parse_failure_count > 0
- `"fail"` otherwise

This is machine-readable so Phase 2 can compare decisions across runs programmatically.

---

## 4. Gold Dataset Format

Two separate JSONL files — versioned independently.

### `data/requirements/mvp_dataset.jsonl`

One JSON object per line:
```json
{"requirement_id": "REQ-001", "requirement_text": "The login form must reject submissions where either the username or password field is empty, displaying a specific validation message for each missing field.", "domain_tag": "validation", "difficulty": "easy"}
```

### `data/gold/gold_test_cases.jsonl`

One JSON object per line:
```json
{
  "requirement_id": "REQ-001",
  "gold_test_cases": [
    {
      "title": "Empty username shows username validation message",
      "preconditions": ["Login page is displayed"],
      "steps": ["Leave username blank", "Enter valid password", "Click Submit"],
      "expected_result": "Validation message 'Username is required' is displayed",
      "priority": "high",
      "type": "negative"
    }
  ],
  "required_coverage_points": [
    "empty username triggers validation",
    "empty password triggers validation",
    "per-field error messages are distinct"
  ],
  "acceptable_variants": {
    "empty username triggers validation": ["blank username shows error", "username required message appears"],
    "empty password triggers validation": ["blank password shows error", "password required message appears"]
  },
  "disallowed_assumptions": [
    "assumes server-side validation only",
    "assumes admin bypass route exists"
  ],
  "review_notes": "Accept tests that treat both-empty as a single case. Flag any test that assumes a specific UI framework error class name."
}
```

### Recommended 10-requirement mix for MVP

| ID | Domain | Difficulty | Purpose |
|---|---|---|---|
| REQ-001 | validation | easy | Baseline — per-field validation messages |
| REQ-002 | auth | easy | Basic role/permission check |
| REQ-003 | auth | medium | Token expiry edge case |
| REQ-004 | validation | medium | Multi-field dependency rule |
| REQ-005 | permissions | medium | Role-based access control |
| REQ-006 | error-handling | medium | Network failure / timeout path |
| REQ-007 | edge-case | hard | Concurrent operation conflict |
| REQ-008 | validation | hard | Internationalization / unicode input |
| REQ-009 | ambiguous | hard | Underspecified requirement — tests assumption flagging |
| REQ-010 | security | hard | Input sanitization / injection vector |

REQ-009 is the most valuable for scoring: it tests whether the model flags uncertainty
via `assumptions` or hallucinates a specific implementation. The `disallowed_assumptions`
for this entry should include common safe-to-assume completions.

---

## 5. Run Config YAML

```yaml
# configs/run_v1.yaml

run:
  config_file: "configs/run_v1.yaml"

model:
  id: "claude-3-5-sonnet-20241022"    # matches RunManifest.model_id
  max_tokens: 2048
  temperature: 0.2                     # low for reproducibility; not 0 (not guaranteed deterministic)

prompt:
  version: "v1"
  path: "src/harness/prompts/v1.txt"

dataset:
  version: "mvp_v1"
  requirements_path: "data/requirements/mvp_dataset.jsonl"
  gold_path: "data/gold/gold_test_cases.jsonl"

scoring:
  version: "v1.0"
  weights:
    correctness: 0.35
    completeness: 0.30
    hallucination_risk: 0.20
    reviewer_usefulness: 0.15

thresholds:
  version: "v1.0"
  pass_threshold: 1.6
  borderline_lower: 1.2
  minimum_dimension_scores:
    correctness: 1.0
    completeness: 1.0
    hallucination_risk: 1.0

output:
  generated_dir: "data/generated"
  runs_dir: "data/runs"
  reviews_dir: "data/reviews"
  reports_dir: "reports"
```

Weights and thresholds live in the config, not hardcoded in score.py. A second run with
adjusted thresholds produces a different decision distribution without touching code —
this is what makes it a harness rather than a script.

---

## 6. Prompt File Format (v1.txt)

The Anthropic API takes a `system` prompt and a `messages` list separately. A flat text
file with one `{requirement}` placeholder produces suboptimal compliance. Use a delimiter:

```
### SYSTEM ###
You are a senior QA engineer. Your task is to generate structured test cases from a software requirement snippet. You must return only valid JSON — no prose before or after the JSON block.

### USER ###
Generate test cases for the following requirement.

Requirement:
{requirement}

Return a JSON object matching this exact shape:
{
  "requirement_id": "<string>",
  "test_cases": [
    {
      "title": "<string>",
      "preconditions": ["<string>"],
      "steps": ["<string>"],
      "expected_result": "<string>",
      "priority": "high" | "medium" | "low",
      "type": "positive" | "negative" | "edge-case" | "security" | "performance"
    }
  ],
  "assumptions": ["<string — list any assumptions you made about the requirement>"],
  "notes": "<string>"
}

Rules:
- Include test cases for both happy-path and failure scenarios.
- If the requirement is ambiguous, add your interpretation to "assumptions" rather than inventing specifics.
- Do not include prose, markdown, or explanation outside the JSON object.
```

`model_adapter.py` splits on `### SYSTEM ###` and `### USER ###` markers before calling
the API. The prompt file is the source of truth; the adapter does not construct prompts.

---

## 7. Scoring Logic Notes (score.py)

### Coverage matching

For Phase 1, use lowercase substring matching with `acceptable_variants` as fallback:

```
For each coverage point P in gold.required_coverage_points:
  1. Check if P (lowercased) appears in any test case title/steps/expected_result (lowercased)
  2. If not, check if any variant in gold.acceptable_variants[P] matches the same way
  3. Hit if either check passes; miss otherwise
```

Document this as a known limitation. The interface (`score_sample` takes `ModelOutput`
and `GoldEntry`, returns `ScoredResult`) is stable — an LLM-judge scorer can be swapped
in during Phase 3 without changing evaluate.py.

### `reviewer_usefulness` proxy signals

Derive automatically from structural signals for Phase 1:
- Test case count vs. gold count ratio (too few = 0, in range = 2, too many = 1)
- All test cases have non-empty `steps` and `expected_result` (binary check)
- No test case has identical `title` values (duplicate check)

Document as automated proxy. Anything scoring 0 or 1 on this dimension routes to review.

### `scoring_notes` population

`score_sample()` constructs this string after computing all dimension scores:
```
"Correctness: 2/2 — all 3 coverage points hit. Completeness: 1/2 — missing: [per-field error messages are distinct]. Hallucination risk: 2/2 — no disallowed assumptions triggered. Reviewer usefulness: 1/2 — test count in range but 2 steps missing expected_result."
```
One sentence per dimension. Machine-generated, human-readable.

### Dimension floor rule

A sample returns `"fail"` if any of correctness, completeness, or hallucination_risk
is below 1.0, **regardless of weighted score**. This check runs in
`apply_decision_bands()` before the threshold comparison.

---

## 8. model_adapter.py Design

```python
# Key behaviors:
# - load_dotenv() at module level
# - split v1.txt on ### SYSTEM ### / ### USER ### markers
# - format {requirement} placeholder in USER section only
# - 3-attempt exponential backoff on API errors (1s, 2s, 4s)
# - raise typed ModelAPIError on final failure
# - return raw string — parsing is caller's responsibility
# - log: model_id, prompt_version, requirement_id on each call (not the response)

class ModelAPIError(Exception):
    pass

class AnthropicAdapter:
    def generate(
        self,
        requirement_id: str,
        requirement_text: str,
        prompt_template: str,
        model_config: dict,
    ) -> str:
        ...
```

**Do not log raw API responses.** They may contain proprietary requirement text.

---

## 9. Phase 1 Implementation Checklist

### Step 1 — pyproject.toml
- [ ] Add `python-dotenv>=1.0` to `dependencies`
- [ ] Add `pytest-mock>=3.0` to dev optional dependencies

### Step 2 — Supporting structure
- [ ] Create `src/harness/__init__.py` (empty)
- [ ] Create `tests/__init__.py` (empty)
- [ ] Create `.env.example` with `ANTHROPIC_API_KEY=your_key_here`
- [ ] Create `data/.gitignore` ignoring `generated/`, `runs/`, `reviews/`

### Step 3 — `src/harness/schemas.py`
- [ ] `Score` Annotated type alias
- [ ] `Requirement`
- [ ] `GoldTestCase`
- [ ] `GoldEntry` with `acceptable_variants: dict[str, list[str]]`
- [ ] `GeneratedTestCase`
- [ ] `ModelOutput`
- [ ] `DimensionScores`
- [ ] `ScoredResult` with `scoring_notes: str`
- [ ] `ParseFailureRecord`
- [ ] `ReviewRecord`
- [ ] `RunManifest` with `model_id`, `is_dirty`, `parse_failure_count`, `quality_gate_decision`

### Step 4 — `src/harness/score.py`
- [ ] `_match_coverage_point(point: str, output: ModelOutput, variants: list[str]) -> bool`
- [ ] `compute_correctness(output, gold, weights) -> tuple[float, str]`
- [ ] `compute_completeness(output, gold) -> tuple[float, str]`
- [ ] `compute_hallucination_risk(output, gold) -> tuple[float, str]`
- [ ] `compute_reviewer_usefulness(output, gold) -> tuple[float, str]`
- [ ] `compute_weighted_score(scores: DimensionScores, weights: dict) -> float`
- [ ] `apply_decision_bands(weighted_score, dimension_scores, thresholds) -> Literal["pass", "borderline", "fail"]`
- [ ] `score_sample(output, gold, config) -> ScoredResult`
  - builds `scoring_notes` from the (float, str) tuples returned by each compute_* function

### Step 5 — `tests/conftest.py`
- [ ] `sample_requirement` fixture
- [ ] `sample_gold_entry` fixture (REQ-001 with 3 coverage points, 2 variants, 1 disallowed assumption)
- [ ] `perfect_model_output` fixture (hits all coverage points, no disallowed assumptions)
- [ ] `failing_model_output` fixture (misses all coverage points)
- [ ] `borderline_model_output` fixture (hits 1 of 3 coverage points)
- [ ] `default_config` fixture (weights + thresholds from run_v1.yaml values)

### Step 6 — `tests/test_scoring.py` + `tests/test_thresholds.py`
Core cases (write all before touching evaluate.py):
- [ ] Perfect output → score ≥ 1.6 → "pass"
- [ ] All coverage points missed → score < 1.2 → "fail"
- [ ] Weighted score in 1.2–1.59 range → "borderline"
- [ ] Correctness = 0 → "fail" even if weighted score ≥ 1.6 (floor rule)
- [ ] Disallowed assumption triggered → hallucination_risk penalized
- [ ] `acceptable_variants` fallback fires when direct match fails
- [ ] Weights read from config dict, not hardcoded
- [ ] Thresholds read from config dict, not hardcoded
- [ ] `scoring_notes` is non-empty on every result
- [ ] `coverage_hit_count + coverage_miss_count == len(required_coverage_points)`

### Step 7 — `data/requirements/mvp_dataset.jsonl`
- [ ] 10 requirement records per the mix in section 4
- [ ] REQ-009 is genuinely ambiguous (lacks a stated success condition)
- [ ] REQ-010 mentions sanitization without specifying implementation

### Step 8 — `data/gold/gold_test_cases.jsonl`
- [ ] 10 GoldEntry records
- [ ] Each with ≥ 2 `required_coverage_points`
- [ ] Each with `acceptable_variants` dict (even if empty `{}` for hard requirements)
- [ ] Each with ≥ 1 `disallowed_assumption`
- [ ] REQ-009 `review_notes` explains what to do when model flags uncertainty

### Step 9 — `src/harness/prompts/v1.txt`
- [ ] `### SYSTEM ###` section with role and output format rule
- [ ] `### USER ###` section with `{requirement}` placeholder
- [ ] Inline JSON shape example (not just described — shown)
- [ ] Explicit instruction to use `assumptions` for ambiguity

### Step 10 — `src/harness/model_adapter.py`
- [ ] `load_dotenv()` at module level
- [ ] Prompt file parsing: split on `### SYSTEM ###` / `### USER ###` markers
- [ ] `ModelAPIError` typed exception class
- [ ] `AnthropicAdapter.generate()` with 3-attempt exponential backoff
- [ ] Structured logging: model_id, prompt_version, requirement_id only

### Step 11 — `src/harness/generate.py`
- [ ] Load config from YAML
- [ ] Load requirements from JSONL, validate each against `Requirement` schema
- [ ] For each requirement: call adapter, write raw string to
      `data/generated/{run_id}/raw_{requirement_id}.txt`
- [ ] Attempt `ModelOutput` parse; on failure write `ParseFailureRecord` to
      `data/generated/{run_id}/parse_failures.jsonl`
- [ ] Return counts: `(generated_count, parse_failure_count)`
- [ ] Entry point: `if __name__ == "__main__"` with argparse `--config`, `--run-id`

### Step 12 — `tests/test_parsing.py`
- [ ] Valid output string parses into `ModelOutput`
- [ ] Missing required field raises `ValidationError`
- [ ] Invalid `priority` value raises `ValidationError`
- [ ] Freeform prose string raises a handled error, not unhandled exception
- [ ] Output with extra unknown fields is rejected (strict mode or explicit config)

### Step 13 — `src/harness/evaluate.py`
- [ ] Load config, generated outputs, gold entries
- [ ] Match by `requirement_id` — if a generated file has no gold counterpart, log warning
- [ ] Call `score_sample()` for each matched pair
- [ ] Write `data/runs/{run_id}/scored_results.jsonl`
- [ ] Entry point: argparse `--config`, `--run-id`

### Step 14 — `src/harness/review_queue.py`
- [ ] Load `scored_results.jsonl`
- [ ] Route borderline → `data/reviews/{run_id}/pending_reviews.jsonl` as `ReviewRecord`
- [ ] Write `data/reviews/{run_id}/auto_pass.jsonl`
- [ ] Write `data/reviews/{run_id}/auto_fail.jsonl`

### Step 15 — `src/harness/report.py`
- [ ] Load scored results + run manifest
- [ ] Use pandas to compute: pass rate, mean per-dimension scores, fail count, top missed
      coverage points, most common disallowed assumption triggers
- [ ] Write `reports/{run_id}/report.md` with sections:
      Run Summary / Quality Gate Recommendation / Dimension Analysis / Failure Analysis
- [ ] Write `reports/{run_id}/results.csv` (one row per requirement)
- [ ] Quality gate recommendation section uses `manifest.quality_gate_decision` plus
      a prose explanation from the dimension analysis

### Step 16 — `src/harness/run_eval.py`
- [ ] Generate `run_id` from timestamp: `run_{YYYYMMDD}_{HHMMSS}`
- [ ] Capture git commit hash: `subprocess.run(["git", "rev-parse", "HEAD"], ...)`
- [ ] Set `is_dirty = True` if `git status --porcelain` returns non-empty output
- [ ] Call generate → evaluate → review_queue → report in sequence
- [ ] Build `RunManifest` after report step (when all counts are known)
- [ ] Write manifest to `data/runs/{run_id}/manifest.json`
- [ ] Entry point: argparse `--config`

### Step 17 — `configs/run_v1.yaml`
- [ ] Complete YAML per section 5

### Step 18 — `README.md`
- [ ] Problem statement (one paragraph)
- [ ] How to install and run
- [ ] Scoring model (table format)
- [ ] Sample report output (paste real output after first run)
- [ ] Known limitations section: heuristic coverage matching, `reviewer_usefulness`
      as proxy only, small gold set, single model

---

## 10. Critical Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Coverage matching method (Phase 1) | Lowercase substring + `acceptable_variants` fallback | Simple, testable; interface is stable for Phase 3 LLM-judge swap |
| No LLM-as-judge in Phase 1 | Heuristic only | Avoids nested API cost; keeps tests deterministic |
| `acceptable_variants` shape | `dict[str, list[str]]` keyed by coverage point | Anchors variants to specific points; scoring logic is unambiguous |
| `model_id` (not `model_name` + `model_version`) | Single field | Version is already embedded in Anthropic model strings; redundancy removed |
| Parse failures | Separate JSONL + `parse_failure_count` in manifest | Silently dropping parse failures contaminates score averages |
| Parse failures in pass rate | Excluded from scored total; denominator = `requirement_count - parse_failure_count` | Parse failure is a generation problem, not a quality score |
| Prompt file format | Delimited `### SYSTEM ### / ### USER ###` | Anthropic API requires separate system/user; flat file produces worse compliance |
| Retry logic | 3-attempt exponential backoff (1s, 2s, 4s) | Required for 10+ sequential API calls in a single run |
| `scoring_notes` source | Built in `score_sample()` from `(float, str)` tuples | Defines exactly where notes originate; no ambiguity |
| `is_dirty` flag | First-class field in `RunManifest` | Dirty-tree runs are less reproducible; should be visible in comparisons |
| `quality_gate_decision` | Machine-readable field in manifest | Enables programmatic run comparison in Phase 2 |
| Weights/thresholds | In YAML config, not hardcoded | Re-run with different bands without touching code |
| `pandas` scope | `report.py` only | Keeps score.py purely testable with no data infrastructure |
| Temperature | 0.2 | Anthropic does not guarantee identical outputs at temp=0; 0.2 balances consistency |

---

## 11. Known Limitations to Document

These belong in README.md and in a `## Known Limitations` section in the report template:

1. Coverage point matching is substring-based — semantic paraphrases that don't share keywords will be missed
2. `reviewer_usefulness` is an automated proxy — structural signals only, not semantic judgment
3. Gold set is small (10 requirements in Phase 1) — results should not be generalized
4. Single model, single prompt — no comparison signal until Phase 2
5. Heuristic scoring is biased toward keyword overlap; requirements with rich vocabulary may score lower than they deserve
6. `is_dirty: true` runs have reduced reproducibility; treat their scores with caution
