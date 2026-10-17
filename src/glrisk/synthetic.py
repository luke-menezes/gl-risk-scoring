"""
Synthetic general ledger of balanced journals (vouchers) with deliberately injected anomalies (the ground truth for evaluation).

The injected anomalies exist only here: a real ledger has no such labels, and the tests never read
them. On a real ledger the tests find characteristics of entries, for the auditor to select from.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .population import movements
from .rules import period_end_labels

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
# Narrations that explain nothing: blank, placeholder, numbers only, too short, generic words only
VAGUE_DESCRIPTIONS = ["", "n/a", "-", "104522", "JV", "Adj", "Misc", "Journal entry", "Being adjustment"]
ANOMALY_SIGNALS = ("round_amount", "ending_99", "weekend", "keyword", "seldom_account", "self_approved",
                   "period_end", "manual", "vague_narration")
# Descriptions for silent anomalies: ordinary text that no keyword matches
SILENT_DESCRIPTIONS = [d for d in DESCRIPTIONS if d != "Director fees"]
# Voucher sizes (lines) and their shares: mostly two-line journals
VOUCHER_SIZES = (2, 3, 4)
VOUCHER_SIZE_SHARES = (0.55, 0.25, 0.20)
MEAN_VOUCHER_LINES = float(np.dot(VOUCHER_SIZES, VOUCHER_SIZE_SHARES))
COUNTER_ACCOUNTS = ["Cash at Bank", "Accounts Receivable", "Accounts Payable", "VAT Payable"]
# Income-statement accounts open the year at zero: last year's result moved to retained earnings
INCOME_STATEMENT = ("Revenue", "Cost of Sales", "Payroll Expense", "Rent Expense", "Utilities", "Travel Expense",
                    "Office Supplies")


def make_ledger(
    n_rows: int = 20_000,
    layout: str = "debit_credit",
    seed: int = 0,
    start: str = "2025-01-01",
    end: str = "2025-12-31",
    anomaly_rate: float = 0.008,
    noise: bool = True,
    silent_share: float = 0.10,
    manual_share: float = 0.15,
    noise_scale: float = 1.0,
) -> pd.DataFrame:
    """
    Build a synthetic ledger of balanced journals (vouchers) of 2 to 4 lines, about ``n_rows`` lines.

    A voucher has one date, number, creator, approver, source and narration, shared by its lines.
    Its main line carries the total; the other side is one counter line (bank, receivables,
    payables or VAT) or the total split across two or three, so debits equal credits. Normal
    vouchers have log-normal amounts with cents, mostly weekday dates, a ``Source`` (mostly
    "System", about ``manual_share`` "Manual") and a realistic amount of "noise": a few weekend
    postings, round totals, double postings, keyword hits, routine system accruals at quarter ends
    and system vouchers with no narration, none of them anomalies.

    Injected anomalies (about ``anomaly_rate`` of the vouchers) each carry one to four signals and a
    larger amount. Weekend, period-end, manual and same-user signals belong to the whole voucher; a
    seldom account, keyword or vague narration is on the main line only, and a round or 99 total
    is on the main line and, in a 2-line voucher, on its counter line too. A weekend or round-amount
    signal is always on a manual voucher, because those tests can be limited to manual lines. Every
    line of an injected voucher is marked in the ``Anomaly`` column, which the tests and the scoring
    never read.

    A share of the anomalous vouchers (``silent_share``) carry no signal at all: an unusually large
    amount with cents, on a common account, on a weekday outside the period-end windows, from the
    system, with an ordinary narration and a different approver. No test is built to find them,
    so they set a recall ceiling below 1, as on real ledgers. Like any normal voucher, a silent one
    can still trip a test by chance: Benford's first digit. Being system vouchers, they can't trip
    the manual-only tests.

    Args:
        n_rows: About this many ledger lines, before double postings are added.
        layout: ``"debit_credit"`` (Debit and Credit columns) or ``"signed"``
            (one Amount column, credits negative).
        seed: Random seed, so every run gives the same ledger.
        start, end: Date range of the postings.
        anomaly_rate: Share of vouchers turned into injected anomalies.
        noise: Add the background false positives described above.
        silent_share: Share of the injected anomalies that carry no signal.
        manual_share: Share of normal vouchers entered by hand.
        noise_scale: Multiplies every kind of background false positive (1 = the default amounts).

    Returns:
        The ledger with ``Sr No`` (the row ID), ``Date``, ``Voucher No``, ``Account``,
        ``Description``, ``Created By``, ``Approved By``, ``Source``, the amount column(s) and
        ``Anomaly`` (the injected signals, e.g. ``"round_amount+weekend"``, ``"silent"``, or ``""``).
    """
    if layout not in ("debit_credit", "signed"):
        raise ValueError("layout must be 'debit_credit' or 'signed'")
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    window = period_end_labels(pd.Series(days)).to_numpy()
    # Dates: weekdays mostly, weekends rare (about 1.5% of vouchers with noise on)
    weights = np.where(days.dayofweek < 5, 1.0, 0.04 * noise_scale if noise else 0.0)
    sizes = rng.choice(VOUCHER_SIZES, size=n_rows // 2 + 1, p=VOUCHER_SIZE_SHARES)
    sizes = sizes[:np.searchsorted(np.cumsum(sizes), n_rows) + 1]    # vouchers until the lines reach n_rows

    vouchers = _headers(rng, sizes, days, weights / weights.sum(), manual_share, noise)
    if noise:
        _add_noise(rng, vouchers, days, window, noise_scale)
    _inject(rng, vouchers, days, window, anomaly_rate, silent_share)
    df = _legs(rng, vouchers)
    if noise:
        # Double postings of normal vouchers: every line copied under a new voucher number
        normal = vouchers.loc[vouchers["Anomaly"] == "", "Voucher No"]
        copies = rng.choice(normal, size=max(1, int(len(vouchers) // 400 * noise_scale)), replace=False)
        dupes = df[df["Voucher No"].isin(copies)].copy()
        dupes["Voucher No"] = dupes["Voucher No"].map({c: f"JV{len(vouchers) + i + 1:05d}" for i, c in enumerate(copies)})
        df = pd.concat([df, dupes], ignore_index=True)

    if layout == "debit_credit":
        df["Debit"] = np.where(df["_debit"], df["_amount"], 0.0)
        df["Credit"] = np.where(df["_debit"], 0.0, df["_amount"])
    else:
        df["Amount"] = np.where(df["_debit"], df["_amount"], -df["_amount"])
    # A stable sort keeps each voucher's lines together, main line first
    df = df.sort_values("Date", kind="stable", ignore_index=True)
    # The row ID is tagged once, before the ledger is split between IDEA and Python
    df.insert(0, "Sr No", np.arange(1, len(df) + 1))
    amount_cols = ["Debit", "Credit"] if layout == "debit_credit" else ["Amount"]
    return df[["Sr No", "Date", "Voucher No", "Account", "Description", "Created By", "Approved By", "Source",
               *amount_cols, "Anomaly"]]


def _headers(rng: np.random.Generator, sizes: np.ndarray, days: pd.DatetimeIndex, p_days: np.ndarray,
             manual_share: float, noise: bool) -> pd.DataFrame:
    """One row per voucher: the fields its lines share, the main line's account and the total."""
    n = len(sizes)
    accounts = np.array(list(ACCOUNTS.values()))
    return pd.DataFrame({
        "Voucher No": [f"JV{i:05d}" for i in range(1, n + 1)],
        "Lines": sizes,
        "Date": pd.to_datetime(rng.choice(days, size=n, p=p_days)),
        "Account": rng.choice(list(ACCOUNTS), size=n, p=accounts / accounts.sum()),
        "Description": rng.choice(DESCRIPTIONS, size=n, p=[0.096] * 10 + [0.04] if noise else None),
        "Created By": rng.choice(USERS, size=n),
        "Approved By": rng.choice(APPROVERS, size=n),
        "Source": np.where(rng.random(n) < manual_share, "Manual", "System"),
        "Total": np.round(rng.lognormal(mean=7.5, sigma=1.3, size=n), 2),
        "Main Debit": rng.random(n) < 0.5,
        "Main Text": None,    # a narration for the main line only (keyword or vague narration signals)
        "Anomaly": "",
    })


