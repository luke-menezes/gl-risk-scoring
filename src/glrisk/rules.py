"""
Simple journal tests. Each takes the ledger and returns the rows that have one characteristic, with
every column kept, so the row ID survives for consolidation. A flagged row is a fact about the entry
(posted on a Saturday, a round amount), not a conclusion about it.

Zero-value lines are skipped by the amount and date tests: they carry no value at risk. Every
threshold, window and word list here is practical judgement, and a parameter.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable, Sequence

import holidays
import pandas as pd

# Illustrative keyword list: generic words that often mark entries outside the normal process. Tune per
# client (some words are normal for some businesses, e.g. "settlement" for a law firm).
DEFAULT_KEYWORDS = ("adjust", "write off", "reversal", "correction", "director", "related party",
                    "cash advance", "settlement", "no invoice", "suspense")
WEEKEND_DAYS = ("Saturday", "Sunday")   # the UAE weekend since 2022
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Narrations that say nothing: placeholders counted as blank, and words that only say "this is a journal"
BLANK_NARRATIONS = ("", "na", "n/a", "nil", "none", "null", "nan", "-", ".")
# Numbers in this range are read as Excel serial dates (days since 1899-12-30): 1954 to 2119
EXCEL_SERIALS = (20_000, 80_000)
GENERIC_WORDS = ("adj", "adjustment", "adjusting", "jv", "je", "journal", "entry", "correction", "reclass",
                 "misc", "miscellaneous", "other", "general", "various", "sundry", "test", "tbd", "being")


def absolute_amount(df: pd.DataFrame, amount_cols: Sequence[str]) -> pd.Series:
    """Largest absolute value across the amount columns, per row (0 where blank)."""
    return df[list(amount_cols)].apply(pd.to_numeric, errors="coerce").abs().max(axis=1).fillna(0)


def parse_dates(values: pd.Series, dayfirst: bool = True) -> pd.Series:
    """
    Dates from a column that may mix formats; unreadable values become NaT.

    A date column is kept as it is, without its time zone. Numbers in ``EXCEL_SERIALS`` are Excel
    serial dates (a date cell that lost its format). Text has any time-zone offset dropped, keeping
    the local date and time as written, so no entry moves to another day. ISO dates (2025-03-08)
    are then read first: read day first, they would become 3 August. pandas guesses one format from
    the first remaining value and blanks the values in any other format, so those are tried again
    one by one. ``dayfirst`` reads 02/03/2025 as 2 March.
    """
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        return values.dt.tz_localize(None)
    if pd.api.types.is_datetime64_dtype(values):
        return values
    dates = pd.Series(pd.NaT, index=values.index, dtype="datetime64[us]")   # one unit for every pass
    numbers = pd.to_numeric(values, errors="coerce")
    serial = numbers.between(*EXCEL_SERIALS)
    dates[serial] = pd.to_datetime(numbers[serial], unit="D", origin="1899-12-30").astype("datetime64[us]")
    text = values.astype("string").str.replace(r"(\d:\d\d(?:\.\d+)?)\s*(?:Z|[+-]\d\d:?\d\d)$", r"\1", regex=True)
    for fmt in ("ISO8601", None, "mixed"):   # ISO, the format pandas infers, then value by value
        if (retry := dates.isna() & text.notna()).any():
            with warnings.catch_warnings():   # "could not infer format": the next pass handles it
                warnings.filterwarnings("ignore", "Could not infer format")
                parsed = pd.to_datetime(text[retry], errors="coerce", format=fmt, dayfirst=dayfirst)
                dates[retry] = parsed.astype("datetime64[us]")
    return dates


def rounded_amounts(df: pd.DataFrame, amount_cols: Sequence[str], multiple: float = 10_000) -> pd.DataFrame:
    """Lines whose amount is a non-zero multiple of ``multiple`` (10,000 = four trailing zeros)."""
    # Rounded to cents first, so float noise from imports (29,999.999999) can't change the result
    amount = absolute_amount(df, amount_cols).round(2)
    return df[(amount > 0) & (amount % multiple == 0)]


def ending_99(df: pd.DataFrame, amount_cols: Sequence[str]) -> pd.DataFrame:
    """Lines with a whole amount (no cents) ending in 99 or 999 (just under a round threshold)."""
    amount = absolute_amount(df, amount_cols).round(2)
    whole = (amount % 1 == 0) & (amount >= 99)
    ends = amount.astype("int64").astype(str).str.endswith("99")
    return df[whole & ends]


def day_of_week(df: pd.DataFrame, date_col: str, amount_cols: Sequence[str], day: str) -> pd.DataFrame:
    """Non-zero lines posted on one day of the week, e.g. ``"Saturday"``."""
    if day.capitalize() not in DAYS:
        raise ValueError(f"Not a day of the week: {day!r}")
    dates = parse_dates(df[date_col])
    return df[(dates.dt.day_name() == day.capitalize()) & (absolute_amount(df, amount_cols) > 0)]


def public_holidays(df: pd.DataFrame, date_col: str, amount_cols: Sequence[str],
                    country: str = "AE") -> pd.DataFrame:
    """Non-zero lines posted on a public holiday (``holidays`` package), with the holiday's name."""
    dates = parse_dates(df[date_col])
    years = sorted(dates.dt.year.dropna().astype(int).unique())
    calendar = holidays.country_holidays(country, years=years)
    names = dates.dt.date.map(calendar.get)
    hits = df[names.notna() & (absolute_amount(df, amount_cols) > 0)].copy()
    hits["Holiday"] = names[hits.index]
    return hits


