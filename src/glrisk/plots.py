"""The four demo charts: flag overlap, score distribution, Benford first digits, priority-list amounts."""

from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from .rules import absolute_amount

BLUE, ORANGE, GREY = "#4C72B0", "#DD8452", "#B0B7C3"


def _compact(x: float, _=None) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"{x / size:.3g}{suffix}"
    return f"{x:.0f}"


def flag_overlap(flagged: pd.DataFrame, top: int = 12, ax: plt.Axes | None = None) -> plt.Axes:
    """The most common combinations of tests among flagged rows (an UpSet-style summary)."""
    ax = ax or plt.subplots(figsize=(9, 5))[1]
    combos = flagged["Flagged By"].value_counts().head(top).iloc[::-1]
    colours = [ORANGE if "," in c else BLUE for c in combos.index]
    ax.barh(combos.index, combos.to_numpy(), color=colours)
    for y, v in enumerate(combos.to_numpy()):
        ax.text(v, y, f" {v:,}", va="center", fontsize=9)
    ax.set_title("Most common test combinations (orange = more than one test)")
    ax.set_xlabel("Flagged lines")
    ax.spines[["top", "right"]].set_visible(False)
    return ax


def score_distribution(scored_all: pd.DataFrame, list_size: int, truth_col: str = "Anomaly",
                       ax: plt.Axes | None = None) -> plt.Axes:
    """Histogram of scores for all flagged rows, injected anomalies highlighted, with the list cut-off."""
    ax = ax or plt.subplots(figsize=(9, 5))[1]
    injected = scored_all[truth_col] != "" if truth_col in scored_all else pd.Series(False, index=scored_all.index)
    bins = np.histogram_bin_edges(scored_all["Score"], bins=40)
    ax.hist(scored_all.loc[~injected, "Score"], bins=bins, color=GREY, label="Other flagged lines")
    ax.hist(scored_all.loc[injected, "Score"], bins=bins, color=ORANGE, alpha=0.9, label="Injected anomalies")
    cutoff = scored_all["Score"].nlargest(list_size).min()
    ax.axvline(cutoff, color="black", linestyle="--", linewidth=1)
    ax.text(cutoff, ax.get_ylim()[1] * 0.95, f"  priority list ({list_size})", va="top", fontsize=9)
    ax.set_yscale("log")
    ax.set_title("Risk score of flagged lines")
    ax.set_xlabel("Score")
    ax.set_ylabel("Lines (log scale)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return ax


def benford_chart(table: pd.DataFrame, ax: plt.Axes | None = None) -> plt.Axes:
    """Actual first-digit shares (bars) against Benford's expected curve, with the MAD verdict."""
    ax = ax or plt.subplots(figsize=(9, 5))[1]
    over = (table["Z"] > 1.96) & (table["Actual"] > table["Expected"])
    ax.bar(table["Digit"], table["Actual"], color=[ORANGE if o else BLUE for o in over], label="Actual")
    ax.plot(table["Digit"], table["Expected"], color="black", marker="o", label="Benford expected")
    ax.set_xticks(range(1, 10))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_title(f"First digits: MAD {table.attrs['mad']:.4f}, {table.attrs['conformity']}\n"
                 f"(orange: significantly above expected, z > 1.96)")
    ax.set_xlabel("First digit")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return ax


def priority_amounts(priority: pd.DataFrame, amount_cols: Sequence[str], truth_col: str = "Anomaly",
                     ax: plt.Axes | None = None) -> plt.Axes:
    """Score against amount for the priority list, injected anomalies highlighted."""
    ax = ax or plt.subplots(figsize=(9, 5))[1]
    amount = absolute_amount(priority, amount_cols)
    injected = priority[truth_col] != "" if truth_col in priority else pd.Series(False, index=priority.index)
    ax.scatter(amount[~injected], priority.loc[~injected, "Score"], color=GREY, label="Other lines", s=30)
    ax.scatter(amount[injected], priority.loc[injected, "Score"], color=ORANGE, label="Injected anomalies", s=30)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(_compact))
    ax.set_title(f"Priority list ({len(priority)} lines): score and amount")
    ax.set_xlabel("Amount (AED, log scale)")
    ax.set_ylabel("Score")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return ax
