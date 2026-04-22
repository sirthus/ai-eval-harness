"""Interactive terminal tool for human review of borderline evaluation results.

Usage:
    python -m harness.review_cli --run-id run_v2_prompt_v2_20260402T130000Z

Loads borderline items from data/reviews/{run_id}/queue.jsonl and presents
each one for adjudication. Saves decisions back to queue.jsonl and writes
data/reviews/{run_id}/adjudicated.jsonl on exit.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from harness.loaders import load_config
from harness.paths import ArtifactPaths
from harness.paths import manifest_path as build_manifest_path
from harness.review_queue import load_queue, write_adjudicated
from harness.schemas import GoldAnnotation, ModelOutput, ReviewRecord, RunManifest, ScoredResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context loaders
# ---------------------------------------------------------------------------


def _load_model_output(
    generated_dir: str, run_id: str, requirement_id: str
) -> ModelOutput | None:
    path = ArtifactPaths(generated_dir, run_id).output_file(requirement_id)
    if not path.exists():
        return None
    return ModelOutput.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_scored_result(
    generated_dir: str, run_id: str, requirement_id: str
) -> ScoredResult | None:
    results_path = ArtifactPaths(generated_dir, run_id).scored_results
    if not results_path.exists():
        return None
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for r in results:
        if r.get("requirement_id") == requirement_id:
            return ScoredResult.model_validate(r)
    return None


def _load_gold_notes(gold_path: str | Path, requirement_id: str) -> str:
    path = Path(gold_path)
    if not path.exists():
        return ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("requirement_id") == requirement_id:
                return GoldAnnotation.model_validate(data).review_notes
    return ""


def _resolve_repo_relative_path(path_str: str, config_path: Path) -> Path:
    raw = Path(path_str)
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend([
            config_path.parent / raw,
            config_path.parent.parent / raw,
        ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_gold_path(gold_path: str | None, run_id: str, runs_dir: str) -> Path:
    if gold_path:
        resolved = Path(gold_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Gold annotations not found: {resolved}")
        return resolved

    mpath = build_manifest_path(runs_dir, run_id)
    if not mpath.exists():
        raise FileNotFoundError(
            "Gold annotations could not be resolved automatically: "
            f"run manifest not found at {mpath}. "
            "Pass --gold-path explicitly or run the full pipeline first."
        )

    manifest = RunManifest.model_validate(
        json.loads(mpath.read_text(encoding="utf-8"))
    )
    config_path = Path(manifest.config_file)
    if not config_path.exists() and not config_path.is_absolute():
        config_path = mpath.parent.parent.parent / manifest.config_file
    if not config_path.exists():
        raise FileNotFoundError(
            "Gold annotations could not be resolved automatically: "
            f"config file referenced by the manifest was not found at {config_path}. "
            "Pass --gold-path explicitly."
        )

    config = load_config(config_path) or {}

    config_gold = config.get("gold_path")
    if not config_gold:
        raise FileNotFoundError(
            "Gold annotations could not be resolved automatically: "
            f"config {config_path} does not define gold_path. "
            "Pass --gold-path explicitly."
        )

    resolved_gold = _resolve_repo_relative_path(config_gold, config_path)
    if not resolved_gold.exists():
        raise FileNotFoundError(
            "Gold annotations could not be resolved automatically: "
            f"gold_path from {config_path} was not found at {resolved_gold}. "
            "Pass --gold-path explicitly."
        )
    return resolved_gold


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _display_item(
    index: int,
    total: int,
    record: ReviewRecord,
    output: ModelOutput | None,
    scored: ScoredResult | None,
    gold_notes: str,
    console=None,
) -> None:
    """Display a borderline item for review.

    console: optional rich.console.Console. When None, falls back to print()
    so existing tests that inject input_fn remain unaffected.
    """
    if console is not None:
        _display_item_rich(index, total, record, output, scored, gold_notes, console)
    else:
        _display_item_plain(index, total, record, output, scored, gold_notes)


def _display_item_plain(
    index: int,
    total: int,
    record: ReviewRecord,
    output: ModelOutput | None,
    scored: ScoredResult | None,
    gold_notes: str,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"=== Review {index} of {total} ===")
    print(f"Run:          {record.run_id}")
    print(f"Requirement:  {record.requirement_id}")

    if gold_notes:
        print(f"Gold notes:   {gold_notes}")

    scores = record.scores
    print(
        f"\nAuto scores:  correctness={scores.correctness:.1f}  "
        f"completeness={scores.completeness:.1f}  "
        f"hallucination={scores.hallucination_risk:.1f}  "
        f"usefulness={scores.reviewer_usefulness:.1f}"
    )
    if scored:
        print(
            f"              Weighted: {record.weighted_score:.2f} (borderline) | "
            f"Coverage: {scored.coverage_ratio:.0%} | "
            f"Disallowed hits: {', '.join(scored.disallowed_hits) or 'none'}"
        )
        if scored.diagnostic_notes:
            print(f"              Diagnostics: {scored.diagnostic_notes}")

    if output:
        print(f"\nGenerated test cases ({len(output.test_cases)}):")
        for i, tc in enumerate(output.test_cases, 1):
            print(f'  [{i}] "{tc.title}" ({tc.type}, {tc.priority})')
            if tc.preconditions:
                print(f"      Preconditions: {'; '.join(tc.preconditions)}")
            print(f"      Steps: {' -> '.join(tc.steps)}")
            print(f"      Expected: {tc.expected_result}")
        if output.assumptions:
            print(f"  Assumptions: {'; '.join(output.assumptions)}")
        if output.notes:
            print(f"  Notes: {output.notes}")
    else:
        print("\n(Generated test cases not available)")


def _display_item_rich(
    index: int,
    total: int,
    record: ReviewRecord,
    output: ModelOutput | None,
    scored: ScoredResult | None,
    gold_notes: str,
    console,
) -> None:
    from rich.panel import Panel
    from rich.table import Table

    header = (
        f"[bold]Review {index} of {total}[/bold]  |  "
        f"Run: [dim]{record.run_id}[/dim]  |  "
        f"Req: [bold]{record.requirement_id}[/bold]\n"
    )
    if gold_notes:
        header += f"Gold notes: [italic]{gold_notes}[/italic]\n"

    scores = record.scores
    header += (
        f"\nAuto scores: "
        f"correctness={scores.correctness:.1f}  "
        f"completeness={scores.completeness:.1f}  "
        f"hallucination={scores.hallucination_risk:.1f}  "
        f"usefulness={scores.reviewer_usefulness:.1f}"
    )
    if scored:
        header += (
            f"\nWeighted: [yellow]{record.weighted_score:.2f}[/yellow] (borderline) | "
            f"Coverage: {scored.coverage_ratio:.0%} | "
            f"Disallowed hits: {', '.join(scored.disallowed_hits) or 'none'}"
        )
        if scored.diagnostic_notes:
            header += f"\nDiagnostics: [dim]{scored.diagnostic_notes}[/dim]"

    console.print(Panel(header, title=f"Borderline Item {index}/{total}", border_style="yellow"))

    if output:
        tc_table = Table(show_header=True, header_style="bold", show_lines=True)
        tc_table.add_column("#", style="dim", width=3)
        tc_table.add_column("Title / Type / Priority")
        tc_table.add_column("Steps")
        tc_table.add_column("Expected Result")
        for i, tc in enumerate(output.test_cases, 1):
            tc_table.add_row(
                str(i),
                f"[bold]{tc.title}[/bold]\n[dim]{tc.type} / {tc.priority}[/dim]",
                " → ".join(tc.steps),
                tc.expected_result,
            )
        console.print(tc_table)
        if output.assumptions:
            console.print(f"[dim]Assumptions:[/dim] {'; '.join(output.assumptions)}")
        if output.notes:
            console.print(f"[dim]Notes:[/dim] {output.notes}")
    else:
        console.print("[dim](Generated test cases not available)[/dim]")


# ---------------------------------------------------------------------------
# Adjudication session
# ---------------------------------------------------------------------------


def adjudicate(
    records: list[ReviewRecord],
    generated_dir: str,
    gold_path: str,
    input_fn=input,
    console=None,
) -> list[ReviewRecord]:
    """Run interactive adjudication session. Returns updated records.

    input_fn can be replaced in tests via monkeypatching.
    console: optional rich.console.Console for rich display.
    """
    pending = [r for r in records if r.review_decision == "pending"]
    decided = [r for r in records if r.review_decision != "pending"]

    if not pending:
        print("No pending items in review queue. Nothing to do.")
        return records

    print(f"\nReview queue: {len(pending)} pending item(s).")
    print("Controls: [p] pass  [f] fail  [s] skip  [q] quit and save\n")

    for i, record in enumerate(pending, 1):
        req_id = record.requirement_id
        run_id = record.run_id

        output = _load_model_output(generated_dir, run_id, req_id)
        scored = _load_scored_result(generated_dir, run_id, req_id)
        gold_notes = _load_gold_notes(gold_path, req_id)

        _display_item(i, len(pending), record, output, scored, gold_notes, console=console)

        while True:
            decision = input_fn("Decision [p=pass / f=fail / s=skip / q=quit]: ").strip().lower()
            if decision in ("p", "f", "s", "q"):
                break
            print("  Enter p, f, s, or q.")

        if decision == "q":
            print("Quitting. All decisions made so far will be saved.")
            decided.append(record)
            decided.extend(pending[i:])
            break

        if decision == "s":
            decided.append(record)
            continue

        notes = input_fn("Notes (optional, press Enter to skip): ").strip()
        record.review_decision = "pass" if decision == "p" else "fail"
        record.reviewer_notes = notes
        record.reviewed_at = datetime.now(UTC).isoformat()
        decided.append(record)

    result_map = {r.requirement_id: r for r in decided}
    return [result_map.get(r.requirement_id, r) for r in records]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run(
    run_id: str,
    reviews_dir: str = "data/reviews",
    generated_dir: str = "data/generated",
    gold_path: str | None = None,
    runs_dir: str = "data/runs",
    console=None,
) -> None:
    queue_path = Path(reviews_dir) / run_id / "queue.jsonl"
    if not queue_path.exists():
        logger.error("Review queue not found: %s", queue_path)
        raise SystemExit(1)

    records = load_queue(queue_path)
    if not records:
        print(f"Review queue is empty: {queue_path}")
        return

    resolved_gold = _resolve_gold_path(gold_path, run_id, runs_dir)
    updated = adjudicate(records, generated_dir, str(resolved_gold), console=console)

    with open(queue_path, "w", encoding="utf-8") as f:
        for record in updated:
            f.write(record.model_dump_json() + "\n")
    logger.info("Updated queue written: %s", queue_path)

    write_adjudicated(updated, run_id, reviews_dir)

    decided_count = sum(1 for r in updated if r.review_decision != "pending")
    print(f"\nSession complete. {decided_count}/{len(updated)} item(s) adjudicated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive human review of borderline results")
    parser.add_argument("--run-id", required=True, help="Run ID to review")
    parser.add_argument("--reviews-dir", default="data/reviews", help="Reviews directory")
    parser.add_argument("--generated-dir", default="data/generated", help="Generated outputs directory")
    parser.add_argument("--runs-dir", default="data/runs", help="Run manifests directory")
    parser.add_argument(
        "--gold-path",
        default=None,
        help="Gold annotations path (optional; otherwise resolved from the run manifest/config)",
    )
    args = parser.parse_args()
    run(
        run_id=args.run_id,
        reviews_dir=args.reviews_dir,
        generated_dir=args.generated_dir,
        gold_path=args.gold_path,
        runs_dir=args.runs_dir,
    )


if __name__ == "__main__":
    main()
