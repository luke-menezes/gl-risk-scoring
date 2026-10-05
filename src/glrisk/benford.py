"""Benford's Law first-digit test: expected vs actual, MAD conformity, and the entries behind the worst digits."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .rules import absolute_amount

# Mean absolute deviation cut-offs for the first-digit test (Nigrini, 2012)
MAD_CUTOFFS = ((0.006, "Close Conformity"), (0.012, "Acceptable Conformity"), (0.015, "Marginal Conformity"))
MIN_ENTRIES = 1_000   # below this the test says little


def first_digits(amounts: pd.Series) -> pd.Series:
    """First significant digit of each amount of 10 or more (smaller amounts are left out)."""
    a = amounts.abs()
    a = a[a >= 10]
    return (a // 10 ** np.floor(np.log10(a))).astype(int)


def first_digit_test(amounts: pd.Series) -> pd.DataFrame:
    """
    Compare first-digit frequencies with Benford's Law.

    Returns:
        One row per digit 1-9: ``Count``, ``Actual`` and ``Expected`` proportions,
        and ``Z`` (Nigrini's z-statistic with continuity correction). The MAD and
        its conformity label are in ``.attrs``.
    """
    digits = first_digits(amounts)
    n = len(digits)
    expected = np.log10(1 + 1 / np.arange(1, 10))
    counts = digits.value_counts().reindex(range(1, 10), fill_value=0).to_numpy()
    actual = counts / n if n else np.zeros(9)
    z = (np.abs(actual - expected) - 1 / (2 * n)) / np.sqrt(expected * (1 - expected) / n) if n else np.zeros(9)
    table = pd.DataFrame({"Digit": range(1, 10), "Count": counts, "Actual": actual, "Expected": expected,
                          "Z": np.round(np.clip(z, 0, None), 2)})
    mad = float(np.mean(np.abs(actual - expected))) if n else float("nan")
    table.attrs.update(n=n, mad=round(mad, 5), conformity=conformity(mad) if n >= MIN_ENTRIES else "Too few entries")
    return table


def conformity(mad: float) -> str:
    """Conformity label for a first-digit MAD."""
    return next((label for cutoff, label in MAD_CUTOFFS if mad <= cutoff), "Nonconformity")


def benford_entries(df: pd.DataFrame, amount_cols: Sequence[str], top: int = 3, z_min: float = 1.96) -> pd.DataFrame:
    """
    Lines whose first digit is one of the ``top`` most over-represented digits.

    A digit qualifies when its actual share is above the expected one with z above ``z_min``
    (significant at 5%), so a conforming ledger may return no rows at all.

    These are the Benford "suspicious" rows that go into consolidation; the digit is added as
    ``Benford Digit``.
    """
    amount = absolute_amount(df, amount_cols)
    table = first_digit_test(amount[amount > 0])
    over = table[(table["Actual"] > table["Expected"]) & (table["Z"] > z_min)].nlargest(top, "Z")["Digit"].tolist()
    digit = pd.Series(np.nan, index=df.index)
    big = amount >= 10
    digit[big] = first_digits(amount[big])
    hits = df[digit.isin(over)].copy()
    hits["Benford Digit"] = digit[hits.index].astype(int)
    hits.attrs = dict(table.attrs, digits=over)
    return hits
