"""Pure price-panel transforms: frequency resampling + freshness signals.

The network fetch paths (yfinance/Stooq) are deliberately not exercised here —
these tests cover the offline logic the risk/valuation layers depend on."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import prices


def test_to_frequency_daily_is_passthrough(panel):
    assert prices.to_frequency(panel, "daily") is panel


def test_to_frequency_weekly_is_friday_valued():
    idx = pd.bdate_range("2026-01-05", periods=10)  # Mon 5th → Fri 16th
    p = pd.DataFrame({"A.DE": np.arange(1.0, 11.0)}, index=idx)
    w = prices.to_frequency(p, "weekly")
    # index is week-ending Friday
    assert (w.index.dayofweek == 4).all()
    # first week (Mon-Fri = values 1..5) is valued at Friday's close = 5.0
    assert w["A.DE"].iloc[0] == 5.0


def test_to_frequency_preserves_attrs():
    idx = pd.bdate_range("2026-01-05", periods=10)
    p = pd.DataFrame({"A.DE": np.arange(1.0, 11.0)}, index=idx)
    p.attrs["currencies"] = {"A.DE": "EUR"}
    w = prices.to_frequency(p, "weekly")
    assert w.attrs["currencies"] == {"A.DE": "EUR"}


def test_last_prices_basic(panel):
    last, stale, age = prices.last_prices(panel)
    assert set(last) == {"A.DE", "B.DE", "C.DE"}
    assert stale == {}  # all series end together
    assert age == 0     # no as_of given


def test_last_prices_cross_sectional_staleness():
    idx = pd.bdate_range("2026-01-01", periods=30)
    df = pd.DataFrame({"A.DE": np.arange(30.0), "B.DE": np.arange(30.0)}, index=idx)
    df.iloc[20:, df.columns.get_loc("B.DE")] = np.nan  # B stops 9 business days early
    last, stale, age = prices.last_prices(df, max_stale_days=7)
    assert "A.DE" not in stale
    assert "B.DE" in stale and stale["B.DE"] > 7


def test_last_prices_absolute_data_age():
    idx = pd.bdate_range("2026-01-01", periods=10)
    df = pd.DataFrame({"A.DE": np.arange(10.0)}, index=idx)
    as_of = idx[-1] + pd.Timedelta(days=25)
    _last, stale, age = prices.last_prices(df, as_of=as_of)
    # wholesale-stale cache: every series lags by zero cross-sectionally,
    # but the absolute age catches it
    assert stale == {}
    assert age == 25


def test_last_prices_empty_panel():
    assert prices.last_prices(pd.DataFrame()) == ({}, {}, 0)


# ---- Known bug, captured as an executable spec (review #9) ------------------- #
@pytest.mark.xfail(
    reason="review #9: last_prices reads panel.index[-1] assuming a sorted index; "
    "an unsorted panel yields a wrong 'latest' observation and data_age.",
    strict=True,
)
def test_last_prices_handles_unsorted_index():
    idx = pd.bdate_range("2026-01-01", periods=10)
    df = pd.DataFrame({"A.DE": np.arange(10.0)}, index=idx)
    shuffled = df.iloc[[9, 0, 1, 2, 3, 4, 5, 6, 7, 8]]  # true latest row no longer last
    as_of = idx[-1] + pd.Timedelta(days=3)
    _last, _stale, age = prices.last_prices(shuffled, as_of=as_of)
    assert age == 3  # must measure from the true newest obs, not the last row
