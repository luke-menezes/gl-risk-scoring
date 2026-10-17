"""
Rank consolidated flags into a priority list.

Score = (sum of test weights, with all date tests counted once) x amount multiplier

Lines are scored per voucher (``to_vouchers``): a voucher meets a test if any of its lines does.

- Test weight = ledger rarity x prior. Rarity is -log10(share of the ledger the test flags), so a
  test that flags 0.1% of lines (rarity 3) counts three times as much as one that flags 10%
  (rarity 1). The prior says how useful the test has been across past ledgers.
- Date tests (weekend days, public holidays, period ends) coincide for calendar reasons, so only the
  strongest one counts for each line.
- Benford's weight is scaled by the ledger's amount diversity: in ledgers full of repeated small
  amounts, Benford failures are expected and carry little information.
- Amount multiplier = 1 + log10(1 + amount / median non-zero amount): large lines rise without a
  hard cut-off, and one rare test on a very large amount can still make the list.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .rules import absolute_amount
from .settings import RunSettings

# Illustrative priors, matched by keyword in the test name (case ignored). In practice they come
# from how often each test has produced the headline finding across past engagements; these values
# are placeholders that only keep the ordering sensible. Tests matching no keyword get 1.0.
DEFAULT_PRIORS = {
    "keyword": 2.5,
    "seldom": 2.5,
    "same user": 2.5,
    "99": 1.5,
    "round": 1.5,
    "duplicate": 1.5,
    "narration": 1.5,   # named in ISA 240, but system lines without text make it noisy
    "manual": 1.0,      # flags a large minority by design: mostly a filter and a tie-breaker
    # Period end is a date test, but ISA 240 requires selecting period-end entries (it doesn't for
    # weekends), so it outranks a weekend of similar rarity
    "period": 1.0,
    "benford": 0.5,
    "date": 0.5,  # the other date tests (weekend days, public holidays)
}
DATE_KEYWORDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                 "weekend", "holiday", "quarter", "period")


def voucher_amounts(lines: pd.DataFrame, amount_cols: Sequence[str], voucher_col: str) -> pd.Series:
    """
    Per voucher, the larger of its total debits and total credits: a balanced voucher's debits, and
    a single line's own amount whichever side it is on.
    """
    values = lines[list(amount_cols)].apply(pd.to_numeric, errors="coerce").fillna(0)
    signed = values.iloc[:, 0] - values.iloc[:, 1] if len(amount_cols) == 2 else values.iloc[:, 0]
    keys = lines[voucher_col]
    return pd.concat([signed.clip(lower=0).groupby(keys).sum(), (-signed).clip(lower=0).groupby(keys).sum()],
                     axis=1).max(axis=1)


def to_vouchers(lines: pd.DataFrame, amount_cols: Sequence[str], settings: RunSettings | None = None) -> pd.DataFrame:
    """
    One row per flagged voucher, to score with ``score_flags(vouchers, ["Voucher Amount"])``.

    ``lines`` is ``flags.consolidate(..., min_flags=0)``: every line is needed for the voucher amounts.
    A voucher meets a test if any of its lines does, so rarity becomes the share of vouchers flagged.
    The fields the lines share (date, narration, source, users, ``Anomaly``) come from the first
    line. Without the voucher column, each line is its own voucher and the ranking is the per-line one.
    """
    s = settings or RunSettings()
    if lines.attrs.get("n_rows") != len(lines):
        raise ValueError("pass flags.consolidate(..., min_flags=0): every line is needed for the voucher amounts")
    key = s.voucher_col if s.voucher_col in lines else s.id_col
    tests, groups = lines.attrs["tests"], lines.groupby(key, sort=False)
    shared = [c for c in (s.date_col, s.text_cols[0], s.source_col, s.creator_col, s.approver_col, "Anomaly")
              if c in lines and c != key]
    hits = groups[tests].any()
    out = groups[shared].first()
    out["Lines"], out["Flagged Lines"] = groups.size(), (lines["N Flags"] > 0).groupby(lines[key], sort=False).sum()
    out[tests] = hits
    out["N Flags"] = hits.sum(axis=1)
    out["Flagged By"] = [", ".join(t for t, hit in zip(tests, row) if hit) for row in hits.to_numpy()]
    out["Voucher Amount"] = voucher_amounts(lines, amount_cols, key)
    out = out[out["N Flags"] > 0].reset_index().sort_values("N Flags", ascending=False, kind="stable")
    out.attrs = {"tests": tests, "test_counts": hits.sum().astype(int).to_dict(), "n_rows": len(hits), "voucher_col": key}
    return out


def priority_list_size(n_rows: int, floor: int = 20, ceiling: int = 150, k: float = 0.577) -> int:
    """
    Suggested priority list length: grows with the square root of ledger size, within [floor, ceiling].

    Small ledgers still get a useful list; very large ones stay reviewable. k = 0.577 puts a
    30,000-line ledger at 100 entries.
    """
    return int(max(floor, min(ceiling, round(k * np.sqrt(n_rows)))))


def test_weights(flagged: pd.DataFrame, priors: dict[str, float] | None = None,
                 date_tests: Sequence[str] | None = None, min_benford_factor: float = 0.2,
                 amount_cols: Sequence[str] | None = None, use_rarity: bool = True, use_priors: bool = True,
                 benford_scaling: bool = True
                 ) -> tuple[dict[str, float], list[str], float, dict[str, float], dict[str, float]]:
    """
    Weight per test (rarity x prior, Benford scaled by amount diversity).

    The ``use_*`` and ``benford_scaling`` switches turn one idea off at a time, for the ablation study.

    Returns:
        ``(weights, date_tests, benford_factor, priors used per test, rarities used per test)``.
    """
    tests = flagged.attrs["tests"]
    counts, n_rows = flagged.attrs["test_counts"], flagged.attrs["n_rows"]
    priors = {**DEFAULT_PRIORS, **(priors or {})}
    if date_tests is None:
        date_tests = [t for t in tests if any(k in t.lower() for k in DATE_KEYWORDS)]

    benford_factor = 1.0
    if amount_cols and benford_scaling:
        amounts = absolute_amount(flagged, amount_cols)
        nonzero = amounts[amounts > 0]
        diversity = nonzero.round(2).nunique() / len(nonzero) if len(nonzero) else 1.0
        benford_factor = min(1.0, max(min_benford_factor, diversity / 0.5))

    weights, used, rarities = {}, {}, {}
    for test in tests:
        rarity = -np.log10(max(counts.get(test, 0), 1) / n_rows) if use_rarity else 1.0
        default = priors["date"] if test in date_tests else 1.0
        prior = next((v for k, v in priors.items() if k != "date" and k in test.lower()), default)
        used[test] = prior if use_priors else 1.0
        rarities[test] = round(float(rarity), 3)
        weight = rarity * used[test] * (benford_factor if "benford" in test.lower() else 1.0)
        weights[test] = round(float(weight), 3)
    return weights, list(date_tests), benford_factor, used, rarities


def score_flags(flagged: pd.DataFrame, amount_cols: Sequence[str], priors: dict[str, float] | None = None,
                top_n: int | str | None = "auto", date_tests: Sequence[str] | None = None,
                use_rarity: bool = True, use_priors: bool = True, collapse_dates: bool = True,
                amount_multiplier: bool = True, benford_scaling: bool = True,
                performance_materiality: float | None = None, clearly_trivial: float | None = None) -> pd.DataFrame:
    """
    Score and rank the output of ``consolidate`` (any ``min_flags``).

    Args:
        flagged: Output of ``flags.consolidate``.
        amount_cols: ``["Debit", "Credit"]`` or ``["Amount"]``; the largest absolute value per row is used.
        priors: Overrides for ``DEFAULT_PRIORS`` (same keyword keys).
        top_n: ``"auto"`` uses ``priority_list_size``; an int gives that many; ``None`` keeps every row.
        date_tests: Test names to treat as date tests (default: detected by ``DATE_KEYWORDS``).
        use_rarity, use_priors, collapse_dates, amount_multiplier, benford_scaling: Each ``False``
            turns one design choice off (ablation). Defaults: all on.
        performance_materiality: Optional, as set by the audit team (ISA 320). Lines above it are
            always listed, after the top ``top_n`` and in addition to them, and marked in
            ``Above Performance Materiality``. The score itself doesn't change.
        clearly_trivial: Optional (ISA 450). Recorded in ``.attrs`` for the working paper only:
            nothing below it is filtered out, because small or split entries can matter.

    Returns:
        Rows sorted by ``Score`` (highest first), then any lines above performance materiality
        outside the top ``top_n``, with ``Base Score``, ``Amount Multiplier``, ``Score`` and
        ``Score Breakdown`` added. The weights, priors and parameters are in ``.attrs``.
    """
    if "tests" not in flagged.attrs:
        raise ValueError("flagged must be the output of consolidate()")
    weights, date_tests, factor, used, rarities = test_weights(flagged, priors, date_tests, amount_cols=amount_cols,
                                                         use_rarity=use_rarity, use_priors=use_priors,
                                                         benford_scaling=benford_scaling)
    if not collapse_dates:
        date_tests = []
    other = [t for t in flagged.attrs["tests"] if t not in date_tests]

    parts = pd.DataFrame({t: flagged[t] * weights[t] for t in other}, index=flagged.index)
    if date_tests:
        dates = pd.DataFrame({t: flagged[t] * weights[t] for t in date_tests}, index=flagged.index)
        parts["date"] = dates.max(axis=1)
        strongest = dates.idxmax(axis=1).where(parts["date"] > 0, "")
    base = parts.sum(axis=1)

    amounts = absolute_amount(flagged, amount_cols)
    nonzero = amounts[amounts > 0]
    median = nonzero.median() if len(nonzero) else 1.0
    out = flagged.copy()
    out["Base Score"] = base.round(3)
    out["Amount Multiplier"] = (1 + np.log10(1 + amounts / median)).round(3) if amount_multiplier else 1.0
    out["Score"] = (base * out["Amount Multiplier"]).round(3)

    # "Seldom Account Entries 6.8 + date (Saturday) 1.0, × amount 2.10": why the line ranks where it does
    def explain(i):
        row = parts.loc[i]
        terms = [f"{'date (' + strongest[i] + ')' if t == 'date' else t} {row[t]:.1f}"
                 for t in row[row > 0].sort_values(ascending=False).index]   # largest first
        return " + ".join(terms) + f", × amount {out.at[i, 'Amount Multiplier']:.2f}"

    out = out.sort_values(["Score", "N Flags"], ascending=False, kind="stable")
    above = (amounts[out.index] > performance_materiality if performance_materiality is not None
             else pd.Series(False, index=out.index))
    if top_n == "auto":
        top_n = priority_list_size(flagged.attrs["n_rows"])
    if top_n is not None:
        out = out[(np.arange(len(out)) < int(top_n)) | above.to_numpy()]
    if performance_materiality is not None:
        out["Above Performance Materiality"] = above[out.index]
    out["Score Breakdown"] = [explain(i) for i in out.index]
    out.attrs = {**flagged.attrs, "weights": weights, "priors": used, "rarities": rarities, "date_tests": date_tests,
                 "benford_factor": factor, "median_amount": float(median), "n_scored": len(flagged),
                 "top_n": top_n, "above_pm_added": int(above.iloc[int(top_n):].sum()) if top_n is not None else 0,
                 "performance_materiality": performance_materiality, "clearly_trivial": clearly_trivial}
    return out
