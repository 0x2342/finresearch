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
    holdings_url: str | None = None   # explicit override; else built from product_id
    product_id: int | None = None     # iShares physical reference fund product id
    site: str = "uk-ishares"          # get-product-data targetSite
    locale: str = "en_GB"             # English labels; German-domiciled funds use en_DE


# product_id = the physical iShares reference fund on the same index (for swap
# holdings, the fund with real published constituents). Used to build the
# get-product-data holdings URL. STOXX 600 (DE) is German-domiciled, so it needs
# the de-ishares site (English labels still come back via en_DE).
REGISTRY: dict[str, Instrument] = {
    "IE00BMTX1Y45": Instrument(
        "IE00BMTX1Y45", "iShares S&P 500 Swap", "S&P 500",
        "swap", "USD", "SXR8.DE", product_id=253743),
    "LU0908500753": Instrument(
        "LU0908500753", "Amundi Core STOXX Europe 600", "STOXX Europe 600",
        "physical", "EUR", "EXSA.DE", product_id=251931,
        site="de-ishares", locale="en_DE"),
    "LU3086269894": Instrument(
        "LU3086269894", "MSCI Japan", "MSCI Japan",
        "swap", "EUR", "IQQJ.DE", product_id=251866),
    "IE000S3N6R34": Instrument(
        "IE000S3N6R34", "MSCI EM Swap USD (Acc)", "MSCI Emerging Markets",
        "swap", "USD", "IS3N.DE", product_id=264659),
    "IE00BG47KH54": Instrument(
        "IE00BG47KH54", "Vanguard Global Aggregate Bond EUR-H",
        "Bloomberg Global Aggregate (EUR-H)", "physical", "EUR", "VAGF.DE",
        product_id=291770),
    "IE00B3F81R35": Instrument(
        "IE00B3F81R35", "iShares Core EUR Corp Bond",
        "Bloomberg Euro Corporate Bond", "physical", "EUR", "IEAC.AS",
        product_id=251726),
}

_HOLDINGS_API = (
    "https://www.ishares.com/varnish-api/blk-one01-product-data/product-data/"
    "api/v2/get-product-data?appSubType=ISHARES&appType=PRODUCT_PAGE"
    "&component=holdings.all&locale={locale}&portfolioId={pid}"
    "&targetSite={site}&userType=individual&excludeContent=True"
)


def holdings_api_url(inst: "Instrument") -> str | None:
    """Build the get-product-data holdings URL for an instrument, if it has a product id."""
    if not inst.product_id:
        return None
    return _HOLDINGS_API.format(locale=inst.locale, pid=inst.product_id, site=inst.site)


def source_for(isin: str, override: str | None = None) -> str | None:
    """Resolve a holdings source: explicit override, else registry URL, else built API URL."""
    if override:
        return override
    inst = REGISTRY.get(isin)
    if not inst:
        return None
    return inst.holdings_url or holdings_api_url(inst)

# Capital split from core-portfolio-risk-overlap.md (12.5% each equity, 25% each bond)
DEFAULT_WEIGHTS: dict[str, float] = {
    "IE00BMTX1Y45": 0.125,
    "LU0908500753": 0.125,
    "LU3086269894": 0.125,
    "IE000S3N6R34": 0.125,
    "IE00BG47KH54": 0.25,
    "IE00B3F81R35": 0.25,
}