def period_end_labels(dates: pd.Series, fy_end_month: int = 12, quarter_days: tuple[int, int] = (3, 2),
                      year_end_days: int = 5, weekend_days: Sequence[str] = WEEKEND_DAYS) -> pd.Series:
    """
    The period-end window each date falls in: "Quarter end", "Year end", "Opening cut-off" or "".

    Quarters are counted from the financial year-end (the last day of ``fy_end_month``), not assumed
    to be calendar quarters. A quarter end covers its last ``quarter_days[0]`` and the next quarter's
    first ``quarter_days[1]`` calendar days. The year-end window is wider, because that is where the
    closing entries are: ``year_end_days`` working days up to the year-end ("Year end") and after it
    ("Opening cut-off"), counted with the same ``weekend_days`` as the weekend test, so a weekend
    inside the window doesn't shorten it.
    """
    dates = parse_dates(dates).dt.normalize()
    workday = pd.offsets.CustomBusinessDay(weekmask=" ".join(d[:3] for d in DAYS if d not in weekend_days))
    labels: dict[pd.Timestamp, str] = {}
    years = dates.dt.year.dropna().astype(int)
    for year in range(years.min() - 1, years.max() + 2) if len(years) else ():
        year_end = pd.Timestamp(year, fy_end_month, 1) + pd.offsets.MonthEnd(0)
        for months in (3, 6, 9):
            quarter_end = year_end - pd.DateOffset(months=months) + pd.offsets.MonthEnd(0)
            for day in pd.date_range(quarter_end - pd.Timedelta(days=quarter_days[0] - 1),
                                     quarter_end + pd.Timedelta(days=quarter_days[1])):
                labels[day] = "Quarter end"
        first = pd.date_range(end=year_end, periods=year_end_days, freq=workday)[0]
        last = pd.date_range(start=year_end + pd.Timedelta(days=1), periods=year_end_days, freq=workday)[-1]
        labels.update({day: "Year end" for day in pd.date_range(first, year_end)})
        labels.update({day: "Opening cut-off" for day in pd.date_range(year_end + pd.Timedelta(days=1), last)})
    return dates.map(labels).fillna("")


def period_end(df: pd.DataFrame, date_col: str, amount_cols: Sequence[str], fy_end_month: int = 12,
               **windows) -> pd.DataFrame:
    """
    Non-zero lines posted in a period-end window, with the window in ``Period-End Window``.

    ``windows`` go to ``period_end_labels`` (quarter days, year-end working days, weekend days).
    """
    labels = period_end_labels(df[date_col], fy_end_month, **windows)
    hits = df[(labels != "") & (absolute_amount(df, amount_cols) > 0)].copy()
    hits["Period-End Window"] = labels[hits.index]
    return hits


def manual_entries(df: pd.DataFrame, source_col: str = "Source", manual_values: Iterable[str] = ("Manual",)
                   ) -> pd.DataFrame:
    """
    Lines whose source is one of ``manual_values`` (case ignored).

    "Manual" is a fact from the client's system, which the audit team confirms (which sources or
    voucher types are keyed in by users). It is never guessed from other columns: without a source
    column this test doesn't run.
    """
    manual = {v.strip().casefold() for v in manual_values}
    return df[df[source_col].astype(str).str.strip().str.casefold().isin(manual)]


def narration(df: pd.DataFrame, text_col: str, generic_words: Iterable[str] = GENERIC_WORDS,
              blank_values: Iterable[str] = BLANK_NARRATIONS, min_letters: int = 3,
              max_blank_share: float = 0.5) -> pd.DataFrame:
    """
    Lines with no or vague narration, with the reason in ``Narration Issue``: "Blank" (including
    placeholders such as "n/a" or "-"), "Numbers only", "Too short" (fewer than ``min_letters``
    letters) or "Generic words only" (every word in ``generic_words``).

    If more than ``max_blank_share`` of the lines are blank, the column isn't being used to explain
    entries: blank lines are then not flagged, and the share is reported in ``.attrs["blank_share"]``.
    To flag every blank line anyway, run the test on the manual lines with ``max_blank_share=1``.
    """
    text = df[text_col].fillna("").astype(str).str.strip()
    words = text.str.lower().str.findall(r"[a-z]+")
    generic = set(generic_words)
    issue = pd.Series("", index=df.index)
    issue[words.map(lambda w: bool(w) and set(w) <= generic)] = "Generic words only"
    issue[words.str.join("").str.len() < min_letters] = "Too short"
    issue[text.str.fullmatch(r"[\d\s.,/-]*\d[\d\s.,/-]*")] = "Numbers only"
    blank = text.str.lower().isin(set(blank_values))
    blank_share = float(blank.mean()) if len(df) else 0.0
    issue[blank] = "Blank" if blank_share <= max_blank_share else ""
    hits = df[issue != ""].copy()
    hits["Narration Issue"] = issue[hits.index]
    hits.attrs["blank_share"] = round(blank_share, 4)
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
    """
    Lines created and approved by the same user ID (compared trimmed and upper-cased).

    Whether that breaches segregation of duties depends on the users' roles and the approval
    workflow, which the audit team knows and the ledger doesn't.
    """
    def clean(s: pd.Series) -> pd.Series:
        return s.astype("string").str.strip().str.upper().replace("", pd.NA)
    creator, approver = clean(df[creator_col]), clean(df[approver_col])
    return df[(creator == approver).fillna(False).astype(bool)]
