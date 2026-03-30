"""Report generation: produce CSV + markdown report from scored results.

Usage:
    python -m harness.report --config configs/run_v1.yaml [--use-human-review]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import yaml

from harness.review_queue import load_adjudicated
from harness.schemas import ReviewRecord, RunManifest, ScoredResult

logger = logging.getLogger(__name__)


def write_report(
    results: list[ScoredResult],
    manifest: RunManifest,
    reports_dir: str,
    adjudicated: dict[str, ReviewRecord] | None = None,
    charts: bool = False,
) -> tuple[Path, Path]:
    """Write CSV and markdown report files. Returns (csv_path, md_path).

    If adjudicated is provided, human review decisions are shown alongside
    auto decisions. Auto-scored data is never modified.
    If charts=True, PNG charts are generated in the same directory and
    embedded as image links in the markdown.
    """
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{manifest.run_id}_scores.csv"
    md_path = out_dir / f"{manifest.run_id}_report.md"

    chart_paths: dict[str, Path] = {}
    if charts:
        from harness import charts as chart_module
        for name, fn, args in [
            ("distribution", chart_module.plot_score_distribution, (results, manifest.run_id, out_dir)),
            ("dimensions", chart_module.plot_dimension_scores, (results, manifest.run_id, out_dir)),
            ("per_requirement", chart_module.plot_per_requirement_scores, (results, manifest.run_id, out_dir)),
        ]:
            path = fn(*args)
            if path:
                chart_paths[name] = path

    _write_csv(results, csv_path, adjudicated=adjudicated)
    _write_markdown(results, manifest, md_path, adjudicated=adjudicated, chart_paths=chart_paths)

    logger.info("Report written: %s", md_path)
    logger.info("Scores CSV written: %s", csv_path)
    return csv_path, md_path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _write_csv(
    results: list[ScoredResult],
    path: Path,
    adjudicated: dict[str, ReviewRecord] | None = None,
) -> None:
    fieldnames = [
        "requirement_id",
        "auto_decision",
        "weighted_score",
        "correctness",
        "completeness",
        "hallucination_risk",
        "reviewer_usefulness",
        "coverage_ratio",
        "disallowed_hits",
        "scoring_notes",
        "diagnostic_notes",
    ]
    if adjudicated is not None:
        fieldnames.append("human_decision")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: x.requirement_id):
            row = {
                "requirement_id": r.requirement_id,
                "auto_decision": r.decision,
                "weighted_score": r.weighted_score,
                "correctness": r.scores.correctness,
                "completeness": r.scores.completeness,
                "hallucination_risk": r.scores.hallucination_risk,
                "reviewer_usefulness": r.scores.reviewer_usefulness,
                "coverage_ratio": f"{r.coverage_ratio:.0%}",
                "disallowed_hits": "; ".join(r.disallowed_hits),
                "scoring_notes": r.scoring_notes,
                "diagnostic_notes": r.diagnostic_notes,
            }
            if adjudicated is not None:
                rec = adjudicated.get(r.requirement_id) if adjudicated else None
                row["human_decision"] = rec.review_decision if rec else ""
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _decision_counts(decisions: list[str]) -> dict[str, int]:
    counts = {"pass": 0, "borderline": 0, "fail": 0}
    for decision in decisions:
        if decision in counts:
            counts[decision] += 1
    return counts


def _quality_gate_recommendation(
    decisions: list[str], pass_threshold: float = 0.7
) -> str:
    total = len(decisions)
    if total == 0:
        return "No results to evaluate."

    counts = _decision_counts(decisions)
    pass_rate = counts["pass"] / total
    borderline_rate = counts["borderline"] / total

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


def _quality_gate_label(decision: str) -> str:
    labels = {
        "pass": "✓ Recommended",
        "needs_review": "~ Needs review",
        "fail": "✗ Not recommended",
    }
    return labels.get(decision, "~ Needs review")


def _quality_gate_supporting_context(
    counts: dict[str, int],
    total: int,
    parse_failures: int,
) -> str:
    if total == 0:
        return f"No scored samples. Parse failures: {parse_failures}."
    return (
        f"Pass {counts['pass']} ({counts['pass'] / total:.0%}), "
        f"borderline {counts['borderline']} ({counts['borderline'] / total:.0%}), "
        f"fail {counts['fail']} ({counts['fail'] / total:.0%}), "
        f"parse failures {parse_failures}."
    )


def _post_review_decisions(
    results: list[ScoredResult],
    adjudicated: dict[str, ReviewRecord],
) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for result in results:
        final_decision = result.decision
        if result.decision == "borderline":
            record = adjudicated.get(result.requirement_id)
            if record and record.review_decision in {"pass", "fail"}:
                final_decision = record.review_decision
        decisions[result.requirement_id] = final_decision
    return decisions


def _append_aggregate_table(
    lines: list[str],
    title: str,
    total: int,
    counts: dict[str, int],
    avg_weighted: float | None = None,
    avg_coverage: float | None = None,
) -> None:
    lines += [
        title,
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total samples | {total} |",
        f"| Pass | {counts['pass']} ({counts['pass'] / total:.0%}) |" if total else "| Pass | 0 |",
        f"| Borderline | {counts['borderline']} ({counts['borderline'] / total:.0%}) |" if total else "| Borderline | 0 |",
        f"| Fail | {counts['fail']} ({counts['fail'] / total:.0%}) |" if total else "| Fail | 0 |",
    ]
    if avg_weighted is not None:
        lines.append(f"| Avg weighted score | {avg_weighted:.2f} / 2.00 |")
    if avg_coverage is not None:
        lines.append(f"| Avg coverage ratio | {avg_coverage:.0%} |")
    lines.append("")


def _write_markdown(
    results: list[ScoredResult],
    manifest: RunManifest,
    path: Path,
    adjudicated: dict[str, ReviewRecord] | None = None,
    chart_paths: dict[str, Path] | None = None,
) -> None:
    total = len(results)
    auto_decisions = [r.decision for r in results]
    auto_counts = _decision_counts(auto_decisions)
    passes = [r for r in results if r.decision == "pass"]
    borderlines = [r for r in results if r.decision == "borderline"]
    fails = [r for r in results if r.decision == "fail"]
    has_adjudications = bool(adjudicated)

    avg_weighted = sum(r.weighted_score for r in results) / total if total else 0.0
    avg_coverage = sum(r.coverage_ratio for r in results) / total if total else 0.0

    post_review = _post_review_decisions(results, adjudicated or {})
    post_review_counts = _decision_counts(list(post_review.values())) if has_adjudications else None

    lines: list[str] = []

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
    ]

    if chart_paths and "distribution" in chart_paths:
        lines += [f"![Score Distribution]({chart_paths['distribution'].name})", ""]

    _append_aggregate_table(
        lines,
        "### Aggregate Scores (Auto)",
        total,
        auto_counts,
        avg_weighted=avg_weighted,
        avg_coverage=avg_coverage,
    )

    if chart_paths and "dimensions" in chart_paths:
        lines += [f"![Dimension Scores]({chart_paths['dimensions'].name})", ""]

    if has_adjudications and post_review_counts is not None:
        _append_aggregate_table(
            lines,
            "### Aggregate Scores (Post-review)",
            total,
            post_review_counts,
        )
        lines += [
            f"Adjudicated borderline items: {len(adjudicated)}",
            "",
        ]

    lines += [
        "## Quality Gate Recommendation",
        "",
    ]
    if has_adjudications and post_review_counts is not None:
        lines += [
            "| View | Status | Notes |",
            "|---|---|---|",
            f"| Auto (persisted gate) | {_quality_gate_label(manifest.quality_gate_decision)} | "
            f"Persisted manifest gate. {_quality_gate_supporting_context(auto_counts, total, manifest.parse_failures)} |",
            f"| Post-review outlook | {_quality_gate_recommendation(list(post_review.values()))} | "
            f"Derived from adjudicated sample decisions only; not persisted to the manifest. "
            f"{_quality_gate_supporting_context(post_review_counts, total, manifest.parse_failures)} |",
            "",
        ]
    else:
        lines += [
            f"Auto gate: {_quality_gate_label(manifest.quality_gate_decision)}",
            f"Basis: persisted manifest gate. {_quality_gate_supporting_context(auto_counts, total, manifest.parse_failures)}",
            "",
        ]

    if chart_paths and "per_requirement" in chart_paths:
        lines += [f"![Per-Requirement Scores]({chart_paths['per_requirement'].name})", ""]

    if adjudicated is not None:
        lines += [
            "## Per-Sample Results",
            "",
            "| ID | Auto Decision | Human Decision | Weighted | Correct | Complete | Halluc Risk | Reviewer Use | Coverage | Notes | Diagnostics |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in sorted(results, key=lambda x: x.requirement_id):
            icon = {"pass": "✓", "borderline": "~", "fail": "✗"}.get(r.decision, "?")
            rec = adjudicated.get(r.requirement_id) if adjudicated else None
            human_dec = rec.review_decision if rec else "—"
            lines.append(
                f"| {r.requirement_id} | {icon} {r.decision} | {human_dec} "
                f"| {r.weighted_score:.2f} "
                f"| {r.scores.correctness:.1f} "
                f"| {r.scores.completeness:.1f} "
                f"| {r.scores.hallucination_risk:.1f} "
                f"| {r.scores.reviewer_usefulness:.1f} "
                f"| {r.coverage_ratio:.0%} "
                f"| {r.scoring_notes or '—'} "
                f"| {r.diagnostic_notes or '—'} |"
            )
    else:
        lines += [
            "## Per-Sample Results",
            "",
            "| ID | Decision | Weighted | Correct | Complete | Halluc Risk | Reviewer Use | Coverage | Notes | Diagnostics |",
            "|---|---|---|---|---|---|---|---|---|---|",
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
                f"| {r.scoring_notes or '—'} "
                f"| {r.diagnostic_notes or '—'} |"
            )
    lines.append("")

    if has_adjudications:
        lines += ["## Human Review Summary", ""]
        noted_records = [
            (req_id, rec)
            for req_id, rec in sorted((adjudicated or {}).items())
            if rec.reviewer_notes
        ]
        if noted_records:
            for req_id, rec in noted_records:
                lines.append(f"- **{req_id}** ({rec.review_decision}): {rec.reviewer_notes}")
        else:
            lines.append("Adjudications were recorded, but no reviewer notes were captured.")
        lines.append("")

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

        lines += ["**Borderline samples (auto-routed to human review queue):**", ""]
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

    lines += [
        "## Known Limitations",
        "",
        "- Gold coverage scoring uses keyword/phrase matching — semantic equivalence is not detected.",
        "- Hallucination risk scoring is heuristic-based; human review of borderline cases is required.",
        "- Correctness scoring is a proxy (disallowed hits + minimum TC count) not a semantic judge.",
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
    parser.add_argument(
        "--use-human-review", action="store_true", default=False,
        help="Merge adjudicated human review decisions into the report",
    )
    parser.add_argument(
        "--charts", action="store_true", default=False,
        help="Generate PNG charts and embed them in the report (requires matplotlib extra)",
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

    adjudicated = None
    if args.use_human_review:
        adjudicated = load_adjudicated(run_id, cfg["reviews_dir"])
        if not adjudicated:
            logger.warning(
                "--use-human-review specified but no adjudicated records found for %s",
                run_id,
            )

    write_report(results, manifest, cfg["reports_dir"], adjudicated=adjudicated, charts=args.charts)


if __name__ == "__main__":
    main()
