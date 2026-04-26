"""Shared data-loading helpers used by multiple harness modules."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from harness.paths import ArtifactPaths, manifest_path
from harness.schemas import Requirement, RunManifest, ScoredResult

logger = logging.getLogger(__name__)

_CONFIG_PATH_KEYS = {
    "dataset_path",
    "gold_path",
    "generated_dir",
    "runs_dir",
    "reviews_dir",
    "reports_dir",
}


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


def _find_repo_root(start: Path) -> Path | None:
    """Return the nearest ancestor containing pyproject.toml."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return None


def _resolve_config_path_value(value: object, base_dir: Path) -> object:
    if not isinstance(value, str):
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def load_config(config_path: str | Path) -> dict:
    """Load and return a YAML run config."""
    resolved_config_path = Path(config_path).expanduser().resolve()
    with open(resolved_config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if not isinstance(cfg, dict):
        return cfg

    base_dir = _find_repo_root(resolved_config_path.parent)
    if base_dir is None:
        base_dir = resolved_config_path.parent
        logger.warning(
            "No pyproject.toml found above %s; resolving config paths relative to %s",
            resolved_config_path,
            base_dir,
        )

    resolved = dict(cfg)
    for key in _CONFIG_PATH_KEYS:
        if key in resolved:
            resolved[key] = _resolve_config_path_value(resolved[key], base_dir)
    return resolved
