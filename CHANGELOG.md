# Changelog

## 0.3.0

Realigned with journal entry testing under ISA 240: each test is described by the characteristic
it covers and the auditor's use of it, and outputs state facts, not conclusions.

- **New tests**: period end (quarter ends from the financial year-end, and a wider year-end
  window in working days), manual entries (from a `Source` column, never guessed), and no or
  vague narration.
- **Manual lines only**: with a `Source` column, the weekend, holiday and round-amount tests count
  manual lines only. Tests that can't run for lack of a column are stated.
- **Population check**: `population.roll_forward` (GL to TB, per account) and
  `synthetic.make_trial_balance`.
- **Materiality, optional**: `performance_materiality` lists lines above it in addition to the top
  k; `clearly_trivial` is recorded and filters nothing.
- **Working paper**: `export.write_working_paper` (Cover, Lines, Method), with a sample in
  `docs/sample_priority_list.xlsx`.
- **Renamed**: "SoD Violation Entries" is now "Same User Created and Approved", and "Suspicious
  Keyword" is now "Keyword Match". The same-user prior (2.5) now applies; before, the test name
  didn't match its prior's keyword and it got 1.0.
- **Generator**: a `Source` column, new injected signals (period end, manual, vague narration) and
  matching false positives; the Isolation Forest baseline gets the same new features.
- **Benchmark re-run**: «CHANGELOG_BENCH»
- **Docs**: README and DESIGN rewritten around the audit problem, with an "Audit context" table;
  the README's top-5 table is now printed by `scripts/make_fixtures.py`.

## 0.2.0

Multi-seed benchmark with ceilings, ablation and sweeps, an Isolation Forest baseline, and a
`Score Breakdown` column.

## 0.1.0

First version: the tests, consolidation on a row ID, the risk score and the mock IDEA exports.
