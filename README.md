# gl-risk-scoring

[![tests](https://github.com/luke-menezes/gl-risk-scoring/actions/workflows/tests.yml/badge.svg)](https://github.com/luke-menezes/gl-risk-scoring/actions/workflows/tests.yml)
![Python 3.10-3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
[![MIT licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

**Ranking flagged journal entries for audit review, on synthetic general ledgers.**

On synthetic ledgers, the top-82 list is 88.5% precise (± 3.2 points over 30 seeds), against
79.1% for counting how many tests each line hits and 69.3% for an Isolation Forest.

Journal entry testing in an audit runs a set of simple tests over the general ledger: weekend
postings, round amounts, suspicious keywords, Benford's Law, seldom-used accounts, duplicates,
segregation of duties. On a typical ledger these flag thousands of lines, often a fifth of the
ledger, far more than anyone can review. This project combines every test's flags on a row ID and
ranks the lines with a transparent score, so the review starts with the entries most likely to
matter, and each line on the list shows why it is there.

![Precision at k](docs/precision_at_k.png)

## Pipeline

```mermaid
flowchart LR
    A[Ledger] --> B["Tag row ID<br/>(Sr No)"]
    B --> C["Python tests<br/>keywords, round, 99/999,<br/>weekend, holidays"]
    B --> D["IDEA macro<br/>Benford, seldom accounts,<br/>duplicates, SoD"]
    D --> E["Excel exports<br/>(keep SR_NO)"]
    C --> F["Consolidate<br/>on row ID"]
    E --> F
    F --> G["Score<br/>rarity × prior,<br/>× amount"]
    G --> H["Priority list<br/>0.577·√n, 20-150"]
```

## Key design decisions

- **One row ID, tagged before the split.** The ledger gets a running number (`Sr No`) before the
  same file goes to Caseware IDEA and to Python. Every IDEA export keeps it, so the results join
  exactly. A hash of the row wouldn't work: identical duplicate lines would share it. Matching on
  date, account and amount fails for the same reason. See [`idea/README.md`](idea/README.md).
- **Weight = ledger rarity × prior.** Rarity is `-log10(share of the ledger flagged)`, so a test
  that flags 0.2% of lines counts much more than one that flags 12%. The prior carries what the
  test has been worth across past ledgers; the values here are illustrative.
- **Correlated tests count once.** A Saturday that is also a public holiday is one calendar signal,
  not two, so only the strongest date test counts for each line.
- **Benford scaled by amount diversity.** In ledgers full of repeated amounts, Benford failures are
  expected and carry little information, so its weight shrinks with the share of distinct amounts.
- **Amount as a log multiplier.** `1 + log10(1 + amount / median)`: large lines rise without a hard
  cut-off, and one rare flag on a very large entry can still make the list.
- **List size grows with √n.** `clip(0.577·√n, 20, 150)`: about 100 lines for a 30,000-line
  ledger, never more than a reviewer can work through.

More detail in [`DESIGN.md`](DESIGN.md).

## Results on synthetic data

Each ledger has 20,000 lines with 0.5% injected anomalies; each anomaly carries one to four red
flags and a larger amount. Alongside them is normal business that trips the tests anyway: round
rent payments, director fees, a fixed-price supplier, weekend postings and double postings. The
priority list is 82 lines. Figures are the mean ± standard deviation over 30 seeds (30 different
ledgers), from `scripts/run_benchmark.py`; every run is in
[`docs/benchmark.csv`](docs/benchmark.csv), and the full tables are in
[`docs/benchmark_results.md`](docs/benchmark_results.md).

| Ranking | Precision@82 | Recall@82 |
|---|---|---|
| **Risk score** | **0.885 ± 0.032** | **0.726 ± 0.026** |
| Number of tests hit | 0.791 ± 0.034 | 0.649 ± 0.028 |
| Isolation Forest (unsupervised, line features) | 0.693 ± 0.057 | 0.569 ± 0.047 |
| Amount only | 0.384 ± 0.056 | 0.315 ± 0.046 |
| Random flagged lines | 0.026 ± 0.016 | 0.021 ± 0.013 |
| Ceiling: best any ranking of flagged lines can do | 1.000 | 1.000 |

How to read the ceiling: recall can't exceed the share of anomalies that trip at least one test,
and precision can't exceed that count divided by k. Here every injected anomaly trips a test, so
the ceiling is 1; on real ledgers some irregular entries trip no test at all, and no ranking can
find them. With 100 anomalies and a list of 82, recall can be at most 0.82 in any case.

### Which design choices earn their place

The same 30 ledgers, scored with one idea switched off at a time:

| Variant | Precision@82 | What it shows |
|---|---|---|
| Full risk score | 0.885 ± 0.032 | |
| Rarity only (all priors = 1) | 0.892 ± 0.029 | The illustrative priors add nothing here: the synthetic data has no history for them to encode. Their job on real ledgers is to carry what past engagements showed |
| Priors only (no rarity) | 0.816 ± 0.036 | Rarity is the main driver: per-ledger rarity is worth about 7 points |
| Date tests not collapsed | 0.885 ± 0.032 | No effect: few injected anomalies fall on a weekend *and* a holiday. It matters where calendar tests pile up (weekend holidays, period ends) |
| No amount multiplier | 0.828 ± 0.039 | Lifting large entries is worth about 6 points |
| No Benford diversity scaling | 0.885 ± 0.032 | No effect: almost every synthetic amount is distinct, so the factor is already 1. It matters in ledgers of repeated fixed amounts |

### Sweeps

| Ledger | Risk score precision@k | Tests-hit precision@k | Ceiling |
|---|---|---|---|
| 2,000 lines, 0.5% (k = 26) | 0.354 ± 0.034 | 0.297 ± 0.048 | 0.385 |
| 20,000 lines, 0.2% (k = 82) | 0.429 ± 0.023 | 0.359 ± 0.038 | 0.488 |
| 20,000 lines, 1.0% (k = 82) | 1.000 ± 0.000 | 0.991 ± 0.017 | 1.000 |
| 200,000 lines, 0.5% (k = 150, 10 seeds) | 1.000 ± 0.000 | 0.999 ± 0.002 | 1.000 |

When anomalies are scarce relative to the list, the risk score gets close to the ceiling and
stays ahead of counting tests. When there are more anomalies than list places (1%, or 1,000
anomalies in 200,000 lines), any sensible ranking fills the list with them, so these settings
can't separate the methods.

**Caveat.** The anomalies come from the same generator the scoring was designed around, so this
shows the method does what it was designed to do, and which parts matter. It isn't evidence about
real ledgers, where the irregular entries are unknown.

### Why each line is on the list

`score_flags` adds a `Score Breakdown` column. The top 5 of the seed-0 list (synthetic
descriptions):

| Sr No | Description | Amount | Score | Score Breakdown |
|---|---|---|---|---|
| 12951 | Write off - settlement | 130,000 | 39.8 | Seldom Account Entries 6.8 + Suspicious Keyword 3.5 + Rounded Amount 2.9 + SoD Violation Entries 2.6, × amount 2.52 |
| 16355 | Cash advance, no invoice | 130,000 | 35.8 | Seldom Account Entries 6.8 + Suspicious Keyword 3.5 + Rounded Amount 2.9 + date (Saturday) 1.0, × amount 2.52 |
| 14020 | Consultancy fee (related party) | 75,999 | 35.0 | Seldom Account Entries 6.8 + Ending 99/999 3.9 + Suspicious Keyword 3.5 + date (Sunday) 1.0, × amount 2.29 |
| 4026 | Utility bill | 150,000 | 34.5 | Seldom Account Entries 6.8 + Rounded Amount 2.9 + SoD Violation Entries 2.6 + date (Saturday) 1.0, × amount 2.58 |
| 3648 | Adjustment per director | 54,999 | 33.0 | Seldom Account Entries 6.8 + Ending 99/999 3.9 + Suspicious Keyword 3.5 + date (Saturday) 1.0, × amount 2.16 |

## Why not a trained model?

- **Real audits have no labels.** Nobody hands the auditor a column saying which entries were
  fraudulent, so there is nothing to train a supervised model on. The Isolation Forest above needs
  no labels, but it ranks the lines below the risk score.
- **Auditors have to explain the selection.** A reviewer must be able to say why a line was
  picked, and the score breakdown does that directly. An anomaly score from a model doesn't.
- **Future work: learn the priors.** Reviewer outcomes (which listed lines turned out to be issues)
  are labels. With enough of them, the priors could be learned, for example with a logistic
  regression on the test columns. That isn't done here.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,ml]"                             # [ml] adds scikit-learn for the Isolation Forest
pytest
jupyter notebook notebooks/demo.ipynb
python scripts/run_benchmark.py                        # about 10 minutes; --quick for a smoke test
```

```python
from glrisk import flags, pipeline, scoring, synthetic

ledger = synthetic.make_ledger(20_000, seed=0)
amount_cols = synthetic.amount_columns(ledger)
flagged = flags.consolidate(ledger,
                            pipeline.run_python_tests(ledger, amount_cols),
                            flags.load_idea_flags("fixtures/idea_exports"))
priority = scoring.score_flags(flagged, amount_cols)          # top 0.577·√n lines, with Score Breakdown
```

`fixtures/idea_exports` holds mock IDEA exports made from the same seeded ledger
(`scripts/make_fixtures.py`), so everything runs without an IDEA licence. With IDEA, run
[`idea/portfolio_sample.ism`](idea/portfolio_sample.ism) and point `load_idea_flags` at the
project's `Exports.ILB` folder.

## Layout

| Path | Contents |
|---|---|
| `src/glrisk/synthetic.py` | Ledger generator with injected anomalies (ground truth) |
| `src/glrisk/rules.py` | The tests: keywords, round, 99/999, day of week, public holidays, duplicates, seldom accounts, segregation of duties |
| `src/glrisk/benford.py` | First-digit test, MAD conformity, entries behind over-represented digits |
| `src/glrisk/flags.py` | Flag logs, IDEA export loader, consolidation on the row ID |
| `src/glrisk/scoring.py` | Weights, date tests counted once, amount multiplier, list size, score breakdown |
| `src/glrisk/evaluate.py` | Rankings, ceilings, precision and recall at k, multi-seed runs and ablation |
| `src/glrisk/ml_baseline.py` | Isolation Forest baseline (optional `[ml]` extra) |
| `src/glrisk/pipeline.py` | Runs the Python tests; computes and writes the mock IDEA exports |
| `src/glrisk/plots.py` | The demo and benchmark charts |
| `scripts/` | Fixture builder and the benchmark |
| `idea/` | IDEAScript sample and the cross-tool design |

## What I'd do next

- **Learn the priors from reviewer outcomes**, once enough reviewed lists exist (see above).
- **Client-specific baselines**: compare each test's rate with the same client's prior years, not
  only with the current ledger.
- **A content hash key** for matching extracts pulled independently from a client's system, where a
  shared running number isn't possible.

## About this project

I built tooling like this in my work as a data analyst. This repository is a reduced, sanitised
version on synthetic data. The production tooling and all client data stay private, and the
scoring priors here are illustrative.

MIT licence.
