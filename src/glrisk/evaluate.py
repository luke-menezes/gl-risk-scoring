"""Check a ranking against the injected anomalies (the synthetic ledger's ground truth)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .rules import absolute_amount


def precision_recall_at_k(ranked_ids: Sequence, truth_ids: set, k: int) -> tuple[float, float]:
    """Share of the top ``k`` that are true anomalies, and share of all anomalies found in the top ``k``."""
    top = list(ranked_ids)[:k]
    hits = sum(1 for i in top if i in truth_ids)
    return hits / k if k else 0.0, hits / len(truth_ids) if truth_ids else 0.0


def compare_rankings(scored: pd.DataFrame, ledger: pd.DataFrame, amount_cols: Sequence[str], k: int,
                     id_col: str = "Sr No", truth_col: str = "Anomaly", seed: int = 0) -> pd.DataFrame:
    """
    Precision and recall at ``k`` for the risk score and three simple baselines.

    - **Risk score**: ``score_flags`` with every flagged row (``top_n=None``).
    - **Number of flags**: most tests first, ties broken by amount (a common manual approach).
    - **Amount only**: the largest lines in the ledger.
    - **Random flagged rows**: the average of 20 random orders of the flagged rows.

    Args:
        scored: ``score_flags(..., top_n=None)`` output.
        ledger: The full ledger, with the ground-truth column.
        k: List size to evaluate (e.g. ``priority_list_size(len(ledger))``).
    """
    truth = set(ledger.loc[ledger[truth_col] != "", id_col])
    by_flags = scored.assign(_amt=absolute_amount(scored, amount_cols)).sort_values(
        ["N Flags", "_amt"], ascending=False, kind="stable")
    by_amount = ledger.assign(_amt=absolute_amount(ledger, amount_cols)).sort_values("_amt", ascending=False)
    rng = np.random.default_rng(seed)
    random_pr = np.mean([precision_recall_at_k(rng.permutation(scored[id_col].to_numpy()), truth, k)
                         for _ in range(20)], axis=0)
    rows = {
        "Risk score": precision_recall_at_k(scored[id_col], truth, k),
        "Number of flags": precision_recall_at_k(by_flags[id_col], truth, k),
        "Amount only": precision_recall_at_k(by_amount[id_col], truth, k),
        "Random flagged rows": tuple(random_pr),
    }
    table = pd.DataFrame(rows, index=[f"Precision@{k}", f"Recall@{k}"]).T.round(3)
    table.attrs.update(k=k, anomalies=len(truth), flagged_rows=len(scored))
    return table
