"""Run the synthetic journal review and write a working paper and reviewer summary."""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from glrisk import RunSettings, export, flags, pipeline, population, scoring, synthetic

SEED = 0
WORKBOOK = "working_paper.xlsx"
SUMMARY = "review_summary.md"


def _review_summary(reconciliation: pd.DataFrame, lines: pd.DataFrame, priority: pd.DataFrame,
                    limitations: list[str], settings: RunSettings) -> str:
    counts = priority.attrs["test_counts"].copy()
    counts.setdefault("Benford", 0)  # The mock export only writes over-represented digits.
    coverage_notes = [f"- {note}" for note in limitations] or ["All selection tests ran without reported limitations."]
    report = [
        "# Synthetic ledger review",
        "",
        (
            f"Seed {SEED} generated {len(lines):,} ledger lines across {priority.attrs['n_rows']:,} vouchers. "
            f"The working paper lists {len(priority):,} of the {priority.attrs['n_scored']:,} flagged vouchers."
        ),
        "",
        "## Reconciliation",
        "",
        (
            f"Reconciled {len(reconciliation):,} accounts from opening balance through ledger movements to closing "
            f"balance. Sum of absolute account differences was **{reconciliation.attrs['total_difference']:,.2f}**."
        ),
        "",
        "## Tests and coverage",
        "",
        "The Python checks and simulated IDEA checks ran on the same ledger.",
        "",
        "| Test run | Vouchers flagged |",
        "| --- | ---: |",
        *[f"| {test} | {count:,} |" for test, count in sorted(counts.items())],
        "",
        *coverage_notes,
        "",
        "## From voucher rank to ledger lines",
        "",
    ]
    if priority.empty:
        report.append("No voucher met a selection test.")
    else:
        top = priority.iloc[0]
        key = priority.attrs["voucher_col"]
        voucher = top[key]
        selected = lines.loc[lines[key] == voucher].sort_values(settings.id_col)
        report.extend([
            (
                f"Voucher **{voucher}** ranked first with a score of **{top['Score']:.2f}** "
                f"and an amount of **{top['Voucher Amount']:,.2f}**."
            ),
            "",
            f"**Score breakdown** · {top['Score Breakdown']}",
            "",
            "| Row ID | Account | Tests that flagged the line |",
            "| --- | --- | --- |",
        ])
        trace = selected[[settings.id_col, settings.account_col, "Flagged By"]]
        for row_id, account, reasons in trace.itertuples(index=False, name=None):
            report.append(f"| {row_id} | {account} | {reasons or 'None'} |")
    return "\n".join(report) + "\n"


def run_demo(output_dir: Path) -> None:
    """Run one seeded example and write both outputs after validation and ranking."""
    settings = RunSettings()
    ledger = synthetic.make_ledger(20_000, seed=SEED).drop(columns="Anomaly")
    amount_cols = synthetic.amount_columns(ledger)
    trial_balance = synthetic.make_trial_balance(ledger, amount_cols, seed=SEED)
    reconciliation = population.roll_forward(ledger, trial_balance, amount_cols)
    difference = reconciliation.attrs["total_difference"]
    if difference:
        raise ValueError(f"Ledger and trial balance do not reconcile (total account difference {difference:,.2f}).")

    python_flags = pipeline.run_python_tests(ledger, amount_cols, settings)
    with TemporaryDirectory(prefix="glrisk-idea-") as mock_exports:
        pipeline.write_idea_exports(ledger, mock_exports, amount_cols, settings)
        idea_flags = flags.load_idea_flags(mock_exports, id_col=settings.id_col)
    lines = flags.consolidate(ledger, python_flags, idea_flags, id_col=settings.id_col, min_flags=0)
    priority = scoring.score_flags(scoring.to_vouchers(lines, amount_cols, settings), ["Voucher Amount"])
    limitations = pipeline.tests_not_run(ledger, amount_cols, settings)
    summary = _review_summary(reconciliation, lines, priority, limitations, settings)

    # The list size the run used, stated on the cover as in scripts/make_fixtures.py
    size = {name: p.default for name, p in inspect.signature(scoring.priority_list_size).parameters.items()}
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir) as temp:
        staging = Path(temp)
        export.write_working_paper(
            priority, lines, staging / WORKBOOK, amount_cols, f"Synthetic ledger, seed {SEED} (not real data)",
            parameters={
                "List size": f"{size['k']} x square root of the vouchers, within {size['floor']}-{size['ceiling']}",
                "Population check": f"{len(reconciliation):,} accounts reconciled (difference {difference:,.2f})",
            },
            not_run=limitations, settings=settings,
        )
        (staging / SUMMARY).write_text(summary, encoding="utf-8")
        for name in (WORKBOOK, SUMMARY):
            (staging / name).replace(output_dir / name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("demo-output"), help="where to write the two outputs")
    args = parser.parse_args()
    try:
        run_demo(args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"Wrote {args.output_dir / WORKBOOK}")
    print(f"Wrote {args.output_dir / SUMMARY}")


if __name__ == "__main__":
    main()
