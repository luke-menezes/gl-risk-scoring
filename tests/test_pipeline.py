from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

from glrisk import benford, evaluate, export, flags, pipeline, population, rules, scoring, synthetic
from glrisk.settings import RunSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "idea_exports"


@pytest.fixture(scope="module")
def ledger():
    return synthetic.make_ledger(5_000, seed=1)


# --- synthetic ledger ---

def test_ledger_layouts_and_ground_truth(ledger):
    assert ledger["Sr No"].is_unique and ledger["Sr No"].min() == 1
    assert {"Debit", "Credit"} <= set(ledger.columns)
    assert ((ledger["Debit"] == 0) | (ledger["Credit"] == 0)).all()
    vouchers = ledger.groupby("Voucher No")
    assert vouchers.size().between(2, 4).all()
    assert ((ledger["Debit"] - ledger["Credit"]).groupby(ledger["Voucher No"]).sum().abs() < 1e-6).all()   # balanced
    shared = ["Date", "Created By", "Approved By", "Source", "Anomaly"]
    assert (vouchers[shared].nunique() == 1).all().all()           # header fields are the voucher's
    assert (vouchers["Anomaly"].first() != "").sum() == 15          # 0.8% of about 1,890 vouchers
    signed = synthetic.make_ledger(1_000, layout="signed", seed=1)
    assert "Amount" in signed.columns and (signed["Amount"] < 0).any()
    with pytest.raises(ValueError):
        synthetic.make_ledger(10, layout="other")


def test_silent_anomalies_carry_no_signal(ledger):
    silent = ledger[ledger["Anomaly"] == "silent"]
    assert silent["Voucher No"].nunique() == 2          # 10% of 15, rounded
    amt = synthetic.amount_columns(ledger)
    # Silent anomalies are system lines, so the manual-only tests (weekend, holiday, round) can't
    # reach them; only Benford's first digit can hit one by chance
    log = {**pipeline.run_python_tests(ledger, amt, RunSettings(manual_only=True)), **pipeline.idea_side_flags(ledger, amt)}
    silent_ids = flags.id_set(silent["Sr No"])
    assert {test for test, ids in log.items() if ids & silent_ids} <= {"Benford"}
    assert (pd.to_datetime(silent["Date"]).dt.dayofweek < 5).all()
    assert (synthetic.make_ledger(5_000, seed=1, silent_share=0)["Anomaly"] == "silent").sum() == 0


def test_same_seed_same_ledger():
    pd.testing.assert_frame_equal(synthetic.make_ledger(500, seed=3), synthetic.make_ledger(500, seed=3))


# --- tests (rules) ---

def small():
    return pd.DataFrame({
        "Sr No": [1, 2, 3, 4, 5, 6],
        "Voucher No": ["V1", "V2", "V3", "V4", "V5", "V6"],     # one line each
        "Date": pd.to_datetime(["2025-03-03", "2025-03-08", "2025-03-09", "2025-12-02", "2025-03-03", "2025-03-04"]),
        "Account": ["Cash", "Cash", "Rare", "Cash", "Cash", "Cash"],
        "Description": ["Rent", "Write off per director", "Adjusted", "Fees", "Rent", "Reversal"],
        "Created By": ["a", "b", " A ", "c", "a", None],
        "Approved By": ["m", "B", "a", "m", "m", None],
        "Source": ["System", "Manual", "System", "Manual", "manual ", "System"],
        "Amount": [20_000.0, 1_999.0, 123.45, 0.0, 20_000.0, 50.0],
    })


def test_amount_rules():
    df = small()
    assert rules.rounded_amounts(df, ["Amount"])["Sr No"].tolist() == [1, 5]
    assert rules.ending_99(df, ["Amount"])["Sr No"].tolist() == [2]
    # Amounts with cents never end in 99, however large; float noise from imports doesn't matter
    amounts = pd.DataFrame({"Sr No": range(5), "Amount": [35_599.30, 199.50, 1_999.00, 250_999.00, 29_999.999999]})
    assert rules.ending_99(amounts, ["Amount"])["Sr No"].tolist() == [2, 3]
    assert rules.rounded_amounts(amounts, ["Amount"])["Sr No"].tolist() == [4]


