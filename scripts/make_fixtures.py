"""
Rebuild the mock IDEA exports in fixtures/idea_exports from the seeded synthetic ledger.

    python scripts/make_fixtures.py                    # fixtures only
    python scripts/make_fixtures.py --ledger ledger.xlsx   # also write the ledger to import into IDEA

The ledger written for IDEA leaves out the ground-truth "Anomaly" column.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from glrisk import pipeline, synthetic

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "idea_exports"


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
    if args.ledger:
        ledger.drop(columns="Anomaly").to_excel(args.ledger, index=False)
        print(f"Wrote the ledger ({len(ledger):,} lines) to {args.ledger}")


if __name__ == "__main__":
    main()
