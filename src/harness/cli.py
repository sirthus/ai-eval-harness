"""Unified CLI entry point for the evaluation harness.

Usage:
    python -m harness <subcommand> [options]

Subcommands:
    run       Run the full evaluation pipeline
    generate  Run generation step only
    evaluate  Run evaluation/scoring step only
    report    Generate report from existing run
    review    Launch interactive human review for borderline items
    compare   Compare two runs side-by-side
    trend     Build cross-run trend report

Rich is used for terminal display only. All business logic is in the existing
modules — this module only dispatches and formats output.
"""

from __future__ import annotations

import argparse
import logging
import sys
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Summary display helpers
# ---------------------------------------------------------------------------


def print_run_summary(manifest, console: Console) -> None:
    """Print a rich Panel summarizing a completed run."""
    gate = manifest.quality_gate_decision if hasattr(manifest, "quality_gate_decision") else None
    total = manifest.total_evaluated
    pass_pct = f"{manifest.pass_count / total:.0%}" if total else "n/a"

    if gate == "pass":
        border_color = "green"
        gate_text = "[bold green]PASS[/bold green]"
    elif gate == "fail":
        border_color = "red"
        gate_text = "[bold red]FAIL[/bold red]"
    else:
        border_color = "yellow"
        gate_text = "[bold yellow]NEEDS REVIEW[/bold yellow]"

    scorer_type = getattr(manifest, "scorer_type", "heuristic")

    body = (
        f"[bold]Run:[/bold] {manifest.run_id}\n"
        f"[bold]Model:[/bold] {manifest.model_version}  "
        f"[bold]Prompt:[/bold] {manifest.prompt_version}  "
        f"[bold]Scorer:[/bold] {scorer_type}\n"
        f"\n"
        f"[bold]Results:[/bold] "
        f"[green]{manifest.pass_count} pass[/green] / "
        f"[yellow]{manifest.borderline_count} borderline[/yellow] / "
        f"[red]{manifest.fail_count} fail[/red]  "
        f"({pass_pct} pass rate)\n"
        f"[bold]Avg score:[/bold] {manifest.avg_weighted_score:.2f} / 2.00  "
        f"[bold]Parse failures:[/bold] {manifest.parse_failures}"
    )
    if gate is not None:
        body += f"\n[bold]Quality gate:[/bold] {gate_text}"

    console.print(Panel(body, title="Run Complete", border_style=border_color))


