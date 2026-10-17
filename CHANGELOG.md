# Changelog

## 0.6.0

Scored per voucher (journal), the unit auditors select and test. Every figure changes.

- **Generator**: balanced vouchers of 2 to 4 lines (55%, 25%, 20%) with a `Voucher No`; a voucher's
  lines share its date, users, source and narration, and debits equal credits. Anomalies are injected
  per voucher (0.8% of vouchers, about 1.2 per list place): weekend, period-end, manual and same-user
  signals on the whole voucher, a seldom account, keyword or vague narration on one line, a round or
  99 total on the main line. Double postings copy the whole voucher. The trial balance still rolls
  forward exactly.
- **Scoring per voucher**: `scoring.to_vouchers` groups `consolidate(..., min_flags=0)` output by
  `RunSettings.voucher_col` (default `Voucher No`): a voucher meets a test if any of its lines does,
  rarity is the share of vouchers flagged, and the amount is the larger of its total debits and total
  credits. `score_flags` is unchanged. Without the voucher column each line is its own voucher, which
  gives exactly the 0.5 ranking, and the cover says "Scored per line".
- **Working paper** (breaking: `write_working_paper(priority, lines, ...)`): four sheets. Vouchers
  holds the list, "why selected" (noting partial hits, "1 of 3 lines") and the testing columns;
  Lines holds every line of the listed vouchers, flagged or not; the cover and Method count vouchers.
- **Benchmark per voucher** (about 20,000 lines, about 7,550 vouchers, k = 50): risk score
  0.849 ± 0.052, counting tests 0.665 ± 0.058, Isolation Forest 0.565 ± 0.079. New baseline: the lines
  scored on their own and listed by voucher does as well (0.852), because the generator puts an
  anomalous voucher's line signals on one line; reported as it is. New voucher-size check: normal
  4-line vouchers are flagged by chance more often than 2-line ones (57% against 38%) but take only a
  little more of the list (21.3% against 19.9% of vouchers). Ablation, sweeps, stress sweep and prior
  sensitivity re-run per voucher; the README keeps the 0.5 per-line figures for reference.
- **Docs**: README, DESIGN, the notebook and the chart per voucher.

## 0.5.1

Fixes from a review of 0.5.0, for inputs the synthetic ledger never produces. The benchmark
figures don't change.

- **Dates that stopped the pipeline**: `rules.parse_dates` raised an error, instead of counting
  lines as unreadable, on times with microseconds, on ISO dates with a time-zone offset and on
  numbers. Every pass now writes into one date type. Time-zone offsets are dropped, keeping the
  local date and time, so no entry moves to another day. Numbers from 20,000 to 80,000 are read as
  Excel serial dates (a date cell that lost its format) instead of as 1970 dates. Compact dates
  such as 20250308 still read; other numbers are unreadable. The cover's Dates row says so.
- **Isolation Forest features** read dates with `parse_dates` (a mixed-format column raised an
  error) and take `RunSettings`, so they use the run's columns, word lists and windows.
- **`RunSettings` holds every column** (breaking): `account_col`, `creator_col`, `approver_col`
  and `duplicate_key` are fields, replacing the keyword arguments of `tests_not_run`,
  `idea_side_results`, `write_idea_exports`, `ml_baseline.line_features` and
  `isolation_forest_ranking`. The duplicate key was defined twice and could disagree; it is now
  defined once and stated on the cover, and "why selected" names it.
- **Seldom threshold with real IDEA exports**: the cover and `idea/README.md` say that the test ran
  with the macro's `SELDOM_MAX`, so `seldom_max_entries` must be kept in step with it.

## 0.5.0

One settings object for a run, and dates in mixed formats. The benchmark figures don't change.

- **Dates in mixed formats**: pandas guessed one format from the first date and blanked every date
  in another format (in `13/01/2025, 2025-01-31` the second was lost). Those lines were stated on
  the cover as unreadable but skipped by the date tests. `rules.parse_dates` now reads ISO dates
  first, then the inferred format, then the rest one by one; ambiguous dates are read day first by
  default (02/03/2025 is 2 March), stated on the cover.
- **Settings reach the tests**: a custom `manual_values` went on the cover but the manual-entry test
  always used "Manual", and the IDEA stand-in always used a seldom threshold of 3 whatever the cover
  said. The defaults agreed, so the sample was right.
- **`RunSettings`** (breaking): the columns, calendar, period-end windows, thresholds and word lists
  are fields of one frozen dataclass, passed to `run_python_tests`, `tests_not_run`, the IDEA
  stand-in and `write_working_paper`, which states it on the cover. It replaces their separate
  keyword arguments, so the cover can't state a value the tests didn't use.
- **Docs**: README settings note and usage example, DESIGN note on dates.

