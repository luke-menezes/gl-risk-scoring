# Benchmark: the detail

The detail behind the README's results: which design choices earn their place, how the ranking holds
up across ledger sizes and anomaly rates, the robustness checks, the effect of voucher size, and the
figures from before scoring per voucher. Every figure is per voucher, the mean ± standard deviation
over 30 seeds unless stated, from `scripts/run_benchmark.py`; every run is in
[`benchmark.csv`](benchmark.csv) and the full tables in
[`benchmark_results.md`](benchmark_results.md).

## Which design choices earn their place

The same 30 ledgers, scored with one idea switched off at a time:

| Variant | Precision@50 | What it shows |
|---|---|---|
| Full risk score | 0.849 ± 0.052 | |
| Rarity only (all priors = 1) | 0.833 ± 0.052 | The illustrative priors add about 1.5 points, within one standard deviation: the synthetic data has no history for them to encode. Their job on real ledgers is to carry what past engagements showed |
| Priors only (no rarity) | 0.791 ± 0.059 | Per-ledger rarity is worth about 6 points |
| Date tests not collapsed | 0.850 ± 0.052 | No effect: the generator never puts a weekend and a period-end signal on the same anomaly, so few vouchers fall on two calendar signals at once. It matters where calendar tests pile up |
| No amount multiplier | 0.774 ± 0.064 | Lifting large vouchers is worth about 7.5 points |
| No Benford diversity scaling | 0.849 ± 0.052 | No effect: almost every synthetic amount is distinct, so the factor is already 1. It matters in ledgers of repeated fixed amounts |

## Sweeps

Share of ceiling is precision@k divided by the best possible precision@k, so rows with different
ceilings can be compared. The size sweep keeps about 1.2 anomalous vouchers per list place (as in the
default ledger), so it tests the ranking, not the ratio of anomalies to list places.

| Ledger | k | Risk score: precision@k (share of ceiling) | Tests hit: precision@k (share of ceiling) |
|---|---|---|---|
| 2,000 lines (about 740 vouchers, 23 anomalous) | 20 | 0.897 ± 0.068 (0.897) | 0.773 ± 0.092 (0.773) |
| 20,000 lines (about 7,550 vouchers, 60 anomalous) | 50 | 0.849 ± 0.052 (0.849) | 0.665 ± 0.058 (0.665) |
| 200,000 lines (about 75,700 vouchers, 181 anomalous; 10 seeds) | 150 | 0.787 ± 0.035 (0.787) | 0.549 ± 0.033 (0.549) |
| 20,000 lines, 0.2% of vouchers (15 anomalous) | 50 | 0.225 ± 0.015 (0.841) | 0.166 ± 0.032 (0.621) |
| 20,000 lines, 0.4% of vouchers (30 anomalous) | 50 | 0.456 ± 0.029 (0.823) | 0.325 ± 0.058 (0.585) |
| 20,000 lines, 1.6% of vouchers (120 anomalous, saturated) | 50 | 0.998 ± 0.008 (0.998) | 0.904 ± 0.042 (0.904) |

The bigger the ledger, the harder the ranking gets, and the risk score stays well ahead of
counting tests: 12 points of share of ceiling at 2,000 lines, 24 at 200,000. When anomalies are
scarce it reaches about 0.82 to 0.84 of the ceiling, against about 0.6 for counting tests. The 1.6%
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
| Risk score | 0.866 ± 0.097 (lowest 0.667) |
| Number of tests hit | 0.688 ± 0.125 (lowest 0.500) |

The risk score is ahead on all 30 ledgers, by 18 points on average and 6 at the least.

**Priors perturbed at random.** Each prior is multiplied by a random factor between 0.5 and 1.5,
20 times on each of the 30 ledgers. Precision@50 averages 0.822 ± 0.060 (0.849 with the
illustrative values; lowest draw 0.640), and on average 90% of the default list stays on it
(lowest 66%). Random priors do about as well as setting every prior to 1 (0.833 in the ablation):
the result rests on per-ledger rarity and the amount multiplier, not on the exact prior values.

**Caveat.** These checks vary the generator's settings, not its design: every anomaly is still one
the tests were built to look for, or a silent one. So the benchmark shows the method does what it
was designed to do, which parts matter, and that it doesn't hinge on hand-picked numbers. It isn't
evidence about real ledgers, where the irregular entries are unknown. The full tables are in
[`benchmark_results.md`](benchmark_results.md).

## Voucher size

**A voucher with more lines is flagged more often by chance.** Among normal vouchers, 38% of 2-line
vouchers meet at least one test, against 52% of 3-line and 57% of 4-line ones. The effect on the list
is small: 4-line vouchers are 19.9% of the vouchers and 21.3% of the priority list, 2-line vouchers
55.0% and 53.6%. The production tooling accepts this bias, since a longer journal also has more to
test; it is reported here rather than corrected.

## Before 0.6.0: scored per line

**Against 0.5 (scored per line).** The ledgers, the unit and the list size all changed, so the figures
aren't directly comparable. For the record, 0.5.1 and earlier, with 20,000 single lines, 0.5% of lines
anomalous and a list of 82 lines:

| Ranking (0.4.0 to 0.5.1, per line) | Precision@82 |
|---|---|
| Risk score | 0.846 ± 0.043 |
| Number of tests hit | 0.646 ± 0.056 |
| Isolation Forest | 0.511 ± 0.050 |

The risk score is about as precise per voucher as it was per line, and stays about 18 to 20 points
ahead of counting tests. The Isolation Forest does better per voucher (0.565 against 0.511), because
a voucher is listed by its most anomalous line, which gives it more chances.
