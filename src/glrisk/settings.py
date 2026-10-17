"""
The settings one run uses, in one object passed to the tests and to the working paper, so the
cover states exactly what was tested. Every value is practical judgement and can be changed.
"""

from __future__ import annotations

from dataclasses import dataclass

import holidays
import pandas as pd

from . import rules


@dataclass(frozen=True)
class RunSettings:
    """
    Columns, calendar, thresholds and word lists for one run.

    ``dayfirst`` reads ambiguous dates such as 02/03/2025 as 2 March (the UAE convention).
    ``voucher_col`` groups lines into vouchers for scoring; without it each line is scored alone.
    ``duplicate_key`` is the columns two lines must share to be duplicates, with the amount always
    added; ``None`` means the date, account and first text column.
    ``manual_only`` limits the weekend, public holiday and round-amount tests to manual lines when
    the ledger has ``source_col``. ``seldom_max_entries`` is the seldom-account threshold of the IDEA
    side: the Python stand-in uses it, but with real IDEA exports the test ran with the macro's
    ``SELDOM_MAX``, so keep the two in step. ``quarter_days`` and ``year_end_days`` set the period-end windows (see
    ``rules.period_end_labels``).
    """

    date_col: str = "Date"
    text_cols: tuple[str, ...] = ("Description",)
    id_col: str = "Sr No"
    source_col: str = "Source"
    voucher_col: str = "Voucher No"
    account_col: str = "Account"
    creator_col: str = "Created By"
    approver_col: str = "Approved By"
    duplicate_key: tuple[str, ...] | None = None
    dayfirst: bool = True
    weekend_days: tuple[str, ...] = rules.WEEKEND_DAYS
    holiday_country: str = "AE"
    fy_end_month: int = 12
    quarter_days: tuple[int, int] = (3, 2)
    year_end_days: int = 5
    manual_only: bool = True
    manual_values: tuple[str, ...] = ("Manual",)
    round_multiple: float = 10_000
    seldom_max_entries: int = 3
    keywords: tuple[str, ...] = rules.DEFAULT_KEYWORDS
    generic_words: tuple[str, ...] = rules.GENERIC_WORDS

    @property
    def dup_key(self) -> tuple[str, ...]:
        """The duplicate key without the amount: ``duplicate_key``, or date, account and first text column."""
        return self.duplicate_key or (self.date_col, self.account_col, self.text_cols[0])

    @property
    def windows(self) -> dict:
        """The period-end window arguments for ``rules.period_end_labels``."""
        return {"quarter_days": self.quarter_days, "year_end_days": self.year_end_days,
                "weekend_days": self.weekend_days}

    def cover(self, has_source: bool = True) -> dict[str, str]:
        """The settings in words, for the working paper's cover (``has_source``: the ledger has ``source_col``)."""
        return {
            "Vouchers": f"lines grouped by {self.voucher_col}; a voucher meets a test if any of its lines does; "
                        "voucher amount = the larger of its total debits and total credits",
            "Financial year-end": f"End of {pd.Timestamp(2001, self.fy_end_month, 1):%B}",
            "Period-end windows": f"last {self.quarter_days[0]} and first {self.quarter_days[1]} days of each "
                                  f"quarter; {self.year_end_days} working days either side of the year-end",
            "Weekend days": ", ".join(self.weekend_days),
            "Public holidays": f"{self.holiday_country} calendar (holidays package {holidays.__version__})",
            "Dates": ("ambiguous dates read day first (02/03 is 2 March)" if self.dayfirst
                      else "ambiguous dates read month first (02/03 is 3 February)")
                     + "; numbers from 20,000 to 80,000 read as Excel serial dates; time-zone offsets dropped, "
                       "local time kept",
            **({"Manual entries": f"{self.source_col} is {' or '.join(self.manual_values)} (case ignored)"}
               if has_source else {}),
            "Weekend, holiday and round-amount tests": "manual lines only" if self.manual_only and has_source
                                                       else "all lines",
            "Round amount": f"multiple of {self.round_multiple:,.0f}",
            "Seldom-used account": f"{self.seldom_max_entries} entries or fewer (with real IDEA exports, the "
                                   "threshold the macro was run with: keep it in step with SELDOM_MAX)",
            "Duplicate key": ", ".join(self.dup_key) + " and the amount",
            "Keywords": ", ".join(self.keywords),
            "Generic narration words": ", ".join(self.generic_words),
        }
