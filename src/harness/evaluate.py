"""Evaluation step: score generated outputs against gold annotations.

Usage:
    python -m harness.evaluate --config configs/run_v1.yaml [--run-id run_v1_20260329T143022]

Writes scored_results.json to {generated_dir}/{run_id}/ so the report step can
find it without requiring the caller to pass results explicitly.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import yaml

from harness import score as scoring
from harness.schemas import GoldAnnotation, ModelOutput, ScoredResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SCORED_RESULTS_FILE = "scored_results.json"


def run(
    config_path: str,
    run_id: str | None = None,
) -> list[ScoredResult]:
    """Score all generated outputs. Returns list of ScoredResult.

    run_id overrides the config's run_id when provided.
    Writes scored_results.json to the generated run directory.
    """
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    effective_run_id = run_id or cfg["run_id"]
    generated_dir = Path(cfg["generated_dir"]) / effective_run_id
    gold_path: str = cfg["gold_path"]
    thresholds: dict = cfg.get("thresholds", {})
    weights: dict = thresholds.get("weights")

    gold_map = _load_gold(gold_path)
    outputs = _load_generated(generated_dir)

    results: list[ScoredResult] = []
    for req_id, output in outputs.items():
        gold = gold_map.get(req_id)
        if gold is None:
            logger.warning("No gold annotation for %s — skipping", req_id)
            continue
        result = scoring.score(output, gold, weights=weights, thresholds=thresholds)
        results.append(result)
        logger.info(
            "%s → %s (weighted=%.2f, coverage=%.0f%%)",
            req_id,
            result.decision.upper(),
            result.weighted_score,
            result.coverage_ratio * 100,
        )

    _write_scored_results(results, generated_dir)
    return results


def _write_scored_results(results: list[ScoredResult], directory: Path) -> None:
    """Write scored results to a predictable location for the report step."""
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / SCORED_RESULTS_FILE
    payload = [r.model_dump() for r in results]
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Scored results written: %s", out_path)


def scored_results_path(config_path: str, run_id: str | None = None) -> Path:
    """Return the canonical path to scored_results.json for a given run."""
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    effective_run_id = run_id or cfg["run_id"]
    return Path(cfg["generated_dir"]) / effective_run_id / SCORED_RESULTS_FILE


def _load_gold(path: str) -> dict[str, GoldAnnotation]:
    gold: dict[str, GoldAnnotation] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ann = GoldAnnotation.model_validate(json.loads(line))
                gold[ann.requirement_id] = ann
    return gold


def _load_generated(directory: Path) -> dict[str, ModelOutput]:
    outputs: dict[str, ModelOutput] = {}
    for json_file in sorted(directory.glob("REQ-*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        output = ModelOutput.model_validate(data)
        outputs[output.requirement_id] = output
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate generated outputs")
    parser.add_argument("--config", required=True, help="Path to run config YAML")
    parser.add_argument(
        "--run-id", dest="run_id", default=None,
        help="Override run ID (default: uses config run_id)"
    )
    args = parser.parse_args()
    results = run(args.config, run_id=args.run_id)
    passes = sum(1 for r in results if r.decision == "pass")
    borderlines = sum(1 for r in results if r.decision == "borderline")
    fails = sum(1 for r in results if r.decision == "fail")
    print(f"\nResults: {passes} pass, {borderlines} borderline, {fails} fail")


if __name__ == "__main__":
    main()
