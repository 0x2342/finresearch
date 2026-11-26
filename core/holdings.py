"""Name-level look-through from iShares holdings data.

Two input shapes, auto-detected:
  - the iShares `get-product-data` JSON API (component=holdings.all) — the
    reliable source; column-oriented parallel arrays under
    componentsByNameMap.holdings.containersByNameMap.all.dataPointsByNameMap.
  - a BlackRock "Detailed Holdings" CSV (kept as a fallback / for fixtures).

`source` may be an http(s) URL or a local file path. `load()` returns a dict:
  {"securities": {isin→w}, "issuers": {name→w}, "labels": {isin→name},
   "sectors": {...}, "countries": {...}, "coverage": {...}, "as_of": str|None, "n": int}
with weights as fractions of the fund, cash/derivatives excluded, sector/country
aggregated up from the per-holding fields.

Physical funds only: a swap fund's own file is a substitute basket, so the
resolver (core/providers) points a swap holding at a physical reference fund.
"""
from __future__ import annotations

import io
import json
import os

import pandas as pd

# BlackRock "Location" / countryOfRisk -> ISO alpha-2, to match factsheet vectors.
_COUNTRY = {
    "United States": "US", "Taiwan": "TW", "Korea (South)": "KR", "South Korea": "KR",
    "China": "CN", "Hong Kong": "HK", "India": "IN", "Japan": "JP",
    "United Kingdom": "GB", "Germany": "DE", "France": "FR", "Netherlands": "NL",
    "Switzerland": "CH", "Spain": "ES", "Italy": "IT", "Sweden": "SE",
    "Denmark": "DK", "Finland": "FI", "Belgium": "BE", "Norway": "NO",
    "Ireland": "IE", "Poland": "PL", "Austria": "AT", "Portugal": "PT",
    "Luxembourg": "LU", "Greece": "GR", "Canada": "CA", "Australia": "AU",
    "Brazil": "BR", "Mexico": "MX", "South Africa": "ZA", "Saudi Arabia": "SA",
    "Indonesia": "ID", "Malaysia": "MY", "Thailand": "TH", "Philippines": "PH",
    "Turkey": "TR", "Chile": "CL", "Qatar": "QA", "Kuwait": "KW",
    "United Arab Emirates": "AE", "Hungary": "HU", "Peru": "PE",
    "Czech Republic": "CZ", "Egypt": "EG", "Colombia": "CO", "New Zealand": "NZ",
}
# Normalise iShares sector labels to the GICS names used by factsheet vectors.
# Bond funds report Bloomberg bond-sector labels (Banking, Treasuries, ...) rather
# than GICS, so without this crosswalk a bond fund's "Banking" never matches an
# equity fund's "Financials" and cross-asset sector overlap collapses to ~0. This
# maps corporate bond sectors to GICS (matching the factsheet tagging) and buckets
# the non-corporate portion (govt / securitized) under labels with no equity
# analog, so those correctly do NOT overlap equities.
_SECTOR = {
    "Communication": "Communication Services",   # equity label variant
    # --- corporate bond sectors (Bloomberg BCLASS) -> GICS ---
    "Banking": "Financials", "Brokerage": "Financials",
    "Brokerage/Asset Managers/Exchanges": "Financials",
    "Finance Companies": "Financials", "Financial Other": "Financials",
    "Financial Institutions": "Financials", "Insurance": "Financials",
    "REITs": "Real Estate", "Reits": "Real Estate",
    "Electric": "Utilities", "Natural Gas": "Utilities", "Utility Other": "Utilities",
    "Capital Goods": "Industrials", "Transportation": "Industrials",
    "Industrial Other": "Industrials", "Basic Industry": "Materials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Non-Cyclical": "Consumer Staples",
    "Communications": "Communication Services", "Technology": "Information Technology",
    "Pharmaceuticals": "Health Care",
    # --- non-corporate (no GICS equity analog) -> consistent buckets ---
    "Treasury": "Government", "Treasuries": "Government", "Sovereign": "Government",
    "Government-Related": "Government", "Government Related": "Government",
    "Agency": "Government", "Agency Fixed Rate": "Government",
    "Agency Variable Rate": "Government", "Supranational": "Government",
    "Local Authority": "Government", "Local Government": "Government",
    "Owned No Guarantee": "Government", "Government Guaranteed": "Government",
    "Mortgage Collateralized": "Securitized", "Securitized": "Securitized",
    "MBS": "Securitized", "ABS": "Securitized", "CMBS": "Securitized",
    "Covered": "Securitized", "Whole Business ABS": "Securitized",
}
# Rows that are not real securities (excluded from look-through).
_CASH_ASSET = {"Cash", "FX", "Futures", "Cash Collateral and Margins"}
_CASH_SECTOR = {"Cash and/or Derivatives"}


