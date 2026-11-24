"""Live name-level look-through from BlackRock / iShares 'Detailed Holdings' CSV.

Secondary to the seeded factsheet exposures: set `holdings_url` on a registry
Instrument (the physical reference fund's CSV) and this parses it into a
name -> weight vector that feeds the same overlap engine. Physical funds only;
a swap fund's own file is a substitute basket and must not be used here.
"""
from __future__ import annotations

import io

import pandas as pd


def fetch_ishares_holdings(url: str) -> pd.DataFrame | None:
    """Download and parse an iShares holdings CSV. None on failure."""
    try:
        import requests

        txt = requests.get(
            url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}
        ).text
        lines = txt.splitlines()
        # The real table starts at the row carrying the weight column header.
        start = next(
            i for i, ln in enumerate(lines) if "Weight (%)" in ln
        )
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])), thousands=",")
        return df
    except Exception:
        return None


def holdings_weights(df: pd.DataFrame) -> dict[str, float]:
    """Name -> weight fraction (0..1) from a parsed holdings frame."""
    if df is None or df.empty:
        return {}
    name_col = next((c for c in df.columns if c.strip().lower() == "name"), None)
    wcol = next((c for c in df.columns if "weight" in c.lower()), None)
    if not name_col or not wcol:
        return {}
    d = df[[name_col, wcol]].dropna()
    d = d[pd.to_numeric(d[wcol], errors="coerce").notna()]
    return {
        str(r[name_col]): float(r[wcol]) / 100.0
        for _, r in d.iterrows()
        if float(r[wcol]) > 0
    }
