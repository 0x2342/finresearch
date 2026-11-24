"""Look-through providers + tier resolution.

Two tiers of look-through for a held ISIN, behind one interface:
  - name-level: a BlackRock/iShares holdings CSV (via a resolved reference fund),
    which serves every dimension (Names, and Sector/Country by aggregation).
  - factsheet:  seeded sector/country vectors (core/exposures) — the fallback.

Tier selection (global, set in the UI):
  - "auto"      : name-level if a source URL resolves, else factsheet.
  - "name"      : name-level only (no fallback) — forces a common tier for valid
                  cross-fund comparison.
  - "factsheet" : seeded vectors only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import exposures, holdings


@dataclass
class LookThrough:
    vectors: dict[str, dict[str, float]] = field(default_factory=dict)  # dim -> {label: w}
    source: str = "none"          # "name-level" | "factsheet" | "none"
    as_of: str | None = None
    n_names: int | None = None

    def vector(self, dimension: str) -> dict[str, float]:
        return self.vectors.get(dimension, {})


def _name_level(url: str) -> LookThrough | None:
    df = holdings.fetch(url)
    if df is None or df.empty:
        return None
    nm = holdings.names(df)
    if not nm:
        return None
    return LookThrough(
        vectors={
            "Holdings (names)": nm,
            "Sector": holdings.sectors(df),
            "Country": holdings.countries(df),
        },
        source="name-level",
        as_of=df.attrs.get("as_of"),
        n_names=len(nm),
    )


def _factsheet(isin: str) -> LookThrough | None:
    sec = exposures.SECTORS.get(isin)
    ctry = exposures.COUNTRIES.get(isin)
    if not sec and not ctry:
        return None
    vecs: dict[str, dict[str, float]] = {}
    if sec:
        vecs["Sector"] = sec
    if ctry:
        vecs["Country"] = ctry
    return LookThrough(vectors=vecs, source="factsheet", as_of=exposures.AS_OF.get(isin))


def resolve(isin: str, tier: str, source_url: str | None) -> LookThrough:
    """Look-through for one holding under the chosen tier."""
    if tier in ("auto", "name") and source_url:
        lt = _name_level(source_url)
        if lt is not None:
            return lt
    if tier == "name":
        return LookThrough(source="none")
    fs = _factsheet(isin)
    return fs if fs is not None else LookThrough(source="none")


def resolve_all(rows, tier: str, source_of) -> dict[str, LookThrough]:
    """rows: iterable with ISIN; source_of: isin -> url|None."""
    return {r["ISIN"]: resolve(r["ISIN"], tier, source_of(r["ISIN"])) for r in rows}
