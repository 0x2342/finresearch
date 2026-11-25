"""Price data layer: fetch EOD series with an on-disk parquet cache.

Primary source yfinance, fallback Stooq (keyless, good EU coverage). Every
successful pull is cached; on a failed fetch the cache is served so the UI keeps
working offline. Never raises -- returns None when nothing is available.
"""
from __future__ import annotations

import io
import os

import pandas as pd

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prices")


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


def get_panel(tickers: list[str], period: str = "5y") -> pd.DataFrame:
    """Aligned close-price panel (inner-joined on common dates).

    `panel.attrs["sources"]` maps ticker -> provenance (see `get_prices`), so the
    UI can flag non-total-return series.
    """
    series, sources = {}, {}
    for t in dict.fromkeys(t for t in tickers if t):
        s = get_prices(t, period)
        if s is not None:
            series[t] = s
            sources[t] = s.attrs.get("source", "?")
    if not series:
        return pd.DataFrame()
    panel = pd.concat(series.values(), axis=1, keys=series.keys())
    panel.attrs["sources"] = sources
    return panel
