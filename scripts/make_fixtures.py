"""
Rebuild the mock IDEA exports in fixtures/idea_exports and the sample working paper
docs/sample_priority_list.xlsx from the seeded synthetic ledger, and print the top 5 for the README.

    python scripts/make_fixtures.py                    # fixtures and sample
    python scripts/make_fixtures.py --ledger ledger.xlsx   # also write the ledger to import into IDEA

The ledger written for IDEA, and the sample, leave out the ground-truth "Anomaly" column.
"""

from __future__ import annotations

import argparse
import inspect
import shutil
from pathlib import Path

from glrisk import export, flags, pipeline, rules, scoring, synthetic

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "idea_exports"
SAMPLE = ROOT / "docs" / "sample_priority_list.xlsx"


def defaults(func) -> dict:
    """A function's default arguments, so the cover states the values the run actually used."""
    return {name: p.default for name, p in inspect.signature(func).parameters.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ledger", type=Path, help="also write the ledger (xlsx) for importing into IDEA")
    args = parser.parse_args()

    ledger = synthetic.make_ledger(args.rows, seed=args.seed)
    if FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    paths = pipeline.write_idea_exports(ledger, FIXTURES, synthetic.amount_columns(ledger))
    print(f"Wrote {len(paths)} mock IDEA exports to {FIXTURES.relative_to(ROOT)}")

    amt = synthetic.amount_columns(ledger)
    # The same parameters go to the tests and to the working paper, which recomputes details with them
    run = {k: defaults(pipeline.run_python_tests)[k] for k in ("weekend_days", "fy_end_month", "holiday_country",
                                                                  "keywords", "generic_words")}
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt, **run), flags.load_idea_flags(FIXTURES))
    priority = scoring.score_flags(flagged, amt)
    windows, size = defaults(rules.period_end_labels), defaults(scoring.priority_list_size)
    parameters = {"Period-end windows": f"last {windows['quarter_days'][0]} and first {windows['quarter_days'][1]} "
                                        f"days of each quarter; {windows['year_end_days']} working days either side "
                                        "of the year-end",
                  "Weekend, holiday and round-amount tests": "manual lines only"
                  if defaults(pipeline.run_python_tests)["manual_only"] else "all lines",
                  "Round amount": f"multiple of {defaults(pipeline.run_python_tests)['round_multiple']:,}",
                  "List size": f"{size['k']} x square root of the ledger lines, within {size['floor']}-{size['ceiling']}"}
    export.write_working_paper(priority, SAMPLE, amt, f"Synthetic ledger, seed {args.seed} (not real data)",
                               parameters, pipeline.tests_not_run(ledger, amount_cols=amt), **run,
                               seldom_max_entries=defaults(rules.seldom_accounts)["max_entries"])
    print(f"Wrote {SAMPLE.relative_to(ROOT)}\n")
    print("| Sr No | Description | Amount | Score | Score Breakdown |\n|---|---|---|---|---|")
    for _, row in priority.head(5).iterrows():
        amount = rules.absolute_amount(row.to_frame().T, amt).iloc[0]
        print(f"| {row['Sr No']} | {row['Description'] or '(blank)'} | {amount:,.0f} | {row['Score']:.1f} "
              f"| {row['Score Breakdown']} |")
    if args.ledger:
        ledger.drop(columns="Anomaly").to_excel(args.ledger, index=False)
        print(f"Wrote the ledger ({len(ledger):,} lines) to {args.ledger}")


if __name__ == "__main__":
    main()
