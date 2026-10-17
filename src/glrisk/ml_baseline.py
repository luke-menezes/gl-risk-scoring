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
from .settings import RunSettings


def line_features(ledger: pd.DataFrame, amount_cols: Sequence[str], settings: RunSettings | None = None
                  ) -> pd.DataFrame:
    """
    One row of numeric features per ledger line: log amount, day of week (-1 if unreadable),
    account frequency, and 0/1 indicators for a keyword hit, a round amount, a 99/999 ending, the
    same user creating and approving, a period-end date, no or vague narration and (with a source
    column) a manual entry. Columns, word lists and windows come from ``settings``.
    """
    def hit(result: pd.DataFrame) -> np.ndarray:
        return ledger.index.isin(result.index).astype(int)

    s = settings or RunSettings()
    ledger = ledger.assign(**{s.date_col: rules.parse_dates(ledger[s.date_col], s.dayfirst)})
    text = [c for c in s.text_cols if c in ledger]   # without text, the text features are 0
    return pd.DataFrame({
        "log_amount": np.log1p(rules.absolute_amount(ledger, amount_cols)),
        "day_of_week": ledger[s.date_col].dt.dayofweek.fillna(-1),
        "account_frequency": ledger[s.account_col].map(ledger[s.account_col].value_counts(normalize=True)),
        "keyword": hit(rules.keywords(ledger, text, s.keywords)) if text else 0,
        "round": hit(rules.rounded_amounts(ledger, amount_cols, s.round_multiple)),
        "ending_99": hit(rules.ending_99(ledger, amount_cols)),
        "same_user": hit(rules.segregation_of_duties(ledger, s.creator_col, s.approver_col))
        if {s.creator_col, s.approver_col} <= set(ledger) else 0,
        "period_end": hit(rules.period_end(ledger, s.date_col, amount_cols, s.fy_end_month, **s.windows)),
        "narration": hit(rules.narration(ledger, s.text_cols[0], s.generic_words)) if s.text_cols[0] in ledger else 0,
        "manual": hit(rules.manual_entries(ledger, s.source_col, s.manual_values)) if s.source_col in ledger else 0,
    }, index=ledger.index)


def isolation_forest_ranking(ledger: pd.DataFrame, amount_cols: Sequence[str], seed: int = 0,
                             settings: RunSettings | None = None) -> pd.Series:
    """
    Row IDs of the whole ledger, most anomalous first, by Isolation Forest (default settings,
    200 trees). Fitted on the ledger itself, without the injected labels.
    """
    from sklearn.ensemble import IsolationForest

    features = line_features(ledger, amount_cols, settings)
    model = IsolationForest(n_estimators=200, random_state=seed).fit(features)
    anomaly = -model.score_samples(features)   # higher = easier to isolate = more anomalous
    order = np.argsort(-anomaly, kind="stable")
    return ledger[(settings or RunSettings()).id_col].iloc[order].reset_index(drop=True)
