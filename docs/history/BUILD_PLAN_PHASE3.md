# AI Eval Harness — Build Plan Phase 3

> Archived planning document. Use [README](../../README.md), [PROJECT.md](../../PROJECT.md),
> and [Architecture](../architecture.md) for the current documentation.
>
> Original purpose: companion to `BUILD_PLAN.md`, containing the Phase 3 implementation
> strategy, module specifications, build order, and file-by-file checklist.
>
> Phase 3 goals (from CLAUDE.md): charts, better CLI, CI checks, second model/prompt.
> This document adds a fifth goal carried forward from BUILD_PLAN.md section 7:
> LLM-as-judge scorer (scorer-swap interface is already stable in evaluate.py).
>
> Status note: Phase 3 has now been implemented. Treat this file as the build plan
> and design record for the delivered work; use `README.md` for current operator-facing
> commands and behavior.

---

## 1. Goals Mapped to Files

| Goal | Primary files | Supporting files |
|---|---|---|
| Charts | `src/harness/charts.py` (new), `report.py`, `compare_report.py`, `trend_report.py` | `tests/test_charts.py` |
| Better CLI (`rich`) | `src/harness/cli.py` (new), `review_cli.py` | `tests/test_cli.py` |
| CI checks | `.github/workflows/ci.yml` (new), `scripts/check_quality_gate.py` (new) | `pyproject.toml` |
| Second model | `configs/run_v3_haiku.yaml` (new), `src/harness/prompts/v3.txt` (new) | No code changes needed |
| LLM-as-judge | `src/harness/llm_judge.py` (new), `src/harness/prompts/judge_v1.txt` (new), `evaluate.py`, `run_eval.py`, `schemas.py` | `tests/test_llm_judge.py` |

---

## 2. Dependency Stack Changes

```toml
# pyproject.toml additions

# Core
rich>=13.0              # CLI display only — never imported in business logic modules

# Optional extras
[project.optional-dependencies]
charts = [
    "matplotlib>=3.8",  # static PNG output; Agg backend for headless/CI
    "numpy>=1.24",      # explicit chart dependency used by compare/trend plots
]
dev = [
    # existing dev deps...
    "pytest-mock>=3.0",  # mock API calls in test_llm_judge.py (deferred from Phase 1)
    "ruff>=0.4",         # linting (new)
]
```

**Scope rules:**
- `rich` is imported only in `cli.py` and the optional `console` parameter in `review_cli._display_item()`
- `matplotlib` lives in `charts.py` only; set `matplotlib.use("Agg")` at module level before any other matplotlib import (required for headless/CI)
- All existing modules are unchanged with respect to imports — tests pass without `rich` or `matplotlib`

---

## 3. New Module Specifications

### A. `src/harness/llm_judge.py`

The scorer-swap interface in `evaluate.py` is already stable. `LLMJudgeScorer.score()` is a drop-in replacement for `score.score()` — same signature, same return type.

**Design constraints:**
- The judge sees the generated `ModelOutput` and the `GoldAnnotation`'s evaluation criteria
- The judge does **not** see the raw requirement text — this prevents the judge from mentally re-generating test cases and scoring against its own output instead of the actual output
- Falls back to the heuristic scorer on API failure (logs a warning); CI never breaks due to a transient judge API error
- Writes a `.judge.json` sidecar per requirement to `data/generated/{run_id}/` for auditability — does not affect downstream processing

