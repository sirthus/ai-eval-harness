#!/usr/bin/env python3
"""Quality gate checker for CI.

Reads run manifests from data/runs/, checks quality_gate_decision field on
the most recent N runs. Reports and exits non-zero if any recent run failed.

This script has no harness package dependency — it reads raw JSON directly.
It also does not import rich — output uses plain text for clean CI logs.

Usage:
    python scripts/check_quality_gate.py [--runs-dir data/runs] [--last 5]

Exit codes:
    0 — all recent runs pass (or no runs found — advisory only)
    1 — one or more recent runs have quality_gate_decision == "fail"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_manifests(runs_dir: Path) -> list[dict]:
    """Load all run manifest JSON files from the given directory."""
    manifests = []
    if not runs_dir.exists():
        return manifests
    for path in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            manifests.append(data)
        except Exception as exc:
            print(f"WARNING: Could not read manifest {path}: {exc}", file=sys.stderr)
    return manifests


def sort_by_timestamp(manifests: list[dict]) -> list[dict]:
    return sorted(manifests, key=lambda m: m.get("timestamp", ""), reverse=True)


def check(runs_dir: Path, last_n: int) -> int:
    """Check quality gate. Returns exit code (0 = pass, 1 = fail)."""
    manifests = load_manifests(runs_dir)

    if not manifests:
        print(f"INFO: No run manifests found in '{runs_dir}'. Quality gate check skipped.")
        return 0

    recent = sort_by_timestamp(manifests)[:last_n]
    print(f"Checking quality gate for {len(recent)} most recent run(s) in '{runs_dir}':\n")

    col_w = [40, 30, 15, 15]
    header = (
        f"{'Run ID':<{col_w[0]}} "
        f"{'Timestamp':<{col_w[1]}} "
        f"{'Avg Score':<{col_w[2]}} "
        f"{'Gate':<{col_w[3]}}"
    )
    print(header)
    print("-" * sum(col_w))

    failures = []
    for m in recent:
        run_id = m.get("run_id", "unknown")[:col_w[0]]
        timestamp = m.get("timestamp", "")[:19]
        avg_score = m.get("avg_weighted_score", 0.0)
        gate = m.get("quality_gate_decision", "n/a")
        marker = "  <-- FAIL" if gate == "fail" else ""
        print(
            f"{run_id:<{col_w[0]}} "
            f"{timestamp:<{col_w[1]}} "
            f"{avg_score:<{col_w[2]}.2f} "
            f"{gate:<{col_w[3]}}"
            f"{marker}"
        )
        if gate == "fail":
            failures.append(run_id)

    print()

    if failures:
        print(
            f"FAIL: {len(failures)} of the last {len(recent)} run(s) have "
            f"quality_gate_decision='fail':"
        )
        for run_id in failures:
            print(f"  - {run_id}")
        print(
            "\nNote: This check is advisory — it reports on evaluation quality, "
            "not code correctness."
        )
        return 1

    print(f"PASS: All {len(recent)} recent run(s) passed the quality gate.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check quality gate status of recent evaluation runs."
    )
    parser.add_argument(
        "--runs-dir",
        default="data/runs",
        help="Directory containing run manifest JSON files (default: data/runs)",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=5,
        metavar="N",
        help="Number of most recent runs to check (default: 5)",
    )
    args = parser.parse_args()
    sys.exit(check(Path(args.runs_dir), args.last))


if __name__ == "__main__":
    main()