def print_results_table(
    results: list,
    console: Console,
    adjudicated: dict | None = None,
) -> None:
    """Print a rich Table with one row per requirement."""
    table = Table(title="Per-Requirement Results", show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Decision", no_wrap=True)
    table.add_column("Weighted", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Correct", justify="right")
    table.add_column("Complete", justify="right")
    table.add_column("Halluc", justify="right")
    table.add_column("Useful", justify="right")
    if adjudicated is not None:
        table.add_column("Human", no_wrap=True)

    decision_styles = {"pass": "green", "borderline": "yellow", "fail": "red"}
    icons = {"pass": "✓", "borderline": "~", "fail": "✗"}

    for r in sorted(results, key=lambda x: x.requirement_id):
        style = decision_styles.get(r.decision, "")
        icon = icons.get(r.decision, "?")
        decision_cell = f"[{style}]{icon} {r.decision}[/{style}]"
        row = [
            r.requirement_id,
            decision_cell,
            f"{r.weighted_score:.2f}",
            f"{r.coverage_ratio:.0%}",
            f"{r.scores.correctness:.1f}",
            f"{r.scores.completeness:.1f}",
            f"{r.scores.hallucination_risk:.1f}",
            f"{r.scores.reviewer_usefulness:.1f}",
        ]
        if adjudicated is not None:
            rec = adjudicated.get(r.requirement_id)
            human = rec.review_decision if rec else "—"
            row.append(human)
        table.add_row(*row)

    console.print(table)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace, console: Console) -> None:
    """Run full pipeline with rich summary panel on completion."""
    from harness import run_eval

    console.print(f"[bold]Starting evaluation run[/bold] — config: [dim]{args.config}[/dim]")
    with console.status("Running pipeline (generate → evaluate → review queue → report)…"):
        manifest = run_eval.run(args.config)

    if manifest:
        print_run_summary(manifest, console)
    else:
        console.print("[yellow]Run completed but no manifest was returned.[/yellow]")


def cmd_generate(args: argparse.Namespace, console: Console) -> None:
    from harness import generate

    console.print(f"[bold]Generating outputs[/bold] — config: [dim]{args.config}[/dim]")
    with console.status("Calling model API for each requirement…"):
        _, failures = generate.run(args.config, run_id=getattr(args, "run_id", None))
    if failures:
        console.print(f"[yellow]Parse failures: {len(failures)}[/yellow]")
    else:
        console.print("[green]Generation complete — no parse failures.[/green]")


def cmd_evaluate(args: argparse.Namespace, console: Console) -> None:
    from harness import evaluate

    console.print(f"[bold]Evaluating outputs[/bold] — config: [dim]{args.config}[/dim]")
    with console.status("Scoring outputs against gold dataset…"):
        results = evaluate.run(args.config, run_id=getattr(args, "run_id", None))
    console.print(f"[green]Evaluation complete — {len(results)} result(s) scored.[/green]")
    print_results_table(results, console)


def cmd_report(args: argparse.Namespace, console: Console) -> None:
    import json
    import yaml
    from harness.evaluate import scored_results_path
    from harness.report import write_report
    from harness.review_queue import load_adjudicated
    from harness.schemas import RunManifest, ScoredResult

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    run_id = getattr(args, "run_id", None) or cfg["run_id"]
    results_path = scored_results_path(args.config, run_id=run_id)
    if not results_path.exists():
        console.print(f"[red]Scored results not found: {results_path}[/red]")
        sys.exit(1)

    results = [ScoredResult.model_validate(r) for r in json.loads(results_path.read_text(encoding="utf-8"))]
    manifest_path = Path(cfg["runs_dir"]) / f"{run_id}.json"
    if not manifest_path.exists():
        console.print(f"[red]Run manifest not found: {manifest_path}[/red]")
        sys.exit(1)
    manifest = RunManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))

    adjudicated = None
    if getattr(args, "use_human_review", False):
        adjudicated = load_adjudicated(run_id, cfg["reviews_dir"])

    charts = getattr(args, "charts", False)
    with console.status("Writing report…"):
        csv_path, md_path = write_report(
            results, manifest, cfg["reports_dir"], adjudicated=adjudicated, charts=charts
        )
    console.print(f"[green]Report:[/green] {md_path}")
    console.print(f"[green]CSV:[/green] {csv_path}")


def cmd_review(args: argparse.Namespace, console: Console) -> None:
    from harness import review_cli

    console.print(f"[bold]Starting human review session[/bold] — run: [dim]{args.run_id}[/dim]")
    review_cli.run(
        run_id=args.run_id,
        reviews_dir=getattr(args, "reviews_dir", "data/reviews"),
        generated_dir=getattr(args, "generated_dir", "data/generated"),
        gold_path=getattr(args, "gold_path", None),
        runs_dir=getattr(args, "runs_dir", "data/runs"),
        console=console,
    )


def cmd_compare(args: argparse.Namespace, console: Console) -> None:
    from harness import compare_report

    console.print(
        f"[bold]Comparing runs[/bold]: [dim]{args.run_a}[/dim] vs [dim]{args.run_b}[/dim]"
    )
    with console.status("Building comparison report…"):
        md_path, csv_path = compare_report.run(
            run_id_a=args.run_a,
            run_id_b=args.run_b,
            dataset_path=args.dataset_path,
            runs_dir=getattr(args, "runs_dir", "data/runs"),
            generated_dir=getattr(args, "generated_dir", "data/generated"),
            reviews_dir=getattr(args, "reviews_dir", "data/reviews"),
            reports_dir=getattr(args, "reports_dir", "reports"),
            use_human_review=getattr(args, "use_human_review", False),
            charts=getattr(args, "charts", False),
        )
    console.print(f"[green]Comparison report:[/green] {md_path}")
    console.print(f"[green]CSV:[/green] {csv_path}")


