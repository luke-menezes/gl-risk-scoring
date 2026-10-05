"""
An unsupervised machine learning baseline: Isolation Forest on simple per-line features.

Needs scikit-learn (``pip install -e ".[ml]"``). It's here for comparison, not as the method: see
"Why not a trained model?" in the README.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from . import rules


def line_features(ledger: pd.DataFrame, amount_cols: Sequence[str], date_col: str = "Date",
                  account_col: str = "Account", text_cols: Sequence[str] = ("Description",),
                  creator_col: str = "Created By", approver_col: str = "Approved By") -> pd.DataFrame:
    """
    One row of numeric features per ledger line: log amount, day of week, account frequency,
    and 0/1 indicators for a keyword hit, a round amount, a 99/999 ending and the same user
    creating and approving.
    """
    def hit(result: pd.DataFrame) -> np.ndarray:
        return ledger.index.isin(result.index).astype(int)

    return pd.DataFrame({
        "log_amount": np.log1p(rules.absolute_amount(ledger, amount_cols)),
        "day_of_week": pd.to_datetime(ledger[date_col]).dt.dayofweek,
        "account_frequency": ledger[account_col].map(ledger[account_col].value_counts(normalize=True)),
        "keyword": hit(rules.keywords(ledger, text_cols)),
        "round": hit(rules.rounded_amounts(ledger, amount_cols)),
        "ending_99": hit(rules.ending_99(ledger, amount_cols)),
        "same_user": hit(rules.segregation_of_duties(ledger, creator_col, approver_col)),
    }, index=ledger.index)


def isolation_forest_ranking(ledger: pd.DataFrame, amount_cols: Sequence[str], seed: int = 0,
                             id_col: str = "Sr No") -> pd.Series:
    """
    Row IDs of the whole ledger, most anomalous first, by Isolation Forest (default settings,
    200 trees). Fitted on the ledger itself, without the injected labels.
    """
    from sklearn.ensemble import IsolationForest

    features = line_features(ledger, amount_cols)
    model = IsolationForest(n_estimators=200, random_state=seed).fit(features)
    anomaly = -model.score_samples(features)   # higher = easier to isolate = more anomalous
    order = np.argsort(-anomaly, kind="stable")
    return ledger[id_col].iloc[order].reset_index(drop=True)
