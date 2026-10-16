"""
The priority list as an Excel working paper, with three sheets:

- **Cover**: what the extract is (source, population, parameters, complete or partial, per line),
  the tests that couldn't run, the date run, and blank preparer and reviewer.
- **Lines**: every listed line, a plain "why selected" sentence next to the score breakdown, and
  blank testing columns for the audit team.
- **Method**: the weights. Internal to the audit team: predictable selection criteria weaken the
  test (ISA 240 para 30(c); ISA 240 (Revised) para 43).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .rules import absolute_amount, period_end_labels

STATUS = "Entries meeting the test criteria, for the audit team to consider; not audit findings."
METHOD_LABEL = "Internal to the audit team: not for the client."
TESTING_COLUMNS = ["Selected", "Planned risk", "Work done", "Evidence ref", "Tested by / date", "Auditor's conclusion"]
# One phrase per test, matched by keyword in the test name (as the priors are)
PHRASES = {
    "keyword": "description matches the keyword list",
    "round": "a round amount",
    "99": "an amount ending in 99 or 999",
    "seldom": "posted to an account with 3 entries or fewer",
    "duplicate": "same date, account, description and amount as another line",
    "same user": "created and approved by the same user ID",
    "benford": "first digit over-represented in this ledger (Benford)",
    "manual": "a manual entry",
    "narration": "no or vague narration",
}
WINDOWS = {"Quarter end": "near a quarter end", "Year end": "near the year-end",
           "Opening cut-off": "just after the prior year-end"}


def why_selected(row: pd.Series, attrs: dict, amount: float, window: str = "") -> str:
    """
    A plain sentence built from per-test phrases, the date tests merged into one "posted ..." clause:
    "Posted on a Saturday and near a quarter end; a round amount; a manual entry."
    """
    dates = [WINDOWS.get(window, "near a period end") if "period" in t.lower()
             else "on a public holiday" if "holiday" in t.lower() else f"on a {t}"
             for t in attrs["date_tests"] if row[t]]
    parts = ["posted " + " and ".join(dates)] if dates else []
    parts += [next((v for k, v in PHRASES.items() if k in t.lower()), t)
              for t in attrs["tests"] if row[t] and t not in attrs["date_tests"]]
    pm, median = attrs.get("performance_materiality"), attrs.get("median_amount")
    if pm is not None and amount > pm:
        parts.append(f"above performance materiality ({amount:,.2f}; performance materiality {pm:,.2f})")
    elif pm is None and median and amount >= 10 * median:
        parts.append(f"a large amount ({amount / median:,.0f} times the median)")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def write_working_paper(priority: pd.DataFrame, path: str | Path, amount_cols: Sequence[str], source: str,
                        parameters: dict | None = None, not_run: Iterable[str] = (), date_col: str = "Date",
                        fy_end_month: int = 12, drop_cols: Sequence[str] = ("Anomaly",)) -> Path:
    """
    Write ``scoring.score_flags`` output to ``path`` (xlsx) as Cover, Lines and Method sheets.

    ``parameters`` (thresholds, windows, keyword lists, exclusions) and ``not_run``
    (``pipeline.tests_not_run``) go on the cover. ``drop_cols`` are left out of the Lines sheet,
    e.g. the synthetic ground truth.
    """
    a = priority.attrs
    tests, k, n = a["tests"], a["top_n"], a["n_scored"]
    amounts = absolute_amount(priority, amount_cols)
    windows = period_end_labels(priority[date_col], fy_end_month)
    lines = priority.drop(columns=[*tests, *drop_cols, "N Flags", "Base Score", "Amount Multiplier"], errors="ignore")
    if "Source" in lines:
        lines.insert(lines.columns.get_loc("Source") + 1, "Manual", lines["Source"].eq("Manual").map({True: "Yes", False: "No"}))
    lines.insert(lines.columns.get_loc("Score Breakdown"), "Why Selected",
                 [why_selected(priority.loc[i], a, amounts[i], windows[i]) for i in priority.index])
    lines = lines.assign(**{c: "" for c in TESTING_COLUMNS})

    extent = (f"Complete: all {n:,} flagged lines" if k is None or k >= n
              else f"Partial: the top {k} of {n:,} flagged lines by score")
    if a["above_pm_added"]:
        extent += f", plus {a['above_pm_added']} more above performance materiality (listed after them)"
    pm, ct = a["performance_materiality"], a["clearly_trivial"]
    cover = [("Status", STATUS), ("Source", source),
             ("Population", f"{a['n_rows']:,} ledger lines; {n:,} meet at least one test"),
             ("Extent", extent + ". One row per ledger line, not per voucher."),
             ("Performance materiality", "Not set" if pm is None else f"{pm:,.2f}"),
             ("Clearly trivial", "Not set" if ct is None else f"{ct:,.2f} (recorded only: nothing below it is "
                                                              "filtered out, because small or split entries can matter)"),
             *[(f"Parameter: {name}", str(value)) for name, value in (parameters or {}).items()],
             *[("Not tested", line) for line in not_run],
             ("Date run (UTC)", datetime.now(timezone.utc).date().isoformat()), ("Prepared by", ""), ("Reviewed by", ""),
             ("Method", "See the Method sheet. " + METHOD_LABEL)]

    counts, n_rows, factor = a["test_counts"], a["n_rows"], a["benford_factor"]
    method = pd.DataFrame([{
        "Test": t, "Lines flagged": counts[t], "Share of ledger": round(counts[t] / n_rows, 4),
        "Rarity": a["rarities"][t],
        "Prior (illustrative)": a["priors"][t], "Weight": a["weights"][t],
        "Note": "; ".join(filter(None, ["date test: only the strongest counts" if t in a["date_tests"] else "",
                                        f"scaled by amount diversity ({factor:.2f})" if "benford" in t.lower() else ""])),
    } for t in tests])
    summary = [METHOD_LABEL,
               "Score = sum of the weights of the tests a line meets (date tests count once), times the amount multiplier.",
               "Weight = rarity in this ledger (-log10 of the share of lines flagged) times the prior.",
               f"Amount multiplier = 1 + log10(1 + amount / median), median non-zero amount {a['median_amount']:,.2f}."]

    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(cover, columns=["Item", "Value"]).to_excel(writer, sheet_name="Cover", index=False)
        lines.to_excel(writer, sheet_name="Lines", index=False)
        pd.DataFrame({"Method": summary}).to_excel(writer, sheet_name="Method", index=False, header=False)
        method.to_excel(writer, sheet_name="Method", index=False, startrow=len(summary) + 1)
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                width = max(len(str(c.value or "")) for c in column[:200])
                sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 70)
    return path