def test_date_rules():
    df = small()
    assert rules.day_of_week(df, "Date", ["Amount"], "Saturday")["Sr No"].tolist() == [2]
    assert rules.day_of_week(df, "Date", ["Amount"], "sunday")["Sr No"].tolist() == [3]
    # 2 December is UAE National Day, but that line is zero-value
    assert rules.public_holidays(df, "Date", ["Amount"]).empty
    with pytest.raises(ValueError):
        rules.day_of_week(df, "Date", ["Amount"], "Funday")


def test_period_end_windows():
    dates = pd.Series(pd.to_datetime(["2025-03-28", "2025-03-29", "2025-04-02", "2025-04-03", "2025-12-24",
                                      "2025-12-27", "2025-01-07", "2025-01-08"]))
    assert rules.period_end_labels(dates).tolist() == [
        "", "Quarter end", "Quarter end", "", "", "Year end", "Opening cut-off", ""]
    # 5 working days either side of 31 December, so the weekend of 27-28 December is inside the window
    # (from Thursday 25 December) and the opening cut-off runs to 7 January; a June year-end moves them
    june = rules.period_end_labels(pd.Series(pd.to_datetime(["2025-12-30", "2025-06-24", "2025-03-31"])), 6)
    assert june.tolist() == ["Quarter end", "Year end", "Quarter end"]


def test_manual_entries_and_manual_only_tests():
    df = small()
    assert rules.manual_entries(df)["Sr No"].tolist() == [2, 4, 5]
    log = pipeline.run_python_tests(df, ["Amount"])
    assert log["Manual Entry"] == {"2", "4", "5"}
    assert log["Rounded Amount"] == {"5"} and log["Saturday"] == {"2"} and log["Sunday"] == set()   # manual only
    everything = pipeline.run_python_tests(df, ["Amount"], RunSettings(manual_only=False))
    assert everything["Rounded Amount"] == {"1", "5"} and everything["Sunday"] == {"3"}
    no_source = df.drop(columns=["Source"])
    assert "Manual Entry" not in pipeline.run_python_tests(no_source, ["Amount"])
    assert pipeline.tests_not_run(no_source) == ["Manual entries not tested: no Source column."]
    assert pipeline.tests_not_run(df) == []


def test_missing_columns():
    ledger = synthetic.make_ledger(1_000, seed=0).drop(columns=["Description", "Approved By"])
    amt = synthetic.amount_columns(ledger)
    log = pipeline.run_python_tests(ledger, amt)
    assert "Keyword Match" not in log and "No or Vague Narration" not in log and "Rounded Amount" in log
    assert pipeline.tests_not_run(ledger, amount_cols=amt) == [
        "Created and approved by the same user not tested: no Approved By column.",
        "No or vague narration not tested: no Description column.",
        "Keyword match not tested: no Description column.",
        "Duplicate test limited: no Description column, so lines are matched without it."]
    assert "Duplicate" in pipeline.idea_side_flags(ledger, amt)
    pytest.importorskip("sklearn")
    from glrisk.ml_baseline import line_features
    assert (line_features(ledger, amt)[["keyword", "narration", "same_user"]] == 0).all().all()


def test_unreadable_values_are_stated():
    df = small().astype({"Date": object, "Amount": object})
    df.loc[0, "Date"], df.loc[1, "Amount"], df.loc[2, "Amount"] = "31/02/2025", "1,999.0x", " "
    assert pipeline.tests_not_run(df, amount_cols=["Amount"]) == [
        "Lines with a missing or unreadable date, not covered by the date tests: 1.",
        "Lines with an unreadable amount, treated as zero and skipped by the amount and date tests: 1."]


def test_mixed_date_formats():
    # pandas alone guesses one format from the first value and blanks the rest; ambiguous dates read day first
    dates = rules.parse_dates(pd.Series(["13/01/2025", "2025-03-08", "31/02/2025", None]))
    assert dates.tolist()[:2] == [pd.Timestamp("2025-01-13"), pd.Timestamp("2025-03-08")] and dates[2:].isna().all()
    ambiguous = pd.Series(["2025-01-31", "02/03/2025"])
    assert rules.parse_dates(ambiguous)[1] == pd.Timestamp("2025-03-02")
    assert rules.parse_dates(ambiguous, dayfirst=False)[1] == pd.Timestamp("2025-02-03")
    df = small().assign(Date=lambda d: d["Date"].dt.strftime("%Y-%m-%d"))
    df.loc[1, "Date"] = "08/03/2025"          # Saturday 8 March, in another format
    assert pipeline.run_python_tests(df, ["Amount"])["Saturday"] == {"2"}
    assert pipeline.tests_not_run(df, ["Amount"]) == []