```python
class LLMJudgeScorerError(Exception):
    """Raised when the judge model returns malformed scoring output."""
    pass


class LLMJudgeScorer:
    def __init__(
        self,
        judge_model: str = "claude-sonnet-4-6",
        judge_prompt_version: str = "judge_v1",
        max_tokens: int = 1024,
    ) -> None: ...

    def score(
        self,
        output: ModelOutput,
        gold: GoldAnnotation,
        weights: dict[str, float] | None = None,
        thresholds: dict | None = None,
        diagnostics: dict[str, bool] | None = None,
    ) -> ScoredResult:
        """
        Drop-in replacement for score.score().
        Calls the judge LLM, parses the JSON verdict, maps to ScoredResult.
        Falls back to heuristic scorer if judge call fails (logs warning).
        """
        ...

    def _build_judge_prompt(self, output: ModelOutput, gold: GoldAnnotation) -> str:
        """
        Inlines the full generated output and the gold annotation's coverage points,
        disallowed assumptions, and review_notes. Does NOT include raw requirement text.
        """
        ...

    def _parse_verdict(self, raw: str, requirement_id: str) -> dict:
        """
        Parse judge's JSON verdict. Raises LLMJudgeScorerError on malformed output.
        """
        ...
```

**Judge verdict JSON schema** (defined in `judge_v1.txt`, validated in `_parse_verdict`):

```json
{
  "coverage_assessment": [
    {"point": "<coverage point text>", "covered": true, "evidence": "<quote from output>"}
  ],
  "correctness_score": 0.0,
  "correctness_rationale": "<one sentence>",
  "hallucination_risk_score": 0.0,
  "hallucination_risk_rationale": "<one sentence>",
  "reviewer_usefulness_score": 0.0,
  "reviewer_usefulness_rationale": "<one sentence>"
}
```

**`completeness_score`** is derived by the harness from `coverage_assessment` (fraction of points with `covered: true`), not reported by the judge directly. This keeps the judge focused on per-point binary assessment rather than a holistic score.

### B. `src/harness/charts.py`

Seven functions. All write PNG files and return the path. All return `None` if `matplotlib` is unavailable (graceful degradation). Use `matplotlib.use("Agg")` at module level.

```python
def plot_score_distribution(
    results: list[ScoredResult],
    run_id: str,
    output_path: Path,
) -> Path | None:
    """
    Horizontal bar chart: pass / borderline / fail counts.
    File: {output_path}/{run_id}_score_distribution.png
    """

def plot_dimension_scores(
    results: list[ScoredResult],
    run_id: str,
    output_path: Path,
) -> Path | None:
    """
    Grouped bar chart: avg score per dimension (correctness, completeness,
    hallucination_risk, reviewer_usefulness). Horizontal line at floor threshold (1.0).
    File: {output_path}/{run_id}_dimensions.png
    """

def plot_per_requirement_scores(
    results: list[ScoredResult],
    run_id: str,
    output_path: Path,
) -> Path | None:
    """
    Bar chart: one bar per requirement, colored by decision band (green/yellow/red).
    x = requirement_id (sorted), y = weighted_score.
    Horizontal lines at pass (1.6) and borderline_low (1.2) thresholds.
    File: {output_path}/{run_id}_per_requirement.png
    """

def plot_compare_distribution(
    results_a: list[ScoredResult],
    results_b: list[ScoredResult],
    run_id_a: str,
    run_id_b: str,
    output_path: Path,
) -> Path | None:
    """
    Side-by-side grouped bar: pass/borderline/fail counts for run A vs. run B.
    File: {output_path}/compare_{run_id_a}_vs_{run_id_b}_distribution.png
    """

def plot_compare_delta(
    results_a: dict[str, ScoredResult],
    results_b: dict[str, ScoredResult],
    run_id_a: str,
    run_id_b: str,
    output_path: Path,
) -> Path | None:
    """
    Scatter/bar: per-requirement score delta (B - A).
    Positive = improvement (green), negative = regression (red).
    Zero line drawn. Requirements sorted by delta ascending.
    File: {output_path}/compare_{run_id_a}_vs_{run_id_b}_delta.png
    """

def plot_trend_pass_rate(
    trend_data: list[dict],  # [{run_id, timestamp, pass_rate, borderline_rate}, ...]
    output_path: Path,
) -> Path | None:
    """
    Line chart: x = run timestamp, y = pass rate.
    Second line for borderline rate (dashed). x-axis labels = run_id (rotated).
    File: {output_path}/trend_pass_rate.png
    """

def plot_domain_heatmap(
    domain_data: dict[str, dict[str, float]],  # {domain: {run_id: pass_rate}}
    output_path: Path,
) -> Path | None:
    """
    Heatmap: rows = domains, columns = run_ids, values = pass_rate (0–1 color scale).
    File: {output_path}/trend_domain_heatmap.png
    """
```

