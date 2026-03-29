"""Generation step: call the model for each requirement, write outputs to disk.

Usage:
    python -m harness.generate --config configs/run_v1.yaml [--run-id run_v1_20260329T143022]

Parse failures are written to {generated_dir}/{run_id}/parse_failures.jsonl so they
are first-class run artifacts and can be counted in the manifest.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from harness import model_adapter
from harness.schemas import Requirement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_FAILURES_FILE = "parse_failures.jsonl"


def run(config_path: str, run_id: str | None = None) -> tuple[Path, list[str]]:
    """Generate outputs for all requirements.

    Returns (generated_dir, failed_requirement_ids).
    run_id overrides the config's run_id when provided (used by run_eval.py
    to write outputs under a timestamped directory).
    """
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    effective_run_id = run_id or cfg["run_id"]
    model_version: str = cfg["model_version"]
    prompt_version: str = cfg["prompt_version"]
    dataset_path: str = cfg["dataset_path"]
    generated_dir = Path(cfg["generated_dir"]) / effective_run_id
    generated_dir.mkdir(parents=True, exist_ok=True)

    requirements = _load_requirements(dataset_path)
    logger.info("Loaded %d requirements from %s", len(requirements), dataset_path)

    # Fail fast if the API key is missing — no point starting the loop.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    failures: list[str] = []
    for req in requirements:
        out_path = generated_dir / f"{req.requirement_id}.json"
        failure_marker = generated_dir / f"{req.requirement_id}.fail.json"
        if out_path.exists():
            logger.info("Skipping %s (already generated)", req.requirement_id)
            continue
        if failure_marker.exists():
            logger.info("Skipping %s (previously failed)", req.requirement_id)
            failures.append(req.requirement_id)
            continue
        try:
            output = model_adapter.generate(
                requirement_id=req.requirement_id,
                requirement_text=req.requirement_text,
                model_version=model_version,
                prompt_version=prompt_version,
            )
            out_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")
            logger.info("Generated %s → %s", req.requirement_id, out_path)
        except Exception as exc:
            # Catches ValueError (parse/schema), anthropic.APIError (rate limit,
            # network, status errors), and any other transient failure. All failures
            # write a marker so reruns skip this requirement rather than retry blindly.
            logger.error(
                "Failed to generate %s (%s): %s",
                req.requirement_id, type(exc).__name__, exc,
            )
            failures.append(req.requirement_id)
            _write_failure_record(generated_dir, req.requirement_id, str(exc))

    if failures:
        logger.warning(
            "%d failure(s): %s", len(failures), failures
        )

    return generated_dir, failures


def _write_failure_record(
    generated_dir: Path, requirement_id: str, error: str
) -> None:
    """Write a per-requirement failure marker and append to the failures log."""
    record = {
        "requirement_id": requirement_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Per-file marker (allows skip-on-resume)
    marker = generated_dir / f"{requirement_id}.fail.json"
    marker.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Append to aggregate failures log
    failures_log = generated_dir / _FAILURES_FILE
    with open(failures_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _load_requirements(path: str) -> list[Requirement]:
    reqs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(Requirement.model_validate(json.loads(line)))
    return reqs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate model outputs")
    parser.add_argument("--config", required=True, help="Path to run config YAML")
    parser.add_argument(
        "--run-id", dest="run_id", default=None,
        help="Override run ID (default: uses config run_id)"
    )
    args = parser.parse_args()
    _, failures = run(args.config, run_id=args.run_id)
    if failures:
        print(f"Parse failures ({len(failures)}): {failures}")


if __name__ == "__main__":
    main()