def test_dates_that_used_to_crash():
    def read(*values):
        return rules.parse_dates(pd.Series(values, dtype=object)).tolist()
    ts = pd.Timestamp
    assert read("08/03/2025 14:05:33.123456", "13/01/2025", 45724, "45724.5") == [
        ts("2025-03-08 14:05:33.123456"), ts("2025-01-13"), ts("2025-03-08"), ts("2025-03-08 12:00")]
    # Offsets dropped, local time kept: neither entry moves to another day
    assert read("2025-03-08T23:30:00+04:00", "2025-03-08T23:30:00-05:00") == [ts("2025-03-08 23:30")] * 2
    assert read("20250308")[0] == ts("2025-03-08") and pd.isna(read(12345, 1.5)).all()
    # A whole ledger with its dates as Excel serial numbers gives the same Saturday hits
    ledger = synthetic.make_ledger(5_000, seed=1)
    serial = ledger.assign(Date=(ledger["Date"] - ts("1899-12-30")).dt.days)
    amt = synthetic.amount_columns(ledger)
    assert pipeline.run_python_tests(serial, amt)["Saturday"] == pipeline.run_python_tests(ledger, amt)["Saturday"]
    assert pipeline.tests_not_run(serial, amt) == []
    pytest.importorskip("sklearn")
    from glrisk.ml_baseline import line_features
    mixed = ledger.assign(Date=ledger["Date"].dt.strftime("%d/%m/%Y").where(ledger.index % 2 == 0, serial["Date"]))
    assert line_features(mixed, amt)["day_of_week"].tolist() == line_features(ledger, amt)["day_of_week"].tolist()


def test_settings_reach_the_tests_and_the_cover(tmp_path):
    df, settings = small(), RunSettings(manual_values=("System",), seldom_max_entries=5)
    log = pipeline.run_python_tests(df, ["Amount"], settings)
    idea = pipeline.idea_side_flags(df, ["Amount"], settings)
    assert log["Manual Entry"] == {"1", "3", "6"} and idea["Seldom Account Entries"] == {str(i) for i in range(1, 7)}
    assert pipeline.idea_side_flags(df, ["Amount"])["Seldom Account Entries"] == {"3"}
    lines = flags.consolidate(df, log, idea, min_flags=0)
    priority = scoring.score_flags(scoring.to_vouchers(lines, ["Amount"], settings), ["Voucher Amount"], top_n=None)
    path = export.write_working_paper(priority, lines, tmp_path / "wp.xlsx", ["Amount"], "small", settings=settings)
    cover = dict(pd.read_excel(path, sheet_name="Cover").to_numpy())
    assert cover["Parameter: Manual entries"] == "Source is System (case ignored)"
    assert cover["Parameter: Seldom-used account"].startswith("5 entries or fewer (with real IDEA exports")
    lines = pd.read_excel(path, sheet_name="Lines")
    assert (lines["Manual"] == "Yes").tolist() == (lines["Source"] == "System").tolist()
    # A custom duplicate key reaches the duplicate test and the cover
    moved, by_account = small(), RunSettings(duplicate_key=("Account", "Description"))
    moved.loc[4, "Date"] = pd.Timestamp("2025-03-05")     # line 5 now differs from line 1 only by date
    assert pipeline.idea_side_flags(moved, ["Amount"])["Duplicate"] == set()
    assert pipeline.idea_side_flags(moved, ["Amount"], by_account)["Duplicate"] == {"1", "5"}
    assert by_account.cover()["Duplicate key"] == "Account, Description and the amount"