def cmd_trend(args: argparse.Namespace, console: Console) -> None:
    from harness import trend_report

    console.print(f"[bold]Building trend report[/bold] — dataset: [dim]{args.dataset_path}[/dim]")
    with console.status("Aggregating run history…"):
        md_path, csv_path = trend_report.run(
            dataset_path=args.dataset_path,
            runs_dir=getattr(args, "runs_dir", "data/runs"),
            generated_dir=getattr(args, "generated_dir", "data/generated"),
            reviews_dir=getattr(args, "reviews_dir", "data/reviews"),
            reports_dir=getattr(args, "reports_dir", "reports"),
            filter_dataset=getattr(args, "filter_dataset", None),
            filter_prompt=getattr(args, "filter_prompt", None),
            use_human_review=getattr(args, "use_human_review", False),
            charts=getattr(args, "charts", False),
        )
    console.print(f"[green]Trend report:[/green] {md_path}")
    console.print(f"[green]CSV:[/green] {csv_path}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="AI Eval Harness — evaluation pipeline for AI-generated test cases",
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    sub.required = True

    # run
    p_run = sub.add_parser("run", help="Run full evaluation pipeline")
    p_run.add_argument("--config", required=True, help="Path to run config YAML")

    # generate
    p_gen = sub.add_parser("generate", help="Run generation step only")
    p_gen.add_argument("--config", required=True)
    p_gen.add_argument("--run-id", dest="run_id", default=None)

    # evaluate
    p_eval = sub.add_parser("evaluate", help="Run scoring step only")
    p_eval.add_argument("--config", required=True)
    p_eval.add_argument("--run-id", dest="run_id", default=None)

    # report
    p_report = sub.add_parser("report", help="Generate report from existing run")
    p_report.add_argument("--config", required=True)
    p_report.add_argument("--run-id", dest="run_id", default=None)
    p_report.add_argument("--use-human-review", dest="use_human_review", action="store_true", default=False)
    p_report.add_argument("--charts", action="store_true", default=False,
                          help="Embed PNG charts (requires matplotlib extra)")

    # review
    p_review = sub.add_parser("review", help="Interactive human review of borderline items")
    p_review.add_argument("--run-id", required=True)
    p_review.add_argument("--reviews-dir", dest="reviews_dir", default="data/reviews")
    p_review.add_argument("--generated-dir", dest="generated_dir", default="data/generated")
    p_review.add_argument("--runs-dir", dest="runs_dir", default="data/runs")
    p_review.add_argument("--gold-path", dest="gold_path", default=None)

    # compare
    p_compare = sub.add_parser("compare", help="Compare two evaluation runs")
    p_compare.add_argument("--run-a", required=True)
    p_compare.add_argument("--run-b", required=True)
    p_compare.add_argument("--dataset-path", required=True)
    p_compare.add_argument("--runs-dir", dest="runs_dir", default="data/runs")
    p_compare.add_argument("--generated-dir", dest="generated_dir", default="data/generated")
    p_compare.add_argument("--reviews-dir", dest="reviews_dir", default="data/reviews")
    p_compare.add_argument("--reports-dir", dest="reports_dir", default="reports")
    p_compare.add_argument("--use-human-review", dest="use_human_review", action="store_true", default=False)
    p_compare.add_argument("--charts", action="store_true", default=False)

    # trend
    p_trend = sub.add_parser("trend", help="Build cross-run trend report")
    p_trend.add_argument("--dataset-path", required=True)
    p_trend.add_argument("--runs-dir", dest="runs_dir", default="data/runs")
    p_trend.add_argument("--generated-dir", dest="generated_dir", default="data/generated")
    p_trend.add_argument("--reviews-dir", dest="reviews_dir", default="data/reviews")
    p_trend.add_argument("--reports-dir", dest="reports_dir", default="reports")
    p_trend.add_argument("--filter-dataset", dest="filter_dataset", default=None)
    p_trend.add_argument("--filter-prompt", dest="filter_prompt", default=None)
    p_trend.add_argument("--use-human-review", dest="use_human_review", action="store_true", default=False)
    p_trend.add_argument("--charts", action="store_true", default=False)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_SUBCOMMAND_HANDLERS = {
    "run": cmd_run,
    "generate": cmd_generate,
    "evaluate": cmd_evaluate,
    "report": cmd_report,
    "review": cmd_review,
    "compare": cmd_compare,
    "trend": cmd_trend,
}


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,  # suppress INFO from sub-modules; rich output takes over
        format="%(levelname)s %(name)s: %(message)s",
    )
    console = Console()
    parser = make_parser()
    args = parser.parse_args()
    handler = _SUBCOMMAND_HANDLERS.get(args.subcommand)
    if handler:
        handler(args, console)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
