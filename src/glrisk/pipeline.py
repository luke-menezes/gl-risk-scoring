"""
The two halves of the pipeline: the Python tests, and a stand-in for the IDEA side.

In practice the IDEA macro (``idea/portfolio_sample.ism``) runs Benford, the seldom account summary
and segregation of duties, and its Excel exports are read back with ``flags.load_idea_flags``.
``write_idea_exports`` produces the same kind of files from the synthetic ledger, so the whole
pipeline runs without an IDEA licence.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from . import benford, flags, rules
from .flags import FlagLog, log_flags


def run_python_tests(ledger: pd.DataFrame, amount_cols: Sequence[str], date_col: str = "Date",
                     text_cols: Sequence[str] = ("Description",), id_col: str = "Sr No",
                     weekend_days: Sequence[str] = rules.WEEKEND_DAYS, source_col: str = "Source",
                     manual_only: bool = True, fy_end_month: int = 12, holiday_country: str = "AE",
                     keywords: Sequence[str] = rules.DEFAULT_KEYWORDS,
                     generic_words: Sequence[str] = rules.GENERIC_WORDS, round_multiple: float = 10_000) -> FlagLog:
    """
    Run the Python tests and return ``{test name: flagged IDs}``.

    When the ledger has ``source_col``, the manual-entry test runs, and with ``manual_only`` (the
    default) the weekend, public holiday and round-amount tests count manual lines only: system
    postings on a Saturday are routine. Without the column the manual-entry test doesn't run (see
    ``tests_not_run``) and those three tests use every line. Without the text columns, the keyword
    and narration tests don't run either.
    """
    manual = rules.manual_entries(ledger, source_col) if source_col in ledger.columns else None
    scope = manual if manual is not None and manual_only else ledger
    text = [c for c in text_cols if c in ledger.columns]
    results = {
        **({"Keyword Match": rules.keywords(ledger, text, keywords)} if text else {}),
        "Rounded Amount": rules.rounded_amounts(scope, amount_cols, round_multiple),
        "Ending 99/999": rules.ending_99(ledger, amount_cols),
        **({"No or Vague Narration": rules.narration(ledger, text_cols[0], generic_words)} if text_cols[0] in text else {}),
        "Period End": rules.period_end(ledger, date_col, amount_cols, fy_end_month, weekend_days=weekend_days),
        "Public Holiday": rules.public_holidays(scope, date_col, amount_cols, holiday_country),
        **{day: rules.day_of_week(scope, date_col, amount_cols, day) for day in weekend_days},
        **({"Manual Entry": manual} if manual is not None else {}),
    }
    flag_log: FlagLog = {}
    for name, result in results.items():
        log_flags(flag_log, name, result, id_col)
    return flag_log


def tests_not_run(ledger: pd.DataFrame, source_col: str = "Source", creator_col: str = "Created By",
                  approver_col: str = "Approved By", text_cols: Sequence[str] = ("Description",),
                  amount_cols: Sequence[str] = (), date_col: str = "Date",
                  duplicate_key: Sequence[str] = ("Date", "Account", "Description")) -> list[str]:
    """
    A statement for each test the ledger lacks a column for, e.g. "Manual entries not tested: no
    Source column.", each test run on fewer columns than usual, and the lines a test can't read.
    Saying so matters: silence would read as "tested, nothing found".
    """
    needs = {"Manual entries": [source_col], "Created and approved by the same user": [creator_col, approver_col],
             "No or vague narration": [text_cols[0]]}
    out = [f"{test} not tested: no {' or '.join(missing)} column."
           for test, cols in needs.items() if (missing := [c for c in cols if c not in ledger.columns])]
    if not any(c in ledger.columns for c in text_cols):   # the keyword test needs any one of them
        out.append(f"Keyword match not tested: no {' or '.join(text_cols)} column.")
    if missing := [c for c in duplicate_key if c not in ledger.columns]:
        out.append(f"Duplicate test limited: no {' or '.join(missing)} column, so lines are matched without it.")
    if date_col in ledger and (n := int(pd.to_datetime(ledger[date_col], errors="coerce").isna().sum())):
        out.append(f"Lines with a missing or unreadable date, not covered by the date tests: {n:,}.")
    raw = ledger[list(amount_cols)].replace(r"^\s*$", None, regex=True)   # blank amounts are zero, not unreadable
    if n := int((raw.notna() & raw.apply(pd.to_numeric, errors="coerce").isna()).any(axis=1).sum()):
        out.append(f"Lines with an unreadable amount, treated as zero and skipped by the amount and date tests: {n:,}.")
    return out


def _idea_names(df: pd.DataFrame) -> pd.DataFrame:
    """IDEA upper-cases field names and replaces spaces with underscores on import."""
    return df.rename(columns=lambda c: str(c).upper().replace(" ", "_").replace("/", "_"))


def idea_side_results(ledger: pd.DataFrame, amount_cols: Sequence[str], account_col: str = "Account",
                      creator_col: str = "Created By", approver_col: str = "Approved By",
                      key_cols: Sequence[str] | None = None) -> dict[str, pd.DataFrame]:
    """
    The IDEA macro's outputs, computed in Python: ``Benford Starting <d>`` (each significantly
    over-represented first digit, at most three), ``Account Summary``, ``Seldom Account Entries``,
    ``Duplicate`` and ``Same User Created and Approved`` (left out without a creator and an
    approver column). The ground-truth column is dropped first.
    """
    data = ledger.drop(columns=["Anomaly"], errors="ignore")
    key_cols = [c for c in key_cols or ["Date", account_col, "Description", *amount_cols] if c in data.columns]
    outputs: dict[str, pd.DataFrame] = {}
    hits = benford.benford_entries(data, amount_cols)
    for digit in hits.attrs["digits"]:
        outputs[f"Benford Starting {digit}"] = hits[hits["Benford Digit"] == digit].drop(columns="Benford Digit")
    amount = rules.absolute_amount(data, amount_cols)
    outputs["Account Summary"] = (data.assign(ABS_AMOUNT=amount).groupby(account_col)
                                  .agg(NO_OF_RECS=(account_col, "size"), ABS_AMOUNT_SUM=("ABS_AMOUNT", "sum"))
                                  .reset_index())
    outputs["Seldom Account Entries"] = rules.seldom_accounts(data, account_col)
    outputs["Duplicate"] = rules.duplicates(data, key_cols)
    if {creator_col, approver_col} <= set(data.columns):
        outputs["Same User Created and Approved"] = rules.segregation_of_duties(data, creator_col, approver_col)
    return outputs


def idea_side_flags(ledger: pd.DataFrame, amount_cols: Sequence[str], id_col: str = "Sr No") -> FlagLog:
    """
    The IDEA-side flags without the Excel round trip, named as ``flags.load_idea_flags`` would name
    them (all Benford outputs as one "Benford" test; summaries without row IDs left out).
    """
    flag_log: FlagLog = {}
    for name, frame in idea_side_results(ledger, amount_cols).items():
        if id_col not in frame.columns:
            continue
        test = "Benford" if name.startswith("Benford") else name
        flag_log[test] = flag_log.get(test, set()) | flags.id_set(frame[id_col])
    return flag_log


def write_idea_exports(ledger: pd.DataFrame, folder: str | Path, amount_cols: Sequence[str],
                       account_col: str = "Account", creator_col: str = "Created By",
                       approver_col: str = "Approved By", key_cols: Sequence[str] | None = None) -> list[Path]:
    """
    Write ``idea_side_results`` as IDEA-style Excel exports (mock fixtures, not real IDEA output).

    Field names are upper-cased as IDEA imports them, and amounts rounded to 2 decimals.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, frame in idea_side_results(ledger, amount_cols, account_col, creator_col, approver_col,
                                         key_cols).items():
        path = folder / f"{name}.xlsx"
        numeric = frame.select_dtypes("float").columns
        # openpyxl stores floats to 17 significant digits, so 71470.54 appears as 71470.53999999999 in
        # the file's XML; Excel reads it back as 71470.54
        _idea_names(frame.assign(**{c: frame[c].round(2) for c in numeric})).to_excel(path, index=False)
        paths.append(path)
    return paths