def test_narration():
    df = pd.DataFrame({"Sr No": range(10), "Text": ["", "n/a", "104522", "JV", "Being adjustment entry",
                                                    "Accrual", "Ab", None, "Rent 2025", "Supplier payment"]})
    hits = rules.narration(df, "Text")
    assert dict(zip(hits["Sr No"], hits["Narration Issue"])) == {
        0: "Blank", 1: "Blank", 2: "Numbers only", 3: "Too short", 4: "Generic words only", 6: "Too short",
        7: "Blank"}
    # Mostly blank: the column isn't used to explain entries, so blank lines aren't flagged
    mostly_blank = rules.narration(pd.DataFrame({"Text": ["", "", "", "JV"]}), "Text")
    assert mostly_blank["Text"].tolist() == ["JV"] and mostly_blank.attrs["blank_share"] == 0.75


def test_text_and_user_rules():
    df = small()
    hits = rules.keywords(df, ["Description"])
    assert hits["Sr No"].tolist() == [2, 6]          # "Adjusted" isn't the whole word "adjust"
    assert hits["Matched Keywords"].iloc[0] == "director, write off"
    assert pipeline.run_python_tests(df, ["Amount"], RunSettings(keywords=("rent",)))["Keyword Match"] == {"1", "5"}
    assert rules.duplicates(df, ["Date", "Account", "Amount"])["Sr No"].tolist() == [1, 5]
    assert rules.seldom_accounts(df, "Account")["Sr No"].tolist() == [3]
    assert rules.segregation_of_duties(df, "Created By", "Approved By")["Sr No"].tolist() == [2, 3]


# --- Benford ---

def test_benford_conforming_and_not():
    rng = np.random.default_rng(0)
    benford_like = pd.Series(10 ** rng.uniform(1, 6, 20_000))
    table = benford.first_digit_test(benford_like)
    assert table.attrs["conformity"] == "Close Conformity"
    assert np.isclose(table["Expected"].sum(), 1)
    fours = pd.Series(rng.uniform(4_000, 5_000, 5_000))
    assert benford.first_digit_test(pd.concat([benford_like, fours])).attrs["conformity"] == "Nonconformity"
    df = pd.DataFrame({"Sr No": range(25_000), "Amount": pd.concat([benford_like, fours], ignore_index=True)})
    hits = benford.benford_entries(df, ["Amount"])
    assert hits.attrs["digits"][0] == 4 and (hits["Benford Digit"] == 4).sum() >= 5_000


# --- flags and scoring ---

def test_ids_normalised_across_tools():
    assert flags.id_set(["0000123", "123.0", " 45 ", None, ""]) == {"123", "45"}


def test_consolidate_and_score():
    df = small()
    log = {"Keyword Match": {"2", "6"}, "Saturday": {"2"}, "Sunday": {"3"}, "Public Holiday": {"2"}}
    idea = {"Keyword Match": {"3"}, "Seldom Account Entries": {"3"}}
    flagged = flags.consolidate(df, log, idea)
    assert flagged.attrs["test_counts"]["Keyword Match"] == 3   # Python and IDEA combined
    assert flagged.loc[flagged["Sr No"] == 2, "N Flags"].item() == 3
    scored = scoring.score_flags(flagged, ["Amount"], top_n=None)
    w = scored.attrs["weights"]
    assert set(scored.attrs["date_tests"]) == {"Saturday", "Sunday", "Public Holiday"}
    # Line 2: keyword + three date tests, but the date tests count once (the strongest)
    base = w["Keyword Match"] + max(w["Saturday"], w["Public Holiday"])
    row = scored[scored["Sr No"] == 2].iloc[0]
    assert row["Score"] == pytest.approx(base * row["Amount Multiplier"], abs=0.01)
    with pytest.raises(ValueError):
        flags.consolidate(df, {"Bad": {"999"}})


def test_priority_list_size_bounds():
    assert scoring.priority_list_size(100) == 20
    assert scoring.priority_list_size(30_000) == 100
    assert scoring.priority_list_size(5_000_000) == 150


# --- end to end, with the committed mock IDEA exports ---

