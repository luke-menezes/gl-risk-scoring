# Design notes

## The problem

ISA 240 presumes a risk that management overrides controls, so the auditor tests journal entries
whatever the risk assessment, and selects entries made at the end of the period among others. The
standard lists characteristics worth selecting on, such as manual entries, round numbers,
seldom-used accounts and entries with little or no description, but doesn't rank them. Each test
here looks for one characteristic, and each is simple and easy to explain, but noisy: weekend
postings happen, rent is a round number, payroll descriptions mention directors. Reviewing every
flagged line is impossible, and reviewing only lines hit by several tests misses the single rare
characteristic on a very large entry. The score ranks lines in a way an auditor can follow and
challenge, to help them select; selecting and concluding stay with the audit team. The README's
"Audit context" table maps each test to the standard.

Tests that **answer a risk** list entries the auditor can select from for a characteristic. Tests
that **describe the ledger** summarise it without pointing at entries (Benford conformity, the
account summary): they can be planning inputs, but they aren't findings.

## Score

For a line flagged by tests T:

    score = (sum of weight(t) over the non-date tests in T
             + max of weight(t) over the date tests in T) × amount multiplier

    weight(t)         = rarity(t) × prior(t)        (× Benford factor for Benford)
    rarity(t)         = -log10(lines flagged by t / lines in the ledger)
    amount multiplier = 1 + log10(1 + |amount| / median non-zero |amount|)

- **Rarity is per ledger.** The same test can be rare in one ledger and routine in the next, for
  example weekend postings in a business that trades on Saturdays. Log scale keeps one very rare
  test from swamping everything else.
- **Priors are per test, across ledgers.** They encode how often a test has turned out to matter.
  In practice they come from past engagements; here they are illustrative values in
  `scoring.DEFAULT_PRIORS`, matched by keyword in the test name, and can be overridden.
- **Date tests count once.** Weekend days, public holidays and period-end windows overlap for
  calendar reasons. Adding them would let the calendar outweigh a genuine signal, so a line
  gets only its strongest date test. Period end has a higher prior (1.0) than the other date
  tests (0.5), because the standard requires selecting period-end entries and doesn't for
  weekends.
- **Benford factor** = clip(distinct amounts / non-zero amounts / 0.5, 0.2, 1). Ledgers of repeated
  fixed prices fail Benford by construction; there the test says little about any one line.
- **Amount multiplier.** No hard materiality cut-off: a line ten times the median gets about
  ×2.0, a hundred times about ×3.0.

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

Every threshold, window and word list is practical judgement, and a parameter.

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
them at planning. Lines above performance materiality are always listed, after the top k and in
addition to it, and labelled. Nothing below clearly trivial is filtered out of any test: fraud can sit
in small entries, and splitting an amount into small entries is a known way round thresholds.
Materiality guides presentation, not what is tested. Both are off by default, so the score, the
amount multiplier and the benchmark don't use them.

## The working paper

`export.write_working_paper` writes the list as an Excel file an auditor can select and test from
and a reviewer can follow: a cover (source, parameters, population, whether the list is complete or
a top-k cut, the tests that couldn't run or were limited, lines a test couldn't read, blank
preparer and reviewer), the lines with a plain "why
selected" sentence and blank testing columns, and the method. The method sheet holds the weights
and is marked internal to the audit team, because selection criteria the client can predict
weaken the test.

## Priority list size

`clip(round(0.577 × √n), 20, 150)`. The square root means a ledger 100 times larger gets a list 10
times longer: bigger ledgers deserve more attention, but review time doesn't scale linearly. The
floor keeps small ledgers useful; the ceiling keeps the list reviewable. k = 0.577 gives 100 lines
at 30,000.

## Joining two tools on a row ID

Some tests are easier in IDEA (Benford, summaries, the duplicate dialog), others in Python. The
row ID is added once, as static values, before the ledger goes to either tool; both sides keep it
in every output. `flags.load_idea_flags` matches the ID column loosely (IDEA renames `Sr No` to
`SR_NO`) and normalises numeric IDs (`0000123`, `123.0` and `123` are the same). Consolidation
refuses IDs it can't find in the ledger, because a silent mismatch would drop flags.

## Evaluation

The synthetic ledger marks injected anomalies in an `Anomaly` column that no test reads; real
ledgers have no such labels. Most carry one to four signals, each a characteristic a test looks
for. A tenth are "silent": an unusually large amount on a common account, on a weekday, with
nothing for any test to find. They keep the recall ceiling below
1, as it would be on real ledgers, and give the Isolation Forest something the rules can't see.
`evaluate.run_once` generates a ledger, runs every test (the IDEA side in memory), scores it, and
measures precision and recall at k for:

- the risk score;
- three baselines (number of tests hit, amount only, a random order of the flagged lines);
- an Isolation Forest on simple line features;
- the five ablation variants;
- the ceiling.

`scripts/run_benchmark.py` repeats this over 30 seeds and sweeps the ledger size and anomaly rate.
The size sweep keeps about 1.2 anomalies per list place at every size, as in the 20,000-line
ledger. With a fixed rate instead, a large ledger has far more anomalies than list places and
every ranking looks perfect; a small one has too few to fill the list.

- **Several seeds**, because one ledger can be lucky. The standard deviation shows how far results
  move between ledgers.
- **The ceiling**, because recall and precision only mean something next to the best achievable:
  no ranking of flagged lines can find an anomaly that trips no test, and a list of k lines can't
  hold more anomalies than exist. The sweeps also report the share of ceiling (precision ÷ the
  best possible precision), so rows with different ceilings can be compared.
- **Ablation**, because each design choice should show what it is worth. On this data, rarity and
  the amount multiplier clearly help. The priors add about 2 points, within one standard
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

- **Scoring per journal (voucher), not per line.** A journal has at least two lines, so counting
  lines overstates, and auditors select and test whole vouchers; this needs a generator that
  writes multi-line journals.
- **Post-closing entries**, created or edited after the period end. The revised standard names
  manual adjusting entries made after the period closes, with little or no support, among the
  most susceptible (240R para A144); testing them needs a created-at column the generator
  doesn't have.

## Out of scope

Anything specific to one client's systems or file formats. The production tooling this is based on
also splits each test's results by debit and credit, analyses users, and writes run summaries;
those are left out to keep the code small enough to read in one sitting. The working paper here is
the only report.
