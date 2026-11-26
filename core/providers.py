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


def _norm(v: dict[str, float]) -> dict[str, float]:
    """Normalise a vector to sum to 1 (of its invested/covered base), so that
    self-overlap (Σ min) reads 100%. Cash/derivatives (and, for factsheet, the
    uncovered tail) are already excluded, so this rebases to what's covered."""
    total = sum(v.values())
    return {k: x / total for k, x in v.items()} if total else v


@dataclass
class LookThrough:
    vectors: dict[str, dict[str, float]] = field(default_factory=dict)  # dim -> {key: w}
    source: str = "none"          # "name-level" | "factsheet" | "none"
    as_of: str | None = None
    n_names: int | None = None
    note: str | None = None       # failure reason when name-level was attempted
    labels: dict[str, str] = field(default_factory=dict)  # security key (ISIN) -> name
    coverage: dict[str, float] | None = None              # dim -> covered weight

    def vector(self, dimension: str) -> dict[str, float]:
        return self.vectors.get(dimension, {})


def _name_level(url: str):
    """Return (LookThrough, None) on success, or (None, error_reason)."""
    h = holdings.load(url)
    if h and h.get("securities"):
        return LookThrough(
            vectors={
                "Holdings (security)": _norm(h["securities"]),  # ISIN-keyed, true security overlap
                "Holdings (issuer)": _norm(h["issuers"]),       # name-keyed, common-issuer exposure
                "Sector": _norm(h["sectors"]),
                "Country": _norm(h["countries"]),
            },
            source="name-level",
            as_of=h.get("as_of"),
            n_names=h["n"],
            labels=h.get("labels", {}),
            coverage=h.get("coverage"),
        ), None
    return None, (h.get("error") if isinstance(h, dict) else "fetch failed")


def _factsheet(isin: str) -> LookThrough | None:
    sec = exposures.SECTORS.get(isin)
    ctry = exposures.COUNTRIES.get(isin)
    if not sec and not ctry:
        return None
    vecs: dict[str, dict[str, float]] = {}
    if sec:
        vecs["Sector"] = _norm(sec)
    if ctry:
        vecs["Country"] = _norm(ctry)
    return LookThrough(vectors=vecs, source="factsheet", as_of=exposures.AS_OF.get(isin))


def resolve(isin: str, tier: str, source_url: str | None) -> LookThrough:
    """Look-through for one holding under the chosen tier."""
    if tier in ("auto", "name") and source_url:
        lt, err = _name_level(source_url)
        if lt is not None:
            return lt
        if tier == "name":
            return LookThrough(source="none", note=err)
        fs = _factsheet(isin)  # auto -> fall back, but keep the reason
        if fs is not None:
            fs.note = err
            return fs
        return LookThrough(source="none", note=err)
    if tier == "name":
        return LookThrough(source="none")
    fs = _factsheet(isin)
    return fs if fs is not None else LookThrough(source="none")


def resolve_all(rows, tier: str, source_of) -> dict[str, LookThrough]:
    """rows: iterable with ISIN; source_of: isin -> url|None."""
    return {r["ISIN"]: resolve(r["ISIN"], tier, source_of(r["ISIN"])) for r in rows}
