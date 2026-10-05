# The IDEA side

Audit teams often run part of the analytics in Caseware IDEA and part in Python. IDEA is the
standard tool in many audit and forensic teams; Python is better for anything custom. Here the
two halves meet on one column, the row ID `Sr No`.

`portfolio_sample.ism` is a small IDEAScript macro, written for this repo. It runs three tests and
exports each result to Excel in the project's `Exports.ILB` folder:

| Step | What it does | Export(s) |
|---|---|---|
| Benford first digit | Adds a `FIRST_DIGIT` virtual field, counts entries per digit, extracts the digits set in `BENFORD_DIGITS` | `Benford First Digit Summary`, `Benford Starting <d>` |
| Seldom accounts | Summarises by account, reads the summary record by record, extracts the entries of accounts with 3 entries or fewer | `Account Summary`, `Seldom Account Entries` |
| Segregation of duties | Extracts entries where creator and approver are the same user (trimmed, case ignored) | `SoD Violation Entries` |

Duplicates are usually checked in IDEA's own Duplicate Key Detection dialog, so they aren't in
the macro. The mock fixtures include a `Duplicate` export to stand in for it.

## Why the row ID is tagged before the split

The ledger is cleaned once, and `Sr No` (1, 2, 3, ...) is added as a static column before the
same file goes to both tools. Every IDEA export keeps it (IDEA calls it `SR_NO`), so
`glrisk.flags.load_idea_flags` can turn each export back into a set of row IDs, and
`consolidate` lines them up with the Python tests exactly:

- **No fuzzy matching.** Re-matching IDEA rows to Python rows on date, account and amount fails on
  duplicates, which are exactly the rows a duplicate test flags.
- **Not a hash of the row.** Two identical lines would get the same hash; a running number keeps
  them apart.
- **Survives the round trip.** IDEA and Excel may read `0000123` as `123` or `123.0`; the loader
  normalises numeric IDs, so both sides agree.

## Running it

1. `python scripts/make_fixtures.py --ledger ledger.xlsx`
2. Import `ledger.xlsx` into an IDEA project as `Synthetic Ledger`.
3. Run `portfolio_sample.ism` (Tools > Macros > Run).
4. Point `load_idea_flags` at the project's `Exports.ILB` folder, instead of `fixtures/idea_exports`.

The committed fixtures were produced by `glrisk.pipeline.write_idea_exports`, which applies the
same logic in Python, so the pipeline runs without an IDEA licence.
