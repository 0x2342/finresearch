"""Resolver seed: held ISIN -> exposure + reference data.

Blueprint mechanic: held ISIN -> precise index variant -> reference physical ETF.
For the prototype this is a static registry seeded with the core sleeve.

- `price_ticker` is an EUR listing used for the *correlation series*. Because
  correlation is a property of the index exposure, not the wrapper, any liquid
  tracker of the same index works here (swap funds included) -- so this is a
  long-history, well-covered index PROXY, not necessarily the held listing.
  Prefer Xetra (.DE) listings (better data coverage than .PA/.AS) and long
  history (avoid new/short share classes, which truncate the correlation
  window). These are seed guesses -- verify in the Prices "Data coverage"
  panel and override in the UI if one fails or is too short.
- `holdings_url` is an iShares "Detailed Holdings" CSV for the *physical*
  reference fund on the same index; when set it drives name-level look-through.
  Left None here -> the app falls back to seeded factsheet exposures
  (core/exposures.py), which is the blueprint's synthetic fallback.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Instrument:
    isin: str
    name: str
    index: str
    replication: str          # 'physical' | 'swap'
    currency: str
    price_ticker: str         # EUR listing for the correlation series
    holdings_url: str | None = None


REGISTRY: dict[str, Instrument] = {
    "IE00BMTX1Y45": Instrument(
        "IE00BMTX1Y45", "iShares S&P 500 Swap", "S&P 500",
        "swap", "USD", "SXR8.DE"),
    "LU0908500753": Instrument(
        "LU0908500753", "Amundi Core STOXX Europe 600", "STOXX Europe 600",
        "physical", "EUR", "EXSA.DE"),
    "LU3086269894": Instrument(
        "LU3086269894", "MSCI Japan", "MSCI Japan",
        "swap", "EUR", "IQQJ.DE"),
    "IE000S3N6R34": Instrument(
        "IE000S3N6R34", "MSCI EM Swap USD (Acc)", "MSCI Emerging Markets",
        "swap", "USD", "IS3N.DE"),
    "IE00BG47KH54": Instrument(
        "IE00BG47KH54", "Vanguard Global Aggregate Bond EUR-H",
        "Bloomberg Global Aggregate (EUR-H)", "physical", "EUR", "VAGF.DE"),
    "IE00B3F81R35": Instrument(
        "IE00B3F81R35", "iShares Core EUR Corp Bond",
        "Bloomberg Euro Corporate Bond", "physical", "EUR", "IEAC.AS"),
}

# Capital split from core-portfolio-risk-overlap.md (12.5% each equity, 25% each bond)
DEFAULT_WEIGHTS: dict[str, float] = {
    "IE00BMTX1Y45": 0.125,
    "LU0908500753": 0.125,
    "LU3086269894": 0.125,
    "IE000S3N6R34": 0.125,
    "IE00BG47KH54": 0.25,
    "IE00B3F81R35": 0.25,
}
