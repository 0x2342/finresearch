"""Name-level look-through from a BlackRock / iShares 'Detailed Holdings' CSV.

`source` may be an http(s) URL (the iShares product-page "Detailed Holdings"
download) or a local file path (used for tests/fixtures). The CSV has a few
metadata rows, then a table whose header carries a "Weight (%)" column; we parse
that table into a name -> weight vector and aggregate it up to sector / country
so a single name-level source can serve every look-through dimension.

Physical funds only: a swap fund's own file is a substitute basket, so the
resolver (core/providers) points a swap holding at a physical reference fund.
"""
from __future__ import annotations

import io
import os

import pandas as pd

# Country name (BlackRock "Location") -> ISO alpha-2, to match factsheet vectors.
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
# Light sector normalisation to the GICS labels used by the factsheet vectors.
_SECTOR = {
    "Communication": "Communication Services",
    "Information Technology": "Information Technology",
    "Health Care": "Health Care", "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
}


def _read_text(source: str) -> str | None:
    try:
        if source.startswith(("http://", "https://")):
            import requests

            return requests.get(source, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
        path = source[7:] if source.startswith("file://") else source
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                return f.read()
    except Exception:
        return None
    return None


def fetch(source: str) -> pd.DataFrame | None:
    """Parse a holdings CSV from URL or path. None on failure. as-of in .attrs."""
    txt = _read_text(source)
    if not txt:
        return None
    lines = txt.splitlines()
    as_of = None
    start = None
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
    df.attrs["as_of"] = as_of
    return df


def _col(df: pd.DataFrame, *names: str) -> str | None:
    low = {c.strip().lower(): c for c in df.columns}
    for n in names:
        if n in low:
            return low[n]
    return None


def names(df: pd.DataFrame) -> dict[str, float]:
    """Name -> weight fraction (0..1)."""
    nc, wc = _col(df, "name"), _col(df, "weight (%)", "weight")
    if not nc or not wc:
        return {}
    d = df[[nc, wc]].copy()
    d[wc] = pd.to_numeric(d[wc], errors="coerce")
    d = d.dropna(subset=[wc])
    out: dict[str, float] = {}
    for _, r in d.iterrows():
        w = float(r[wc]) / 100.0
        if w > 0:
            out[str(r[nc])] = out.get(str(r[nc]), 0.0) + w
    return out


def _aggregate(df: pd.DataFrame, group_col: str, mapping: dict | None) -> dict[str, float]:
    gc, wc = _col(df, group_col), _col(df, "weight (%)", "weight")
    if not gc or not wc:
        return {}
    d = df[[gc, wc]].copy()
    d[wc] = pd.to_numeric(d[wc], errors="coerce")
    d = d.dropna(subset=[wc])
    out: dict[str, float] = {}
    for _, r in d.iterrows():
        label = str(r[gc]).strip()
        if mapping:
            label = mapping.get(label, label)
        w = float(r[wc]) / 100.0
        if w > 0 and label and label.lower() != "nan":
            out[label] = out.get(label, 0.0) + w
    return out


def sectors(df: pd.DataFrame) -> dict[str, float]:
    return _aggregate(df, "sector", _SECTOR)


def countries(df: pd.DataFrame) -> dict[str, float]:
    return _aggregate(df, "location", _COUNTRY)
