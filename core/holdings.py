"""Name-level look-through from iShares holdings data.

Two input shapes, auto-detected:
  - the iShares `get-product-data` JSON API (component=holdings.all) — the
    reliable source; column-oriented parallel arrays under
    componentsByNameMap.holdings.containersByNameMap.all.dataPointsByNameMap.
  - a BlackRock "Detailed Holdings" CSV (kept as a fallback / for fixtures).

`source` may be an http(s) URL or a local file path. `load()` returns a dict:
  {"names": {...}, "sectors": {...}, "countries": {...}, "as_of": str|None, "n": int}
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
    "China": "CN", "Hong Kong": "CN", "India": "IN", "Japan": "JP",
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
_SECTOR = {"Communication": "Communication Services"}
# Rows that are not real securities (excluded from look-through).
_CASH_ASSET = {"Cash", "FX", "Futures", "Cash Collateral and Margins"}
_CASH_SECTOR = {"Cash and/or Derivatives"}


def _read_text(source: str) -> str | None:
    try:
        if source.startswith(("http://", "https://")):
            import requests

            return requests.get(source, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text
        path = source[7:] if source.startswith("file://") else source
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                return f.read()
    except Exception:
        return None
    return None


def _accumulate(names, weights, sectors, locations, assets):
    nm: dict[str, float] = {}
    sec: dict[str, float] = {}
    ctry: dict[str, float] = {}
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
        name = str(raw_name).strip() if raw_name else ""
        if name:
            nm[name] = nm.get(name, 0.0) + wf
        if s_raw:
            s = _SECTOR.get(s_raw, s_raw)
            sec[s] = sec.get(s, 0.0) + wf
        loc = locations[i] if locations and i < len(locations) else None
        if loc:
            c = _COUNTRY.get(str(loc), str(loc))
            ctry[c] = ctry.get(c, 0.0) + wf
    return {"names": nm, "sectors": sec, "countries": ctry, "n": len(nm)}


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
    out = _accumulate(names, weights, arr("sectorName"), arr("countryOfRisk"), arr("assetClass"))
    as_of = None
    node = dp.get("asOfDate")
    if isinstance(node, dict):
        as_of = node.get("formattedValue")
    out["as_of"] = as_of
    return out if out["names"] else None


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
    ac = col("asset class")
    if not nc or not wc:
        return None
    out = _accumulate(
        list(df[nc]), list(df[wc]),
        list(df[sc]) if sc else None,
        list(df[lc]) if lc else None,
        list(df[ac]) if ac else None,
    )
    out["as_of"] = as_of
    return out if out["names"] else None


def load(source: str) -> dict | None:
    """Return normalized look-through for a holdings URL or path. None on failure."""
    text = _read_text(source)
    if not text:
        return None
    return _parse_json(text) if text.lstrip().startswith("{") else _parse_csv(text)