**Integration with reporting modules:**

- `report.py`: `write_report()` gains `charts: bool = False`. When `True`, calls the three single-run chart functions and embeds `![Score Distribution](...)` links in the markdown.
- `compare_report.py`: `write_compare_report()` gains `charts: bool = False`. Calls `plot_compare_distribution()` and `plot_compare_delta()`.
- `trend_report.py`: `write_trend_report()` gains `charts: bool = False`. Calls `plot_trend_pass_rate()` and `plot_domain_heatmap()`.

Chart files land in the same directory as the corresponding markdown report.

### C. `src/harness/cli.py`

Unified entry point. Replaces calling each module as `python -m harness.X`. `rich` is used for display only — all business logic is delegated to existing modules unchanged.

**Subcommands:**

```
python -m harness run       --config <path> [--scorer heuristic|llm-judge] [--charts]
python -m harness generate  --config <path> [--run-id <id>]
python -m harness evaluate  --config <path> [--run-id <id>]
python -m harness report    --config <path> [--run-id <id>] [--use-human-review] [--charts]
python -m harness review    --run-id <id>
python -m harness compare   --run-a <id> --run-b <id> --dataset-path <path> [--charts]
python -m harness trend     --dataset-path <path> [--filter-dataset <ver>] [--charts]
```

**Rich output additions** (display only, no effect on file outputs):

1. **Progress bar during generation** — `rich.progress.Progress` wrapping the generate loop: `[N/40] Generating REQ-XXX...`
2. **Step completion panels** — `rich.panel.Panel` after each pipeline step with outcome counts
3. **Results table** — `rich.table.Table` replacing bare print of per-requirement results
4. **Quality gate banner** — `rich.panel.Panel` with colored background: green = pass, yellow = needs_review, red = fail

```python
def make_parser() -> argparse.ArgumentParser: ...

def cmd_run(args: argparse.Namespace, console: Console) -> None: ...
def cmd_generate(args: argparse.Namespace, console: Console) -> None: ...
def cmd_evaluate(args: argparse.Namespace, console: Console) -> None: ...
def cmd_report(args: argparse.Namespace, console: Console) -> None: ...
def cmd_review(args: argparse.Namespace, console: Console) -> None: ...
def cmd_compare(args: argparse.Namespace, console: Console) -> None: ...
def cmd_trend(args: argparse.Namespace, console: Console) -> None: ...

def print_run_summary(manifest: RunManifest, console: Console) -> None:
    """Rich Panel: pass/borderline/fail counts, avg score, quality gate decision (colored)."""

def print_results_table(
    results: list[ScoredResult],
    console: Console,
    adjudicated: dict[str, ReviewRecord] | None = None,
) -> None:
    """Rich Table: ID | Decision (colored) | Weighted | Coverage | Dimensions."""

def main() -> None: ...
```

**`review_cli.py` migration**: `_display_item()` gains `console: rich.console.Console | None = None`. When `None`, falls back to `print()` for backward compatibility with tests that inject `input_fn`. When a console is provided, uses `rich.panel.Panel` for the item header and `rich.table.Table` for test case display. No other changes to `review_cli.py`.

### D. `src/harness/prompts/judge_v1.txt`

Uses the same `### SYSTEM ### / ### USER ###` delimiter format as generation prompts. The system section establishes the judge role. The user section inlines the generated output and gold criteria.

Key design rules baked into the prompt:
- Assess each `required_coverage_point` as a binary covered/not-covered verdict with a direct quote from the output as evidence
- Score correctness, hallucination_risk, reviewer_usefulness on 0–2 scale (completeness is derived by the harness from the coverage assessment, not scored by the judge)
- Return only JSON — no prose before or after
- Do not penalize the output for issues not reflected in the gold annotation's `disallowed_assumptions`

