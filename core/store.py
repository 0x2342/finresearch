"""Portfolio persistence: multiple named portfolios, each with a weight mode.

Layout under data/portfolios/:
  index.json   -> {"active": <slug>, "portfolios": [{slug, name, mode}, ...]}
  <slug>.csv   -> that portfolio's rows (ISIN, Name, Ticker, Weight, Units)

Weight mode (per portfolio):
  "research" -> effective weights come from the manual Weight column
  "tracked"  -> effective weights come from Units x last price (the real book)

CSV-per-portfolio keeps everything hand-editable; the index is small JSON.
A legacy single data/portfolio.csv is migrated into a "Core" research portfolio.
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd

_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "portfolios")
_LEGACY = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.csv")
COLUMNS = ["ISIN", "Name", "Ticker", "Weight", "Units"]
MODES = ("research", "tracked")


def _index_file() -> str:
    return os.path.join(_DIR, "index.json")


def _csv_file(slug: str) -> str:
    return os.path.join(_DIR, f"{slug}.csv")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return s or "portfolio"


def _read_csv(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS]
    for c in ("ISIN", "Name", "Ticker"):
        df[c] = df[c].where(df[c].notna(), "").astype(str)
    for c in ("Weight", "Units"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _read_index() -> dict | None:
    if os.path.exists(_index_file()):
        try:
            with open(_index_file()) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_index(idx: dict) -> None:
    os.makedirs(_DIR, exist_ok=True)
    with open(_index_file(), "w") as f:
        json.dump(idx, f, indent=2)


def load_index() -> dict | None:
    """Return the portfolios index, migrating a legacy file, else None."""
    idx = _read_index()
    if idx is not None:
        return idx
    if os.path.exists(_LEGACY):
        df = _read_csv(_LEGACY)
        if df is not None and not df.empty:
            create_portfolio("Core", "research", df)
            try:
                os.remove(_LEGACY)
            except Exception:
                pass
            return _read_index()
    return None


def save_portfolio(slug: str, df: pd.DataFrame) -> None:
    os.makedirs(_DIR, exist_ok=True)
    try:
        df.reindex(columns=COLUMNS).to_csv(_csv_file(slug), index=False)
    except Exception:
        pass


def load_portfolio(slug: str) -> pd.DataFrame | None:
    path = _csv_file(slug)
    return _read_csv(path) if os.path.exists(path) else None


def create_portfolio(name: str, mode: str = "research", rows: pd.DataFrame | None = None) -> str:
    idx = _read_index() or {"active": None, "portfolios": []}
    base = slugify(name)
    slug, n = base, 2
    existing = {p["slug"] for p in idx["portfolios"]}
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1
    mode = mode if mode in MODES else "research"
    save_portfolio(slug, rows if rows is not None else pd.DataFrame(columns=COLUMNS))
    idx["portfolios"].append({"slug": slug, "name": name, "mode": mode})
    idx["active"] = slug
    _write_index(idx)
    return slug


def delete_portfolio(slug: str) -> None:
    idx = _read_index()
    if not idx:
        return
    idx["portfolios"] = [p for p in idx["portfolios"] if p["slug"] != slug]
    if idx.get("active") == slug:
        idx["active"] = idx["portfolios"][0]["slug"] if idx["portfolios"] else None
    _write_index(idx)
    try:
        os.remove(_csv_file(slug))
    except Exception:
        pass


def set_active(slug: str) -> None:
    idx = _read_index()
    if idx and any(p["slug"] == slug for p in idx["portfolios"]):
        idx["active"] = slug
        _write_index(idx)


def set_mode(slug: str, mode: str) -> None:
    idx = _read_index()
    if not idx or mode not in MODES:
        return
    for p in idx["portfolios"]:
        if p["slug"] == slug:
            p["mode"] = mode
    _write_index(idx)


def rename(slug: str, name: str) -> None:
    idx = _read_index()
    if not idx:
        return
    for p in idx["portfolios"]:
        if p["slug"] == slug:
            p["name"] = name
    _write_index(idx)


def mode_of(idx: dict, slug: str) -> str:
    for p in idx["portfolios"]:
        if p["slug"] == slug:
            return p.get("mode", "research")
    return "research"


# --- Look-through source URLs (ISIN -> iShares holdings CSV) ---------------- #
_SOURCES = os.path.join(os.path.dirname(__file__), "..", "data", "sources.csv")


def load_sources() -> dict[str, str]:
    try:
        if os.path.exists(_SOURCES):
            df = pd.read_csv(_SOURCES)
            out = {}
            for _, r in df.iterrows():
                isin, url = str(r.get("ISIN", "")).strip(), str(r.get("URL", "")).strip()
                if isin and url and url.lower() != "nan":
                    out[isin] = url
            return out
    except Exception:
        pass
    return {}


def save_sources(mapping: dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(_SOURCES), exist_ok=True)
        rows = [{"ISIN": k, "URL": v} for k, v in mapping.items() if k and v]
        pd.DataFrame(rows, columns=["ISIN", "URL"]).to_csv(_SOURCES, index=False)
    except Exception:
        pass
