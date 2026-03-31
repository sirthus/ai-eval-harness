"""Full evaluation pipeline orchestrator.

Usage:
    python -m harness.run_eval --config configs/run_v1.yaml

Each invocation generates a unique run ID of the form `{config_run_id}_{timestamp}`
(e.g. run_v1_20260329T143022Z). This ensures every run produces isolated output
directories and a distinct manifest entry, making the evaluation history reproducible
and comparable.

Steps:
    1. Load run config; assign unique run ID
    2. Generate model outputs (calls model API)
    3. Score generated outputs against gold
    4. Write review queue for borderline results
    5. Write CSV + markdown report
    6. Save run manifest (includes parse failure counts)
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import yaml

from harness import evaluate, generate, review_queue, report
from harness.schemas import RunManifest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _git_commit_hash() -> str:
    command = ["git", "rev-parse", "--short", "HEAD"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as exc:
        logger.warning("Failed to determine git commit hash via %s: %s", command, exc)
        return "unknown"


def _git_is_dirty() -> bool:
    """Return True if the working tree has uncommitted changes. Defaults to True on error."""
    command = ["git", "status", "--porcelain"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except Exception as exc:
        logger.warning("Failed to determine git dirty state via %s: %s", command, exc)
        return True  # unknown state — treat as dirty


def _make_run_id(base: str, timestamp: datetime) -> str:
    """Produce a sortable, unique run ID: {base}_{YYYYMMDDTHHMMSSz}."""
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return f"{base}_{stamp}"


def _build_scorer(cfg: dict, run_id: str) -> Callable | None:
    """Construct scorer from config. Returns None for the default heuristic scorer."""
    scorer_type = cfg.get("scorer", "heuristic")
    if scorer_type == "llm-judge":
        from harness.llm_judge import LLMJudgeScorer
        sidecar_dir = Path(cfg["generated_dir"]) / run_id
        return LLMJudgeScorer(
            judge_model=cfg.get("judge_model", cfg["model_version"]),
            judge_prompt_version=cfg.get("judge_prompt_version", "judge_v1"),
            sidecar_dir=sidecar_dir,
        ).score
    return None  # None → evaluate.run() uses heuristic default


def _compute_quality_gate(
    pass_rate: float,
    borderlines: int,
    parse_failures: int,
) -> Literal["pass", "needs_review", "fail"]:
    """Compute run-level quality gate decision from aggregate outcomes."""
    if pass_rate >= 0.70 and borderlines <= 2 and parse_failures == 0:
        return "pass"
    if pass_rate < 0.40:
        return "fail"
    if borderlines > 0 or parse_failures > 0:
        return "needs_review"
    return "fail"


def run(config_path: str) -> RunManifest:
    logger.info("=== Starting evaluation run ===")
    logger.info("Config: %s", config_path)

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    timestamp = datetime.now(timezone.utc)
    # Unique ID for this execution; config run_id is the series/version identifier.
    run_id = _make_run_id(cfg["run_id"], timestamp)
    git_hash = _git_commit_hash()
    git_dirty = _git_is_dirty()

    logger.info("Run ID: %s", run_id)

    # Step 1: Generate
    logger.info("--- Step 1: Generate ---")
    _, parse_failure_ids = generate.run(config_path, run_id=run_id)

    # Step 2: Evaluate (with optional LLM judge scorer)
    logger.info("--- Step 2: Evaluate ---")
    scorer = _build_scorer(cfg, run_id)
    results = evaluate.run(config_path, run_id=run_id, scorer=scorer)

    if not results and not parse_failure_ids:
        logger.error("No results produced — check generated outputs.")
        sys.exit(1)

    # Step 3: Review queue
    logger.info("--- Step 3: Review queue ---")
    review_queue.write_queue(
        results,
        run_id=run_id,
        reviews_dir=cfg["reviews_dir"],
    )

    # Step 4: Report
    logger.info("--- Step 4: Report ---")

    # Load total requirements count from dataset
    with open(cfg["dataset_path"], encoding="utf-8") as f:
        total_requirements = sum(1 for line in f if line.strip())

    passes = sum(1 for r in results if r.decision == "pass")
    borderlines = sum(1 for r in results if r.decision == "borderline")
    fails = sum(1 for r in results if r.decision == "fail")
    avg_score = sum(r.weighted_score for r in results) / len(results) if results else 0.0
    parse_failure_count = len(parse_failure_ids)

    evaluated = len(results)
    pass_rate = passes / evaluated if evaluated else 0.0
    quality_gate_decision = _compute_quality_gate(
        pass_rate,
        borderlines,
        parse_failure_count,
    )

    manifest = RunManifest(
        run_id=run_id,
        model_name=cfg["model_name"],
        model_version=cfg["model_version"],
        prompt_version=cfg["prompt_version"],
        dataset_version=cfg["dataset_version"],
        scoring_version=cfg["scoring_version"],
        threshold_version=cfg["threshold_version"],
        timestamp=timestamp.isoformat(),
        git_commit_hash=git_hash,
        is_dirty=git_dirty,
        config_file=config_path,
        total_requirements=total_requirements,
        parse_failures=parse_failure_count,
        total_evaluated=len(results),
        pass_count=passes,
        borderline_count=borderlines,
        fail_count=fails,
        avg_weighted_score=round(avg_score, 4),
        scorer_type=cfg.get("scorer", "heuristic"),
        quality_gate_decision=quality_gate_decision,
    )
    report.write_report(results, manifest, cfg["reports_dir"])

    # Step 5: Save run manifest
    runs_dir = Path(cfg["runs_dir"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = runs_dir / f"{run_id}.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Run manifest saved: %s", manifest_path)

    # Summary
    logger.info("=== Run complete: %s ===", run_id)
    logger.info(
        "Results: %d/%d evaluated | %d pass / %d borderline / %d fail | %d parse failure(s) | avg score %.2f",
        len(results),
        total_requirements,
        passes,
        borderlines,
        fails,
        len(parse_failure_ids),
        avg_score,
    )

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full evaluation pipeline")
    parser.add_argument("--config", required=True, help="Path to run config YAML")
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