### E. `src/harness/prompts/v3.txt`

Concise variant of v2 for haiku. The Phase 2 v2 prompt contains a multi-step behavior-enumeration prelude that may degrade compliance on a smaller model. v3 retains the same:
- Seniority signal ("senior QA engineer")
- Ambiguity gate (write uncertainty in `assumptions`)
- JSON schema (identical)
- Constraint set (same rules)

v3 removes:
- The explicit "enumerate behaviors internally before writing" meta-cognitive instruction
- Replaces it with: "Write at least one test case per distinct testable behavior you can identify in the requirement."

This keeps the comparison to the haiku model clean: one variable changed (model), not two (model + prompt strategy).

### F. `configs/run_v3_haiku.yaml`

```yaml
run_id: run_v3_haiku
model_name: claude
model_version: claude-haiku-4-5-20251001
prompt_version: v3
dataset_version: mvp_v2
dataset_path: data/requirements/mvp_dataset_v2.jsonl
gold_path: data/gold/gold_test_cases_v2.jsonl
generated_dir: data/generated
runs_dir: data/runs
reviews_dir: data/reviews
reports_dir: reports
scoring_version: v2
threshold_version: v2
scorer: heuristic
thresholds:
  pass: 1.6
  borderline_low: 1.2
  weights:
    correctness: 0.35
    completeness: 0.30
    hallucination_risk: 0.20
    reviewer_usefulness: 0.15
  floor:
    correctness: 1.0
    completeness: 1.0
    hallucination_risk: 1.0
diagnostics:
  flag_long_expected_result: true
  flag_low_step_verbosity: true
```

The `scorer` field is new (see `schemas.py` changes). It defaults to `"heuristic"` when absent — all existing configs continue to work without it. `"llm-judge"` enables `LLMJudgeScorer`.

### G. `scripts/check_quality_gate.py`

Standalone script — no `harness` package import. Called by the CI `quality-gate` job.

```python
#!/usr/bin/env python3
"""
Usage: python scripts/check_quality_gate.py [--runs-dir data/runs] [--last N]
Exit 0: all recent runs have quality_gate_decision != "fail"
Exit 1: one or more recent runs failed; prints a summary table
Exit 0 with notice: runs_dir is empty or does not exist
"""
```

Reads `*.json` files from `--runs-dir`, sorts by `timestamp` descending, checks the last `N` (default 5). Outputs a plain-text table to stdout. Does not use `rich` (CI log readability without color codes).

### H. `.github/workflows/ci.yml`

Two jobs:

**`test`** (blocking gate):
```yaml
- run: pip install -e ".[dev]"
- run: pytest tests/ --cov=harness --cov-report=term-missing
```

**`quality-gate`** (advisory, non-blocking):
```yaml
needs: test
- run: pip install -e .
- run: python scripts/check_quality_gate.py --runs-dir data/runs --last 5
  continue-on-error: true  # advisory only — does not block PR merge
```

CI **never** calls the Anthropic API. All tests use synthetic fixtures or monkeypatched API calls. This is enforced by convention, not tooling — document explicitly in the workflow file comments.

---

## 4. Modifications to Existing Files

### `src/harness/schemas.py`

Add `scorer_type` to `RunManifest` (backward-compatible default):

```python
class RunManifest(BaseModel):
    # ... all existing fields unchanged ...
    scorer_type: str = "heuristic"  # "heuristic" | "llm-judge"
```

Add two new schemas for LLM judge auditability (do not affect existing code):

```python
class CoveragePointAssessment(BaseModel):
    point: str
    covered: bool
    evidence: str = ""

class LLMJudgeVerdict(BaseModel):
    requirement_id: str
    coverage_assessments: list[CoveragePointAssessment]
    correctness_score: Score
    correctness_rationale: str
    hallucination_risk_score: Score
    hallucination_risk_rationale: str
    reviewer_usefulness_score: Score
    reviewer_usefulness_rationale: str
    judge_model: str
    judge_prompt_version: str
```

