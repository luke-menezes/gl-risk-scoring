# Design notes

## The problem

ISA 240 presumes a risk that management overrides controls, so the auditor tests journal entries
whatever the risk assessment, and selects entries made at the end of the period among others. The
standard lists characteristics worth selecting on, such as manual entries, round numbers,
seldom-used accounts and entries with little or no description, but doesn't rank them. Each test
here looks for one characteristic, and each is simple and easy to explain, but noisy: weekend
postings happen, rent is a round number, payroll descriptions mention directors. Reviewing every
flagged line is impossible, and reviewing only lines hit by several tests misses the single rare
characteristic on a very large entry. The score ranks vouchers in a way an auditor can follow and
challenge, to help them select; selecting and concluding stay with the audit team. The README's
"Audit context" table maps each test to the standard.

Tests that **answer a risk** list entries the auditor can select from for a characteristic. Tests
that **describe the ledger** summarise it without pointing at entries (Benford conformity, the
account summary): they can be planning inputs, but they aren't findings.

## Score per voucher

Auditors select and test whole journals (vouchers), so the score ranks vouchers. `scoring.to_vouchers`
groups the consolidated lines by `Voucher No`: a voucher meets a test if any of its lines does, and its
amount is the larger of its total debits and total credits (a balanced voucher's debits). The fields a
voucher's lines share (date, users, source) are the voucher's, so the date, manual and same-user tests
are voucher facts; a seldom account, a keyword or a round amount may sit on one line only, and the
working paper says so ("1 of 3 lines"). Without a voucher column each line is its own voucher: the
per-line ranking of earlier versions, except that the amount multiplier divides by the median over
all non-zero lines rather than over flagged lines (see below).

A voucher with more lines has more chances to meet a test by chance. That bias is measured in the
benchmark and reported, not corrected: the production tooling accepts it, because a longer journal
also has more to test.

For a voucher flagged by tests T:

    score = (sum of weight(t) over the non-date tests in T
             + max of weight(t) over the date tests in T) × amount multiplier

    weight(t)         = rarity(t) × prior(t)        (× Benford factor for Benford)
    rarity(t)         = -log10(vouchers flagged by t / vouchers in the ledger)
    amount multiplier = 1 + log10(1 + voucher amount / median voucher amount)

- **Rarity is per ledger.** The same test can be rare in one ledger and routine in the next, for
  example weekend postings in a business that trades on Saturdays. Log scale keeps one very rare
  test from swamping everything else.
- **Priors are per test, across ledgers.** They encode how often a test has turned out to matter.
  In practice they come from past engagements; here they are illustrative values in
  `scoring.DEFAULT_PRIORS`, matched by keyword in the test name, and can be overridden.
- **Date tests count once.** Weekend days, public holidays and period-end windows overlap for
  calendar reasons. Adding them would let the calendar outweigh a genuine signal, so a voucher
  gets only its strongest date test. Period end has a higher prior (1.0) than the other date
  tests (0.5), because the standard requires selecting period-end entries and doesn't for
  weekends.
- **Benford factor** = clip(distinct amounts / non-zero amounts / 0.5, 0.2, 1), on the non-zero
  line amounts, which are what Benford tests. Ledgers of repeated fixed prices fail Benford by
  construction; there the test says little about any one entry. Voucher totals wouldn't do: a total
  that adds several legs varies even when every leg is a repeated fixed fee.
- **Amount multiplier.** No hard materiality cut-off: a voucher ten times the median gets about
  ×2.0, a hundred times about ×3.0. The median is over **all** vouchers with a non-zero amount, so
  it doesn't move when a test is added or a threshold changes. (Before 0.6.0 it was the median of
  the flagged lines; the benchmark's per-line baseline keeps that, as `score_flags` does when given
  lines directly.)

## The tests added in 0.3.0

