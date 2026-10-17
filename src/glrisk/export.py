"""
The priority list as an Excel working paper, with four sheets:

- **Cover**: what the extract is (source, population, settings, complete or partial), the tests
  that couldn't run, the date run, and blank preparer and reviewer.
- **Vouchers**: every listed voucher, a plain "why selected" sentence next to the score breakdown,
  and blank testing columns for the audit team, who select and test whole vouchers.
- **Lines**: every line of the listed vouchers, flagged or not, with the facts each test found.
- **Method**: the weights. Internal to the audit team: predictable selection criteria weaken the
  test (ISA 240 para 30(c); ISA 240 (Revised) para 43).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import rules
from .rules import absolute_amount, period_end_labels
from .settings import RunSettings

STATUS = "Entries meeting the test criteria, for the audit team to consider; not audit findings."
METHOD_LABEL = "Internal to the audit team: not for the client."
# A line this many times the median non-zero amount is called large in "why selected" (without PM)
LARGE_MULTIPLE = 10
TESTING_COLUMNS = ["Selected", "Planned risk", "Work done", "Evidence ref", "Tested by / date", "Auditor's conclusion"]
# One phrase per test, matched by keyword in the test name (as the priors are)
PHRASES = {
    "keyword": "description matches the keyword list",
    "round": "a round amount",
    "99": "an amount ending in 99 or 999",
    "seldom": "posted to an account with {seldom} entries or fewer",
    "duplicate": "same {key} and amount as another line",
    "same user": "created and approved by the same user ID",
    "benford": "first digit over-represented in this ledger (Benford)",
    "manual": "a manual entry",
    "narration": "no or vague narration",
}
WINDOWS = {"Quarter end": "near a quarter end", "Year end": "near the year-end",
           "Opening cut-off": "just after the prior year-end"}


def why_selected(row: pd.Series, attrs: dict, amount: float, window: str = "", seldom_max_entries: int = 3,
                 key: str = "date, account, description", hits: pd.Series | None = None, n_lines: int = 1) -> str:
    """
    A plain sentence built from per-test phrases, the date tests merged into one "posted ..." clause:
    "Posted on a Saturday and near a quarter end; a round amount (1 of 3 lines); a manual entry."
    ``hits`` is the number of the voucher's ``n_lines`` lines each test flagged, to note partial hits.
    """
    dates = [WINDOWS.get(window, "near a period end") if "period" in t.lower()
             else "on a public holiday" if "holiday" in t.lower() else f"on a {t}"
             for t in attrs["date_tests"] if row[t]]
    parts = ["posted " + " and ".join(dates)] if dates else []
    parts += [next((v for k, v in PHRASES.items() if k in t.lower()), t).format(seldom=seldom_max_entries, key=key)
              + (f" ({hits[t]} of {n_lines} lines)" if hits is not None and hits[t] < n_lines else "")
              for t in attrs["tests"] if row[t] and t not in attrs["date_tests"]]
    pm, median = attrs.get("performance_materiality"), attrs.get("median_amount")
    if pm is not None and amount > pm:
        parts.append(f"above performance materiality ({amount:,.2f}; performance materiality {pm:,.2f})")
    elif pm is None and median and amount >= LARGE_MULTIPLE * median:
        parts.append(f"a large amount ({amount / median:,.0f} times the median)")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def write_working_paper(priority: pd.DataFrame, lines: pd.DataFrame, path: str | Path, amount_cols: Sequence[str],
                        source: str, parameters: dict | None = None, not_run: Iterable[str] = (),
                        settings: RunSettings | None = None, drop_cols: Sequence[str] = ("Anomaly",)) -> Path:
    """
    Write the scored vouchers to ``path`` (xlsx) as Cover, Vouchers, Lines and Method sheets.

    ``priority`` is ``scoring.score_flags(scoring.to_vouchers(lines, ...), ["Voucher Amount"])``, and
    ``lines`` the ``flags.consolidate(..., min_flags=0)`` output it came from. Pass the ``settings``
    the tests ran with (default ``RunSettings()``): the period-end window, narration issue and
    matched keywords are recomputed for the listed lines with them, and they go on the cover with
    ``parameters`` (anything else to state, e.g. the list size) and ``not_run``
    (``pipeline.tests_not_run``). ``drop_cols`` are left out, e.g. the synthetic ground truth.
    """
    s, a = settings or RunSettings(), priority.attrs
    key, tests, k, n = a["voucher_col"], a["tests"], a["top_n"], a["n_scored"]
    unit = "lines" if key == s.id_col else "vouchers"     # without a voucher column, each line is a voucher
    rank = pd.Series(range(1, len(priority) + 1), index=priority[key].to_numpy())
    legs = lines[lines[key].isin(rank.index)]
    legs = legs.assign(**{"Voucher Rank": legs[key].map(rank)}).sort_values("Voucher Rank", kind="stable")
    amounts = absolute_amount(legs, amount_cols)
    dates = rules.parse_dates(legs[s.date_col], s.dayfirst)
    windows = period_end_labels(dates, s.fy_end_month, **s.windows).where(amounts > 0, "")
    text = [c for c in s.text_cols if c in legs.columns]

    # Lines: every line of the listed vouchers, and the facts each test found, to filter on
    out = legs.drop(columns=[*tests, *drop_cols, "N Flags", "Flagged By"], errors="ignore")
    out.insert(0, "Voucher Rank", out.pop("Voucher Rank"))
    if s.source_col in out:
        manual = legs.index.isin(rules.manual_entries(legs, s.source_col, s.manual_values).index)
        out.insert(out.columns.get_loc(s.source_col) + 1, "Manual", pd.Series(manual, legs.index).map(
            {True: "Yes", False: "No"}))
    out["Flagged Line"], out["Flagged By"] = (legs["N Flags"] > 0).map({True: "Yes", False: "No"}), legs["Flagged By"]
    details = {"Period-End Window": windows,
               "Narration Issue": rules.narration(legs, s.text_cols[0], s.generic_words,
                                                  max_blank_share=1)["Narration Issue"] if s.text_cols[0] in text else None,
               "Matched Keywords": rules.keywords(legs, text, s.keywords)["Matched Keywords"] if text else None}
    for name, values in details.items():
        if values is not None:
            out[name] = values.reindex(legs.index, fill_value="")

    # Vouchers: one row each, why it was selected, and the testing columns
    hits, window = legs.groupby(key)[tests].sum(), windows.groupby(legs[key]).max()
    vouchers = priority.drop(columns=[*tests, *drop_cols, "N Flags", "Base Score", "Amount Multiplier"],
                             errors="ignore")
    vouchers.insert(0, "Rank", range(1, len(priority) + 1))
    vouchers.insert(vouchers.columns.get_loc("Score Breakdown"), "Why Selected", [
        why_selected(row, a, row["Voucher Amount"], window[row[key]], s.seldom_max_entries,
                     ", ".join(s.dup_key).lower(), hits.loc[row[key]], row["Lines"]) for _, row in priority.iterrows()])
    vouchers = vouchers.assign(**{c: "" for c in TESTING_COLUMNS})

    extent = (f"Complete: all {n:,} flagged {unit}" if k is None or k >= n
              else f"Partial: the top {k} of {n:,} flagged {unit} by score")
    if a["above_pm_added"]:
        extent += f", plus {a['above_pm_added']} more above performance materiality (listed after them)"
    extent += (". One row per voucher on the Vouchers sheet; every line of those vouchers, flagged or not, on "
               "the Lines sheet." if unit == "vouchers" else ". Scored per line: one row per line on both sheets.")
    pm, ct = a["performance_materiality"], a["clearly_trivial"]
    population = (f"{len(lines):,} ledger lines in {a['n_rows']:,} vouchers; {n:,} vouchers meet at least one test"
                  if unit == "vouchers" else f"{a['n_rows']:,} ledger lines; {n:,} meet at least one test")
    cover = [("Status", STATUS), ("Source", source), ("Population", population), ("Extent", extent),
             ("Performance materiality", "Not set" if pm is None else f"{pm:,.2f} (compared with the voucher amount)"),
             ("Clearly trivial", "Not set" if ct is None else f"{ct:,.2f} (recorded only: nothing below it is "
                                                              "filtered out, because small or split entries can matter)"),
             *[(f"Parameter: {name}", str(value)) for name, value in {
                 **s.cover(has_source=s.source_col in lines),
                 "Large amount": f"{LARGE_MULTIPLE} times the median voucher amount, used in \"why selected\" only "
                                 "when performance materiality isn't set (practical judgement)",
                 **(parameters or {})}.items()],
             *[("Not tested or limited", line) for line in not_run],
             ("Date run (UTC)", datetime.now(UTC).date().isoformat()), ("Prepared by", ""), ("Reviewed by", ""),
             ("Method", "See the Method sheet. " + METHOD_LABEL)]

    counts, n_rows, factor = a["test_counts"], a["n_rows"], a["benford_factor"]
    method = pd.DataFrame([{
        "Test": t, f"{unit.capitalize()} flagged": counts[t], f"Share of {unit}": round(counts[t] / n_rows, 4),
        "Rarity": a["rarities"][t],
        "Prior (illustrative)": a["priors"][t], "Weight": a["weights"][t],
        "Note": "; ".join(filter(None, ["date test: only the strongest counts" if t in a["date_tests"] else "",
                                        f"scaled by amount diversity ({factor:.2f})" if "benford" in t.lower() else ""])),
    } for t in tests])
    summary = [METHOD_LABEL,
               "Score = sum of the weights of the tests a voucher meets through any line (date tests count once), times the amount multiplier.",
               f"Weight = rarity in this ledger (-log10 of the share of {unit} flagged) times the prior.",
               f"Amount multiplier = 1 + log10(1 + voucher amount / median); voucher amount = larger of total debits and credits; median {a['median_amount']:,.2f}."]

    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(cover, columns=["Item", "Value"]).to_excel(writer, sheet_name="Cover", index=False)
        vouchers.to_excel(writer, sheet_name="Vouchers", index=False)
        out.to_excel(writer, sheet_name="Lines", index=False)
        pd.DataFrame({"Method": summary}).to_excel(writer, sheet_name="Method", index=False, header=False)
        method.to_excel(writer, sheet_name="Method", index=False, startrow=len(summary) + 1)
        for name, frame in (("Vouchers", vouchers), ("Lines", out)):
            sheet = writer.sheets[name]
            sheet.freeze_panes, sheet.auto_filter.ref = "A2", sheet.dimensions
            for col in frame.select_dtypes("datetime").columns:   # dates as dates, without a time
                for cell in sheet[sheet.cell(1, frame.columns.get_loc(col) + 1).column_letter][1:]:
                    cell.number_format = "yyyy-mm-dd"
        writer.sheets["Method"].freeze_panes = f"A{len(summary) + 3}"   # below the table's header
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                width = max(len(str(c.value or "")) for c in column[:200])
                sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 70)
    return path