### `src/harness/evaluate.py`

Add optional `scorer` parameter. Fully backward-compatible — all existing callers continue to work:

```python
def run(
    config_path: str,
    run_id: str | None = None,
    scorer: Callable[[ModelOutput, GoldAnnotation, ...], ScoredResult] | None = None,
) -> list[ScoredResult]:
    ...
    score_fn = scorer or scoring.score
    result = score_fn(output, gold, weights=weights, thresholds=thresholds, diagnostics=diagnostics)
```

### `src/harness/run_eval.py`

Add scorer construction from config and `scorer_type` in manifest:

```python
def _build_scorer(cfg: dict) -> Callable | None:
    scorer_type = cfg.get("scorer", "heuristic")
    if scorer_type == "llm-judge":
        from harness.llm_judge import LLMJudgeScorer
        return LLMJudgeScorer(
            judge_model=cfg.get("judge_model", cfg["model_version"]),
            judge_prompt_version=cfg.get("judge_prompt_version", "judge_v1"),
        ).score
    return None  # None → evaluate.run() uses heuristic default

# In build_manifest():
manifest = RunManifest(
    ...
    scorer_type=cfg.get("scorer", "heuristic"),
)
```

---

## 5. Build Order

Stages 2, 3, and 4 are fully parallel after Stage 1.

```
[Stage 1 — Scaffolding and config]
  pyproject.toml                      ← add rich, matplotlib extra, pytest-mock, ruff
  src/harness/schemas.py              ← add scorer_type to RunManifest, add LLMJudgeVerdict
  configs/run_v3_haiku.yaml           ← new config (no code changes needed)
  src/harness/prompts/v3.txt          ← haiku-tuned prompt

[Stage 2 — LLM judge]  (parallel with Stages 3 and 4)
  src/harness/prompts/judge_v1.txt    ← judge prompt template
  src/harness/llm_judge.py            ← LLMJudgeScorer
  src/harness/evaluate.py             ← inject scorer parameter (backward-compatible)
  src/harness/run_eval.py             ← _build_scorer(), scorer_type in manifest
  tests/test_llm_judge.py             ← all mocked, no API calls

[Stage 3 — Charts]  (parallel with Stages 2 and 4)
  src/harness/charts.py               ← all chart generation functions
  src/harness/report.py               ← charts: bool = False parameter, embed links
  src/harness/compare_report.py       ← charts: bool = False parameter
  src/harness/trend_report.py         ← charts: bool = False parameter
  tests/test_charts.py                ← file-creation tests with importorskip

[Stage 4 — Rich CLI]  (parallel with Stages 2 and 3)
  src/harness/cli.py                  ← unified subcommand entry point
  src/harness/review_cli.py           ← optional console parameter in _display_item()
  src/harness/__main__.py             ← entry point: from harness.cli import main; main()
  tests/test_cli.py                   ← parser tests, summary panel rendering

[Stage 5 — CI]  (after all tests pass)
  scripts/check_quality_gate.py       ← standalone manifest checker
  .github/workflows/ci.yml            ← test + quality-gate jobs

[Stage 6 — Second model run and docs]  (after Stage 1 and Stage 2 complete)
  Run: python -m harness run --config configs/run_v3_haiku.yaml
  Run: python -m harness compare --run-a <sonnet_run> --run-b <haiku_run> ...
  README.md                           ← Phase 3 commands, chart output, comparison
```

---

## 6. Phase 3 Implementation Checklist

### Stage 1 — Scaffolding

- [ ] `pyproject.toml`: add `rich>=13.0` to core dependencies
- [ ] `pyproject.toml`: add `matplotlib>=3.8` to `[project.optional-dependencies] charts`
- [ ] `pyproject.toml`: add `pytest-mock>=3.0` to dev dependencies
- [ ] `pyproject.toml`: add `ruff>=0.4` to dev dependencies
- [ ] `src/harness/schemas.py`: add `scorer_type: str = "heuristic"` to `RunManifest`
- [ ] `src/harness/schemas.py`: add `CoveragePointAssessment` and `LLMJudgeVerdict` models
- [ ] `configs/run_v3_haiku.yaml`: complete config per section 3F
- [ ] `src/harness/prompts/v3.txt`: concise v2 variant (retain schema and constraints, remove behavior-enumeration prelude)