- **Period end.** Quarters are counted from the financial year-end, not assumed to be calendar
  quarters. Each quarter end covers its last 3 and the next quarter's first 2 calendar days. The
  year-end window is wider, 5 working days either side, because that is where the closing entries
  are; it is counted in working days with the weekend test's weekend, so a weekend doesn't shorten
  it. The output says which window each line fell in: quarter end, year end, or the opening
  cut-off just after the prior year-end.
- **Manual entries.** "Manual" is a fact from the client's system, confirmed by the audit team
  (which sources or voucher types users key in), never a guess: without a source column the test
  doesn't run, and the outputs say so. When the column exists, the weekend, holiday and
  round-amount tests count manual lines only, because system postings on a Saturday or round
  system charges are routine.
- **No or vague narration.** Blank (including placeholders such as "n/a" and "-"), numbers only,
  fewer than 3 letters, or only generic words ("adj", "journal", "misc", ...). If more than half the
  lines are blank, the column isn't being used to explain entries: that is reported, and blank
  lines aren't flagged, unless the test is run on manual lines only.

Every threshold, window and word list is practical judgement, and a field of `RunSettings`. One
settings object goes to the tests and to the working paper, which prints it on the cover, so the
cover can't state a value the tests didn't use.

**Dates.** Ledger extracts often mix date formats. pandas guesses one format from the first value and
silently blanks values in any other format, so `rules.parse_dates` reads ISO dates first, then the
format pandas infers, then any remaining values one by one. Ambiguous dates are read day first by
default (02/03/2025 is 2 March, as in the UAE); `dayfirst=False` reads them month first. ISO dates
are read before the day-first pass because that pass would turn 2025-03-08 into 3 August. Numbers
from 20,000 to 80,000 are read as Excel serial dates, which is what a date cell holds when it loses
its format (45724 is 8 March 2025). Time-zone offsets are dropped, keeping the local date and time as
written: a ledger date is a local business date, and converting to UTC could move an entry onto
another day. Values that still can't be read are counted on the cover and skipped by the date tests.

## Population first

A test is only as good as its population. `population.roll_forward` checks, per account, that the
opening trial balance plus the ledger's movements equals the closing trial balance. Amounts are
rounded to their own decimals before comparing, with no other tolerance, and differences are
totalled as absolutes so they can't net off. A difference means the ledger may be incomplete: it
is resolved before any test or ranking, not explained away. Top-side adjustments made after the
trial balance, directly in the financial statements, never reach the ledger, so this check can't
show them.

## Materiality

`score_flags` takes optional `performance_materiality` and `clearly_trivial`, as the audit team set
them at planning. Vouchers whose amount is above performance materiality are always listed, after the top k and in
addition to it, and labelled. Nothing below clearly trivial is filtered out of any test: fraud can sit
in small entries, and splitting an amount into small entries is a known way round thresholds.
Materiality guides presentation, not what is tested. Both are off by default, so the score, the
amount multiplier and the benchmark don't use them.

## The working paper

`export.write_working_paper` writes the list as an Excel file an auditor can select and test from
and a reviewer can follow: a cover (source, settings, population, whether the list is complete or a
top-k cut, the tests that couldn't run or were limited, lines a test couldn't read, blank preparer
and reviewer), the vouchers with a plain "why selected" sentence and blank testing columns, every
line of those vouchers (flagged or not, so the tester sees the whole journal), and the method. The method sheet holds the weights
and is marked internal to the audit team, because selection criteria the client can predict
weaken the test.

## Priority list size

`clip(round(0.577 × √n), 20, 150)` for n vouchers. The square root means a ledger 100 times larger
gets a list 10 times longer: bigger ledgers deserve more attention, but review time doesn't scale linearly. The
floor keeps small ledgers useful; the ceiling keeps the list reviewable. k = 0.577 gives 100
vouchers at 30,000.

## Joining two tools on a row ID

Some tests are easier in IDEA (Benford, summaries, the duplicate dialog), others in Python. The
row ID is added once, as static values, before the ledger goes to either tool; both sides keep it
in every output. `flags.load_idea_flags` matches the ID column loosely (IDEA renames `Sr No` to
`SR_NO`) and normalises numeric IDs (`0000123`, `123.0` and `123` are the same). Consolidation
refuses IDs it can't find in the ledger, because a silent mismatch would drop flags.

