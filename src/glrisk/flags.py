"""
Collect each test's flagged row IDs, from Python and from IDEA exports, and consolidate them into one
table with a column per test.

Everything joins on the row ID (``Sr No``), tagged once before the ledger is split between IDEA and
Python. Only ID sets are kept per test, so large results are cheap to hold.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

FlagLog = dict[str, set[str]]


def normalise_ids(values: pd.Series) -> pd.Series:
    """
    IDs as comparable strings.

    Purely numeric IDs lose leading zeros and a trailing ".0", because IDEA and Excel often read
    "0000123" as the number 123 (or 123.0). Other IDs are only trimmed.
    """
    ids = pd.Series(values).astype(str).str.strip()
    numeric = ids.str.fullmatch(r"\d+(\.0+)?")
    ids[numeric] = ids[numeric].str.replace(r"\.0+$", "", regex=True).str.lstrip("0").replace("", "0")
    return ids


def id_set(values) -> set[str]:
    """A set of normalised IDs, blanks dropped."""
    ids = normalise_ids(pd.Series(list(values)).dropna())
    return set(ids[ids != ""])


def log_flags(flag_log: FlagLog, test_name: str, result: pd.DataFrame, id_col: str = "Sr No") -> None:
    """Record the IDs a test flagged. Call it on the full result, not a top-N export."""
    if id_col not in result.columns:
        raise KeyError(f"'{id_col}' not in the result of test '{test_name}'")
    flag_log[test_name] = id_set(result[id_col])


def _simplify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def load_idea_flags(folder: str | Path, id_col: str = "Sr No", benford_prefix: str = "Benford") -> FlagLog:
    """
    Read flagged IDs from every IDEA export (xlsx/csv) in a folder: one test per file.

    - The ID column is matched ignoring case, spaces and punctuation, because IDEA renames fields
      on import ("Sr No" becomes "SR_NO").
    - Files starting with ``benford_prefix`` are combined into one "Benford" test, so the
      overlapping Benford outputs aren't counted as separate tests.
    - "Debit"/"Credit" variants of one test ("Duplicate Debit", "Duplicate Credit") are combined.
    - Files without the ID column (summaries) are skipped.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    target = _simplify(id_col)
    flags: FlagLog = {}
    for path in sorted(folder.iterdir()):
        if path.name.startswith("~$") or path.suffix.lower() not in (".xlsx", ".csv"):
            continue
        usecols = lambda col: _simplify(col) == target
        sheets = ({"csv": pd.read_csv(path, usecols=usecols, dtype=str)} if path.suffix.lower() == ".csv"
                  else pd.read_excel(path, sheet_name=None, usecols=usecols, dtype=str))
        sheets = [s for s in sheets.values() if len(s.columns)]
        if not sheets:
            continue
        if path.stem.lower().startswith(benford_prefix.lower()):
            name = "Benford"
        else:
            name = re.sub(r"[\s_-]*\(?\b(debit|credit)\b\)?\s*$", "", path.stem, flags=re.IGNORECASE).strip()
        for sheet in sheets:
            flags[name] = flags.get(name, set()) | id_set(sheet.iloc[:, 0])
    return flags


def consolidate(df: pd.DataFrame, *flag_logs: FlagLog, id_col: str = "Sr No", min_flags: int = 1) -> pd.DataFrame:
    """
    One row per ledger line with a True/False column per test, ``N Flags`` and ``Flagged By``.

    Tests with the same name in several logs (e.g. a test run in both Python and IDEA) are combined
    into one. Rows flagged by fewer than ``min_flags`` tests are dropped (0 keeps every row). The
    ledger size and each test's count are kept in ``.attrs`` for the scoring.
    """
    if id_col not in df.columns:
        raise KeyError(f"'{id_col}' not in the ledger")
    tests: FlagLog = {}
    for log in flag_logs:
        for name, ids in log.items():
            tests[name] = tests.get(name, set()) | ids
    clashes = [t for t in tests if t in df.columns]
    if clashes:
        raise ValueError(f"Test names clash with ledger columns: {clashes}")

    ids = normalise_ids(df[id_col])
    unmatched = {t: len(s - set(ids)) for t, s in tests.items() if s - set(ids)}
    if unmatched:
        raise ValueError(f"Flagged IDs not in the ledger (check the ID format): {unmatched}")
    out = df.copy()
    for name, flagged in tests.items():
        out[name] = ids.isin(flagged).to_numpy()
    names = list(tests)
    out["N Flags"] = out[names].sum(axis=1)
    out["Flagged By"] = [", ".join(n for n, hit in zip(names, row) if hit) for row in out[names].to_numpy()]
    counts = out[names].sum().astype(int).to_dict()
    out = out[out["N Flags"] >= min_flags].sort_values("N Flags", ascending=False, kind="stable")
    out.attrs = {"tests": names, "test_counts": counts, "n_rows": len(df)}
    return out
