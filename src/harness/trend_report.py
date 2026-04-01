"""Trend report: aggregate scoring history across multiple runs.

Usage:
    python -m harness.trend_report \
        --dataset-path data/requirements/mvp_dataset_v2.jsonl \
        [--filter-dataset mvp_v2] \
        [--filter-prompt v2] \
        [--use-human-review]

Default: --filter-dataset defaults to the most recent dataset_version seen in runs_dir.
Pass --filter-dataset all to include all dataset versions (adds a mixed-dataset warning).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from harness.charts import inject_chart_markdown
from harness.loaders import load_requirements, load_scored_results
from harness.review_queue import load_adjudicated
from harness.schemas import Requirement, RunManifest, RunSummary, ScoredResult, TrendReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_TIMESTAMP_SUFFIX_RE = re.compile(r"_\d{8}T\d{6}Z$")


def _quality_gate_label(decision: str) -> str:
    labels = {
        "pass": "✓ Recommended",
        "needs_review": "~ Needs review",
        "fail": "✗ Not recommended",
    }
    return labels.get(decision, "~ Needs review")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_all_manifests(runs_dir: str) -> list[RunManifest]:
    manifests = []
    for path in sorted(Path(runs_dir).glob("*.json")):
        try:
            manifests.append(RunManifest.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        except Exception as e:
            logger.warning("Could not load manifest %s: %s", path, e)
    return manifests


# ---------------------------------------------------------------------------
# Trend data builder
# ---------------------------------------------------------------------------


def consistently_borderline_requirements(
    per_req_history: dict[str, list[dict]],
    threshold: float = 0.5,
) -> list[str]:
    """Return req_ids where borderline rate > threshold across included runs."""
    result = []
    for req_id, history in per_req_history.items():
        if not history:
            continue
        borderline_count = sum(1 for h in history if h["decision"] == "borderline")
        if borderline_count / len(history) > threshold:
            result.append(req_id)
    return sorted(result)


def domain_pass_rates(
    per_req_history: dict[str, list[dict]],
    requirements: list[Requirement],
    run_ids: list[str],
) -> dict[str, dict[str, float]]:
    """Compute per-domain pass rates for each run_id."""
    req_map = {r.requirement_id: r for r in requirements}
    rates: dict[str, dict[str, float]] = defaultdict(dict)

    for run_id in run_ids:
        domain_pass: dict[str, list[bool]] = defaultdict(list)
        for req_id, history in per_req_history.items():
            req = req_map.get(req_id)
            if req is None:
                continue
            for h in history:
                if h["run_id"] == run_id:
                    domain_pass[req.domain_tag].append(h["decision"] == "pass")
        for domain, outcomes in domain_pass.items():
            rates[domain][run_id] = sum(outcomes) / len(outcomes) if outcomes else 0.0

    return dict(rates)


def build_trend_data(
    manifests: list[RunManifest],
    generated_dir: str,
    requirements: list[Requirement],
    filter_dataset: str | None = None,
    filter_prompt: str | None = None,
    use_human_review: bool = False,
    reviews_dir: str = "data/reviews",
) -> TrendReport:
    """Build a TrendReport from manifests and generated results."""
    if filter_dataset is None or filter_dataset == "":
        if manifests:
            most_recent = max(manifests, key=lambda m: m.timestamp)
            filter_dataset = most_recent.dataset_version
        else:
            filter_dataset = None

    mixed_mode = filter_dataset == "all"

    filtered = manifests
    if not mixed_mode and filter_dataset:
        filtered = [m for m in manifests if m.dataset_version == filter_dataset]
    if filter_prompt:
        filtered = [m for m in filtered if m.prompt_version == filter_prompt]

    filtered = sorted(filtered, key=lambda m: m.timestamp)

    run_summaries = [
        RunSummary(
            run_id=m.run_id,
            timestamp=m.timestamp,
            model_version=m.model_version,
            prompt_version=m.prompt_version,
            dataset_version=m.dataset_version,
            quality_gate_decision=m.quality_gate_decision,
            pass_count=m.pass_count,
            borderline_count=m.borderline_count,
            fail_count=m.fail_count,
            total_evaluated=m.total_evaluated,
            parse_failures=m.parse_failures,
            avg_weighted_score=m.avg_weighted_score,
        )
        for m in filtered
    ]

    per_req_history: dict[str, list[dict]] = defaultdict(list)
    req_ids_in_dataset = {r.requirement_id for r in requirements} if requirements else set()

    for manifest in filtered:
        results = load_scored_results(generated_dir, manifest.run_id, raise_on_missing=False)
        adj = load_adjudicated(manifest.run_id, reviews_dir) if use_human_review else {}

        for req_id, result in results.items():
            if req_ids_in_dataset and req_id not in req_ids_in_dataset:
                continue
            entry = {
                "run_id": manifest.run_id,
                "decision": result.decision,
                "weighted_score": result.weighted_score,
                "dataset_version": manifest.dataset_version,
            }
            if use_human_review and req_id in adj:
                entry["human_decision"] = adj[req_id].review_decision
            per_req_history[req_id].append(entry)

    run_id_list = [m.run_id for m in filtered]
    consistently_bl = consistently_borderline_requirements(per_req_history)
    dom_rates = domain_pass_rates(per_req_history, requirements, run_id_list)

    return TrendReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        runs=run_summaries,
        per_requirement_history=dict(per_req_history),
        consistently_borderline=consistently_bl,
        domain_pass_rates=dom_rates,
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _run_family(run_id: str) -> str:
    return _TIMESTAMP_SUFFIX_RE.sub("", run_id)


def _human_review_annotations(trend: TrendReport) -> list[tuple[str, str, str]]:
    annotations: list[tuple[str, str, str]] = []
    for req_id, history in sorted(trend.per_requirement_history.items()):
        for entry in history:
            human_decision = entry.get("human_decision")
            if human_decision:
                annotations.append((entry["run_id"], req_id, human_decision))
    return sorted(annotations)


def render_trend_markdown(
    trend: TrendReport,
    filter_dataset: str | None,
    run_counts: dict[str, int],
    mixed_mode: bool = False,
) -> str:
    lines: list[str] = []

    if trend.runs:
        ts_min = min(r.timestamp for r in trend.runs)[:10]
        ts_max = max(r.timestamp for r in trend.runs)[:10]
        date_range = f"{ts_min} – {ts_max}" if ts_min != ts_max else ts_min
    else:
        date_range = "no runs"

    run_dist = ", ".join(f"{run_id} ×{cnt}" for run_id, cnt in sorted(run_counts.items()))
    dataset_note = "⚠ Mixed datasets" if mixed_mode else f"Filtered to dataset_version: {filter_dataset}"

    lines += [
        f"# Trend Report — {len(trend.runs)} run(s) ({date_range})",
        f"{dataset_note} | Run distribution: {run_dist}",
        "",
    ]

    lines += [
        "## Runs Included",
        "",
        "| Run ID | Timestamp | Model | Prompt | Dataset | Pass% | Avg Score |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in trend.runs:
        total = r.total_evaluated
        pass_pct = f"{r.pass_count / total:.0%}" if total else "n/a"
        lines.append(
            f"| `{r.run_id}` | {r.timestamp[:19]} | `{r.model_version}` "
            f"| `{r.prompt_version}` | `{r.dataset_version}` | {pass_pct} | {r.avg_weighted_score:.2f} |"
        )
    lines.append("")

    lines += [
        "## Pass Rate Over Time",
        "",
        "| Run ID | Pass | Borderline | Fail | Avg Score |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(trend.runs, key=lambda x: x.timestamp):
        total = r.total_evaluated
        lines.append(
            f"| `{r.run_id}` | {r.pass_count}/{total} | {r.borderline_count}/{total} "
            f"| {r.fail_count}/{total} | {r.avg_weighted_score:.2f} |"
        )
    lines.append("")

    run_ids = [r.run_id for r in trend.runs]
    lines += [
        "## Per-Requirement Pass Rate (same dataset)",
        "",
    ]
    header = "| Req ID | " + " | ".join(f"Score ({rid[:12]})" for rid in run_ids) + " | Consistency |"
    sep = "|---|" + "---|" * (len(run_ids) + 1)
    lines += [header, sep]

    req_rows = []
    for req_id, history in trend.per_requirement_history.items():
        run_scores = {h["run_id"]: (h["decision"], h["weighted_score"]) for h in history}
        pass_frac = sum(1 for h in history if h["decision"] == "pass") / len(history) if history else 0.0
        req_rows.append((req_id, run_scores, pass_frac))

    req_rows.sort(key=lambda x: x[2])
    for req_id, run_scores, pass_frac in req_rows:
        cells = []
        for rid in run_ids:
            if rid in run_scores:
                dec, score = run_scores[rid]
                icon = {"pass": "✓", "borderline": "~", "fail": "✗"}.get(dec, "?")
                cells.append(f"{icon} {score:.2f}")
            else:
                cells.append("—")
        consistency = f"{pass_frac:.0%}"
        lines.append(f"| {req_id} | " + " | ".join(cells) + f" | {consistency} |")
    lines.append("")

    lines += ["## Consistently Borderline Requirements", ""]
    if trend.consistently_borderline:
        lines.append(
            "Requirements that were borderline in >50% of included runs "
            "— prime candidates for gold annotation review or prompt improvement:"
        )
        for req_id in trend.consistently_borderline:
            lines.append(f"- {req_id}")
    else:
        lines.append("No requirements were consistently borderline across included runs.")
    lines.append("")

    if trend.domain_pass_rates:
        lines += [
            "## Domain Trends",
            "",
            "| Domain | " + " | ".join(f"Pass% ({rid[:12]})" for rid in run_ids) + " |",
            "|---|" + "---|" * len(run_ids),
        ]
        for domain in sorted(trend.domain_pass_rates):
            rate_by_run = trend.domain_pass_rates[domain]
            cells = [f"{rate_by_run.get(rid, 0.0):.0%}" for rid in run_ids]
            lines.append(f"| {domain} | " + " | ".join(cells) + " |")
        lines.append("")

    annotations = _human_review_annotations(trend)
    if annotations:
        lines += [
            "## Human Review Annotations",
            "",
            "Trend calculations remain based on auto decisions. These adjudications are included as context only.",
            "",
            "| Run ID | Requirement | Human Decision |",
            "|---|---|---|",
        ]
        for run_id, requirement_id, human_decision in annotations:
            lines.append(f"| `{run_id}` | {requirement_id} | {human_decision} |")
        lines.append("")

    lines += [
        "## Quality Gate Evolution",
        "",
        "| Run | Pass% | Decision |",
        "|---|---|---|",
    ]
    for r in sorted(trend.runs, key=lambda x: x.timestamp):
        total = r.total_evaluated
        pass_pct = r.pass_count / total if total else 0.0
        gate = _quality_gate_label(r.quality_gate_decision)
        lines.append(f"| `{r.run_id}` | {pass_pct:.0%} | {gate} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(
    dataset_path: str,
    runs_dir: str = "data/runs",
    generated_dir: str = "data/generated",
    reviews_dir: str = "data/reviews",
    reports_dir: str = "reports",
    filter_dataset: str | None = None,
    filter_prompt: str | None = None,
    use_human_review: bool = False,
    charts: bool = False,
) -> tuple[Path, Path]:
    """Build and write trend report. Returns (md_path, csv_path)."""
    manifests = _load_all_manifests(runs_dir)
    requirements = load_requirements(dataset_path)

    mixed_mode = filter_dataset == "all"
    effective_filter = filter_dataset

    if not filter_dataset:
        if manifests:
            most_recent = max(manifests, key=lambda m: m.timestamp)
            effective_filter = most_recent.dataset_version
        else:
            effective_filter = None

    trend = build_trend_data(
        manifests,
        generated_dir=generated_dir,
        requirements=requirements,
        filter_dataset=filter_dataset,
        filter_prompt=filter_prompt,
        use_human_review=use_human_review,
        reviews_dir=reviews_dir,
    )

    run_counts: dict[str, int] = Counter(_run_family(r.run_id) for r in trend.runs)
    md_content = render_trend_markdown(trend, effective_filter, dict(run_counts), mixed_mode=mixed_mode)

    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    chart_lines: list[str] = []
    if charts and trend.runs:
        from harness import charts as chart_module
        trend_data_for_chart = [
            {
                "run_id": r.run_id,
                "pass_rate": r.pass_count / r.total_evaluated if r.total_evaluated else 0.0,
                "borderline_rate": r.borderline_count / r.total_evaluated if r.total_evaluated else 0.0,
            }
            for r in sorted(trend.runs, key=lambda x: x.timestamp)
        ]
        pass_rate_path = chart_module.plot_trend_pass_rate(trend_data_for_chart, out_dir, timestamp=timestamp)
        if pass_rate_path:
            chart_lines.append(f"![Pass Rate Over Time]({pass_rate_path.name})")

        run_ids = [r.run_id for r in trend.runs]
        heatmap_path = chart_module.plot_domain_heatmap(trend.domain_pass_rates, run_ids, out_dir, timestamp=timestamp)
        if heatmap_path:
            chart_lines.append(f"![Domain Pass Rates]({heatmap_path.name})")

    if chart_lines:
        md_content = inject_chart_markdown(md_content, chart_lines, "## Runs Included")

    md_path = out_dir / f"trend_{timestamp}.md"
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("Trend report written: %s", md_path)

    csv_path = out_dir / f"trend_{timestamp}.csv"
    fieldnames = [
        "requirement_id",
        "run_id",
        "decision",
        "weighted_score",
        "dataset_version",
    ]
    if use_human_review:
        fieldnames.append("human_decision")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for req_id, history in sorted(trend.per_requirement_history.items()):
            for entry in history:
                row = {
                    "requirement_id": req_id,
                    "run_id": entry["run_id"],
                    "decision": entry["decision"],
                    "weighted_score": entry["weighted_score"],
                    "dataset_version": entry["dataset_version"],
                }
                if use_human_review:
                    row["human_decision"] = entry.get("human_decision", "")
                writer.writerow(row)
    logger.info("Trend CSV written: %s", csv_path)

    return md_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trend report across runs")
    parser.add_argument("--dataset-path", default="data/requirements/mvp_dataset_v2.jsonl")
    parser.add_argument("--runs-dir", default="data/runs")
    parser.add_argument("--generated-dir", default="data/generated")
    parser.add_argument("--reviews-dir", default="data/reviews")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument(
        "--filter-dataset",
        default=None,
        help="Filter by dataset_version ('all' for mixed, default: most recent)",
    )
    parser.add_argument("--filter-prompt", default=None, help="Filter by prompt version")
    parser.add_argument("--use-human-review", action="store_true", default=False)
    parser.add_argument("--charts", action="store_true", default=False,
                        help="Generate PNG charts (requires matplotlib extra)")
    args = parser.parse_args()
    run(
        dataset_path=args.dataset_path,
        runs_dir=args.runs_dir,
        generated_dir=args.generated_dir,
        reviews_dir=args.reviews_dir,
        reports_dir=args.reports_dir,
        filter_dataset=args.filter_dataset,
        filter_prompt=args.filter_prompt,
        use_human_review=args.use_human_review,
        charts=args.charts,
    )


if __name__ == "__main__":
    main()