## 0.4.0

Robustness checks for the benchmark, answering "is it just the generator agreeing with itself?".
The existing figures don't change.

- **Stress sweep**: the generator's settings (anomaly rate, silent share, manual share, background
  noise) are drawn at random per seed. The risk score is ahead of counting tests on all 30
  ledgers: share of ceiling 0.871 ± 0.080 against 0.663 ± 0.124, a lead of 21 points on average
  and 7 at the least.
- **Prior sensitivity**: every prior multiplied by a random factor in 0.5-1.5, 20 times per
  ledger. Precision@82 averages 0.819 ± 0.051 (0.846 with the illustrative priors), and 90% of
  the default list stays on it on average. The result rests on rarity and the amount multiplier,
  not on the exact prior values.
- **Generator**: `make_ledger(noise_scale=...)` scales every kind of background false positive;
  the default leaves existing ledgers unchanged.
- **Docs**: README "Is it just the generator agreeing with itself?", DESIGN evaluation notes.

## 0.3.2

Smaller fixes from a review of 0.3.1, and maintenance. The benchmark figures don't change.

- **Gaps are stated**: `tests_not_run` also says when the duplicate test runs without a key
  column (e.g. no Description), and how many lines have a missing or unreadable date (not
  covered by the date tests) or an unreadable amount (treated as zero). The cover row is now
  "Not tested or limited".
- **Missing columns**: the Isolation Forest features no longer fail without a creator or
  approver column, and the IDEA stand-in's account summary no longer relies on a `Sr No` column.
- **Parameters**: `run_python_tests` takes `keywords`, `generic_words` and `round_multiple`;
  `write_working_paper` takes the same lists, so the Lines columns can't disagree with the flags,
  and states them on the cover.
- **Python 3.11+**: 3.10 is end of life, and current pandas and numpy need 3.11. CI tests 3.11
  to 3.14.
- **Reproducibility**: `docs/benchmark-constraints.txt` pins the package versions behind the
  published figures; Dependabot keeps the GitHub Actions versions current.
- **Docs**: README "Gaps are stated" note, `python -m pytest`; CONTRIBUTING no longer says CI
  runs the benchmark.

## 0.3.1

Fixes found in a review of 0.3.0.

- **Ending 99/999**: the test counted large amounts with cents as whole (35,599.30 was flagged,
  and above about 100,000 any amount whose rounded value ends in 99), so it flagged nearly twice
  the lines it should. It now requires zero cents. Re-run over 30 seeds: risk score 0.846 ± 0.043
  (0.838 ± 0.045 in 0.3.0), counting tests 0.646 (0.647), Isolation Forest 0.511 (0.519); the
  200,000-line sweep rose most (0.767 against 0.737). The rounded-amount test also rounds to
  cents first, so float noise from imports can't change it.
- **No Description column**: the keyword and narration tests are skipped and stated as not run,
  instead of raising an error.
- **Working paper**: the period-end window, narration issue and matched keywords get their own
  columns; Manual matches the source values as the manual-entry test does; the cover states the
  year-end, weekend, holiday calendar, manual values, seldom threshold and large-amount rule,
  built from the run's parameters; dates without a time, a frozen header and filters; the Method
  sheet shows the rarities used.
- **Parameters**: `holiday_country` on `run_python_tests`; `weekend_days`, `manual_values` and
  the seldom threshold on `write_working_paper`. The README states the defaults (UAE holidays, a
  Saturday-Sunday weekend).
- **Guards**: tests check that every built-in test matches a prior key and that the README's top
  5 match the code. CI runs Python 3.10 to 3.14 and executes the demo notebook.
- **Reproducibility**: the benchmark records the library versions, and the "Amount only"
  baseline sorts ties stably.
- **Docs**: DESIGN's out-of-scope and post-closing paragraphs corrected (240R para A144); silent
  anomalies can only hit Benford by chance; the ledger size is 20,000 lines plus 50 double postings.

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
- **Benchmark re-run**: precision@82 is 0.838 ± 0.045 (0.837 ± 0.027 in 0.2.0), against
  0.647 for counting tests (0.750) and 0.519 for the Isolation Forest (0.641). The lead over
  counting tests grew mainly because counting tests got worse. With scarce anomalies the risk
  score is further from its ceiling than before (0.83 to 0.85, against about 0.9).
- **Docs**: README and DESIGN rewritten around the audit problem, with an "Audit context" table;
  the README's top-5 table is now printed by `scripts/make_fixtures.py`.

## 0.2.0

Multi-seed benchmark with ceilings, ablation and sweeps, an Isolation Forest baseline, and a
`Score Breakdown` column.

## 0.1.0

First version: the tests, consolidation on a row ID, the risk score and the mock IDEA exports.