def test_fixtures_load_and_scoring_beats_baselines():
    ledger = synthetic.make_ledger(20_000, seed=0)   # the ledger the fixtures were built from
    amt = synthetic.amount_columns(ledger)
    idea = flags.load_idea_flags(FIXTURES)
    assert {"Benford", "Duplicate", "Seldom Account Entries", "Same User Created and Approved"} <= set(idea)
    assert "Account Summary" not in idea   # no row IDs: skipped
    lines = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), idea, min_flags=0)
    vouchers = scoring.to_vouchers(lines, amt)
    scored = scoring.score_flags(vouchers, ["Voucher Amount"], top_n=None)
    k = scoring.priority_list_size(vouchers.attrs["n_rows"])
    table = evaluate.compare_rankings(scored, lines, ledger, amt, k)
    precision = table[f"Precision@{k}"]
    assert precision["Risk score"] > precision["Number of tests hit"] > precision["Amount only"]
    assert precision["Ceiling (flagged vouchers)"] >= precision["Risk score"]
    # The in-memory IDEA side matches the committed exports
    assert pipeline.idea_side_flags(ledger, amt) == idea


def test_voucher_scoring():
    ledger = synthetic.make_ledger(5_000, seed=2)
    amt = synthetic.amount_columns(ledger)
    py, idea = pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt)
    lines = flags.consolidate(ledger, py, idea, min_flags=0)
    # Without a voucher column each line is its own voucher: exactly the per-line ranking and scores
    per_line = scoring.score_flags(flags.consolidate(ledger, py, idea), amt, top_n=None)
    alone = scoring.score_flags(scoring.to_vouchers(lines, amt, RunSettings(voucher_col="Journal")), ["Voucher Amount"],
                                top_n=None)
    assert alone["Sr No"].tolist() == per_line["Sr No"].tolist() and alone["Score"].tolist() == per_line["Score"].tolist()
    assert "Scored per line: no Voucher No column." in pipeline.tests_not_run(ledger.drop(columns="Voucher No"), amt)
    # A voucher meets a test if any of its lines does; rarity counts vouchers
    vouchers = scoring.to_vouchers(lines, amt)
    assert vouchers.attrs["n_rows"] == ledger["Voucher No"].nunique()
    keyword = set(ledger.loc[ledger["Sr No"].astype(str).isin(py["Keyword Match"]), "Voucher No"])
    assert set(vouchers.loc[vouchers["Keyword Match"], "Voucher No"]) == keyword
    assert vouchers.attrs["test_counts"]["Keyword Match"] == len(keyword)
    # Voucher amount: the larger of total debits and credits, the same in both layouts
    debit_credit, signed = synthetic.make_ledger(1_000, seed=1), synthetic.make_ledger(1_000, layout="signed", seed=1)
    amounts = scoring.voucher_amounts(debit_credit, ["Debit", "Credit"], "Voucher No")
    assert np.allclose(amounts, debit_credit.groupby("Voucher No")["Debit"].sum())
    assert np.allclose(amounts, scoring.voucher_amounts(signed, ["Amount"], "Voucher No"))
    with pytest.raises(ValueError, match="min_flags=0"):
        scoring.to_vouchers(flags.consolidate(ledger, py, idea), amt)     # unflagged lines are needed
    bias = evaluate.size_bias(2_000, seed=0)
    assert set(bias["lines"]) == {2, 3, 4} and bias["listed"].sum() == scoring.priority_list_size(len(bias))


def test_every_test_has_a_prior():
    # A test whose name matches no prior key silently gets 1.0 (how the same-user prior went unused)
    ledger = synthetic.make_ledger(20_000, seed=0)
    amt = synthetic.amount_columns(ledger)
    names = [*pipeline.run_python_tests(ledger, amt), *pipeline.idea_side_flags(ledger, amt)]
    keys = [k for k in scoring.DEFAULT_PRIORS if k != "date"]
    for name in names:
        assert any(k in name.lower() for k in keys + list(scoring.DATE_KEYWORDS)), f"No prior key for {name!r}"


def test_readme_top_5_matches_the_code():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    table = readme.split("### Why each voucher is on the list")[1].split("\n\n")[2]
    listed = [row.split("|")[1].strip() for row in table.splitlines()[2:]]
    ledger = synthetic.make_ledger(20_000, seed=0)
    amt = synthetic.amount_columns(ledger)
    lines = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), flags.load_idea_flags(FIXTURES), min_flags=0)
    vouchers = scoring.score_flags(scoring.to_vouchers(lines, amt), ["Voucher Amount"])
    assert listed == vouchers.head(5)["Voucher No"].tolist()


