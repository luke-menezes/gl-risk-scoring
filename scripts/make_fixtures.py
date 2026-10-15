"""
Rebuild the mock IDEA exports in fixtures/idea_exports and the sample working paper
docs/sample_priority_list.xlsx from the seeded synthetic ledger, and print the top 5 for the README.

    python scripts/make_fixtures.py                    # fixtures and sample
    python scripts/make_fixtures.py --ledger ledger.xlsx   # also write the ledger to import into IDEA

The ledger written for IDEA, and the sample, leave out the ground-truth "Anomaly" column.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from glrisk import export, flags, pipeline, rules, scoring, synthetic

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "idea_exports"
SAMPLE = ROOT / "docs" / "sample_priority_list.xlsx"


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
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), flags.load_idea_flags(FIXTURES))
    priority = scoring.score_flags(flagged, amt)
    parameters = {"Weekend days": ", ".join(rules.WEEKEND_DAYS), "Financial year-end": "31 December",
                  "Period-end windows": "last 3 and first 2 days of each quarter; 5 working days either side "
                                        "of the year-end", "Weekend, holiday and round-amount tests": "manual lines only",
                  "Round amount": "multiple of 10,000", "Seldom-used account": "3 entries or fewer",
                  "Keywords": ", ".join(rules.DEFAULT_KEYWORDS), "Generic narration words": ", ".join(rules.GENERIC_WORDS),
                  "List size": "0.577 x square root of the ledger lines, within 20-150"}
    export.write_working_paper(priority, SAMPLE, amt, f"Synthetic ledger, seed {args.seed} (not real data)",
                               parameters, pipeline.tests_not_run(ledger))
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