## Evaluation

The synthetic ledger is made of balanced vouchers of 2 to 4 lines (55%, 25% and 20%), whose lines
share a date, users, source and narration. It marks the lines of injected anomalous vouchers in an
`Anomaly` column that no test reads; real ledgers have no such labels. Most carry one to four
signals, each a characteristic a test looks for: weekend, period end, manual and same user apply to
the whole voucher, a seldom account, keyword or vague narration to one line, and a round or 99 total
to the main line (and its counter line in a 2-line voucher). A tenth are "silent": an unusually large
amount on a common account, on a weekday, with nothing for any test to find. They keep the recall ceiling below
1, as it would be on real ledgers, and give the Isolation Forest something the rules can't see.
`evaluate.run_once` generates a ledger, runs every test (the IDEA side in memory), scores its
vouchers, and measures precision and recall at k, per voucher, for:

- the risk score;
- three baselines (number of tests hit, voucher amount only, a random order of the flagged vouchers);
- the lines scored on their own, each voucher listed where its first line appears, which shows
  whether scoring per voucher beats ranking lines;
- an Isolation Forest fitted on simple line features, each voucher listed where its most anomalous
  line appears;
- the five ablation variants;
- the ceiling.

`scripts/run_benchmark.py` repeats this over 30 seeds and sweeps the ledger size and anomaly rate.
The default anomaly rate (0.8% of vouchers) and the size sweep keep about 1.2 anomalous vouchers per
list place at every size. With a fixed rate instead, a large ledger has far more anomalies than list places and
every ranking looks perfect; a small one has too few to fill the list.

- **Several seeds**, because one ledger can be lucky. The standard deviation shows how far results
  move between ledgers.
- **The ceiling**, because recall and precision only mean something next to the best achievable:
  no ranking of flagged vouchers can find an anomaly that trips no test, and a list of k vouchers
  can't hold more anomalies than exist. The sweeps also report the share of ceiling (precision ÷ the
  best possible precision), so rows with different ceilings can be compared.
- **Ablation**, because each design choice should show what it is worth. On this data, rarity and
  the amount multiplier clearly help. The priors add about 1.5 points, within one standard
  deviation, and the date collapse and the Benford scaling make no difference. That is reported as
  it is: the generator has no history for priors to encode, rarely puts anomalies on two calendar
  signals at once, and produces almost no repeated amounts.
- **Robustness to the generator**, because the anomalies come from the generator the score was
  designed around. The stress sweep draws the generator's own settings at random for each seed
  (anomaly rate, share of silent anomalies, share of manual lines, and a `noise_scale` that
  multiplies every kind of background false positive) and compares the risk score with counting
  tests in share of ceiling, since the anomaly rate, and so the ceiling, changes from seed to seed.
  The ranges are practical judgement.
- **Prior sensitivity**, because the priors are illustrative. Every prior is multiplied by a random
  factor between 0.5 and 1.5, twenty times per seed, and the benchmark reports how precision moves
  and how much of the default list survives. A ranking that only worked with the exact values
  chosen would be fragile; one that barely moves shows the result doesn't rest on them.
- **Isolation Forest is unsupervised** and fitted with default settings on the ledger itself.
  Tuning it on the injected labels would turn it into a supervised model and an unfair comparison.

What the evaluation shows is whether the scoring does what it was designed to do, on data built
for that purpose. It isn't evidence about real ledgers, where the anomalies are unknown.

## Not done yet

- **Post-closing entries**, created or edited after the period end. The revised standard names
  manual adjusting entries made after the period closes, with little or no support, among the
  most susceptible (240R para A144); testing them needs a created-at column the generator
  doesn't have.

## Out of scope

Anything specific to one client's systems or file formats. The production tooling this is based on
also splits each test's results by debit and credit, analyses users, and writes run summaries;
those are left out to keep the code small enough to read in one sitting. The working paper here is
the only report.
