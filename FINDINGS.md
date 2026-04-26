# Code Review Findings

Captured on 2026-04-26 for follow-up polish after the GitHub showpiece pass.

## 1. [P1] Incomplete Runs Can Still Pass The Quality Gate

- File: `src/harness/run_eval.py`
- Lines reviewed: 131-147
- Issue: The gate uses `passes / len(results)` and only considers explicit parse failures. A run with missing or skipped requirements can still get `quality_gate_decision="pass"` if the scored subset passes.
- Follow-up: Treat `total_requirements - total_evaluated - parse_failures` as missing coverage and force `needs_review` or `fail`.

## 2. [P1] LLM-Judge Fallback Breaks Scorer Provenance

- File: `src/harness/llm_judge.py`
- Lines reviewed: 78-95
- Issue: When the judge fails or the API key is missing, results silently fall back to the heuristic scorer, but the manifest can still record `scorer_type="llm-judge"`.
- Follow-up: Either fail closed by default, or persist fallback counts and per-result scorer source.

## 3. [P2] Generated Output IDs Are Not Reconciled With Requested IDs

- File: `src/harness/model_adapter.py`
- Lines reviewed: 167-174
- Issue: The adapter validates the payload but never checks that `output.requirement_id` equals the requirement being generated. A mismatch or duplicate can overwrite results, skip gold lookup, or make a run look complete when it is not.
- Follow-up: Enforce ID equality during parsing/loading and add tests for mismatched and duplicate IDs.

## 4. [P2] LLM Schemas Allow Extra Fields Silently

- File: `src/harness/schemas.py`
- Lines reviewed: 14-27
- Issue: Pydantic ignores unknown fields by default, so model output with extra top-level or test-case keys can pass validation even though the project contract says output must match the schema.
- Follow-up: Add `ConfigDict(extra="forbid")` at least to `ModelOutput` and `TestCase`, plus regression tests.

## 5. [P2] Markdown Tables Are Not Escaped

- File: `src/harness/report.py`
- Lines reviewed: 327-356
- Issue: Report cells interpolate raw scoring notes and diagnostics. LLM judge rationales, reviewer notes, or diagnostics containing `|` or newlines can corrupt the markdown table.
- Follow-up: Add a markdown table-cell escaping and normalization helper, then cover notes with pipes and newlines.

## 6. [P2] Built Wheels Omit Prompt Templates

- File: `pyproject.toml`
- Lines reviewed: 37-38
- Issue: A built wheel contains the Python modules but not `harness/prompts/*.txt`; non-editable installs will fail generation and judge prompt loading.
- Follow-up: Add setuptools package-data for prompt text files and a packaging test that inspects the wheel contents.

## 7. [P3] Config Paths Depend On Current Working Directory

- File: `src/harness/loaders.py`
- Lines reviewed: 58-61
- Issue: Config values like `data/generated` are used as raw relative paths. Running `harness report --config /abs/path/configs/run_v1.yaml` from another directory looks for artifacts under the current working directory instead of the repo/config location.
- Follow-up: Resolve config-relative paths centrally, or explicitly document and enforce repo-root execution.
