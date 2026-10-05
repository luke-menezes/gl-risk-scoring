"""Synthetic general ledger with deliberately injected anomalies (the ground truth for evaluation)."""

from __future__ import annotations

import numpy as np
import pandas as pd

ACCOUNTS = {
    "Cash at Bank": 0.22, "Accounts Receivable": 0.16, "Accounts Payable": 0.16, "Revenue": 0.12,
    "Cost of Sales": 0.10, "Payroll Expense": 0.08, "Rent Expense": 0.04, "Utilities": 0.04,
    "Travel Expense": 0.03, "Office Supplies": 0.03, "VAT Payable": 0.02,
}
DESCRIPTIONS = [
    "Customer receipt", "Supplier payment", "Monthly payroll", "Sales invoice", "Purchase invoice",
    "Bank charges", "Accrual", "Prepayment release", "Utility bill", "Staff travel claim",
    "Director fees",  # a normal entry that contains a keyword: a realistic false positive
]
USERS = ["user_a", "user_b", "user_c", "user_d", "user_e"]
APPROVERS = ["manager_1", "manager_2"]
# Description text used by injected anomalies (the keyword test should find these)
ANOMALY_DESCRIPTIONS = ["Adjustment per director", "Write off - settlement", "Cash advance, no invoice",
                        "Correction entry - reversal", "Consultancy fee (related party)"]
ANOMALY_SIGNALS = ("round_amount", "ending_99", "weekend", "keyword", "seldom_account", "self_approved")


def make_ledger(
    n_rows: int = 20_000,
    layout: str = "debit_credit",
    seed: int = 0,
    start: str = "2025-01-01",
    end: str = "2025-12-31",
    anomaly_rate: float = 0.005,
    noise: bool = True,
) -> pd.DataFrame:
    """
    Build a synthetic ledger, one row per journal line.

    Normal lines have log-normal amounts with cents, mostly weekday dates and
    a realistic amount of "noise": a few weekend postings, round amounts,
    duplicates and keyword hits that are not anomalies. Injected anomalies
    (about ``anomaly_rate`` of the rows) each carry one to four red flags
    and a larger amount, and are marked in the ``Anomaly`` column, which the
    tests and the scoring never read.

    Args:
        n_rows: Number of ledger lines before duplicates are added.
        layout: ``"debit_credit"`` (Debit and Credit columns) or ``"signed"``
            (one Amount column, credits negative).
        seed: Random seed, so every run gives the same ledger.
        start, end: Date range of the postings.
        anomaly_rate: Share of rows turned into injected anomalies.
        noise: Add the background false positives described above.

    Returns:
        The ledger with ``Sr No`` (the row ID), ``Date``, ``Account``,
        ``Description``, ``Created By``, ``Approved By``, the amount column(s)
        and ``Anomaly`` (the injected signals, e.g. ``"round_amount+weekend"``,
        or ``""``).
    """
    if layout not in ("debit_credit", "signed"):
        raise ValueError("layout must be 'debit_credit' or 'signed'")
    rng = np.random.default_rng(seed)

    # Dates: weekdays mostly, weekends rare (about 1.5% of lines with noise on)
    days = pd.date_range(start, end, freq="D")
    weights = np.where(days.dayofweek < 5, 1.0, 0.04 if noise else 0.0)
    dates = rng.choice(days, size=n_rows, p=weights / weights.sum())

    amounts = np.round(rng.lognormal(mean=7.5, sigma=1.3, size=n_rows), 2)
    is_debit = rng.random(n_rows) < 0.5
    df = pd.DataFrame({
        "Date": pd.to_datetime(dates),
        "Account": rng.choice(list(ACCOUNTS), size=n_rows, p=np.array(list(ACCOUNTS.values())) / sum(ACCOUNTS.values())),
        "Description": rng.choice(DESCRIPTIONS, size=n_rows, p=[0.096] * 10 + [0.04] if noise else None),
        "Created By": rng.choice(USERS, size=n_rows),
        "Approved By": rng.choice(APPROVERS, size=n_rows),
        "_amount": amounts,
        "_debit": is_debit,
        "Anomaly": "",
    })
    if noise:
        # Round amounts in normal business (e.g. rent, fixed fees)
        idx = rng.choice(n_rows, size=n_rows // 100, replace=False)
        df.loc[idx, "_amount"] = rng.choice([10_000, 20_000, 50_000], size=len(idx))
        # A supplier on fixed prices (4,000-4,999): ordinary business that pushes the first digit 4
        # above Benford's expectation, so the Benford test has something to flag
        idx = rng.choice(np.setdiff1d(np.arange(n_rows), idx), size=n_rows // 40, replace=False)
        df.loc[idx, "_amount"] = np.round(rng.uniform(4_000, 5_000, size=len(idx)), 2)
        df.loc[idx, "Description"] = "Supplier payment"

    # Injected anomalies: 1-4 signals each, and a larger than usual amount
    n_anomalies = max(1, int(n_rows * anomaly_rate))
    rows = rng.choice(n_rows, size=n_anomalies, replace=False)
    weekends = days[days.dayofweek >= 5]
    for i, row in enumerate(rows):
        signals = list(rng.choice(ANOMALY_SIGNALS, size=rng.integers(1, 5), replace=False))
        if "round_amount" in signals and "ending_99" in signals:
            signals.remove("ending_99")
        base = float(rng.choice([5, 10, 25])) * float(np.exp(7.5))
        amount = round(base * rng.uniform(1, 4), 2)
        if "round_amount" in signals:
            amount = float(round(amount, -4) or 10_000)
        if "ending_99" in signals:
            amount = float(int(amount) // 1000 * 1000 + 999)
        df.loc[row, "_amount"] = amount
        if "weekend" in signals:
            df.loc[row, "Date"] = rng.choice(weekends)
        if "keyword" in signals:
            df.loc[row, "Description"] = rng.choice(ANOMALY_DESCRIPTIONS)
        if "seldom_account" in signals:
            df.loc[row, "Account"] = f"Suspense Account {i // 2 + 1}"   # at most two entries per account
        if "self_approved" in signals:
            df.loc[row, "Approved By"] = df.loc[row, "Created By"]
        df.loc[row, "Anomaly"] = "+".join(sorted(signals))

    if noise:
        # Exact duplicates of normal lines (double postings that are not injected anomalies)
        normal = df.index[df["Anomaly"] == ""]
        dupes = df.loc[rng.choice(normal, size=max(1, n_rows // 400), replace=False)]
        df = pd.concat([df, dupes], ignore_index=True)

    if layout == "debit_credit":
        df["Debit"] = np.where(df["_debit"], df["_amount"], 0.0)
        df["Credit"] = np.where(df["_debit"], 0.0, df["_amount"])
    else:
        df["Amount"] = np.where(df["_debit"], df["_amount"], -df["_amount"])
    df = df.drop(columns=["_amount", "_debit"]).sort_values("Date", kind="stable", ignore_index=True)
    # The row ID is tagged once, before the ledger is split between IDEA and Python
    df.insert(0, "Sr No", np.arange(1, len(df) + 1))
    amount_cols = ["Debit", "Credit"] if layout == "debit_credit" else ["Amount"]
    return df[["Sr No", "Date", "Account", "Description", "Created By", "Approved By", *amount_cols, "Anomaly"]]


def amount_columns(df: pd.DataFrame) -> list[str]:
    """The ledger's amount column(s): ``["Debit", "Credit"]`` or ``["Amount"]``."""
    return ["Debit", "Credit"] if "Debit" in df.columns else ["Amount"]
