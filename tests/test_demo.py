import runpy
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pytest

from glrisk import synthetic

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "scripts" / "run_demo.py"


def test_demo_writes_workbook_and_summary(tmp_path):
    output = tmp_path / "demo"
    subprocess.run(
        [sys.executable, str(DEMO), "--output-dir", str(output)],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )

    assert {path.name for path in output.iterdir()} == {"working_paper.xlsx", "review_summary.md"}
    workbook = pd.read_excel(output / "working_paper.xlsx", sheet_name=None)
    assert list(workbook) == ["Cover", "Vouchers", "Lines", "Method"]
    cover = workbook["Cover"].set_index("Item")["Value"]
    assert "difference 0.00" in cover["Parameter: Population check"]
    assert "x square root of the vouchers" in cover["Parameter: List size"]
    vouchers = workbook["Vouchers"]
    lines = workbook["Lines"]
    assert len(vouchers) == 50 and "Anomaly" not in vouchers and "Anomaly" not in lines

    summary = (output / "review_summary.md").read_text(encoding="utf-8")
    voucher = vouchers.iloc[0]["Voucher No"]
    voucher_lines = lines.loc[lines["Voucher No"] == voucher]
    assert "**0.00**" in summary
    assert "| Benford |" in summary
    assert f"Voucher **{voucher}** ranked first" in summary
    for row_id in voucher_lines["Sr No"]:
        assert f"| {row_id} |" in summary


def test_demo_summary_matches_docs_on_pinned_versions(tmp_path):
    # Library upgrades can move the figures (a holidays release moved UAE dates), so the committed
    # summary is compared only on the versions in the constraints file (CI's Python 3.11 job)
    pinned = dict(line.split("==") for line in (ROOT / "docs" / "benchmark-constraints.txt").read_text().split()
                  if "==" in line)
    differ = {name: version(name) for name in ("numpy", "pandas", "holidays") if version(name) != pinned[name]}
    if differ:
        pytest.skip(f"versions differ from docs/benchmark-constraints.txt: {differ}")
    subprocess.run([sys.executable, str(DEMO), "--output-dir", str(tmp_path)], check=True, capture_output=True)
    summary = (tmp_path / "review_summary.md").read_text(encoding="utf-8")
    assert summary == (ROOT / "docs" / "demo_summary.md").read_text(encoding="utf-8"), "rerun scripts/run_demo.py"


def test_demo_stops_before_export_if_trial_balance_differs(tmp_path, monkeypatch, capsys):
    make_trial_balance = synthetic.make_trial_balance

    def trial_balance_with_difference(*args, **kwargs):
        trial_balance = make_trial_balance(*args, **kwargs)
        trial_balance.loc[0, "Closing"] += 1
        return trial_balance

    output = tmp_path / "demo"
    monkeypatch.setattr(synthetic, "make_trial_balance", trial_balance_with_difference)
    monkeypatch.setattr(sys, "argv", [str(DEMO), "--output-dir", str(output)])

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(DEMO), run_name="__main__")
    assert error.value.code == 1
    assert "do not reconcile (total account difference 1.00)" in capsys.readouterr().err
    assert not output.exists()