def _read_text(source: str):
    """Return (text, error). error is None on success, else a short reason string.

    HTTP: 120s timeout (the Global Aggregate holdings payload is ~20k rows) and one
    retry on a 5xx / network error, since the API 500s intermittently under load.
    """
    if source.startswith(("http://", "https://")):
        import time

        try:
            import requests
        except Exception:
            return None, "requests unavailable"
        last = "no response"
        for attempt in range(2):
            try:
                r = requests.get(source, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    return r.text, None
                last = f"HTTP {r.status_code}"
                if r.status_code < 500:
                    break
            except Exception as e:
                last = type(e).__name__
            if attempt == 0:
                time.sleep(2)
        return None, last
    path = source[7:] if source.startswith("file://") else source
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                return f.read(), None
        return None, "file not found"
    except Exception as e:
        return None, type(e).__name__


def _accumulate(names, weights, sectors, locations, assets, isins=None):
    sic: dict[str, float] = {}    # security-level, keyed by ISIN (fallback name)
    iss: dict[str, float] = {}    # issuer-level, keyed by name
    lbl: dict[str, str] = {}      # security key -> display label
    sec: dict[str, float] = {}
    ctry: dict[str, float] = {}
    # pre-normalisation weight that carried each identifier, to report coverage
    cov = {"total": 0.0, "security": 0.0, "sector": 0.0, "country": 0.0}
    for i, raw_name in enumerate(names):
        w = weights[i] if i < len(weights) else None
        if w in (None, ""):
            continue
        try:
            wf = float(w) / 100.0
        except (TypeError, ValueError):
            continue
        if wf <= 0:
            continue
        asset = str(assets[i]) if assets and i < len(assets) and assets[i] else ""
        s_raw = str(sectors[i]) if sectors and i < len(sectors) and sectors[i] else ""
        if asset in _CASH_ASSET or s_raw in _CASH_SECTOR:
            continue
        cov["total"] += wf
        name = str(raw_name).strip() if raw_name else ""
        isin = str(isins[i]).strip() if isins and i < len(isins) and isins[i] else ""
        # Security identity: ISIN distinguishes distinct bonds of one issuer
        # (different maturities) that share a name; fall back to name when absent.
        key = isin or name
        if key:
            sic[key] = sic.get(key, 0.0) + wf
            lbl.setdefault(key, name or isin)
            cov["security"] += wf
        if name:
            iss[name] = iss.get(name, 0.0) + wf
        if s_raw:
            s = _SECTOR.get(s_raw, s_raw)
            sec[s] = sec.get(s, 0.0) + wf
            cov["sector"] += wf
        loc = locations[i] if locations and i < len(locations) else None
        if loc:
            c = _COUNTRY.get(str(loc), str(loc))
            ctry[c] = ctry.get(c, 0.0) + wf
            cov["country"] += wf
    return {"securities": sic, "issuers": iss, "labels": lbl,
            "sectors": sec, "countries": ctry, "n": len(sic), "coverage": cov}


def _parse_json(text: str) -> dict | None:
    try:
        d = json.loads(text)
        dp = (d["componentsByNameMap"]["holdings"]["containersByNameMap"]
              ["all"]["dataPointsByNameMap"])
    except Exception:
        return None

    def arr(field):
        node = dp.get(field)
        return node.get("value") if isinstance(node, dict) else None

    names, weights = arr("issueName"), arr("holdingPercent")
    if not names or not weights:
        return None
    out = _accumulate(names, weights, arr("sectorName"), arr("countryOfRisk"),
                      arr("assetClass"), isins=arr("isin"))
    as_of = None
    node = dp.get("asOfDate")
    if isinstance(node, dict):
        as_of = node.get("formattedValue")
    out["as_of"] = as_of
    return out if out["securities"] else None


def _parse_csv(text: str) -> dict | None:
    lines = text.splitlines()
    as_of, start = None, None
    for i, ln in enumerate(lines):
        if as_of is None and "as of" in ln.lower():
            rest = ln.split(",", 1)
            if len(rest) > 1:
                as_of = rest[1].strip().strip('"').strip()
        if "Weight (%)" in ln:
            start = i
            break
    if start is None:
        return None
    try:
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])), thousands=",")
    except Exception:
        return None

    def col(*cands):
        low = {c.strip().lower(): c for c in df.columns}
        for c in cands:
            if c in low:
                return low[c]
        return None

    nc, wc = col("name"), col("weight (%)", "weight")
    sc, lc = col("sector"), col("location")
    ac, ic = col("asset class"), col("isin")
    if not nc or not wc:
        return None
    out = _accumulate(
        list(df[nc]), list(df[wc]),
        list(df[sc]) if sc else None,
        list(df[lc]) if lc else None,
        list(df[ac]) if ac else None,
        isins=list(df[ic]) if ic else None,
    )
    out["as_of"] = as_of
    return out if out["securities"] else None


def load(source: str) -> dict:
    """Normalized look-through for a holdings URL/path.

    On success returns {"securities", "issuers", "labels", "sectors",
    "countries", "coverage", "as_of", "n"}. `securities` is keyed by ISIN
    (fallback name); `issuers` by name; `labels` maps security key -> display name.
    On failure returns {"error": "<reason>"} so callers can surface why.
    """
    text, err = _read_text(source)
    if text is None:
        return {"error": err or "fetch failed"}
    if text.lstrip().startswith("{"):
        parsed = _parse_json(text)
        if parsed and parsed.get("securities"):
            return parsed
        try:  # recognise the iShares error-JSON body
            d = json.loads(text)
            if isinstance(d, dict) and d.get("error"):
                return {"error": f"API: {d.get('error')}"}
        except Exception:
            pass
        return {"error": "no holdings in response"}
    parsed = _parse_csv(text)
    if parsed and parsed.get("securities"):
        return parsed
    return {"error": "could not parse holdings"}
