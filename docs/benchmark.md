# Benchmark: the detail

The detail behind the README's results: which design choices earn their place, how the ranking holds
up across ledger sizes and anomaly rates, the robustness checks, the effect of voucher size, and the
figures from before batch vouchers and before scoring per voucher. Every figure is per voucher, the mean ± standard deviation
over 30 seeds unless stated, from `scripts/run_benchmark.py`; every run is in
[`benchmark.csv`](benchmark.csv) and the full tables in
[`benchmark_results.md`](benchmark_results.md).

## Which design choices earn their place

The same 30 ledgers, scored with one idea switched off at a time:

| Variant | Precision@50 | What it shows |
|---|---|---|
| Full risk score | 0.825 ± 0.046 | |
| Rarity only (all priors = 1) | 0.812 ± 0.044 | The illustrative priors add about 1.3 points, within one standard deviation: the synthetic data has no history for them to encode. Their job on real ledgers is to carry what past engagements showed |
| Priors only (no rarity) | 0.790 ± 0.045 | Per-ledger rarity is worth about 3.5 points |
| Date tests not collapsed | 0.827 ± 0.048 | No effect: the generator never puts a weekend and a period-end signal on the same anomaly, so few vouchers fall on two calendar signals at once. It matters where calendar tests pile up |
| No amount multiplier | 0.765 ± 0.059 | Lifting large entries is worth about 6 points |
| No Benford diversity scaling | 0.825 ± 0.046 | No effect: almost every synthetic amount is distinct, so the factor is already 1. It matters in ledgers of repeated fixed amounts |
| Whole-voucher amount in the multiplier | 0.786 ± 0.049 | Sizing the multiplier on the largest flagged line is worth about 4 points (ahead on 27 of the 30 ledgers, behind on none): with the whole voucher's amount, batch vouchers flagged on a few small lines are lifted by their total (see "Voucher size") |

## Sweeps

Share of ceiling is precision@k divided by the best possible precision@k, so rows with different
ceilings can be compared. The size sweep keeps about 1.2 anomalous vouchers per list place (as in the
default ledger), so it tests the ranking, not the ratio of anomalies to list places.

| Ledger | k | Risk score: precision@k (share of ceiling) | Tests hit: precision@k (share of ceiling) |
|---|---|---|---|
| 2,000 lines (about 740 vouchers, 23 anomalous) | 20 | 0.863 ± 0.088 (0.863) | 0.720 ± 0.113 (0.720) |
| 20,000 lines (about 7,550 vouchers, 60 anomalous) | 50 | 0.825 ± 0.046 (0.825) | 0.659 ± 0.056 (0.659) |
| 200,000 lines (about 75,700 vouchers, 181 anomalous; 10 seeds) | 150 | 0.761 ± 0.022 (0.761) | 0.449 ± 0.050 (0.449) |
| 20,000 lines, 0.2% of vouchers (15 anomalous) | 50 | 0.224 ± 0.021 (0.847) | 0.161 ± 0.035 (0.607) |
| 20,000 lines, 0.4% of vouchers (30 anomalous) | 50 | 0.459 ± 0.039 (0.822) | 0.348 ± 0.038 (0.623) |
| 20,000 lines, 1.6% of vouchers (120 anomalous, saturated) | 50 | 0.989 ± 0.015 (0.989) | 0.845 ± 0.053 (0.845) |

The line counts are the generator's setting; batch vouchers add about 4% to each ledger. The bigger
the ledger, the harder the ranking gets, and the risk score stays well ahead of counting tests: 14
points of share of ceiling at 2,000 lines, 31 at 200,000. When anomalies are scarce it reaches about
0.82 to 0.85 of the ceiling, against about 0.6 for counting tests. The 1.6%
row is saturated (more anomalies than list places), so it says little about the ranking.

## Is it just the generator agreeing with itself?

