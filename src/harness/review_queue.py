"""Review queue: route borderline scored results to data/reviews/ for human review.

Usage:
    python -m harness.review_queue --config configs/run_v1.yaml
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from harness.schemas import ReviewRecord, ScoredResult

logger = logging.getLogger(__name__)


def write_queue(
    results: list[ScoredResult],
    run_id: str,
    reviews_dir: str,
) -> Path:
    """Write borderline results to the review queue. Returns the queue file path."""
    borderlines = [r for r in results if r.decision == "borderline"]
    queue_dir = Path(reviews_dir) / run_id
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_path = queue_dir / "queue.jsonl"

    with open(queue_path, "w", encoding="utf-8") as f:
        for result in borderlines:
            record = ReviewRecord(
                run_id=run_id,
                requirement_id=result.requirement_id,
                weighted_score=result.weighted_score,
                scores=result.scores,
                review_decision="pending",
                reviewer_notes="",
            )
            f.write(record.model_dump_json() + "\n")

    logger.info(
        "Wrote %d borderline item(s) to review queue: %s",
        len(borderlines),
        queue_path,
    )
    return queue_path


def load_queue(queue_path: Path) -> list[ReviewRecord]:
    """Load an existing review queue file."""
    records: list[ReviewRecord] = []
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(ReviewRecord.model_validate(json.loads(line)))
    return records


def write_adjudicated(
    records: list[ReviewRecord],
    run_id: str,
    reviews_dir: str,
) -> Path:
    """Write adjudicated (non-pending) records to adjudicated.jsonl.

    Only records where review_decision != 'pending' are written.
    Returns the path to the adjudicated file.
    """
    decided = [r for r in records if r.review_decision != "pending"]
    adj_dir = Path(reviews_dir) / run_id
    adj_dir.mkdir(parents=True, exist_ok=True)
    adj_path = adj_dir / "adjudicated.jsonl"

    with open(adj_path, "w", encoding="utf-8") as f:
        for record in decided:
            f.write(record.model_dump_json() + "\n")

    logger.info(
        "Wrote %d adjudicated record(s) to %s",
        len(decided),
        adj_path,
    )
    return adj_path


def load_adjudicated(run_id: str, reviews_dir: str) -> dict[str, "ReviewRecord"]:
    """Load adjudicated records for a run. Returns a dict keyed by requirement_id."""
    adj_path = Path(reviews_dir) / run_id / "adjudicated.jsonl"
    if not adj_path.exists():
        return {}
    records: dict[str, ReviewRecord] = {}
    with open(adj_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = ReviewRecord.model_validate(json.loads(line))
                records[rec.requirement_id] = rec
    return records
