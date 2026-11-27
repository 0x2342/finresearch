"""Risk decomposition: the invariants that make the Euler numbers meaningful."""
from __future__ import annotations

import math

import numpy as np

from core import risk


def test_decompose_shape_and_priced_subset(panel, weights):
    d = risk.decompose(panel, weights)
    assert d is not None
    # only the three priced, positive-weight tickers appear
    assert set(d["tickers"]) == {"A.DE", "B.DE", "C.DE"}
    # covered = raw weight mass (0.4+0.3+0.2), renormalised internally
    assert math.isclose(d["covered"], 0.9, rel_tol=1e-9)
    assert math.isclose(sum(d["w"].values()), 1.0, rel_tol=1e-9)


def test_rc_fractions_sum_to_one(panel, weights):
    d = risk.decompose(panel, weights)
    assert math.isclose(sum(d["rc_frac"].values()), 1.0, rel_tol=1e-9)
    # Euler contributions are additive but individually can't exceed the whole
    assert all(-1e-9 <= v <= 1.0 + 1e-9 for v in d["rc_frac"].values())


def test_diversification_reduces_volatility(panel, weights):
    """Portfolio volatility must not exceed the weighted-average standalone
    volatility — correlation < 1 buys diversification."""
    d = risk.decompose(panel, weights)
    assert d["ann_vol"] <= d["wavg_vol"] + 1e-12


def test_annualisation_scales_with_frequency(panel, weights):
    """Same per-period covariance, different periods_per_year ⇒ ann_vol scales by
    √(ppy ratio). This is the daily(252) vs weekly(52) wiring."""
    daily = risk.decompose(panel, weights, periods_per_year=252)
    weekly = risk.decompose(panel, weights, periods_per_year=52)
    ratio = daily["ann_vol"] / weekly["ann_vol"]
    assert math.isclose(ratio, math.sqrt(252 / 52), rel_tol=1e-9)


def test_portfolio_returns_std_matches_decompose(panel, weights):
    """The documented identity: std(constant-mix return series)·√ppy == ann_vol."""
    d = risk.decompose(panel, weights, periods_per_year=252)
    r = risk.portfolio_returns(panel, weights)
    assert r is not None
    recovered = float(r.std(ddof=1) * math.sqrt(252))
    assert math.isclose(recovered, d["ann_vol"], rel_tol=1e-9)


def test_decompose_none_when_nothing_priced(panel):
    assert risk.decompose(panel, {"ZZZ": 1.0}) is None
    assert risk.decompose(panel, {}) is None


def test_decompose_none_on_too_few_observations(weights):
    import pandas as pd

    tiny = pd.DataFrame({"A.DE": [100.0], "B.DE": [100.0]})
    assert risk.decompose(tiny, weights) is None


def test_rolling_vol_labels_and_windows(panel, weights):
    rv = risk.rolling_vol(panel, weights, windows=(252, 756), periods_per_year=252)
    assert rv is not None
    # 252 trading days ≈ 12m fits (panel has 380 rows); 756 (36m) does not
    assert "12m" in rv.columns
    assert "36m" not in rv.columns
    assert (rv.dropna() > 0).all().all()


def test_rolling_vol_weekly_month_labels(panel, weights):
    # weekly windows (52, 156) at ppy 52 → 12m / 36m labels
    rv = risk.rolling_vol(panel, weights, windows=(52, 156), periods_per_year=52)
    assert rv is not None
    assert "12m" in rv.columns


def test_binding_holdings_identifies_latest_starter(panel):
    import numpy as np

    p = panel.copy()
    # make C.DE start 100 days later than A/B
    p.iloc[:100, p.columns.get_loc("C.DE")] = np.nan
    binding, latest, earliest = risk.binding_holdings(p, list(p.columns))
    assert binding == ["C.DE"]
    assert latest > earliest


def test_binding_holdings_empty_when_unpriced(panel):
    assert risk.binding_holdings(panel, ["ZZZ"]) == ([], None, None)
