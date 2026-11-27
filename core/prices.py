"""Price data layer: fetch EOD series with an on-disk parquet cache.

Primary source yfinance, fallback Stooq (keyless, good EU coverage). Every
successful pull is cached; on a failed fetch the cache is served so the UI keeps
working offline. Never raises -- returns None when nothing is available.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone

import pandas as pd

from core import fx, registry

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "prices")
_CCY_CACHE = os.path.join(_CACHE_DIR, "_ccy.json")


def _cache_file(ticker: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    safe = ticker.replace("/", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.parquet")


def _meta_file(ticker: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{ticker.replace('/', '_')}.meta.json")


_ADJUSTMENT = {"yfinance": "total-return", "stooq": "raw-close"}


def _save(ticker: str, s: pd.Series) -> None:
    try:
        s.to_frame("close").to_parquet(_cache_file(ticker))
    except Exception:
        return
    # Persist provenance alongside the prices so a later cache reload keeps the
    # original provider + adjustment (otherwise the Stooq-unadjusted warning
    # silently disappears once a series is served from cache).
    try:
        src = s.attrs.get("source", "?")
        meta = {
            "source": src,
            "adjustment": _ADJUSTMENT.get(src, "unknown"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with open(_meta_file(ticker), "w") as fh:
            json.dump(meta, fh)
    except Exception:
        pass


def _load(ticker: str) -> pd.Series | None:
    try:
        df = pd.read_parquet(_cache_file(ticker))
        s = df["close"].rename(ticker)
    except Exception:
        return None
    try:
        with open(_meta_file(ticker)) as fh:
            meta = json.load(fh)
        s.attrs["orig_source"] = meta.get("source")
        s.attrs["adjustment"] = meta.get("adjustment")
        s.attrs["retrieved_at"] = meta.get("retrieved_at")
    except Exception:
        pass
    return s


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
    When served from the on-disk cache (both live sources unreachable) the series
    keeps its *original* provider in `.attrs["source"]` (restored from the cache
    metadata) and sets `.attrs["from_cache"] = True` + `.attrs["retrieved_at"]`,
    so adjustment warnings survive a cache reload.
    """
    if not ticker:
        return None
    s = _from_yfinance(ticker, period)
    src = "yfinance"
    if s is None:
        s = _from_stooq(ticker, period)
        src = "stooq"
    if s is not None:
        s.attrs["source"] = src
        _save(ticker, s)
        return s
    c = _load(ticker)
    if c is not None:
        # keep the original provider so the Stooq/adjustment warning still fires
        c.attrs["source"] = c.attrs.get("orig_source") or "cache"
        c.attrs["from_cache"] = True
    return c


def to_frequency(panel: pd.DataFrame, freq: str = "daily", max_stale: int = 5) -> pd.DataFrame:
    """Resample a daily price panel to the chosen return frequency.

    "weekly" uses a Friday valuation convention: forward-fill to the most recent
    available close, then take the week-ending (W-FRI) value. This reduces the Epps
    effect — US and Asian closes on the same calendar day sit hours apart, biasing
    daily cross-correlations down — and sidesteps the holiday-intersection data
    loss of complete-case daily returns. "daily" is a pass-through. Panel `attrs`
    (sources / currencies / converted) are preserved.

    `max_stale` caps the forward-fill at that many trading rows (~1 week by
    default): a week whose most recent close is older than that is left NaN rather
    than valued from a stale price, so a holiday or a halt can't masquerade as a
    flat (zero-return) week.
    """
    if panel is None or panel.empty or freq == "daily":
        return panel
    if freq == "weekly":
        out = panel.ffill(limit=max_stale).resample("W-FRI").last()
        out.attrs = dict(getattr(panel, "attrs", {}))
        return out
    return panel


def last_prices(panel, max_stale_days: int = 7, as_of=None) -> tuple[dict, dict, int]:
    """Latest valid close per ticker for valuation, with two freshness signals.

    Returns ``(prices, stale, data_age)``:
      - `prices`: ticker → last valid close.
      - `stale`:  ticker → calendar days since that close, for any ticker whose
                  last observation lags the *panel's* latest by more than
                  `max_stale_days` (**cross-sectional** — one listing falling behind
                  the others, e.g. a halt/delisting).
      - `data_age`: calendar days between the panel's newest observation and
                  `as_of` (today, if given) — **absolute** freshness. Catches a
                  wholesale-stale dataset (all providers down → cached data) that
                  the cross-sectional check can't, since every series then lags by
                  zero. 0 when `as_of` is None.

    Valuation still uses the last known price; the UI flags staleness rather than
    silently distorting market value and weights.
    """
    prices_out: dict[str, float] = {}
    stale: dict[str, int] = {}
    if panel is None or getattr(panel, "empty", True):
        return prices_out, stale, 0
    end = panel.index[-1]
    ref = pd.Timestamp(as_of) if as_of is not None else end
    data_age = max(int((ref - end).days), 0)
    for c in panel.columns:
        s = panel[c].dropna()
        if s.empty:
            continue
        prices_out[c] = float(s.iloc[-1])
        age = (end - s.index[-1]).days
        if age > max_stale_days:
            stale[c] = age
    return prices_out, stale, data_age


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
      - ``ccy_assumed``: set of tickers whose currency was *assumed* USD from a
                        bare symbol (no registry pin / metadata / suffix).
    """
    series, sources, cached = {}, {}, set()
    for t in dict.fromkeys(t for t in tickers if t):
        s = get_prices(t, period)
        if s is not None:
            series[t] = s
            sources[t] = s.attrs.get("source", "?")
            if s.attrs.get("from_cache"):
                cached.add(t)
    if not series:
        return pd.DataFrame()

    # Normalise to EUR. Resolve each quote currency (explicit registry pin →
    # metadata → suffix → assumed-USD), then fetch each needed <base>EUR cross once.
    currencies: dict[str, str] = {}
    converted: dict[str, bool] = {}
    assumed: set[str] = set()
    fx_cache: dict[str, pd.Series | None] = {}

    def _cross(base: str) -> pd.Series | None:
        if base not in fx_cache:
            fx_cache[base] = get_prices(f"{base}EUR=X", period)
        return fx_cache[base]

    for t, s in list(series.items()):
        ccy, src = fx.resolve_currency(
            t, meta_lookup=_currency_meta, registry_lookup=registry.quote_currency_for
        )
        currencies[t] = ccy or "?"
        if src == "assumed-usd":
            assumed.add(t)
        base, _scale = fx.fx_base(ccy)
        if ccy and base != "EUR":
            conv, ok = fx.to_eur(s, ccy, _cross(base))
            series[t] = conv
            converted[t] = ok

    panel = pd.concat(series.values(), axis=1, keys=series.keys())
    panel.attrs["sources"] = sources
    panel.attrs["cached"] = cached
    panel.attrs["currencies"] = currencies
    panel.attrs["converted"] = converted
    panel.attrs["ccy_assumed"] = assumed
    return panel