def _add_noise(rng: np.random.Generator, v: pd.DataFrame, days: pd.DatetimeIndex, window: np.ndarray,
               scale: float) -> None:
    """Background false positives, per voucher (in place)."""
    n = len(v)
    # Round totals in normal business (e.g. rent, fixed fees)
    idx = rng.choice(n, size=int(n // 100 * scale), replace=False)
    v.loc[idx, "Total"] = rng.choice([10_000, 20_000, 50_000], size=len(idx))
    # A supplier on fixed prices (4,000-4,999): ordinary business that pushes the first digit 4
    # above Benford's expectation, so the Benford test has something to flag
    idx = rng.choice(np.setdiff1d(np.arange(n), idx), size=int(n // 40 * scale), replace=False)
    v.loc[idx, "Total"] = np.round(rng.uniform(4_000, 5_000, size=len(idx)), 2)
    v.loc[idx, "Description"] = "Supplier payment"
    # Routine system accruals and releases in the quarter-end windows, and system vouchers with no text
    quarter_days = days[(window == "Quarter end") & (days.dayofweek < 5)]
    idx = rng.choice(n, size=int(n // 100 * scale) if len(quarter_days) else 0, replace=False)
    v.loc[idx, "Date"] = rng.choice(quarter_days, size=len(idx)) if len(idx) else []
    v.loc[idx, "Source"] = "System"
    v.loc[idx, "Description"] = rng.choice(["Accrual", "Prepayment release"], size=len(idx))
    system = v.index[v["Source"] == "System"]
    v.loc[rng.choice(system, size=int(n // 50 * scale), replace=False), "Description"] = ""


def _inject(rng: np.random.Generator, v: pd.DataFrame, days: pd.DatetimeIndex, window: np.ndarray,
            anomaly_rate: float, silent_share: float) -> None:
    """Injected anomalies: 1-4 signals each and a larger than usual total, per voucher (in place)."""
    n_anomalies = max(1, int(len(v) * anomaly_rate))
    rows = rng.choice(len(v), size=n_anomalies, replace=False)
    weekends = days[days.dayofweek >= 5]
    # Not filtered by a holiday calendar: the ledger must not change with the holidays package version
    weekdays = days[(days.dayofweek < 5) & (window == "")]
    period_days = days[window != ""]
    n_silent = round(n_anomalies * silent_share)
    for i, row in enumerate(rows):
        base = float(rng.choice([5, 10, 25])) * float(np.exp(7.5))
        if i < n_silent:     # rows are already in random order
            amount = round(base * rng.uniform(1, 4), 2)
            if amount == round(amount):
                amount += 0.37   # keep cents, so neither amount test can match
            v.loc[row, ["Total", "Date", "Account", "Description", "Approved By", "Source", "Anomaly"]] = [
                amount, rng.choice(weekdays), rng.choice(list(ACCOUNTS)), rng.choice(SILENT_DESCRIPTIONS),
                rng.choice(APPROVERS), "System", "silent"]
            continue
        signals = list(rng.choice(ANOMALY_SIGNALS, size=rng.integers(1, 5), replace=False))
        if "round_amount" in signals and "ending_99" in signals:
            signals.remove("ending_99")
        if "period_end" in signals and ("weekend" in signals or not len(period_days)):
            signals.remove("period_end")
        if "keyword" in signals and "vague_narration" in signals:
            signals.remove("vague_narration")
        amount = round(base * rng.uniform(1, 4), 2)
        if "round_amount" in signals:
            amount = float(round(amount, -4) or 10_000)
        if "ending_99" in signals:
            amount = float(int(amount) // 1000 * 1000 + 999)
        v.loc[row, "Total"] = amount
        v.loc[row, "Date"] = rng.choice(weekends if "weekend" in signals
                                        else period_days if "period_end" in signals else weekdays)
        v.loc[row, "Description"] = rng.choice(SILENT_DESCRIPTIONS)
        if {"keyword", "vague_narration"} & set(signals):
            v.loc[row, "Main Text"] = rng.choice(ANOMALY_DESCRIPTIONS if "keyword" in signals else VAGUE_DESCRIPTIONS)
        manual = {"manual", "weekend", "round_amount"} & set(signals)
        v.loc[row, "Source"] = "Manual" if manual else "System"
        if "seldom_account" in signals:
            v.loc[row, "Account"] = f"Suspense Account {i // 2 + 1}"   # at most two entries per account
        if "self_approved" in signals:
            v.loc[row, "Approved By"] = v.loc[row, "Created By"]
        v.loc[row, "Anomaly"] = "+".join(sorted(signals))


def _legs(rng: np.random.Generator, v: pd.DataFrame) -> pd.DataFrame:
    """Each voucher's lines: the main line carries the total, the counter lines balance it."""
    legs = v.loc[v.index.repeat(v["Lines"])].reset_index(drop=True)
    leg = legs.groupby("Voucher No").cumcount().to_numpy()
    main, by_voucher = leg == 0, legs["Voucher No"]
    # Counter lines: bank, receivables, payables or VAT, never the main line's own account
    counter = rng.choice(COUNTER_ACCOUNTS, size=len(legs))
    clash = counter == legs["Account"].to_numpy()
    counter[clash] = np.where(legs.loc[clash, "Account"] == "Cash at Bank", "Accounts Payable", "Cash at Bank")
    legs["Account"] = np.where(main, legs["Account"], counter)
    # The total split across the counter lines; the last takes the rounding difference, so the voucher balances
    share = pd.Series(np.where(main, 0.0, rng.uniform(0.2, 1.0, len(legs))))
    part = (legs["Total"] * share / share.groupby(by_voucher).transform("sum")).round(2)
    last = leg == legs["Lines"].to_numpy() - 1
    part = part.where(~last, legs["Total"] - (part.groupby(by_voucher).transform("sum") - part))
    legs["_amount"] = np.where(main, legs["Total"], part).round(2)
    legs["_debit"] = np.where(main, legs["Main Debit"], ~legs["Main Debit"])
    legs["Description"] = legs["Main Text"].where(main & legs["Main Text"].notna(), legs["Description"])
    return legs


def make_trial_balance(ledger: pd.DataFrame, amount_cols: Sequence[str] | None = None, seed: int = 0,
                       account_col: str = "Account") -> pd.DataFrame:
    """
    An opening and closing trial balance that the ledger rolls forward exactly, for the population check.

    Balance-sheet accounts get a random opening balance; income-statement accounts open at zero.
    Closing = opening + debits - credits per account, rounded to 2 decimals.
    """
    rng = np.random.default_rng(seed)
    movement = movements(ledger, amount_cols or amount_columns(ledger), account_col)
    opening = pd.Series(np.round(rng.normal(0, 250_000, len(movement)), 2), index=movement.index)
    opening[opening.index.isin(INCOME_STATEMENT)] = 0.0
    return pd.DataFrame({account_col: movement.index, "Opening": opening.to_numpy(),
                         "Closing": (opening + movement).round(2).to_numpy()})


def amount_columns(df: pd.DataFrame) -> list[str]:
    """The ledger's amount column(s): ``["Debit", "Credit"]`` or ``["Amount"]``."""
    return ["Debit", "Credit"] if "Debit" in df.columns else ["Amount"]
