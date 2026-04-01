"""Shared data-loading helpers used by multiple harness modules."""

from __future__ import annotations

import json
import logging

import yaml

from harness.paths import ArtifactPaths, manifest_path
from harness.schemas import Requirement, RunManifest, ScoredResult

logger = logging.getLogger(__name__)


def load_manifest(runs_dir: str, run_id: str) -> RunManifest:
    """Load and return the RunManifest for a given run. Raises FileNotFoundError if missing."""
    path = manifest_path(runs_dir, run_id)
    if not path.exists():
        raise FileNotFoundError(f"Run manifest not found: {path}")
    return RunManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_scored_results(
    generated_dir: str,
    run_id: str,
    *,
    raise_on_missing: bool = True,
) -> dict[str, ScoredResult]:
    """Load scored results for a run.

    When raise_on_missing=True (default), raises FileNotFoundError if the file does not
    exist — consistent with compare_report's strict contract.
    When raise_on_missing=False, logs a warning and returns an empty dict — consistent
    with trend_report's tolerant contract.
    """
    path = ArtifactPaths(generated_dir, run_id).scored_results
    if not path.exists():
        if raise_on_missing:
            raise FileNotFoundError(f"Scored results not found: {path}")
        logger.warning("scored_results.json not found for run %s", run_id)
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {r["requirement_id"]: ScoredResult.model_validate(r) for r in raw}


def load_requirements(dataset_path: str) -> list[Requirement]:
    """Load and return requirements from a JSONL dataset file."""
    reqs = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(Requirement.model_validate(json.loads(line)))
    return reqs


def load_config(config_path: str) -> dict:
    """Load and return a YAML run config."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
