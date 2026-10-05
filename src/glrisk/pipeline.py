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

from . import benford, rules
from .flags import FlagLog, log_flags


def run_python_tests(ledger: pd.DataFrame, amount_cols: Sequence[str], date_col: str = "Date",
                     text_cols: Sequence[str] = ("Description",), id_col: str = "Sr No",
                     weekend_days: Sequence[str] = rules.WEEKEND_DAYS) -> FlagLog:
    """Run the Python tests and return ``{test name: flagged IDs}``."""
    results = {
        "Suspicious Keyword": rules.keywords(ledger, text_cols),
        "Rounded Amount": rules.rounded_amounts(ledger, amount_cols),
        "Ending 99/999": rules.ending_99(ledger, amount_cols),
        "Public Holiday": rules.public_holidays(ledger, date_col, amount_cols),
        **{day: rules.day_of_week(ledger, date_col, amount_cols, day) for day in weekend_days},
    }
    flag_log: FlagLog = {}
    for name, result in results.items():
        log_flags(flag_log, name, result, id_col)
    return flag_log


def _idea_names(df: pd.DataFrame) -> pd.DataFrame:
    """IDEA upper-cases field names and replaces spaces with underscores on import."""
    return df.rename(columns=lambda c: str(c).upper().replace(" ", "_").replace("/", "_"))


def write_idea_exports(ledger: pd.DataFrame, folder: str | Path, amount_cols: Sequence[str],
                       account_col: str = "Account", creator_col: str = "Created By",
                       approver_col: str = "Approved By", key_cols: Sequence[str] | None = None) -> list[Path]:
    """
    Write IDEA-style Excel exports for the synthetic ledger (mock fixtures, not real IDEA output).

    Files: ``Benford Starting <d>`` for the three most over-represented first digits, ``Account
    Summary`` (no row IDs, so the loader skips it), ``Seldom Account Entries``, ``Duplicate`` and
    ``SoD Violation Entries``. The ground-truth column is dropped first.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    data = ledger.drop(columns=["Anomaly"], errors="ignore")
    key_cols = list(key_cols or ["Date", account_col, "Description", *amount_cols])
    outputs: dict[str, pd.DataFrame] = {}

    hits = benford.benford_entries(data, amount_cols)
    for digit in hits.attrs["digits"]:
        outputs[f"Benford Starting {digit}"] = hits[hits["Benford Digit"] == digit].drop(columns="Benford Digit")
    amount = rules.absolute_amount(data, amount_cols)
    outputs["Account Summary"] = (data.assign(ABS_AMOUNT=amount).groupby(account_col)
                                  .agg(NO_OF_RECS=("Sr No", "size"), ABS_AMOUNT_SUM=("ABS_AMOUNT", "sum"))
                                  .reset_index())
    outputs["Seldom Account Entries"] = rules.seldom_accounts(data, account_col)
    outputs["Duplicate"] = rules.duplicates(data, key_cols)
    outputs["SoD Violation Entries"] = rules.segregation_of_duties(data, creator_col, approver_col)

    paths = []
    for name, frame in outputs.items():
        path = folder / f"{name}.xlsx"
        _idea_names(frame).to_excel(path, index=False)
        paths.append(path)
    return paths
