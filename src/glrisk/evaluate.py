"""Check voucher rankings against the injected anomalies (the synthetic ledger's ground truth)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from . import flags, pipeline, scoring, synthetic

# Ablation: the risk score with one design choice turned off at a time (score_flags switches)
VARIANTS = {
    "Rarity only (priors = 1)": {"use_priors": False},
    "Priors only (no rarity)": {"use_rarity": False},
    "Date tests not collapsed": {"collapse_dates": False},
    "No amount multiplier": {"amount_multiplier": False},
    "No Benford diversity scaling": {"benford_scaling": False},
}


VOUCHER_AMOUNT = ["Voucher Amount"]   # the amount column of to_vouchers' output


def precision_recall_at_k(ranked_ids: Sequence, truth_ids: set, k: int) -> tuple[float, float]:
    """Share of the top ``k`` that are true anomalies, and share of all anomalies found in the top ``k``."""
    top = list(ranked_ids)[:k]
    hits = sum(1 for i in top if i in truth_ids)
    return hits / k if k else 0.0, hits / len(truth_ids) if truth_ids else 0.0


def prepare(n_rows: int, seed: int, anomaly_rate: float = 0.008, **ledger_kwargs
            ) -> tuple[pd.DataFrame, list[str], pd.DataFrame, pd.DataFrame]:
    """
    Generate a ledger and run every test (the IDEA side in memory). Returns the ledger, its amount
    columns, every line consolidated (``min_flags=0``) and the flagged vouchers (``to_vouchers``).
    """
    ledger = synthetic.make_ledger(n_rows, seed=seed, anomaly_rate=anomaly_rate, **ledger_kwargs)
    amt = synthetic.amount_columns(ledger)
    lines = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt),
                              min_flags=0)
    return ledger, amt, lines, scoring.to_vouchers(lines, amt)


def rankings(scored: pd.DataFrame, lines: pd.DataFrame, ledger: pd.DataFrame, amount_cols: Sequence[str],
             id_col: str = "Sr No", seed: int = 0, ml: bool = False) -> dict[str, list]:
    """
    Voucher numbers in ranked order for the risk score and the baselines.

    - **Risk score**: ``score_flags`` on the flagged vouchers (``top_n=None``).
    - **Number of tests hit**: most tests first, ties broken by voucher amount (a common manual approach).
    - **Amount only**: the largest vouchers in the whole ledger.
    - **Random flagged vouchers**: the flagged vouchers in a random order.
    - **Per-line score, listed by voucher**: lines scored on their own, each voucher listed where its
      first line appears. Shows whether scoring per voucher beats ranking lines.
    - **Isolation Forest** (``ml=True``, needs scikit-learn): fitted on the lines of the whole
      ledger, each voucher listed where its most anomalous line appears.
    """
    key = scored.attrs["voucher_col"]
    voucher_of = dict(zip(ledger[id_col], ledger[key]))

    def first_seen(line_ids) -> list:
        return list(dict.fromkeys(voucher_of[i] for i in line_ids))

    flagged_lines = lines[lines["N Flags"] > 0]
    by_tests = scored.sort_values(["N Flags", "Voucher Amount"], ascending=False, kind="stable")
    by_amount = scoring.voucher_amounts(ledger, amount_cols, key).sort_values(ascending=False, kind="stable")
    out = {
        "Risk score": scored[key].tolist(),
        "Number of tests hit": by_tests[key].tolist(),
        "Amount only": by_amount.index.tolist(),
        "Random flagged vouchers": list(np.random.default_rng(seed).permutation(scored[key].to_numpy())),
        "Per-line score, listed by voucher": first_seen(scoring.score_flags(flagged_lines, amount_cols, top_n=None)[id_col]),
    }
    if ml:
        from .ml_baseline import isolation_forest_ranking
        out["Isolation Forest"] = first_seen(isolation_forest_ranking(ledger, amount_cols, seed=seed))
    return out


def ceilings(scored: pd.DataFrame, truth: set, k: int) -> tuple[float, float]:
    """
    The best any ranking of the flagged vouchers can do: (precision@k, recall@k).

    Recall can't exceed the share of anomalous vouchers with a flagged line; precision can't exceed
    that number divided by k.
    """
    reachable = len(truth & set(scored[scored.attrs["voucher_col"]]))
    return min(reachable, k) / k, reachable / len(truth) if truth else 0.0


def truth_of(ledger: pd.DataFrame, key: str, truth_col: str = "Anomaly") -> set:
    """The vouchers with an injected anomaly on any line."""
    return set(ledger.loc[ledger[truth_col] != "", key])


def compare_rankings(scored: pd.DataFrame, lines: pd.DataFrame, ledger: pd.DataFrame, amount_cols: Sequence[str],
                     k: int, truth_col: str = "Anomaly", seed: int = 0, ml: bool = False) -> pd.DataFrame:
    """Precision and recall at ``k`` for each ranking, with the ceiling as the last row."""
    truth = truth_of(ledger, scored.attrs["voucher_col"], truth_col)
    rows = {name: precision_recall_at_k(ids, truth, k)
            for name, ids in rankings(scored, lines, ledger, amount_cols, seed=seed, ml=ml).items()}
    rows["Ceiling (flagged vouchers)"] = ceilings(scored, truth, k)
    table = pd.DataFrame(rows, index=[f"Precision@{k}", f"Recall@{k}"]).T.round(3)
    table.attrs.update(k=k, anomalies=len(truth), flagged_vouchers=len(scored))
    return table


def run_once(n_rows: int, anomaly_rate: float, seed: int, ks: Iterable[int] | None = None,
             ablation: bool = False, ml: bool = False, **ledger_kwargs) -> pd.DataFrame:
    """
    Generate one ledger, run every test, score its vouchers and measure each ranking at each k.

    Returns a long table: ``n_rows``, ``anomaly_rate``, ``seed``, ``ranking``, ``k``, ``default_k``,
    ``precision``, ``recall`` and ``share_of_ceiling`` (precision ÷ the best possible precision at
    that k), all per voucher. ``ledger_kwargs`` go to ``synthetic.make_ledger`` (e.g. ``noise_scale``).
    """
    ledger, amt, lines, vouchers = prepare(n_rows, seed, anomaly_rate, **ledger_kwargs)
    key = vouchers.attrs["voucher_col"]
    truth = truth_of(ledger, key)
    default_k = scoring.priority_list_size(vouchers.attrs["n_rows"])
    ks = sorted(set(ks or []) | {default_k})

    scored = scoring.score_flags(vouchers, VOUCHER_AMOUNT, top_n=None)
    ranked = rankings(scored, lines, ledger, amt, seed=seed, ml=ml)
    if ablation:
        for name, switches in VARIANTS.items():
            ranked[name] = scoring.score_flags(vouchers, VOUCHER_AMOUNT, top_n=None, **switches)[key].tolist()

    rows = []
    for k in ks:
        best = ceilings(scored, truth, k)
        for name, ids in ranked.items():
            precision, recall = precision_recall_at_k(ids, truth, k)
            rows.append((name, k, precision, recall, precision / best[0] if best[0] else 0.0))
        rows.append(("Ceiling (flagged vouchers)", k, *best, 1.0))
    out = pd.DataFrame(rows, columns=["ranking", "k", "precision", "recall", "share_of_ceiling"])
    return out.assign(n_rows=n_rows, anomaly_rate=anomaly_rate, seed=seed, default_k=default_k)


def stress_settings(seed: int) -> dict[str, float]:
    """Generator settings drawn at random per seed, for the stress sweep (ranges: practical judgement)."""
    rng = np.random.default_rng(seed + 1_000)   # not the ledger's own seed
    return {"anomaly_rate": round(rng.uniform(0.003, 0.016), 4), "silent_share": round(rng.uniform(0.05, 0.25), 2),
            "manual_share": round(rng.uniform(0.05, 0.30), 2), "noise_scale": round(rng.uniform(0.5, 2.0), 2)}


def prior_sensitivity(n_rows: int, seed: int, draws: int = 20, spread: float = 0.5) -> pd.DataFrame:
    """
    Re-score one ledger with every prior multiplied by a random factor in [1 - spread, 1 + spread].

    One row per draw: ``precision`` at the default k, and ``overlap``, the share of the default
    priority list still on the list. Shows whether the ranking depends on the exact prior values.
    """
    ledger, _, _, vouchers = prepare(n_rows, seed)
    key = vouchers.attrs["voucher_col"]
    truth, k = truth_of(ledger, key), scoring.priority_list_size(vouchers.attrs["n_rows"])
    default = set(scoring.score_flags(vouchers, VOUCHER_AMOUNT, top_n=k)[key])
    rng, rows = np.random.default_rng(seed), []
    for draw in range(draws):
        priors = {name: v * rng.uniform(1 - spread, 1 + spread) for name, v in scoring.DEFAULT_PRIORS.items()}
        top = scoring.score_flags(vouchers, VOUCHER_AMOUNT, priors=priors, top_n=k)[key].tolist()
        rows.append((seed, draw, precision_recall_at_k(top, truth, k)[0], len(default & set(top)) / k))
    return pd.DataFrame(rows, columns=["seed", "draw", "precision", "overlap"])


def size_bias(n_rows: int, seed: int) -> pd.DataFrame:
    """
    One row per voucher: its number of lines, whether it is normal (no injected anomaly), flagged by
    any test, and on the default priority list. A voucher with more lines has more chances to be
    flagged by chance; this measures how much.
    """
    ledger, _, _, vouchers = prepare(n_rows, seed)
    key = vouchers.attrs["voucher_col"]
    groups = ledger.groupby(key)
    listed = scoring.score_flags(vouchers, VOUCHER_AMOUNT)[key]
    return pd.DataFrame({"lines": groups.size(), "normal": groups["Anomaly"].first() == "",
                         "flagged": groups.size().index.isin(vouchers[key]),
                         "listed": groups.size().index.isin(listed)}).assign(seed=seed)


def summarise(results: pd.DataFrame, default_k_only: bool = True) -> pd.DataFrame:
    """Mean and standard deviation of precision, recall and share of ceiling per ranking (over seeds)."""
    data = results[results["k"] == results["default_k"]] if default_k_only else results
    keys = ["n_rows", "anomaly_rate", "ranking"] + ([] if default_k_only else ["k"])
    metrics = [m for m in ("precision", "recall", "share_of_ceiling") if m in data.columns]
    table = data.groupby(keys, sort=False)[metrics].agg(["mean", "std"]).round(3)
    table.columns = [f"{m} {s}" for m, s in table.columns]
    return table.assign(seeds=data.groupby(keys, sort=False)["seed"].nunique()).reset_index()
