"""Check rankings against the injected anomalies (the synthetic ledger's ground truth)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from . import flags, pipeline, scoring, synthetic
from .rules import absolute_amount

# Ablation: the risk score with one design choice turned off at a time (score_flags switches)
VARIANTS = {
    "Rarity only (priors = 1)": {"use_priors": False},
    "Priors only (no rarity)": {"use_rarity": False},
    "Date tests not collapsed": {"collapse_dates": False},
    "No amount multiplier": {"amount_multiplier": False},
    "No Benford diversity scaling": {"benford_scaling": False},
}


def precision_recall_at_k(ranked_ids: Sequence, truth_ids: set, k: int) -> tuple[float, float]:
    """Share of the top ``k`` that are true anomalies, and share of all anomalies found in the top ``k``."""
    top = list(ranked_ids)[:k]
    hits = sum(1 for i in top if i in truth_ids)
    return hits / k if k else 0.0, hits / len(truth_ids) if truth_ids else 0.0


def rankings(scored: pd.DataFrame, ledger: pd.DataFrame, amount_cols: Sequence[str], id_col: str = "Sr No",
             seed: int = 0, ml: bool = False) -> dict[str, list]:
    """
    Row IDs in ranked order for the risk score and the baselines.

    - **Risk score**: ``score_flags`` with every flagged row (``top_n=None``).
    - **Number of tests hit**: most tests first, ties broken by amount (a common manual approach).
    - **Amount only**: the largest lines in the whole ledger.
    - **Random flagged lines**: the flagged rows in a random order.
    - **Isolation Forest** (``ml=True``, needs scikit-learn): the whole ledger, most anomalous first.
    """
    by_tests = scored.assign(_amt=absolute_amount(scored, amount_cols)).sort_values(
        ["N Flags", "_amt"], ascending=False, kind="stable")
    by_amount = ledger.assign(_amt=absolute_amount(ledger, amount_cols)).sort_values("_amt", ascending=False)
    out = {
        "Risk score": scored[id_col].tolist(),
        "Number of tests hit": by_tests[id_col].tolist(),
        "Amount only": by_amount[id_col].tolist(),
        "Random flagged lines": list(np.random.default_rng(seed).permutation(scored[id_col].to_numpy())),
    }
    if ml:
        from .ml_baseline import isolation_forest_ranking
        out["Isolation Forest"] = isolation_forest_ranking(ledger, amount_cols, seed=seed).tolist()
    return out


def ceilings(scored: pd.DataFrame, truth: set, k: int, id_col: str = "Sr No") -> tuple[float, float]:
    """
    The best any ranking of the flagged lines can do: (precision@k, recall@k).

    Recall can't exceed the share of anomalies that trip at least one test; precision can't exceed
    that number of anomalies divided by k.
    """
    reachable = len(truth & set(scored[id_col]))
    return min(reachable, k) / k, reachable / len(truth) if truth else 0.0


def compare_rankings(scored: pd.DataFrame, ledger: pd.DataFrame, amount_cols: Sequence[str], k: int,
                     id_col: str = "Sr No", truth_col: str = "Anomaly", seed: int = 0,
                     ml: bool = False) -> pd.DataFrame:
    """Precision and recall at ``k`` for each ranking, with the ceiling as the last row."""
    truth = set(ledger.loc[ledger[truth_col] != "", id_col])
    rows = {name: precision_recall_at_k(ids, truth, k)
            for name, ids in rankings(scored, ledger, amount_cols, id_col, seed, ml).items()}
    rows["Ceiling (flagged lines)"] = ceilings(scored, truth, k, id_col)
    table = pd.DataFrame(rows, index=[f"Precision@{k}", f"Recall@{k}"]).T.round(3)
    table.attrs.update(k=k, anomalies=len(truth), flagged_rows=len(scored))
    return table


def run_once(n_rows: int, anomaly_rate: float, seed: int, ks: Iterable[int] | None = None,
             ablation: bool = False, ml: bool = False) -> pd.DataFrame:
    """
    Generate one ledger, run every test, score it and measure each ranking at each k.

    The IDEA-side tests are computed in memory (``pipeline.idea_side_flags``). Returns a long
    table: ``n_rows``, ``anomaly_rate``, ``seed``, ``ranking``, ``k``, ``default_k``, ``precision``,
    ``recall`` and ``share_of_ceiling`` (precision ÷ the best possible precision at that k).
    """
    ledger = synthetic.make_ledger(n_rows, seed=seed, anomaly_rate=anomaly_rate)
    amt = synthetic.amount_columns(ledger)
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt))
    truth = set(ledger.loc[ledger["Anomaly"] != "", "Sr No"])
    default_k = scoring.priority_list_size(len(ledger))
    ks = sorted(set(ks or []) | {default_k})

    scored = scoring.score_flags(flagged, amt, top_n=None)
    ranked = rankings(scored, ledger, amt, seed=seed, ml=ml)
    if ablation:
        for name, switches in VARIANTS.items():
            ranked[name] = scoring.score_flags(flagged, amt, top_n=None, **switches)["Sr No"].tolist()

    rows = []
    for k in ks:
        best = ceilings(scored, truth, k)
        for name, ids in ranked.items():
            precision, recall = precision_recall_at_k(ids, truth, k)
            rows.append((name, k, precision, recall, precision / best[0] if best[0] else 0.0))
        rows.append(("Ceiling (flagged lines)", k, *best, 1.0))
    out = pd.DataFrame(rows, columns=["ranking", "k", "precision", "recall", "share_of_ceiling"])
    return out.assign(n_rows=n_rows, anomaly_rate=anomaly_rate, seed=seed, default_k=default_k)


def summarise(results: pd.DataFrame, default_k_only: bool = True) -> pd.DataFrame:
    """Mean and standard deviation of precision, recall and share of ceiling per ranking (over seeds)."""
    data = results[results["k"] == results["default_k"]] if default_k_only else results
    keys = ["n_rows", "anomaly_rate", "ranking"] + ([] if default_k_only else ["k"])
    metrics = [m for m in ("precision", "recall", "share_of_ceiling") if m in data.columns]
    table = data.groupby(keys, sort=False)[metrics].agg(["mean", "std"]).round(3)
    table.columns = [f"{m} {s}" for m, s in table.columns]
    return table.assign(seeds=data.groupby(keys, sort=False)["seed"].nunique()).reset_index()
