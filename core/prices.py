"""Price data layer: fetch EOD series with an on-disk parquet cache.

Primary source yfinance, fallback Stooq (keyless, good EU coverage). Every
successful pull is cached; on a failed fetch the cache is served so the UI keeps
working offline. Never raises -- returns None when nothing is available.
"""
from __future__ import annotations

import io
import json
import os

import pandas as pd

from core import fx

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prices")
_CCY_CACHE = os.path.join(_CACHE_DIR, "_ccy.json")


def _cache_file(ticker: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    safe = ticker.replace("/", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.parquet")


def _save(ticker: str, s: pd.Series) -> None:
    try:
        s.to_frame("close").to_parquet(_cache_file(ticker))
    except Exception:
        pass


def _load(ticker: str) -> pd.Series | None:
    try:
        df = pd.read_parquet(_cache_file(ticker))
        return df["close"].rename(ticker)
    except Exception:
        return None


def _from_yfinance(ticker: str, period: str) -> pd.Series | None:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        s = hist["Close"].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s.rename(ticker) if len(s) else None
    except Exception:
        return None


def _from_stooq(ticker: str, period: str) -> pd.Series | None:
    try:
        import requests

        sym = ticker.lower()
        url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
        txt = requests.get(url, timeout=30).text
        if "Date" not in txt.splitlines()[0]:
            return None
        df = pd.read_csv(io.StringIO(txt), parse_dates=["Date"]).set_index("Date")
        s = df["Close"].dropna().rename(ticker)
        return s if len(s) else None
    except Exception:
        return None


def get_prices(ticker: str, period: str = "5y") -> pd.Series | None:
    """Close series for `ticker`, cache-backed. None if unavailable.

    The series carries its provenance in `.attrs["source"]`:
      - "yfinance": auto_adjust=True → split- AND dividend-adjusted (total return).
      - "stooq":    raw Close — split-adjusted but not reliably dividend-adjusted,
                    so volatility can be overstated for distributing funds.
      - "cache":    last good on-disk copy (provenance of whichever source wrote it).
    """
    if not ticker:
        return None
    s = _from_yfinance(ticker, period)
    src = "yfinance"
    if s is None:
        s = _from_stooq(ticker, period)
        src = "stooq"
    if s is not None:
        _save(ticker, s)
        s.attrs["source"] = src
        return s
    c = _load(ticker)
    if c is not None:
        c.attrs["source"] = "cache"
    return c


def _currency_meta(ticker: str) -> str | None:
    """Quote currency from yfinance `fast_info`, memoised to a JSON sidecar.

    Only successful (non-empty) results are cached, so a ticker that failed while
    offline is retried later rather than being pinned to 'unknown'. Returns None
    when metadata is unavailable; the suffix fallback then takes over.
    """
    try:
        cache = {}
        if os.path.exists(_CCY_CACHE):
            with open(_CCY_CACHE) as fh:
                cache = json.load(fh)
        if ticker in cache and cache[ticker]:
            return cache[ticker]
        c = None
        try:
            import yfinance as yf

            fi = yf.Ticker(ticker).fast_info
            c = fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None)
        except Exception:
            c = None
        if c:
            cache[ticker] = c
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                with open(_CCY_CACHE, "w") as fh:
                    json.dump(cache, fh)
            except Exception:
                pass
        return c or None
    except Exception:
        return None


def get_panel(tickers: list[str], period: str = "5y") -> pd.DataFrame:
    """Aligned close-price panel, normalised to a common base currency (EUR).

    Non-EUR-quoted series are converted to EUR (price × FX) before any returns
    are taken, so FX risk is captured consistently and local-currency returns are
    never pooled. EUR-quoted series pass through unchanged.

    `panel.attrs`:
      - ``sources``:    ticker -> data provenance (see `get_prices`).
      - ``currencies``: ticker -> resolved quote currency ('?' if unknown).
      - ``converted``:  ticker -> True (converted to EUR) / False (non-EUR but the
                        cross was unavailable, so left in native currency).
    """
    series, sources = {}, {}
    for t in dict.fromkeys(t for t in tickers if t):
        s = get_prices(t, period)
        if s is not None:
            series[t] = s
            sources[t] = s.attrs.get("source", "?")
    if not series:
        return pd.DataFrame()

    # Normalise to EUR. Resolve each quote currency, then fetch each needed
    # <base>EUR cross at most once.
    currencies: dict[str, str] = {}
    converted: dict[str, bool] = {}
    fx_cache: dict[str, pd.Series | None] = {}

    def _cross(base: str) -> pd.Series | None:
        if base not in fx_cache:
            fx_cache[base] = get_prices(f"{base}EUR=X", period)
        return fx_cache[base]

    for t, s in list(series.items()):
        ccy = fx.native_currency(t, _currency_meta)
        currencies[t] = ccy or "?"
        base, _scale = fx.fx_base(ccy)
        if ccy and base != "EUR":
            conv, ok = fx.to_eur(s, ccy, _cross(base))
            series[t] = conv
            converted[t] = ok

    panel = pd.concat(series.values(), axis=1, keys=series.keys())
    panel.attrs["sources"] = sources
    panel.attrs["currencies"] = currencies
    panel.attrs["converted"] = converted
    return panel
