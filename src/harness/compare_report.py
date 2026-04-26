"""Side-by-side comparison of two evaluation runs.

Usage:
    python -m harness.compare_report \\
        --run-a run_v2_prompt_v1_TIMESTAMP \\
        --run-b run_v2_prompt_v2_TIMESTAMP \\
        --dataset-path data/requirements/mvp_dataset_v2.jsonl

Fails fast if the two runs used different dataset_version values.
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import UTC, datetime
from pathlib import Path

from harness.charts import inject_chart_markdown
from harness.loaders import load_manifest, load_requirements, load_scored_results
from harness.review_queue import load_adjudicated
from harness.schemas import Requirement, ReviewRecord, RunManifest, ScoredResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _pct(n: int | float, d: int | float) -> str:
    return f"{n/d:.0%}" if d else "n/a"


def _delta_str(x: float) -> str:
    return f"+{x:.2f}" if x > 0 else f"{x:.2f}"


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def _compute_deltas(
    results_a: dict[str, ScoredResult],
    results_b: dict[str, ScoredResult],
) -> dict[str, dict]:
    """Return per-requirement delta info for requirements present in both runs."""
    intersection = sorted(set(results_a) & set(results_b))
    deltas = {}
    for req_id in intersection:
        a = results_a[req_id]
        b = results_b[req_id]
        score_delta = round(b.weighted_score - a.weighted_score, 4)
        regression = a.decision in ("pass",) and b.decision in ("borderline", "fail")
        improvement = a.decision in ("borderline", "fail") and b.decision == "pass"
        deltas[req_id] = {
            "decision_a": a.decision,
            "decision_b": b.decision,
            "score_a": a.weighted_score,
            "score_b": b.weighted_score,
            "delta": score_delta,
            "regression": regression,
            "improvement": improvement,
        }
    return deltas


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def build_compare_report(
    results_a: dict[str, ScoredResult],
    manifest_a: RunManifest,
    results_b: dict[str, ScoredResult],
    manifest_b: RunManifest,
    requirements: list[Requirement],
    adjudicated_a: dict[str, ReviewRecord] | None = None,
    adjudicated_b: dict[str, ReviewRecord] | None = None,
) -> str:
    """Build comparison report markdown. Fails fast on dataset version mismatch."""
    if manifest_a.dataset_version != manifest_b.dataset_version:
        raise ValueError(
            f"Dataset version mismatch: run A uses '{manifest_a.dataset_version}' "
            f"but run B uses '{manifest_b.dataset_version}'. "
            "Comparing runs on different datasets produces meaningless deltas."
        )

    req_map = {r.requirement_id: r for r in requirements}
    all_req_ids = sorted(req_map)

    # Intersection
    intersection = sorted(set(results_a) & set(results_b))
    excluded = sorted(
        (set(results_a) | set(results_b)) - set(intersection)
    )
    deltas = _compute_deltas(results_a, results_b)

    lines: list[str] = []

    # ---------- Header ----------
    now = datetime.now(UTC).isoformat()
    lines += [
        "# Comparison Report",
        "",
        "| Field | Run A | Run B |",
        "|---|---|---|",
        f"| Run ID | `{manifest_a.run_id}` | `{manifest_b.run_id}` |",
        f"| Model | `{manifest_a.model_version}` | `{manifest_b.model_version}` |",
        f"| Prompt | `{manifest_a.prompt_version}` | `{manifest_b.prompt_version}` |",
        f"| Dataset | `{manifest_a.dataset_version}` | `{manifest_b.dataset_version}` |",
        f"| Timestamp | {manifest_a.timestamp} | {manifest_b.timestamp} |",
        f"| Comparison generated | {now} | — |",
        "",
    ]
    if excluded:
        lines += [
            f"> ⚠ {len(excluded)} requirement(s) excluded from comparison (present in one run only "
            f"— likely parse failures): {', '.join(excluded)}. "
            f"Analysis covers {len(intersection)} of {len(all_req_ids)} requirements.",
            "",
        ]

    # ---------- Aggregate delta ----------
    total_a = len(results_a)
    total_b = len(results_b)
    pass_a = sum(1 for r in results_a.values() if r.decision == "pass")
    pass_b = sum(1 for r in results_b.values() if r.decision == "pass")
    bl_a = sum(1 for r in results_a.values() if r.decision == "borderline")
    bl_b = sum(1 for r in results_b.values() if r.decision == "borderline")
    fail_a = sum(1 for r in results_a.values() if r.decision == "fail")
    fail_b = sum(1 for r in results_b.values() if r.decision == "fail")
    avg_a = sum(r.weighted_score for r in results_a.values()) / total_a if total_a else 0.0
    avg_b = sum(r.weighted_score for r in results_b.values()) / total_b if total_b else 0.0

    lines += [
        "## Aggregate Delta",
        "",
        "| Metric | Run A | Run B | Delta |",
        "|---|---|---|---|",
        f"| Pass rate | {_pct(pass_a, total_a)} | {_pct(pass_b, total_b)} "
        f"| {_delta_str((pass_b/total_b if total_b else 0) - (pass_a/total_a if total_a else 0))} |",
        f"| Borderline rate | {_pct(bl_a, total_a)} | {_pct(bl_b, total_b)} "
        f"| {_delta_str((bl_b/total_b if total_b else 0) - (bl_a/total_a if total_a else 0))} |",
        f"| Fail rate | {_pct(fail_a, total_a)} | {_pct(fail_b, total_b)} "
        f"| {_delta_str((fail_b/total_b if total_b else 0) - (fail_a/total_a if total_a else 0))} |",
        f"| Avg weighted score | {avg_a:.2f} | {avg_b:.2f} | {_delta_str(avg_b - avg_a)} |",
        f"| Parse failures | {manifest_a.parse_failures} | {manifest_b.parse_failures} | — |",
        "",
    ]

    # ---------- Per-dimension averages ----------
    def _avg_dim(results: dict[str, ScoredResult], dim: str) -> float:
        vals = [getattr(r.scores, dim) for r in results.values()]
        return sum(vals) / len(vals) if vals else 0.0

    dims = ["correctness", "completeness", "hallucination_risk", "reviewer_usefulness"]
    lines += [
        "## Per-Dimension Averages",
        "",
        "| Dimension | Run A | Run B | Delta |",
        "|---|---|---|---|",
    ]
    for d in dims:
        va = _avg_dim(results_a, d)
        vb = _avg_dim(results_b, d)
        lines.append(f"| {d} | {va:.2f} | {vb:.2f} | {_delta_str(vb - va)} |")
    lines.append("")

    # ---------- Per-requirement delta (sorted by abs delta) ----------
    human_col = adjudicated_a is not None or adjudicated_b is not None
    if human_col:
        header = "| Req ID | Decision A | Decision B | Score A | Score B | Delta | Human A | Human B |"
        sep    = "|---|---|---|---|---|---|---|---|"
    else:
        header = "| Req ID | Decision A | Decision B | Score A | Score B | Delta |"
        sep    = "|---|---|---|---|---|---|"

    lines += ["## Per-Requirement Delta", "", header, sep]
    sorted_deltas = sorted(deltas.items(), key=lambda kv: abs(kv[1]["delta"]), reverse=True)
    for req_id, d in sorted_deltas:
        reg_marker = " ⚠" if d["regression"] else ""
        imp_marker = " ✓" if d["improvement"] else ""
        row = (
            f"| {req_id} | {d['decision_a']} | {d['decision_b']}{reg_marker}{imp_marker} "
            f"| {d['score_a']:.2f} | {d['score_b']:.2f} | {_delta_str(d['delta'])} |"
        )
        if human_col:
            ha = adjudicated_a.get(req_id).review_decision if adjudicated_a and adjudicated_a.get(req_id) else "—"
            hb = adjudicated_b.get(req_id).review_decision if adjudicated_b and adjudicated_b.get(req_id) else "—"
            row = row.rstrip("|") + f" {ha} | {hb} |"
        lines.append(row)
    lines.append("")

    # ---------- Domain breakdown ----------
    domains = sorted({r.domain_tag for r in req_map.values()})
    lines += [
        "## Domain Breakdown",
        "",
        "| Domain | Pass Rate A | Pass Rate B | Delta |",
        "|---|---|---|---|",
    ]
    for domain in domains:
        domain_ids = [r.requirement_id for r in req_map.values() if r.domain_tag == domain]
        res_a_dom = [results_a[rid] for rid in domain_ids if rid in results_a]
        res_b_dom = [results_b[rid] for rid in domain_ids if rid in results_b]
        pa = sum(1 for r in res_a_dom if r.decision == "pass") / len(res_a_dom) if res_a_dom else 0.0
        pb = sum(1 for r in res_b_dom if r.decision == "pass") / len(res_b_dom) if res_b_dom else 0.0
        lines.append(f"| {domain} | {pa:.0%} | {pb:.0%} | {_delta_str(pb - pa)} |")
    lines.append("")

    # ---------- Difficulty breakdown ----------
    difficulties = ["easy", "medium", "hard", "ambiguous"]
    lines += [
        "## Difficulty Breakdown",
        "",
        "| Difficulty | Pass Rate A | Pass Rate B | Delta |",
        "|---|---|---|---|",
    ]
    for diff in difficulties:
        diff_ids = [r.requirement_id for r in req_map.values() if r.difficulty == diff]
        res_a_diff = [results_a[rid] for rid in diff_ids if rid in results_a]
        res_b_diff = [results_b[rid] for rid in diff_ids if rid in results_b]
        pa = sum(1 for r in res_a_diff if r.decision == "pass") / len(res_a_diff) if res_a_diff else 0.0
        pb = sum(1 for r in res_b_diff if r.decision == "pass") / len(res_b_diff) if res_b_diff else 0.0
        lines.append(f"| {diff} | {pa:.0%} | {pb:.0%} | {_delta_str(pb - pa)} |")
    lines.append("")

    # ---------- Notable changes ----------
    improvements = sorted(
        [(rid, d) for rid, d in deltas.items() if d["improvement"]],
        key=lambda x: x[1]["delta"], reverse=True
    )[:5]
    regressions = sorted(
        [(rid, d) for rid, d in deltas.items() if d["regression"]],
        key=lambda x: x[1]["delta"]
    )[:5]

    lines += ["## Notable Changes", ""]
    if improvements:
        lines.append("**Top improvements (fail/borderline → pass):**")
        for rid, d in improvements:
            lines.append(f"- {rid}: {d['decision_a']} → {d['decision_b']} ({d['score_a']:.2f} → {d['score_b']:.2f})")
        lines.append("")
    if regressions:
        lines.append("**Top regressions (pass → fail/borderline):**")
        for rid, d in regressions:
            lines.append(f"- ⚠ {rid}: {d['decision_a']} → {d['decision_b']} ({d['score_a']:.2f} → {d['score_b']:.2f})")
        lines.append("")

    # ---------- Conclusion ----------
    hard_ids = {r.requirement_id for r in req_map.values() if r.difficulty == "hard"}
    hard_a = [results_a[rid] for rid in hard_ids if rid in results_a]
    hard_b = [results_b[rid] for rid in hard_ids if rid in results_b]
    hard_pass_a = sum(1 for r in hard_a if r.decision == "pass") / len(hard_a) if hard_a else 0.0
    hard_pass_b = sum(1 for r in hard_b if r.decision == "pass") / len(hard_b) if hard_b else 0.0
    hard_delta = hard_pass_b - hard_pass_a

    direction = "improved" if avg_b > avg_a else "decreased"
    reg_count = len([d for d in deltas.values() if d["regression"]])
    imp_count = len([d for d in deltas.values() if d["improvement"]])

    lines += [
        "## Conclusion",
        "",
        f"Run B ({manifest_b.prompt_version}) {direction} average weighted score by "
        f"{abs(avg_b - avg_a):.2f} ({_delta_str(avg_b - avg_a)}). "
        f"Hard requirement pass rate changed by {hard_delta:+.0%}. "
        f"{imp_count} improvement(s), {reg_count} regression(s) observed.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(
    run_id_a: str,
    run_id_b: str,
    dataset_path: str,
    runs_dir: str = "data/runs",
    generated_dir: str = "data/generated",
    reviews_dir: str = "data/reviews",
    reports_dir: str = "reports",
    use_human_review: bool = False,
    charts: bool = False,
) -> tuple[Path, Path]:
    """Run comparison and write report files. Returns (md_path, csv_path)."""
    manifest_a = load_manifest(runs_dir, run_id_a)
    manifest_b = load_manifest(runs_dir, run_id_b)
    results_a = load_scored_results(generated_dir, run_id_a)
    results_b = load_scored_results(generated_dir, run_id_b)
    requirements = load_requirements(dataset_path)

    adjudicated_a = load_adjudicated(run_id_a, reviews_dir) if use_human_review else None
    adjudicated_b = load_adjudicated(run_id_b, reviews_dir) if use_human_review else None

    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    chart_lines: list[str] = []
    if charts:
        from harness import charts as chart_module
        dist_path = chart_module.plot_compare_distribution(
            list(results_a.values()), list(results_b.values()),
            run_id_a, run_id_b, out_dir, timestamp=timestamp,
        )
        delta_path = chart_module.plot_compare_delta(
            results_a, results_b, run_id_a, run_id_b, out_dir, timestamp=timestamp,
        )
        if dist_path:
            chart_lines.append(f"![Distribution Comparison]({dist_path.name})")
        if delta_path:
            chart_lines.append(f"![Score Delta]({delta_path.name})")

    md_content = build_compare_report(
        results_a, manifest_a, results_b, manifest_b, requirements,
        adjudicated_a=adjudicated_a, adjudicated_b=adjudicated_b,
    )

    if chart_lines:
        md_content = inject_chart_markdown(md_content, chart_lines, "## Aggregate Delta")

    md_path = out_dir / f"compare_{run_id_a}_vs_{run_id_b}_{timestamp}.md"
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("Comparison report written: %s", md_path)

    # CSV: per-requirement delta rows
    csv_path = out_dir / f"compare_{run_id_a}_vs_{run_id_b}_{timestamp}.csv"
    intersection = sorted(set(results_a) & set(results_b))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "requirement_id", "decision_a", "decision_b",
                "score_a", "score_b", "delta", "regression", "improvement",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        deltas = _compute_deltas(results_a, results_b)
        for req_id in intersection:
            d = deltas[req_id]
            writer.writerow({"requirement_id": req_id, **d})
    logger.info("Comparison CSV written: %s", csv_path)
    return md_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two evaluation runs")
    parser.add_argument("--run-a", required=True, help="Run ID for baseline run")
    parser.add_argument("--run-b", required=True, help="Run ID for comparison run")
    parser.add_argument("--dataset-path", required=True, help="Path to requirements JSONL")
    parser.add_argument("--runs-dir", default="data/runs")
    parser.add_argument("--generated-dir", default="data/generated")
    parser.add_argument("--reviews-dir", default="data/reviews")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--use-human-review", action="store_true", default=False)
    parser.add_argument("--charts", action="store_true", default=False,
                        help="Generate PNG charts (requires matplotlib extra)")
    args = parser.parse_args()
    run(
        run_id_a=args.run_a,
        run_id_b=args.run_b,
        dataset_path=args.dataset_path,
        runs_dir=args.runs_dir,
        generated_dir=args.generated_dir,
        reviews_dir=args.reviews_dir,
        reports_dir=args.reports_dir,
        use_human_review=args.use_human_review,
        charts=args.charts,
    )


if __name__ == "__main__":
    main()