def test_score_breakdown_adds_up():
    ledger = synthetic.make_ledger(5_000, seed=2)
    amt = synthetic.amount_columns(ledger)
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt))
    scored = scoring.score_flags(flagged, amt, top_n=50)
    for breakdown, base in zip(scored["Score Breakdown"], scored["Base Score"]):
        terms = breakdown.split(", × amount ")[0].split(" + ")
        parts = [float(t.rsplit(" ", 1)[1]) for t in terms]      # "Seldom Account Entries 6.8" -> 6.8
        assert sum(parts) == pytest.approx(base, abs=0.05 * len(parts))   # each term rounded to 1 dp
    assert (scored["Score"] - (scored["Base Score"] * scored["Amount Multiplier"])).abs().max() < 0.01
    assert scored["Score Breakdown"].iloc[0].count("date") <= 1   # date tests appear once at most


def test_ablation_switches():
    df = small()
    flagged = flags.consolidate(df, {"Keyword Match": {"2", "6"}, "Saturday": {"2"}, "Sunday": {"3"},
                                     "Period End": {"6"}, "Same User Created and Approved": {"2"}})
    flat = scoring.score_flags(flagged, ["Amount"], top_n=None, amount_multiplier=False)
    assert (flat["Amount Multiplier"] == 1.0).all()
    no_rarity = scoring.score_flags(flagged, ["Amount"], top_n=None, use_rarity=False).attrs["weights"]
    assert no_rarity == {"Keyword Match": 2.5, "Saturday": 0.5, "Sunday": 0.5, "Period End": 1.0,
                         "Same User Created and Approved": 2.5}
    uncollapsed = scoring.score_flags(flagged, ["Amount"], top_n=None, collapse_dates=False)
    assert uncollapsed.attrs["date_tests"] == []


def test_benchmark_run_once_is_consistent():
    results = evaluate.run_once(2_000, 0.008, seed=0, ks=[10])
    assert set(results["k"]) == {10, scoring.priority_list_size(synthetic.make_ledger(2_000)["Voucher No"].nunique())}
    assert results["precision"].between(0, 1).all() and results["recall"].between(0, 1).all()
    at = results.set_index(["k", "ranking"])["recall"]
    assert all(at[(k, "Ceiling (flagged vouchers)")] >= at[(k, "Risk score")] for k in results["k"].unique())
    summary = evaluate.summarise(results)
    assert {"precision mean", "recall std", "seeds"} <= set(summary.columns)


def test_robustness_checks():
    round_lines = [(rules.rounded_amounts(synthetic.make_ledger(5_000, seed=1, noise_scale=s), ["Debit", "Credit"])
                    ["Anomaly"] == "").sum() for s in (1, 2)]
    assert round_lines[1] > round_lines[0]                          # more background noise
    draws = evaluate.prior_sensitivity(2_000, seed=0, draws=3)
    assert draws[["precision", "overlap"]].stack().between(0, 1).all()
    same = evaluate.prior_sensitivity(2_000, seed=0, draws=1, spread=0)
    assert same["overlap"].item() == 1                               # unchanged priors, unchanged list


def test_isolation_forest_ranks_every_line():
    pytest.importorskip("sklearn")
    from glrisk.ml_baseline import isolation_forest_ranking
    ledger = synthetic.make_ledger(1_000, seed=0)
    ranked = isolation_forest_ranking(ledger, synthetic.amount_columns(ledger))
    assert sorted(ranked) == sorted(ledger["Sr No"])


# --- population, materiality and the working paper ---

def test_roll_forward_finds_a_missing_line():
    ledger = synthetic.make_ledger(2_000, seed=4)
    amt = synthetic.amount_columns(ledger)
    tb = synthetic.make_trial_balance(ledger)
    assert tb.loc[tb["Account"] == "Revenue", "Opening"].item() == 0       # income statement opens at zero
    assert population.roll_forward(ledger, tb, amt).attrs["total_difference"] == 0
    missing = ledger.iloc[10]
    result = population.roll_forward(ledger.drop(index=10), tb, amt)
    assert result.iloc[0]["Account"] == missing["Account"]
    assert result.attrs["total_difference"] == pytest.approx(missing["Debit"] + missing["Credit"])


