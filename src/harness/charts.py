"""Chart generation for evaluation reports.

Requires the optional 'charts' extra:
    pip install -e ".[charts]"

All functions return the Path to the written PNG, or None if matplotlib is not
installed (graceful degradation — reports still work without charts).

matplotlib.use("Agg") is set at module level so charts render correctly in
headless CI environments and on Windows without a display server.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.figure import Figure
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False


def _check_available() -> bool:
    if not _MATPLOTLIB_AVAILABLE:
        logger.warning(
            "matplotlib is not installed — charts disabled. "
            "Run: pip install -e '.[charts]'"
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Per-run charts
# ---------------------------------------------------------------------------


def plot_score_distribution(
    results: list,
    run_id: str,
    output_path: Path,
) -> Path | None:
    """Horizontal bar chart: pass / borderline / fail counts."""
    if not _check_available():
        return None

    pass_n = sum(1 for r in results if r.decision == "pass")
    border_n = sum(1 for r in results if r.decision == "borderline")
    fail_n = sum(1 for r in results if r.decision == "fail")

    fig, ax = plt.subplots(figsize=(6, 3))
    bars = ax.barh(
        ["fail", "borderline", "pass"],
        [fail_n, border_n, pass_n],
        color=["#e74c3c", "#f39c12", "#2ecc71"],
    )
    ax.bar_label(bars, padding=4)
    ax.set_xlabel("Count")
    ax.set_title(f"Score Distribution — {run_id}")
    ax.set_xlim(0, max(pass_n + border_n + fail_n, 1) + 2)
    fig.tight_layout()

    out = Path(output_path) / f"{run_id}_score_distribution.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def plot_dimension_scores(
    results: list,
    run_id: str,
    output_path: Path,
) -> Path | None:
    """Grouped bar chart: average per-dimension scores with floor threshold line."""
    if not _check_available():
        return None

    dims = ["correctness", "completeness", "hallucination_risk", "reviewer_usefulness"]
    avgs = [
        sum(getattr(r.scores, d) for r in results) / len(results) if results else 0.0
        for d in dims
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(dims))
    bars = ax.bar(x, avgs, color="#3498db", width=0.6)
    ax.bar_label(bars, fmt="%.2f", padding=3)
    ax.axhline(y=1.0, color="#e74c3c", linestyle="--", linewidth=1, label="Floor (1.0)")
    ax.set_xticks(list(x))
    ax.set_xticklabels([d.replace("_", "\n") for d in dims])
    ax.set_ylim(0, 2.2)
    ax.set_ylabel("Avg Score (0–2)")
    ax.set_title(f"Per-Dimension Averages — {run_id}")
    ax.legend(fontsize=8)
    fig.tight_layout()

    out = Path(output_path) / f"{run_id}_dimensions.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def plot_per_requirement_scores(
    results: list,
    run_id: str,
    output_path: Path,
) -> Path | None:
    """Bar per requirement, colored by decision band, with threshold lines."""
    if not _check_available():
        return None

    sorted_results = sorted(results, key=lambda r: r.requirement_id)
    labels = [r.requirement_id for r in sorted_results]
    scores = [r.weighted_score for r in sorted_results]
    colors = [
        "#2ecc71" if r.decision == "pass"
        else "#f39c12" if r.decision == "borderline"
        else "#e74c3c"
        for r in sorted_results
    ]

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.5), 5))
    ax.bar(range(len(labels)), scores, color=colors, width=0.7)
    ax.axhline(y=1.6, color="#2ecc71", linestyle="--", linewidth=1, label="Pass (1.6)")
    ax.axhline(y=1.2, color="#f39c12", linestyle="--", linewidth=1, label="Borderline (1.2)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 2.2)
    ax.set_ylabel("Weighted Score")
    ax.set_title(f"Per-Requirement Scores — {run_id}")
    ax.legend(fontsize=8)
    fig.tight_layout()

    out = Path(output_path) / f"{run_id}_per_requirement.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Compare report charts
# ---------------------------------------------------------------------------


def plot_compare_distribution(
    results_a: list,
    results_b: list,
    run_id_a: str,
    run_id_b: str,
    output_path: Path,
    timestamp: str = "",
) -> Path | None:
    """Side-by-side grouped bar: pass/borderline/fail for two runs."""
    if not _check_available():
        return None

    def _counts(results):
        return (
            sum(1 for r in results if r.decision == "pass"),
            sum(1 for r in results if r.decision == "borderline"),
            sum(1 for r in results if r.decision == "fail"),
        )

    pa, ba, fa = _counts(results_a)
    pb, bb, fb = _counts(results_b)

    import numpy as np
    x = np.arange(3)
    width = 0.35
    labels = ["Pass", "Borderline", "Fail"]
    vals_a = [pa, ba, fa]
    vals_b = [pb, bb, fb]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars_a = ax.bar(x - width / 2, vals_a, width, label=run_id_a[:20], color="#3498db")
    bars_b = ax.bar(x + width / 2, vals_b, width, label=run_id_b[:20], color="#e67e22")
    ax.bar_label(bars_a, padding=2)
    ax.bar_label(bars_b, padding=2)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Count")
    ax.set_title("Score Distribution Comparison")
    ax.legend(fontsize=8)
    fig.tight_layout()

    prefix = f"{timestamp}_" if timestamp else ""
    out = Path(output_path) / f"{prefix}compare_{run_id_a[:20]}_vs_{run_id_b[:20]}_distribution.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def plot_compare_delta(
    results_a: dict,
    results_b: dict,
    run_id_a: str,
    run_id_b: str,
    output_path: Path,
    timestamp: str = "",
) -> Path | None:
    """Per-requirement score delta (B − A), colored by direction."""
    if not _check_available():
        return None

    intersection = sorted(set(results_a) & set(results_b))
    if not intersection:
        return None

    deltas = [
        (req_id, results_b[req_id].weighted_score - results_a[req_id].weighted_score)
        for req_id in intersection
    ]
    deltas.sort(key=lambda x: x[1])

    labels = [d[0] for d in deltas]
    values = [d[1] for d in deltas]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in values]

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.5), 5))
    ax.bar(range(len(labels)), values, color=colors, width=0.7)
    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Score Delta (B − A)")
    ax.set_title(f"Per-Requirement Delta: {run_id_a[:15]} vs {run_id_b[:15]}")
    fig.tight_layout()

    prefix = f"{timestamp}_" if timestamp else ""
    out = Path(output_path) / f"{prefix}compare_{run_id_a[:20]}_vs_{run_id_b[:20]}_delta.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Trend report charts
# ---------------------------------------------------------------------------


def plot_trend_pass_rate(
    trend_data: list[dict],
    output_path: Path,
    timestamp: str = "",
) -> Path | None:
    """Line chart: pass rate over time. Second dashed line for borderline rate.

    trend_data: list of {run_id, pass_rate, borderline_rate} dicts, sorted by time.
    timestamp: used as a filename prefix so repeated runs do not overwrite each other's
               chart images when the markdown report also uses a timestamp in its name.
    """
    if not _check_available():
        return None
    if not trend_data:
        return None

    x = range(len(trend_data))
    labels = [d["run_id"][-16:] for d in trend_data]  # truncate for readability
    pass_rates = [d["pass_rate"] for d in trend_data]
    borderline_rates = [d.get("borderline_rate", 0.0) for d in trend_data]

    fig, ax = plt.subplots(figsize=(max(6, len(trend_data) * 1.2), 4))
    ax.plot(list(x), pass_rates, marker="o", color="#2ecc71", label="Pass rate")
    ax.plot(list(x), borderline_rates, marker="s", linestyle="--", color="#f39c12", label="Borderline rate")
    ax.axhline(y=0.7, color="#2ecc71", linestyle=":", linewidth=1, alpha=0.6)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Rate")
    ax.set_title("Pass Rate Over Time")
    ax.legend(fontsize=8)
    fig.tight_layout()

    prefix = f"{timestamp}_" if timestamp else ""
    out = Path(output_path) / f"{prefix}trend_pass_rate.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out


def plot_domain_heatmap(
    domain_data: dict[str, dict[str, float]],
    run_ids: list[str],
    output_path: Path,
    timestamp: str = "",
) -> Path | None:
    """Heatmap: rows=domains, columns=run_ids, values=pass_rate."""
    if not _check_available():
        return None
    if not domain_data or not run_ids:
        return None

    import numpy as np

    domains = sorted(domain_data)
    matrix = [
        [domain_data[d].get(rid, 0.0) for rid in run_ids]
        for d in domains
    ]

    fig, ax = plt.subplots(figsize=(max(6, len(run_ids) * 1.5), max(3, len(domains) * 0.6)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(run_ids)))
    ax.set_xticklabels([rid[-14:] for rid in run_ids], rotation=35, ha="right", fontsize=7)
    ax.set_yticks(range(len(domains)))
    ax.set_yticklabels(domains, fontsize=8)
    ax.set_title("Domain Pass Rates")
    fig.colorbar(im, ax=ax, label="Pass rate")
    fig.tight_layout()

    prefix = f"{timestamp}_" if timestamp else ""
    out = Path(output_path) / f"{prefix}trend_domain_heatmap.png"
    fig.savefig(out, dpi=100)
    plt.close(fig)
    return out
