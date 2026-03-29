"""Report generation: produce CSV + markdown report from scored results.

Usage:
    python -m harness.report --config configs/run_v1.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import yaml

from harness.schemas import RunManifest, ScoredResult

logger = logging.getLogger(__name__)


def write_report(
    results: list[ScoredResult],
    manifest: RunManifest,
    reports_dir: str,
) -> tuple[Path, Path]:
    """Write CSV and markdown report files. Returns (csv_path, md_path)."""
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{manifest.run_id}_scores.csv"
    md_path = out_dir / f"{manifest.run_id}_report.md"

    _write_csv(results, csv_path)
    _write_markdown(results, manifest, md_path)

    logger.info("Report written: %s", md_path)
    logger.info("Scores CSV written: %s", csv_path)
    return csv_path, md_path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _write_csv(results: list[ScoredResult], path: Path) -> None:
    fieldnames = [
        "requirement_id",
        "decision",
        "weighted_score",
        "correctness",
        "completeness",
        "hallucination_risk",
        "reviewer_usefulness",
        "coverage_ratio",
        "disallowed_hits",
        "scoring_notes",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: x.requirement_id):
            writer.writerow(
                {
                    "requirement_id": r.requirement_id,
                    "decision": r.decision,
                    "weighted_score": r.weighted_score,
                    "correctness": r.scores.correctness,
                    "completeness": r.scores.completeness,
                    "hallucination_risk": r.scores.hallucination_risk,
                    "reviewer_usefulness": r.scores.reviewer_usefulness,
                    "coverage_ratio": f"{r.coverage_ratio:.0%}",
                    "disallowed_hits": "; ".join(r.disallowed_hits),
                    "scoring_notes": r.scoring_notes,
                }
            )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _quality_gate_recommendation(
    results: list[ScoredResult], pass_threshold: float = 0.7
) -> str:
    total = len(results)
    if total == 0:
        return "No results to evaluate."
    pass_rate = sum(1 for r in results if r.decision == "pass") / total
    borderline_rate = sum(1 for r in results if r.decision == "borderline") / total

    if pass_rate >= pass_threshold:
        return (
            f"**Recommended for assisted internal use with reviewer oversight.** "
            f"Pass rate: {pass_rate:.0%}. "
            f"Borderline rate ({borderline_rate:.0%}) requires human review before production use."
        )
    if pass_rate >= 0.5:
        return (
            f"**Promising, but not yet reliable enough for routine use.** "
            f"Pass rate: {pass_rate:.0%}. Significant improvement needed before deployment."
        )
    return (
        f"**Not recommended for use without substantial human review.** "
        f"Pass rate: {pass_rate:.0%}. Model/prompt combination needs improvement."
    )


def _write_markdown(
    results: list[ScoredResult], manifest: RunManifest, path: Path
) -> None:
    total = len(results)
    passes = [r for r in results if r.decision == "pass"]
    borderlines = [r for r in results if r.decision == "borderline"]
    fails = [r for r in results if r.decision == "fail"]

    avg_weighted = (
        sum(r.weighted_score for r in results) / total if total else 0.0
    )
    avg_coverage = (
        sum(r.coverage_ratio for r in results) / total if total else 0.0
    )

    lines: list[str] = []

    # Header
    lines += [
        f"# Evaluation Report — {manifest.run_id}",
        "",
        "## Run Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run ID | `{manifest.run_id}` |",
        f"| Model | `{manifest.model_version}` |",
        f"| Prompt version | `{manifest.prompt_version}` |",
        f"| Dataset version | `{manifest.dataset_version}` |",
        f"| Scoring version | `{manifest.scoring_version}` |",
        f"| Timestamp | {manifest.timestamp} |",
        f"| Git commit | `{manifest.git_commit_hash}` |",
        f"| Config | `{manifest.config_file}` |",
        "",
        "### Aggregate Scores",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total samples | {total} |",
        f"| Pass | {len(passes)} ({len(passes)/total:.0%}) |",
        f"| Borderline | {len(borderlines)} ({len(borderlines)/total:.0%}) |",
        f"| Fail | {len(fails)} ({len(fails)/total:.0%}) |",
        f"| Avg weighted score | {avg_weighted:.2f} / 2.00 |",
        f"| Avg coverage ratio | {avg_coverage:.0%} |",
        "",
    ]

    # Quality gate
    lines += [
        "## Quality Gate Recommendation",
        "",
        _quality_gate_recommendation(results),
        "",
    ]

    # Per-sample table
    lines += [
        "## Per-Sample Results",
        "",
        "| ID | Decision | Weighted | Correct | Complete | Halluc Risk | Reviewer Use | Coverage | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda x: x.requirement_id):
        icon = {"pass": "✓", "borderline": "~", "fail": "✗"}.get(r.decision, "?")
        lines.append(
            f"| {r.requirement_id} | {icon} {r.decision} "
            f"| {r.weighted_score:.2f} "
            f"| {r.scores.correctness:.1f} "
            f"| {r.scores.completeness:.1f} "
            f"| {r.scores.hallucination_risk:.1f} "
            f"| {r.scores.reviewer_usefulness:.1f} "
            f"| {r.coverage_ratio:.0%} "
            f"| {r.scoring_notes or '—'} |"
        )
    lines.append("")

    # Failure analysis
    problem_results = borderlines + fails
    lines += ["## Failure Analysis", ""]
    if not problem_results:
        lines += ["All samples passed. No failure analysis needed.", ""]
    else:
        all_hits: list[str] = []
        low_coverage = []
        for r in problem_results:
            all_hits.extend(r.disallowed_hits)
            if r.coverage_ratio < 0.5:
                low_coverage.append(r.requirement_id)

        if low_coverage:
            lines += [
                f"**Low coverage (<50%):** {', '.join(low_coverage)}",
                "",
            ]
        if all_hits:
            from collections import Counter

            top_hits = Counter(all_hits).most_common(5)
            lines += ["**Most common disallowed assumption violations:**", ""]
            for phrase, count in top_hits:
                lines.append(f"- `{phrase}` — {count} occurrence(s)")
            lines.append("")

        lines += [
            "**Borderline samples (routed to human review queue):**",
            "",
        ]
        for r in borderlines:
            lines.append(
                f"- {r.requirement_id}: weighted={r.weighted_score:.2f}, "
                f"coverage={r.coverage_ratio:.0%}"
            )
        lines.append("")

        if fails:
            lines += ["**Failed samples:**", ""]
            for r in fails:
                lines.append(
                    f"- {r.requirement_id}: weighted={r.weighted_score:.2f}, "
                    f"coverage={r.coverage_ratio:.0%}. {r.scoring_notes}"
                )
            lines.append("")

    # Limitations
    lines += [
        "## Known Limitations",
        "",
        "- Gold coverage scoring uses keyword/phrase matching — semantic equivalence is not detected.",
        "- Hallucination risk scoring is heuristic-based; human review of borderline cases is required.",
        "- Gold dataset (10 requirements) is narrow; domain coverage is limited to TaskFlow SaaS scenarios.",
        "- Reviewer usefulness scoring uses structural proxies, not semantic judgment.",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Generate evaluation report")
    parser.add_argument("--config", required=True, help="Path to run config YAML")
    parser.add_argument(
        "--run-id", dest="run_id", default=None,
        help="Run ID to report on (default: uses config run_id)",
    )
    args = parser.parse_args()

    from harness.evaluate import scored_results_path

    results_path = scored_results_path(args.config, run_id=args.run_id)
    if not results_path.exists():
        raise FileNotFoundError(
            f"Scored results not found at {results_path}. "
            "Run `python -m harness.evaluate --config ...` first."
        )

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    raw = json.loads(results_path.read_text(encoding="utf-8"))
    results = [ScoredResult.model_validate(r) for r in raw]

    # Load manifest from runs dir
    run_id = args.run_id or cfg["run_id"]
    manifest_path = Path(cfg["runs_dir"]) / f"{run_id}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Run manifest not found at {manifest_path}. "
            "Run the full pipeline with `python -m harness.run_eval --config ...` first."
        )
    manifest = RunManifest.model_validate(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    write_report(results, manifest, cfg["reports_dir"])


if __name__ == "__main__":
    main()
