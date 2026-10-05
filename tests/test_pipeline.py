from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glrisk import benford, evaluate, flags, pipeline, rules, scoring, synthetic

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
    for result in (rules.rounded_amounts(ledger, amt), rules.ending_99(ledger, amt),
                   rules.public_holidays(ledger, "Date", amt), rules.keywords(ledger, ["Description"]),
                   rules.seldom_accounts(ledger, "Account"),
                   rules.segregation_of_duties(ledger, "Created By", "Approved By")):
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
    log = {"Suspicious Keyword": {"2", "6"}, "Saturday": {"2"}, "Sunday": {"3"}, "Public Holiday": {"2"}}
    idea = {"Suspicious Keyword": {"3"}, "Seldom Account Entries": {"3"}}
    flagged = flags.consolidate(df, log, idea)
    assert flagged.attrs["test_counts"]["Suspicious Keyword"] == 3   # Python and IDEA combined
    assert flagged.loc[flagged["Sr No"] == 2, "N Flags"].item() == 3
    scored = scoring.score_flags(flagged, ["Amount"], top_n=None)
    w = scored.attrs["weights"]
    assert set(scored.attrs["date_tests"]) == {"Saturday", "Sunday", "Public Holiday"}
    # Line 2: keyword + three date tests, but the date tests count once (the strongest)
    base = w["Suspicious Keyword"] + max(w["Saturday"], w["Public Holiday"])
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
    assert {"Benford", "Duplicate", "Seldom Account Entries", "SoD Violation Entries"} <= set(idea)
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
    flagged = flags.consolidate(df, {"Suspicious Keyword": {"2", "6"}, "Saturday": {"2"}, "Sunday": {"3"}})
    flat = scoring.score_flags(flagged, ["Amount"], top_n=None, amount_multiplier=False)
    assert (flat["Amount Multiplier"] == 1.0).all()
    no_rarity = scoring.score_flags(flagged, ["Amount"], top_n=None, use_rarity=False).attrs["weights"]
    assert no_rarity == {"Suspicious Keyword": 2.5, "Saturday": 0.5, "Sunday": 0.5}
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
