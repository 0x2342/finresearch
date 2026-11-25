"""Portfolio risk decomposition.

Daily returns -> daily covariance Σ -> annualized (×√252). Portfolio volatility
is √(wᵀΣw); each asset's component risk contribution RCᵢ = wᵢ·(Σw)ᵢ/σ sums to σ,
so rc_frac sums to 1 (share of total risk). Weights are renormalized over the
*priced* subset, and `covered` reports how much of the book that was.

The percentage decomposition depends only on weights + covariance (same for
tracked and research). Absolute € figures are layered on in the app for tracked
books, where weights are real market-value weights.
"""
from __future__ import annotations

import numpy as np

TRADING_DAYS = 252


def decompose(panel, weights: dict[str, float], periods_per_year: int = TRADING_DAYS) -> dict | None:
    """Risk decomposition for a weight vector keyed by ticker.

    panel: price DataFrame (columns = tickers). weights: ticker -> weight (need
    not sum to 1; renormalized over priced tickers). None if nothing is priced.
    `periods_per_year` sets the annualisation (252 daily, 52 weekly) — pass the
    value that matches the panel's sampling frequency.
    """
    cols = getattr(panel, "columns", [])
    tickers = [t for t in weights if t and t in cols and weights[t] > 0]
    if not tickers:
        return None
    rets = panel[tickers].pct_change().dropna(how="any")
    if len(rets) < 2:
        return None

    raw = np.array([weights[t] for t in tickers], dtype=float)
    covered = float(raw.sum())
    w = raw / covered
    cov = rets[tickers].cov().values                      # per-period covariance
    ann = float(np.sqrt(periods_per_year))
    standalone = {t: float(np.sqrt(max(cov[i, i], 0.0)) * ann) for i, t in enumerate(tickers)}
    wavg_vol = float(sum(w[i] * standalone[t] for i, t in enumerate(tickers)))

    sigma = float(np.sqrt(max(w @ cov @ w, 0.0)))         # daily portfolio volatility
    if sigma <= 0:
        rc_frac = {t: 0.0 for t in tickers}
    else:
        rc = w * (cov @ w / sigma)                        # component RC (daily), Σ = sigma
        rc_frac = {t: float(rc[i] / sigma) for i, t in enumerate(tickers)}

    return {
        "ann_vol": sigma * ann,
        "wavg_vol": wavg_vol,                             # undiversified (weighted-avg standalone)
        "obs": len(rets),
        "start": rets.index[0], "end": rets.index[-1],
        "covered": covered,
        "tickers": tickers,
        "w": {t: float(w[i]) for i, t in enumerate(tickers)},
        "rc_frac": rc_frac,
        "standalone": standalone,
    }


def portfolio_returns(panel, weights: dict[str, float]):
    """Daily return series of the book at fixed current weights (constant-mix).

    Same priced-subset filter and renormalisation as `decompose`, so the std of
    this series over the full window equals `decompose(...)['ann_vol']/√252`.
    Returns a pandas Series, or None if nothing is priced.
    """
    cols = getattr(panel, "columns", [])
    tickers = [t for t in weights if t and t in cols and weights[t] > 0]
    if not tickers:
        return None
    rets = panel[tickers].pct_change().dropna(how="any")
    if len(rets) < 2:
        return None
    raw = np.array([weights[t] for t in tickers], dtype=float)
    tot = raw.sum()
    if tot <= 0:
        return None
    w = raw / tot
    return rets[tickers] @ w


def rolling_vol(panel, weights: dict[str, float], windows=(252, 756),
                periods_per_year: int = TRADING_DAYS):
    """Annualised rolling volatility of the book for each window.

    `windows` and `periods_per_year` are both in the panel's sampling periods
    (daily: windows (252, 756), ppy 252; weekly: windows (52, 156), ppy 52).
    Returns a DataFrame indexed by date with one column per window that has enough
    history, labelled in months. None if no window fits. A regime lens: how the
    full-window number (a flat reference) is really a blend of calmer and more
    turbulent stretches.
    """
    r = portfolio_returns(panel, weights)
    if r is None or r.empty:
        return None
    import pandas as pd

    out = {}
    for win in windows:
        if len(r) >= win:
            label = f"{round(win / periods_per_year * 12)}m"
            out[label] = r.rolling(win).std(ddof=1) * np.sqrt(periods_per_year)
    if not out:
        return None
    return pd.DataFrame(out).dropna(how="all")
