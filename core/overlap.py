"""Overlap engine -- the app's reason to exist.

Operates on weight vectors (label -> fraction of fund). Works identically on
seeded sector/country vectors (offline) and on live name-level holdings
(BlackRock CSV) -- same maths, different granularity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def weight_overlap(a: dict[str, float], b: dict[str, float]) -> float:
    """Shared economic exposure: sum of min(weight) over the union of labels.

    For two vectors that each sum to ~1 this is the classic overlap coefficient
    in [0, 1] -- the fraction of capital the two funds hold in common buckets.
    """
    keys = set(a) | set(b)
    return float(sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in keys))


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of the two weight vectors (shape, ignoring magnitude)."""
    keys = sorted(set(a) | set(b))
    va = np.array([a.get(k, 0.0) for k in keys])
    vb = np.array([b.get(k, 0.0) for k in keys])
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(va @ vb / denom) if denom else 0.0


def pairwise(vectors: dict[str, dict[str, float]], metric=weight_overlap) -> pd.DataFrame:
    """Symmetric overlap matrix across the given funds."""
    keys = list(vectors)
    m = pd.DataFrame(index=keys, columns=keys, dtype=float)
    for i in keys:
        for j in keys:
            m.loc[i, j] = metric(vectors[i], vectors[j])
    return m


def portfolio_lookthrough(
    weights: dict[str, float], vectors: dict[str, dict[str, float]]
) -> pd.Series:
    """Aggregate portfolio exposure: sum_i w_i * vector_i.

    Only funds that have a vector contribute; the result is expressed as a
    fraction of total portfolio capital (so uncovered funds read as absent,
    not renormalised away). Surfaces true portfolio-wide concentration --
    e.g. stacked semiconductor exposure across US + EM sleeves.
    """
    agg: dict[str, float] = {}
    for isin, w in weights.items():
        v = vectors.get(isin)
        if not v:
            continue
        for label, x in v.items():
            agg[label] = agg.get(label, 0.0) + w * x
    return pd.Series(agg).sort_values(ascending=False)


def normalise(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()} if total else weights


def _to_float(x, default: float = 0.0) -> float:
    try:
        import math

        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def effective_weights(rows, mode: str, last_prices: dict[str, float]) -> dict[str, float]:
    """Portfolio weights per mode.

    rows: iterable of dicts with ISIN / Ticker / Weight / Units.
    - "tracked": normalise(Units x last price) -- the real book.
    - "research": normalise(manual Weight) -- a hypothetical allocation.
    """
    if mode == "tracked":
        mv: dict[str, float] = {}
        for r in rows:
            units = _to_float(r.get("Units"))
            price = last_prices.get(r.get("Ticker"))
            if price and units:
                mv[r["ISIN"]] = units * float(price)
        return normalise(mv)
    manual = {r["ISIN"]: _to_float(r.get("Weight")) for r in rows}
    return normalise({k: v for k, v in manual.items() if v > 0})
