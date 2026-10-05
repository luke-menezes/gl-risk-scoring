"""
Rank consolidated flags into a priority list.

Score = (sum of test weights, with all date tests counted once) x amount multiplier

- Test weight = ledger rarity x prior. Rarity is -log10(share of the ledger the test flags), so a
  test that flags 0.1% of lines (rarity 3) counts three times as much as one that flags 10%
  (rarity 1). The prior says how useful the test has been across past ledgers.
- Date tests (weekend days, public holidays, ...) coincide for calendar reasons, so only the
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

# Illustrative priors, matched by keyword in the test name (case ignored). In practice they come
# from how often each test has produced the headline finding across past engagements; these values
# are placeholders that only keep the ordering sensible. Tests matching no keyword get 1.0.
DEFAULT_PRIORS = {
    "keyword": 2.5,
    "seldom": 2.5,
    "segregation": 2.5,
    "99": 1.5,
    "round": 1.5,
    "duplicate": 1.5,
    "benford": 0.5,
    "date": 0.5,  # the single combined date signal
}
DATE_KEYWORDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                 "weekend", "holiday", "quarter")


def priority_list_size(n_rows: int, floor: int = 20, ceiling: int = 150, k: float = 0.577) -> int:
    """
    Suggested priority list length: grows with the square root of ledger size, within [floor, ceiling].

    Small ledgers still get a useful list; very large ones stay reviewable. k = 0.577 puts a
    30,000-line ledger at 100 entries.
    """
    return int(max(floor, min(ceiling, round(k * np.sqrt(n_rows)))))


def test_weights(flagged: pd.DataFrame, priors: dict[str, float] | None = None,
                 date_tests: Sequence[str] | None = None, min_benford_factor: float = 0.2,
                 amount_cols: Sequence[str] | None = None) -> tuple[dict[str, float], list[str], float]:
    """
    Weight per test (rarity x prior, Benford scaled by amount diversity).

    Returns:
        ``(weights, date_tests, benford_factor)``.
    """
    tests = flagged.attrs["tests"]
    counts, n_rows = flagged.attrs["test_counts"], flagged.attrs["n_rows"]
    priors = {**DEFAULT_PRIORS, **(priors or {})}
    if date_tests is None:
        date_tests = [t for t in tests if any(k in t.lower() for k in DATE_KEYWORDS)]

    benford_factor = 1.0
    if amount_cols:
        amounts = absolute_amount(flagged, amount_cols)
        nonzero = amounts[amounts > 0]
        diversity = nonzero.round(2).nunique() / len(nonzero) if len(nonzero) else 1.0
        benford_factor = min(1.0, max(min_benford_factor, diversity / 0.5))

    weights = {}
    for test in tests:
        rarity = -np.log10(max(counts.get(test, 0), 1) / n_rows)
        if test in date_tests:
            prior = priors["date"]
        else:
            prior = next((v for k, v in priors.items() if k != "date" and k in test.lower()), 1.0)
        weight = rarity * prior * (benford_factor if "benford" in test.lower() else 1.0)
        weights[test] = round(float(weight), 3)
    return weights, list(date_tests), benford_factor


def score_flags(flagged: pd.DataFrame, amount_cols: Sequence[str], priors: dict[str, float] | None = None,
                top_n: int | str | None = "auto", date_tests: Sequence[str] | None = None) -> pd.DataFrame:
    """
    Score and rank the output of ``consolidate`` (any ``min_flags``).

    Args:
        flagged: Output of ``flags.consolidate``.
        amount_cols: ``["Debit", "Credit"]`` or ``["Amount"]``; the largest absolute value per row is used.
        priors: Overrides for ``DEFAULT_PRIORS`` (same keyword keys).
        top_n: ``"auto"`` uses ``priority_list_size``; an int gives that many; ``None`` keeps every row.
        date_tests: Test names to treat as date tests (default: detected by ``DATE_KEYWORDS``).

    Returns:
        Rows sorted by ``Score`` (highest first), with ``Amount Multiplier`` and ``Score`` added and
        the weights in ``.attrs["weights"]``.
    """
    if "tests" not in flagged.attrs:
        raise ValueError("flagged must be the output of consolidate()")
    weights, date_tests, factor = test_weights(flagged, priors, date_tests, amount_cols=amount_cols)
    other = [t for t in flagged.attrs["tests"] if t not in date_tests]

    base = sum((flagged[t] * weights[t] for t in other), start=pd.Series(0.0, index=flagged.index))
    if date_tests:
        base = base + pd.DataFrame({t: flagged[t] * weights[t] for t in date_tests}).max(axis=1)

    amounts = absolute_amount(flagged, amount_cols)
    nonzero = amounts[amounts > 0]
    median = nonzero.median() if len(nonzero) else 1.0
    out = flagged.copy()
    out["Amount Multiplier"] = (1 + np.log10(1 + amounts / median)).round(3)
    out["Score"] = (base * out["Amount Multiplier"]).round(3)
    out = out.sort_values(["Score", "N Flags"], ascending=False, kind="stable")
    if top_n == "auto":
        top_n = priority_list_size(flagged.attrs["n_rows"])
    if top_n is not None:
        out = out.head(int(top_n))
    out.attrs = {**flagged.attrs, "weights": weights, "date_tests": date_tests, "benford_factor": factor}
    return out
