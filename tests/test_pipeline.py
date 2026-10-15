from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glrisk import benford, evaluate, export, flags, pipeline, population, rules, scoring, synthetic

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "idea_exports"


@pytest.fixture(scope="module")
def ledger():
    return synthetic.make_ledger(5_000, seed=1)


# --- synthetic ledger ---

def test_ledger_layouts_and_ground_truth(ledger):
    assert ledger["Sr No"].is_unique and ledger["Sr No"].min() == 1
    assert {"Debit", "Credit"} <= set(ledger.columns)
    assert ((ledger["Debit"] == 0) | (ledger["Credit"] == 0)).all()
    assert (ledger["Anomaly"] != "").sum() == 25
    signed = synthetic.make_ledger(1_000, layout="signed", seed=1)
    assert "Amount" in signed.columns and (signed["Amount"] < 0).any()
    with pytest.raises(ValueError):
        synthetic.make_ledger(10, layout="other")


def test_silent_anomalies_carry_no_red_flag(ledger):
    silent = ledger[ledger["Anomaly"] == "silent"]
    assert len(silent) == 2          # 10% of 25, rounded
    amt = synthetic.amount_columns(ledger)
    # Public holidays aren't checked: a silent anomaly may land on one by chance
    for result in (rules.rounded_amounts(ledger, amt), rules.ending_99(ledger, amt),
                   rules.keywords(ledger, ["Description"]), rules.seldom_accounts(ledger, "Account"),
                   rules.segregation_of_duties(ledger, "Created By", "Approved By"),
                   rules.period_end(ledger, "Date", amt), rules.manual_entries(ledger),
                   rules.narration(ledger, "Description")):
        assert not set(silent["Sr No"]) & set(result["Sr No"])
    assert (pd.to_datetime(silent["Date"]).dt.dayofweek < 5).all()
    assert (synthetic.make_ledger(5_000, seed=1, silent_share=0)["Anomaly"] == "silent").sum() == 0


def test_same_seed_same_ledger():
    pd.testing.assert_frame_equal(synthetic.make_ledger(500, seed=3), synthetic.make_ledger(500, seed=3))


# --- tests (rules) ---

def small():
    return pd.DataFrame({
        "Sr No": [1, 2, 3, 4, 5, 6],
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
    everything = pipeline.run_python_tests(df, ["Amount"], manual_only=False)
    assert everything["Rounded Amount"] == {"1", "5"} and everything["Sunday"] == {"3"}
    no_source = df.drop(columns=["Source"])
    assert "Manual Entry" not in pipeline.run_python_tests(no_source, ["Amount"])
    assert pipeline.tests_not_run(no_source) == ["Manual entries not tested: no Source column."]
    assert pipeline.tests_not_run(df) == []


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
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), idea)
    scored = scoring.score_flags(flagged, amt, top_n=None)
    k = scoring.priority_list_size(len(ledger))
    table = evaluate.compare_rankings(scored, ledger, amt, k)
    precision = table[f"Precision@{k}"]
    assert precision["Risk score"] > precision["Number of tests hit"] > precision["Amount only"]
    assert precision["Ceiling (flagged lines)"] >= precision["Risk score"]
    # The in-memory IDEA side matches the committed exports
    assert pipeline.idea_side_flags(ledger, amt) == idea


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
    results = evaluate.run_once(2_000, 0.005, seed=0, ks=[10])
    assert set(results["k"]) == {10, scoring.priority_list_size(2_000 + 5)}
    assert results["precision"].between(0, 1).all() and results["recall"].between(0, 1).all()
    at = results.set_index(["k", "ranking"])["recall"]
    assert all(at[(k, "Ceiling (flagged lines)")] >= at[(k, "Risk score")] for k in results["k"].unique())
    summary = evaluate.summarise(results)
    assert {"precision mean", "recall std", "seeds"} <= set(summary.columns)


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
    flagged = flags.consolidate(ledger, pipeline.run_python_tests(ledger, amt), pipeline.idea_side_flags(ledger, amt))
    priority = scoring.score_flags(flagged, amt, top_n=20)
    path = export.write_working_paper(priority, tmp_path / "wp.xlsx", amt, "synthetic", {"k": 20},
                                      ["Manual entries not tested: no Source column."])
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    assert list(sheets) == ["Cover", "Lines", "Method"]
    cover = dict(sheets["Cover"].iloc[1:].to_numpy())
    assert cover["Status"] == export.STATUS and cover["Extent"].startswith("Partial: the top 20 of")
    assert cover["Not tested"].startswith("Manual entries not tested")
    lines = pd.read_excel(path, sheet_name="Lines")
    assert len(lines) == 20 and "Anomaly" not in lines and lines.columns[-6:].tolist() == export.TESTING_COLUMNS
    assert lines["Why Selected"].str.endswith(".").all() and lines[export.TESTING_COLUMNS].isna().all().all()
    assert sheets["Method"].iloc[0, 0] == export.METHOD_LABEL