def test_performance_materiality_lines_are_always_listed():
    ledger = synthetic.make_ledger(5_000, seed=2)
    amt = synthetic.amount_columns(ledger)
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt))
    plain = scoring.score_flags(flagged, amt, top_n=10)
    pm = scoring.score_flags(flagged, amt, top_n=10, performance_materiality=100_000, clearly_trivial=100)
    big = rules.absolute_amount(flagged, amt) > 100_000
    assert pm.head(10)["Sr No"].tolist() == plain["Sr No"].tolist()            # the score doesn't change
    assert set(flagged.loc[big, "Sr No"]) <= set(pm["Sr No"])
    assert pm.attrs["above_pm_added"] == len(pm) - 10 > 0
    assert pm["Above Performance Materiality"].tail(pm.attrs["above_pm_added"]).all()
    assert scoring.score_flags(flagged, amt, top_n=None, performance_materiality=100_000).attrs["above_pm_added"] == 0


def test_working_paper(tmp_path):
    ledger = synthetic.make_ledger(5_000, seed=2)
    amt = synthetic.amount_columns(ledger)
    lines = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt),
                              min_flags=0)
    priority = scoring.score_flags(scoring.to_vouchers(lines, amt), ["Voucher Amount"], top_n=20)
    path = export.write_working_paper(priority, lines, tmp_path / "wp.xlsx", amt, "synthetic", {"k": 20},
                                      ["Manual entries not tested: no Source column."])
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    assert list(sheets) == ["Cover", "Vouchers", "Lines", "Method"]
    cover = dict(sheets["Cover"].iloc[1:].to_numpy())
    assert cover["Status"] == export.STATUS and cover["Extent"].startswith("Partial: the top 20 of")
    assert cover["Not tested or limited"].startswith("Manual entries not tested")
    vouchers = pd.read_excel(path, sheet_name="Vouchers")
    assert len(vouchers) == 20 and "Anomaly" not in vouchers and vouchers.columns[-6:].tolist() == export.TESTING_COLUMNS
    assert vouchers["Why Selected"].str.endswith(".").all() and vouchers[export.TESTING_COLUMNS].isna().all().all()
    assert sheets["Method"].iloc[0, 0] == export.METHOD_LABEL
    # Every line of the listed vouchers, flagged or not, with the facts the tests found
    lines_sheet = pd.read_excel(path, sheet_name="Lines")
    assert len(lines_sheet) == vouchers["Lines"].sum() and set(lines_sheet["Voucher Rank"]) == set(range(1, 21))
    assert set(lines_sheet["Flagged Line"]) <= {"Yes", "No"}
    keyword_lines = lines_sheet["Matched Keywords"].notna()
    keyword_vouchers = vouchers["Voucher No"].isin(lines_sheet.loc[keyword_lines, "Voucher No"])
    assert keyword_lines.any() and vouchers.loc[keyword_vouchers, "Why Selected"].str.contains("keyword list").all()
    # A test that flags only some of a voucher's lines says so; one that flags them all doesn't
    v = vouchers.set_index("Voucher No")
    partial = lines_sheet.groupby("Voucher No")["Matched Keywords"].count().reindex(v.index) < v["Lines"]
    noted = v["Why Selected"].str.contains(r"keyword list \(\d of \d lines\)")
    assert (noted == (v["Why Selected"].str.contains("keyword list") & partial)).all()
    assert noted.any()
    assert {"Period-End Window", "Narration Issue"} <= set(lines_sheet.columns)
    assert cover["Parameter: Public holidays"].startswith("AE calendar") and "Parameter: Large amount" in cover
    assert (lines_sheet["Manual"] == "Yes").sum() == lines_sheet["Source"].str.casefold().eq("manual").sum()
    # Filterable, frozen header, dates without a time
    for name, cell in (("Vouchers", "C2"), ("Lines", "C2")):
        sheet = openpyxl.load_workbook(path)[name]
        assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref and sheet[cell].number_format == "yyyy-mm-dd"
