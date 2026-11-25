"""Currency normalisation: express every price series in a common base (EUR).

A fund *quoted* in USD/GBP/… carries FX risk for a EUR investor; its return in
EUR is price-return + FX-return. We convert non-EUR series to EUR (price × FX)
*before* returns/covariance are computed, so local-currency returns are never
pooled. EUR-quoted series pass through untouched.

This is about the *quote* currency, not the fund's underlying exposure: a
EUR-listed S&P 500 ETF already embeds the USD move in its EUR price, so
converting it would be wrong (and is a no-op here). Hedged-vs-unhedged *exposure*
is a separate, look-through concern.

Pure and dependency-light (pandas only); the live metadata/FX fetch lives in
`core.prices`, injected via callables so this module is fully testable offline.
"""
from __future__ import annotations

import pandas as pd

# High-confidence quote currency by listing suffix. Deliberately conservative:
# .L (LSE) is absent because it quotes both USD lines and GBp (pence); such
# venues are resolved from provider metadata or left unconverted + flagged.
SUFFIX_CCY = {
    ".DE": "EUR", ".F": "EUR", ".BE": "EUR", ".MU": "EUR", ".SG": "EUR",
    ".DU": "EUR", ".HM": "EUR", ".AS": "EUR", ".PA": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".VI": "EUR", ".BR": "EUR", ".LS": "EUR", ".HE": "EUR",
    ".IR": "EUR",
    ".SW": "CHF", ".T": "JPY", ".TO": "CAD", ".AX": "AUD", ".ST": "SEK",
    ".CO": "DKK", ".OL": "NOK", ".HK": "HKD", ".SI": "SGD",
}


def native_currency(ticker: str, meta_lookup=None) -> str | None:
    """Resolve a ticker's quote currency.

    Order: `meta_lookup(ticker)` (e.g. provider metadata) wins, then the suffix
    map, then a bare (suffix-less) symbol is treated as a US/USD listing. Returns
    None when genuinely unknown — the caller then leaves the series unconverted
    and flags it, rather than guessing and corrupting price levels.
    """
    if meta_lookup is not None:
        try:
            c = meta_lookup(ticker)
        except Exception:
            c = None
        if c:
            return c
    up = (ticker or "").upper()
    for suf, ccy in SUFFIX_CCY.items():
        if up.endswith(suf):
            return ccy
    if up and "." not in up and "=" not in up:
        return "USD"  # bare symbol ~ US listing
    return None


def fx_base(ccy: str | None) -> tuple[str, float]:
    """Major-unit base and price scale for a quote currency.

    GBp (pence) -> (GBP, 0.01): divide the pence price by 100, then apply the
    GBP/EUR cross. Everything else is its own base at scale 1.
    """
    if ccy == "GBp":
        return "GBP", 0.01
    return (ccy or "EUR"), 1.0


def to_eur(price: pd.Series, ccy: str | None, fx: pd.Series | None) -> tuple[pd.Series, bool]:
    """Convert a native-currency price series to EUR.

    `fx` is EUR per 1 unit of the base currency (e.g. the ``USDEUR=X`` series).
    Returns ``(series, converted)``. It is a no-op (``converted=False``) when the
    currency is EUR/unknown or the cross is unavailable — a missing FX series must
    never silently rescale levels.
    """
    base, scale = fx_base(ccy)
    if not ccy or base == "EUR":
        return price, False
    if fx is None or len(fx) == 0:
        return price, False
    aligned = (
        fx.reindex(price.index.union(fx.index)).sort_index().ffill().reindex(price.index)
    )
    eur = ((price * scale) * aligned).dropna()
    if not len(eur):
        return price, False
    eur = eur.rename(price.name)
    eur.attrs = dict(price.attrs)
    return eur, True