### Stage 2 — LLM Judge

- [ ] `src/harness/prompts/judge_v1.txt`: judge prompt with `### SYSTEM ###` / `### USER ###` delimiters
  - [ ] System section establishes evaluator role, requires JSON-only output
  - [ ] User section inlines generated output and gold criteria (not raw requirement text)
  - [ ] Per-point coverage assessment with evidence quote
  - [ ] Scores correctness, hallucination_risk, reviewer_usefulness on 0–2 scale
- [ ] `src/harness/llm_judge.py`: `LLMJudgeScorerError` exception
- [ ] `src/harness/llm_judge.py`: `LLMJudgeScorer.__init__()` with model, prompt version, max_tokens
- [ ] `src/harness/llm_judge.py`: `LLMJudgeScorer.score()` matching `score.score()` signature exactly
- [ ] `src/harness/llm_judge.py`: `LLMJudgeScorer._build_judge_prompt()` — does NOT include raw requirement text
- [ ] `src/harness/llm_judge.py`: `LLMJudgeScorer._parse_verdict()` — raises `LLMJudgeScorerError` on malformed output
- [ ] `src/harness/llm_judge.py`: fallback to `score.score()` on API failure, log warning with failure reason
- [ ] `src/harness/llm_judge.py`: write `{req_id}.judge.json` sidecar to `data/generated/{run_id}/`
- [ ] `src/harness/llm_judge.py`: derive `completeness_score` from coverage_assessments, not from judge verdict
- [ ] `src/harness/evaluate.py`: add `scorer: Callable | None = None` parameter to `run()`
- [ ] `src/harness/evaluate.py`: `score_fn = scorer or scoring.score` — backward-compatible
- [ ] `src/harness/run_eval.py`: `_build_scorer(cfg)` function
- [ ] `src/harness/run_eval.py`: pass `scorer_type` to `RunManifest` construction
- [ ] `tests/test_llm_judge.py`: valid verdict parses to correct `ScoredResult`
- [ ] `tests/test_llm_judge.py`: malformed JSON raises `LLMJudgeScorerError`
- [ ] `tests/test_llm_judge.py`: verdict missing required field raises error
- [ ] `tests/test_llm_judge.py`: API error triggers fallback to heuristic scorer
- [ ] `tests/test_llm_judge.py`: coverage assessments drive completeness score correctly
- [ ] `tests/test_llm_judge.py`: `ScoredResult` fields map correctly from verdict
- [ ] `tests/test_llm_judge.py`: judge prompt contains coverage points
- [ ] `tests/test_llm_judge.py`: judge prompt does NOT contain raw requirement text
- [ ] `tests/test_llm_judge.py`: verdict sidecar `.judge.json` is written to disk

### Stage 3 — Charts

- [ ] `src/harness/charts.py`: `matplotlib.use("Agg")` at module level before any other matplotlib import
- [ ] `src/harness/charts.py`: graceful `None` return and logged warning when matplotlib unavailable
- [ ] `src/harness/charts.py`: `plot_score_distribution()` — horizontal bar, pass/borderline/fail counts
- [ ] `src/harness/charts.py`: `plot_dimension_scores()` — grouped bar, avg per-dimension scores with floor line
- [ ] `src/harness/charts.py`: `plot_per_requirement_scores()` — bar per requirement, colored by decision band, threshold lines
- [ ] `src/harness/charts.py`: `plot_compare_distribution()` — side-by-side grouped bar for two runs
- [ ] `src/harness/charts.py`: `plot_compare_delta()` — per-requirement delta scatter, improvement/regression coloring
- [ ] `src/harness/charts.py`: `plot_trend_pass_rate()` — line chart with pass rate and borderline rate
- [ ] `src/harness/charts.py`: `plot_domain_heatmap()` — rows = domains, columns = run_ids, values = pass rate
- [ ] `src/harness/report.py`: `write_report()` gains `charts: bool = False` parameter
- [ ] `src/harness/report.py`: embed `![chart](...)` markdown links when charts generated
- [ ] `src/harness/compare_report.py`: `write_compare_report()` gains `charts: bool = False`
- [ ] `src/harness/trend_report.py`: `write_trend_report()` gains `charts: bool = False`
- [ ] `tests/test_charts.py`: `pytest.importorskip("matplotlib")` at module level
- [ ] `tests/test_charts.py`: each chart function creates a non-empty `.png` file in `tmp_path`
- [ ] `tests/test_charts.py`: graceful `None` return when matplotlib unavailable (mock sys.modules)

