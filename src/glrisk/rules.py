"""
Simple journal tests. Each takes the ledger and returns the rows it flags, with every column kept,
so the row ID survives for consolidation.

Zero-value lines are skipped by the amount and date tests: they carry no value at risk.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

import holidays
import numpy as np
import pandas as pd

# Illustrative keyword list: generic red-flag words. Tune per client (some words are normal for some
# businesses, e.g. "settlement" for a law firm).
DEFAULT_KEYWORDS = ("adjust", "write off", "reversal", "correction", "director", "related party",
                    "cash advance", "settlement", "no invoice", "suspense")
WEEKEND_DAYS = ("Saturday", "Sunday")   # the UAE weekend since 2022


def absolute_amount(df: pd.DataFrame, amount_cols: Sequence[str]) -> pd.Series:
    """Largest absolute value across the amount columns, per row (0 where blank)."""
    return df[list(amount_cols)].apply(pd.to_numeric, errors="coerce").abs().max(axis=1).fillna(0)


def rounded_amounts(df: pd.DataFrame, amount_cols: Sequence[str], multiple: float = 10_000) -> pd.DataFrame:
    """Lines whose amount is a non-zero multiple of ``multiple`` (10,000 = four trailing zeros)."""
    amount = absolute_amount(df, amount_cols)
    return df[(amount > 0) & (np.isclose(amount % multiple, 0))]


def ending_99(df: pd.DataFrame, amount_cols: Sequence[str]) -> pd.DataFrame:
    """Lines with a whole amount ending in 99 or 999 (just under a round threshold)."""
    amount = absolute_amount(df, amount_cols)
    whole = np.isclose(amount, amount.round()) & (amount >= 99)
    ends = amount.round().astype("int64").astype(str).str.endswith("99")
    return df[whole & ends]


def day_of_week(df: pd.DataFrame, date_col: str, amount_cols: Sequence[str], day: str) -> pd.DataFrame:
    """Non-zero lines posted on one day of the week, e.g. ``"Saturday"``."""
    if day.capitalize() not in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        raise ValueError(f"Not a day of the week: {day!r}")
    dates = pd.to_datetime(df[date_col], errors="coerce")
    return df[(dates.dt.day_name() == day.capitalize()) & (absolute_amount(df, amount_cols) > 0)]


def public_holidays(df: pd.DataFrame, date_col: str, amount_cols: Sequence[str],
                    country: str = "AE") -> pd.DataFrame:
    """Non-zero lines posted on a public holiday (``holidays`` package), with the holiday's name."""
    dates = pd.to_datetime(df[date_col], errors="coerce")
    years = sorted(dates.dt.year.dropna().astype(int).unique())
    calendar = holidays.country_holidays(country, years=years)
    names = dates.dt.date.map(calendar.get)
    hits = df[names.notna() & (absolute_amount(df, amount_cols) > 0)].copy()
    hits["Holiday"] = names[hits.index]
    return hits


def keywords(df: pd.DataFrame, text_cols: Sequence[str], words: Iterable[str] = DEFAULT_KEYWORDS) -> pd.DataFrame:
    """Lines whose text columns contain a keyword (whole words, case ignored), with the words found."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)
    text = df[list(text_cols)].fillna("").astype(str).agg(" ".join, axis=1)
    found = text.map(lambda t: ", ".join(sorted({m.lower() for m in pattern.findall(t)})))
    hits = df[found != ""].copy()
    hits["Matched Keywords"] = found[hits.index]
    return hits


def duplicates(df: pd.DataFrame, key_cols: Sequence[str]) -> pd.DataFrame:
    """Lines that repeat on every key column (all copies are returned, not just the extras)."""
    return df[df.duplicated(list(key_cols), keep=False)]


def seldom_accounts(df: pd.DataFrame, account_col: str, max_entries: int = 3) -> pd.DataFrame:
    """Lines posted to accounts used ``max_entries`` times or fewer in the ledger."""
    counts = df[account_col].map(df[account_col].value_counts())
    return df[counts <= max_entries]


def segregation_of_duties(df: pd.DataFrame, creator_col: str, approver_col: str) -> pd.DataFrame:
    """Lines created and approved by the same user (IDs compared trimmed and upper-cased)."""
    def clean(s: pd.Series) -> pd.Series:
        return s.astype("string").str.strip().str.upper().replace("", pd.NA)
    creator, approver = clean(df[creator_col]), clean(df[approver_col])
    return df[(creator == approver).fillna(False).astype(bool)]
