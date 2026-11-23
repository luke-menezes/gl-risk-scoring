"""
Population check: does the ledger roll the trial balance forward, account by account?

Any journal entry test is only as good as its population. Before ranking, the audit team needs
evidence that the ledger is complete for the period (ISA 500 para 9; ISA 240 (Revised) para 49(b)).
A difference means lines may be missing or extra: it is resolved before testing, not explained away.
Top-side adjustments made after the trial balance, directly in the financial statements, never pass
through the ledger, so this check can't show them.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def _read_amounts(data: pd.DataFrame, columns: Sequence[str], source: str) -> pd.DataFrame:
    raw = data[list(columns)].replace(r"^\s+$", "", regex=True)
    amounts = raw.apply(pd.to_numeric, errors="coerce")
    populated = raw.notna() & raw.ne("")
    invalid = populated & (amounts.isna() | amounts.isin([float("inf"), float("-inf")]))
    counts = invalid.sum()
    if counts.any():
        details = ", ".join(f"{column}: {count:,}" for column, count in counts.items() if count)
        raise ValueError(f"{source} contains unreadable or non-finite amounts ({details}).")
    return amounts.fillna(0.0)


def movements(ledger: pd.DataFrame, amount_cols: Sequence[str], account_col: str = "Account") -> pd.Series:
    """Net movement per account: debits minus credits (``["Debit", "Credit"]``), or the signed amount."""
    amounts = _read_amounts(ledger, amount_cols, "Ledger")
    net = amounts.iloc[:, 0] - amounts.iloc[:, 1] if len(amount_cols) == 2 else amounts.iloc[:, 0]
    return net.groupby(ledger[account_col]).sum()


def roll_forward(ledger: pd.DataFrame, trial_balance: pd.DataFrame, amount_cols: Sequence[str],
                 account_col: str = "Account", opening_col: str = "Opening", closing_col: str = "Closing",
                 decimals: int = 2) -> pd.DataFrame:
    """
    Per account, opening balance + ledger movements - closing balance.

    Everything is rounded to ``decimals`` (the amounts' own precision) before comparing, so there is
    no tolerance beyond that and no comparison of unrounded floats. Accounts in only one of the
    ledger and the trial balance are kept, with the missing side as zero. Blank amount cells are
    zero. Nonblank unreadable or non-finite amounts raise ValueError before reconciliation.

    Returns:
        One row per account with ``Opening``, ``Movement``, ``Closing`` and ``Difference`` (absolute),
        accounts with a difference first. ``.attrs["total_difference"]`` is the sum of the absolute
        differences, so differences on two accounts can't net off.
    """
    tb = _read_amounts(trial_balance.set_index(account_col), [opening_col, closing_col], "Trial balance")
    out = tb.join(movements(ledger, amount_cols, account_col).rename("Movement"), how="outer").fillna(0.0)
    out = out.round(decimals)
    out["Difference"] = (out[opening_col] + out["Movement"] - out[closing_col]).round(decimals).abs()
    out = out[[opening_col, "Movement", closing_col, "Difference"]].reset_index()
    out = out.sort_values("Difference", ascending=False, kind="stable", ignore_index=True)
    out.attrs["total_difference"] = round(float(out["Difference"].sum()), decimals)
    return out