### Stage 4 — Rich CLI

- [ ] `src/harness/cli.py`: `make_parser()` with all subcommands and their required arguments
- [ ] `src/harness/cli.py`: `cmd_run()` with `rich.progress.Progress` wrapping generate loop
- [ ] `src/harness/cli.py`: `cmd_generate()`, `cmd_evaluate()`, `cmd_report()`, `cmd_review()`, `cmd_compare()`, `cmd_trend()`
- [ ] `src/harness/cli.py`: `print_run_summary()` — rich Panel, quality gate colored (green/yellow/red)
- [ ] `src/harness/cli.py`: `print_results_table()` — rich Table, decision column colored
- [ ] `src/harness/cli.py`: `main()` entry point
- [ ] `src/harness/__main__.py`: `from harness.cli import main; main()` (enables `python -m harness`)
- [ ] `src/harness/review_cli.py`: `_display_item()` gains `console: Console | None = None` parameter
- [ ] `src/harness/review_cli.py`: falls back to `print()` when `console is None` (existing tests unaffected)
- [ ] `tests/test_cli.py`: `run` subcommand requires `--config`
- [ ] `tests/test_cli.py`: `review` subcommand requires `--run-id`
- [ ] `tests/test_cli.py`: `compare` subcommand requires both `--run-a` and `--run-b`
- [ ] `tests/test_cli.py`: unknown subcommand exits with non-zero code
- [ ] `tests/test_cli.py`: `print_run_summary()` contains "pass"/"fail"/"needs_review" text (use `Console(file=StringIO())`)
- [ ] `tests/test_cli.py`: `print_results_table()` contains all requirement IDs

### Stage 5 — CI

- [ ] `scripts/check_quality_gate.py`: reads `*.json` from `--runs-dir`, sorts by timestamp, checks last N
- [ ] `scripts/check_quality_gate.py`: exit 0 with notice when `runs_dir` is empty or missing
- [ ] `scripts/check_quality_gate.py`: exit 0 when all recent runs have `quality_gate_decision != "fail"`
- [ ] `scripts/check_quality_gate.py`: exit 1 with summary table when any recent run failed
- [ ] `scripts/check_quality_gate.py`: no `harness` package import, no `rich` dependency
- [ ] `.github/workflows/ci.yml`: `test` job with `pip install -e ".[dev]"` and `pytest tests/`
- [ ] `.github/workflows/ci.yml`: `quality-gate` job with `continue-on-error: true` (advisory)
- [ ] `.github/workflows/ci.yml`: comment in workflow file: "This workflow never calls the Anthropic API"
- [ ] `.github/workflows/ci.yml`: `quality-gate` job is a no-op (exit 0) if `data/runs/` is empty

### Stage 6 — Second model run and documentation

