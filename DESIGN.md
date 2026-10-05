# Design notes

## The problem

Each journal test is simple and easy to explain to an auditor, but each is noisy: weekend
postings happen, rent is a round number, payroll descriptions mention directors. Reviewing every
flag is impossible, and reviewing only lines hit by several tests misses the single rare flag on
a very large entry. The score has to rank lines in a way an auditor can follow and challenge.

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
  gets only its strongest date test.
- **Benford factor** = clip(distinct amounts / non-zero amounts / 0.5, 0.2, 1). Ledgers of repeated
  fixed prices fail Benford by construction; there the test says little about any one line.
- **Amount multiplier.** No hard materiality cut-off: a line ten times the median gets about
  ×2.0, a hundred times about ×3.0.

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

The synthetic ledger marks injected anomalies in an `Anomaly` column that no test reads.
`evaluate.run_once` generates a ledger, runs every test (the IDEA side in memory), scores it, and
measures precision and recall at k for:

- the risk score;
- three baselines (number of tests hit, amount only, a random order of the flagged lines);
- an Isolation Forest on simple line features;
- the five ablation variants;
- the ceiling.

`scripts/run_benchmark.py` repeats this over 30 seeds and sweeps the ledger size and anomaly rate.

- **Several seeds**, because one ledger can be lucky. The standard deviation shows how far results
  move between ledgers.
- **The ceiling**, because recall and precision only mean something next to the best achievable:
  no ranking of flagged lines can find an anomaly that trips no test, and a list of k lines can't
  hold more anomalies than exist.
- **Ablation**, because each design choice should show what it is worth. On this data, rarity and
  the amount multiplier clearly help. The priors, the date collapse and the Benford scaling make
  no difference. That is reported as it is: the generator has no history for priors to encode,
  rarely puts anomalies on two calendar signals at once, and produces almost no repeated amounts.
- **Isolation Forest is unsupervised** and fitted with default settings on the ledger itself.
  Tuning it on the injected labels would turn it into a supervised model and an unfair comparison.

What the evaluation shows is whether the scoring does what it was designed to do, on data built
for that purpose. It isn't evidence about real ledgers, where the anomalies are unknown.

## Out of scope

Reporting, and anything specific to one client's systems or file formats. The production tooling
this is based on also handles debit/credit splits per test, configurable weekends, user analysis
and run summaries; those are left out to keep the code small enough to read in one sitting.
