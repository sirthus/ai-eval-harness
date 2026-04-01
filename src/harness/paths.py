"""Centralised path helpers for harness run artifacts."""

from __future__ import annotations

from pathlib import Path


class ArtifactPaths:
    """Path helpers for artifacts stored under the generated directory for a single run."""

    def __init__(self, generated_dir: str, run_id: str) -> None:
        self.run_dir = Path(generated_dir) / run_id
        self.scored_results = self.run_dir / "scored_results.json"
        self.parse_failures = self.run_dir / "parse_failures.jsonl"

    def output_file(self, requirement_id: str) -> Path:
        """Path to the generated output JSON for a requirement."""
        return self.run_dir / f"{requirement_id}.json"

    def failure_marker(self, requirement_id: str) -> Path:
        """Path to the failure marker JSON for a requirement."""
        return self.run_dir / f"{requirement_id}.fail.json"

    def judge_sidecar(self, requirement_id: str) -> Path:
        """Path to the LLM judge sidecar JSON for a requirement."""
        return self.run_dir / f"{requirement_id}.judge.json"


def manifest_path(runs_dir: str, run_id: str) -> Path:
    """Return the canonical path to a run manifest file."""
    return Path(runs_dir) / f"{run_id}.json"