- [ ] Verify exact Anthropic model ID for Haiku and update `configs/run_v3_haiku.yaml`
- [ ] Run: `python -m harness run --config configs/run_v3_haiku.yaml`
- [ ] Run: `python -m harness compare --run-a <best_sonnet_run> --run-b <haiku_run> ...`
- [ ] Run: `python -m harness trend --dataset-path data/requirements/mvp_dataset_v2.jsonl`
- [ ] Calibrate judge: run both heuristic and llm-judge on same 10 requirements, compare score distributions before making llm-judge default for any config
- [ ] `README.md`: add Phase 3 CLI commands (`python -m harness <subcommand>`)
- [ ] `README.md`: add chart output section with embedded sample PNGs
- [ ] `README.md`: add haiku vs. sonnet comparison summary
- [ ] `README.md`: add LLM-as-judge section explaining when to use and cost implications
- [ ] `README.md`: update Known Limitations: remove "single model, single prompt" from item 4

---

## 7. Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `matplotlib` as optional extra | `pip install -e ".[charts]"` | Core harness stays lightweight; charts are human-consumption only, not needed for CI or scoring |
| LLM-judge as a callable, not a subclass | `LLMJudgeScorer().score` passed as `scorer=` arg | Matches existing function signature with no Protocol overhead; one alternative implementation does not justify an ABC |
| Judge sees gold, not raw requirement | Gold criteria only in judge prompt | Prevents the judge from scoring against its own mental re-generation of test cases |
| `rich` confined to `cli.py` and one optional param | No `rich` import in business logic modules | All existing tests continue to pass without `rich` installed; `rich` can be upgraded without touching scoring logic |
| CI quality gate is advisory | `continue-on-error: true` | A historical evaluation `"fail"` should not block a PR; code correctness (pytest) is the hard gate |
| v3 prompt is a concise v2 | Remove behavior-enumeration prelude only | Keeps haiku comparison to one variable (model) rather than two (model + prompt strategy) |
| Completeness derived in harness, not by judge | Coverage assessment is binary per-point | More consistent than asking the judge for a holistic 0–2 score; matches heuristic dimension definition |
| `data/runs/` handling in CI | No-op if directory is empty | Avoids blocking CI for projects that don't commit run manifests; quality gate is advisory anyway |

---

## 8. Anticipated Challenges

1. **Judge calibration** — The first `judge_v1.txt` will likely produce scores systematically higher or lower than the heuristic. Run both scorers on the same 10 requirements and compare distributions before committing the judge as the default scorer for any config. Document this calibration result in `docs/phase3_decisions.md`.

2. **`matplotlib` in headless environments** — Must call `matplotlib.use("Agg")` before any other matplotlib import in `charts.py`. Forgetting this causes `UserWarning: Matplotlib is currently using TkAgg` in CI and may crash in environments without a display server.

3. **`rich` on Windows terminals** — The project runs on Windows (win32). `rich` handles Windows color codes correctly, but test `rich` output via `Console(force_terminal=True)` in tests to avoid environment-dependent rendering differences between Windows dev and Linux CI.

4. **`data/runs/` not in git** — The CI quality gate job needs committed manifests. Options: (a) commit a small set of sample manifests to `data/runs/sample/` for CI demonstration, or (b) make the job unconditionally no-op when the directory is empty (chosen approach — simpler, avoids committing run artifacts).

5. **Haiku model string** — Confirm the exact Anthropic model identifier before writing `run_v3_haiku.yaml`. Current best guess based on environment: `claude-haiku-4-5-20251001`. Wrong model string produces an API error on the first `generate` call.

6. **`scorer` field missing from existing configs** — All existing YAML configs omit the `scorer` field. `run_eval.py`'s `_build_scorer()` must default to `"heuristic"` when the field is absent (not raise a KeyError). Test this explicitly.

---

## 9. Known Limitations to Document (Phase 3 additions)

In addition to the limitations carried forward from Phase 1/2, add to README.md and report template:

7. LLM-as-judge scores are model-dependent — the same output may score differently across judge model versions; pin `judge_model` in configs for reproducibility
8. Chart output requires the `charts` extra (`pip install -e ".[charts]"`); reports without it embed no images
9. Haiku comparison uses a different prompt version (v3) to account for model size — this is a deliberate design choice, not a bug; it means the comparison is "best haiku config vs. best sonnet config" rather than a pure model-only comparison
