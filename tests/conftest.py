"""Shared fixtures. Everything here is offline and deterministic — no network,
no yfinance/Stooq, no reliance on the real data/ directory."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    return np.random.default_rng(20261127)


@pytest.fixture
def panel(rng):
    """A deterministic 3-asset daily EUR price panel (~1.5y of business days).

    Built from correlated return streams so the covariance is non-trivial:
    A and B share a common factor (so they co-move), C is more independent.
    Returned as a price DataFrame (columns = tickers), the shape the risk/price
    functions consume.
    """
    n = 380
    idx = pd.bdate_range("2025-01-02", periods=n)
    common = rng.normal(0, 0.008, n)
    ra = common + rng.normal(0, 0.004, n)
    rb = 0.8 * common + rng.normal(0, 0.005, n)
    rc = rng.normal(0, 0.011, n)
    prices = {}
    for t, r in (("A.DE", ra), ("B.DE", rb), ("C.DE", rc)):
        prices[t] = 100.0 * np.cumprod(1.0 + r)
    return pd.DataFrame(prices, index=idx)


@pytest.fixture
def weights():
    """Weights keyed by ticker; deliberately un-normalised (sum 0.9) to exercise
    the priced-subset renormalisation."""
    return {"A.DE": 0.4, "B.DE": 0.3, "C.DE": 0.2}


@pytest.fixture
def store_tmp(tmp_path, monkeypatch):
    """Point core.store at an isolated temp directory so persistence tests never
    touch the real data/ tree. Returns the store module."""
    from core import store

    pdir = tmp_path / "portfolios"
    pdir.mkdir()
    monkeypatch.setattr(store, "_DIR", str(pdir))
    monkeypatch.setattr(store, "_LEGACY", str(tmp_path / "portfolio.csv"))
    monkeypatch.setattr(store, "_SOURCES", str(tmp_path / "sources.csv"))
    return store


# A minimal iShares-style "Detailed Holdings" CSV: a preamble, the as-of line,
# a Weight (%) header row, two real holdings (one bond sector that must crosswalk
# to a GICS name), and a cash row that must be excluded from look-through.
HOLDINGS_CSV = (
    "iShares Sample Fund\n"
    "Fund Holdings as of,\"Nov 25, 2026\"\n"
    "\n"
    "Name,ISIN,Weight (%),Sector,Location,Asset Class\n"
    "APPLE INC,US0378331005,10.0,Information Technology,United States,Equity\n"
    "JPMORGAN CHASE,US46625H1005,6.0,Banking,United States,Equity\n"
    "USD CASH,-,4.0,Cash and/or Derivatives,United States,Cash\n"
)


@pytest.fixture
def holdings_csv():
    return HOLDINGS_CSV