The anomalies come from the same generator the scoring was designed around, so two checks test how
much the result depends on the generator's settings and on the illustrative priors.

**Generator settings drawn at random.** For each of 30 ledgers the anomaly rate (0.3% to 1.6% of
vouchers), the share of silent anomalies (5% to 25%), the share of manual vouchers (5% to 30%) and the
amount of background noise (half to double every kind of false positive) are drawn at random. Results
are in share of ceiling, because the anomaly rate, and so the best possible precision, changes between
ledgers.

| Ranking | Share of ceiling at k = 50 |
|---|---|
| Risk score | 0.841 ± 0.119 (lowest 0.556) |
| Number of tests hit | 0.628 ± 0.137 (lowest 0.333) |

The risk score is ahead on all 30 ledgers, by 21 points on average and 6 at the least.

**Priors perturbed at random.** Each prior is multiplied by a random factor between 0.5 and 1.5,
20 times on each of the 30 ledgers. Precision@50 averages 0.803 ± 0.051 (0.825 with the
illustrative values; lowest draw 0.640), and on average 90% of the default list stays on it
(lowest 68%). Random priors do about as well as setting every prior to 1 (0.812 in the ablation):
the result rests on per-ledger rarity and the amount multiplier, not on the exact prior values.

**Caveat.** These checks vary the generator's settings, not its design: every anomaly is still one
the tests were built to look for, or a silent one. So the benchmark shows the method does what it
was designed to do, which parts matter, and that it doesn't hinge on hand-picked numbers. It isn't
evidence about real ledgers, where the irregular entries are unknown. The full tables are in
[`benchmark_results.md`](benchmark_results.md).

## Voucher size

**A voucher with more lines is flagged more often by chance.** Among normal vouchers, 38% of 2-line
vouchers meet at least one test, against 53% of 3-line and 59% of 4-line ones, and 98% of the batch
vouchers (20 to 60 lines). Among the ordinary sizes the effect on the list is small: 2-line vouchers
are 54.8% of the vouchers and 50.5% of the suggested list, 4-line vouchers 19.9% and 17.9%. Batch
vouchers are another matter: 0.3% of the vouchers but 9.1% of the list. They meet tests on different
lines by chance (a duplicate on one, a 99 ending on another), and the voucher score adds those
together. Sizing the amount multiplier on the whole voucher made it worse (17.9% of the list), which
is why it is sized on the largest flagged line. The rest of the bias is accepted, as in the
production tooling, since a longer journal also has more to test, and reported rather than
corrected; it is why the per-line baseline is now slightly ahead (README, "Results").

## Before 0.8.0: no batch vouchers

Up to 0.7.0 the generator made only vouchers of 2 to 4 lines, and the multiplier sized the whole
voucher. On those ledgers: risk score 0.849 ± 0.052, the per-line baseline 0.852 ± 0.053 (a tie),
counting tests 0.665 ± 0.058, Isolation Forest 0.565 ± 0.079. Adding the batch vouchers cost the
risk score about 6 points with the whole-voucher amount (0.786); sizing on the largest flagged line
won back about 4 (0.825).

## Before 0.6.0: scored per line

**Against 0.5 (scored per line).** The ledgers, the unit and the list size all changed, so the figures
aren't directly comparable. For the record, 0.5.1 and earlier, with 20,000 single lines, 0.5% of lines
anomalous and a list of 82 lines:

| Ranking (0.4.0 to 0.5.1, per line) | Precision@82 |
|---|---|
| Risk score | 0.846 ± 0.043 |
| Number of tests hit | 0.646 ± 0.056 |
| Isolation Forest | 0.511 ± 0.050 |

On the 0.7.0 ledgers (without batch vouchers) the risk score was about as precise per voucher as it
was per line, about 18 to 20 points ahead of counting tests. The Isolation Forest does better per
voucher (0.565 in 0.7.0 against 0.511), because
a voucher is listed by its most anomalous line, which gives it more chances.
