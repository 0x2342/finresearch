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

import re
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


def holdings_api_url_for(product_id: int | None, site: str = "uk-ishares",
                         locale: str = "en_GB") -> str | None:
    """Build a get-product-data holdings URL for a product id."""
    if not product_id:
        return None
    return _HOLDINGS_API.format(locale=locale, pid=product_id, site=site)


def holdings_api_url(inst: "Instrument") -> str | None:
    return holdings_api_url_for(inst.product_id, inst.site, inst.locale)


# --------------------------------------------------------------------------- #
# Automatic ISIN -> index -> reference-fund resolution
#
# There is no free ISIN->index feed (index membership is licensed), so the index
# comes from the curated registry, an explicit hint, or the fund's name. The
# index then maps to a physical iShares reference fund (verified product ids).
# --------------------------------------------------------------------------- #
@dataclass
class RefFund:
    product_id: int
    site: str = "uk-ishares"
    locale: str = "en_GB"


# canonical index name -> physical iShares reference fund
INDEX_REF: dict[str, RefFund] = {
    "S&P 500": RefFund(253743),
    "STOXX Europe 600": RefFund(251931, "de-ishares", "en_DE"),
    "MSCI Japan": RefFund(251866),
    "MSCI Emerging Markets": RefFund(264659),
    "Bloomberg Euro Corporate Bond": RefFund(251726),
    "Bloomberg Global Aggregate (EUR-H)": RefFund(291770),
}

# substrings (normalised) that map a fund name / index hint to a canonical index.
# Kept specific (euro-corp, not generic "corporate bond") to avoid mis-mapping.
_INDEX_ALIASES: dict[str, list[str]] = {
    "S&P 500": ["s&p 500", "s&p500", "sp 500", "sp500", "s and p 500"],
    "STOXX Europe 600": ["stoxx europe 600", "stoxx 600", "stoxx600"],
    "MSCI Japan": ["msci japan"],
    "MSCI Emerging Markets": ["msci em ", "msci emerging markets"],
    "Bloomberg Euro Corporate Bond": ["euro corp", "eur corp", "euro corporate", "core corp bond"],
    "Bloomberg Global Aggregate (EUR-H)": ["global aggregate", "global agg"],
}


@dataclass
class Reference:
    product_id: int
    site: str
    locale: str
    index: str
    how: str          # 'registry' | 'index-hint' | 'name-match'


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9& ]+", " ", str(s).lower()) + " "


def match_index(text: str | None) -> str | None:
    """Map a fund name or index hint to a canonical index name, or None."""
    if not text:
        return None
    t = _norm_text(text)
    for canon, aliases in _INDEX_ALIASES.items():
        if any(a in t for a in aliases):
            return canon
    return None


def resolve_reference(isin: str, name: str | None = None,
                      index: str | None = None) -> Reference | None:
    """Resolve a held ISIN to a physical iShares reference fund.

    Priority: curated registry -> explicit index hint -> fund-name match. Returns
    None when nothing matches (caller falls back to factsheet).
    """
    inst = REGISTRY.get(isin)
    if inst and inst.product_id:
        return Reference(inst.product_id, inst.site, inst.locale, inst.index, "registry")
    canon, how = match_index(index), "index-hint"
    if not canon:
        canon, how = match_index(name), "name-match"
    if canon and canon in INDEX_REF:
        r = INDEX_REF[canon]
        return Reference(r.product_id, r.site, r.locale, canon, how)
    return None


def source_for(isin: str, override: str | None = None, name: str | None = None) -> str | None:
    """Resolve a holdings source: override -> registry -> auto-resolved reference."""
    if override:
        return override
    inst = REGISTRY.get(isin)
    if inst:
        return inst.holdings_url or holdings_api_url(inst)
    ref = resolve_reference(isin, name=name)
    return holdings_api_url_for(ref.product_id, ref.site, ref.locale) if ref else None

# Capital split from core-portfolio-risk-overlap.md (12.5% each equity, 25% each bond)
DEFAULT_WEIGHTS: dict[str, float] = {
    "IE00BMTX1Y45": 0.125,
    "LU0908500753": 0.125,
    "LU3086269894": 0.125,
    "IE000S3N6R34": 0.125,
    "IE00BG47KH54": 0.25,
    "IE00B3F81R35": 0.25,
}
