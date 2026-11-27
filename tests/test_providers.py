"""Tier resolution for look-through providers."""
from __future__ import annotations

import math

from core import providers

# ISINs present in the seeded exposures (offline factsheet tier).
ISIN_FULL = "IE000S3N6R34"   # has both Sector and Country vectors
ISIN_CTRY_ONLY = "IE00BG47KH54"  # Country only (bond-style, no GICS sector)


def test_norm_rebases_to_covered():
    assert providers._norm({"a": 1.0, "b": 3.0}) == {"a": 0.25, "b": 0.75}
    assert providers._norm({}) == {}


def test_factsheet_tier_returns_seeded_vectors():
    lt = providers.resolve(ISIN_FULL, "factsheet", None)
    assert lt.source == "factsheet"
    assert "Sector" in lt.vectors and "Country" in lt.vectors
    # normalised to sum 1
    assert math.isclose(sum(lt.vector("Sector").values()), 1.0, rel_tol=1e-6)


def test_factsheet_country_only_instrument():
    lt = providers.resolve(ISIN_CTRY_ONLY, "factsheet", None)
    assert "Country" in lt.vectors
    assert "Sector" not in lt.vectors


def test_unknown_isin_resolves_to_none():
    lt = providers.resolve("XX0000000000", "factsheet", None)
    assert lt.source == "none"


def test_name_tier_without_url_returns_none_source():
    lt = providers.resolve(ISIN_FULL, "name", None)
    assert lt.source == "none"


def test_auto_tier_falls_back_to_factsheet_with_reason(monkeypatch):
    monkeypatch.setattr(providers.holdings, "load", lambda url: {"error": "HTTP 500"})
    lt = providers.resolve(ISIN_FULL, "auto", "https://example.com/h.csv")
    # name-level failed, auto falls back to factsheet but keeps the failure note
    assert lt.source == "factsheet"
    assert lt.note == "HTTP 500"


def test_name_level_success_path(monkeypatch):
    fake = {
        "securities": {"US1": 0.6, "US2": 0.4}, "issuers": {"A": 0.6, "B": 0.4},
        "sectors": {"IT": 1.0}, "countries": {"US": 1.0},
        "labels": {"US1": "A"}, "coverage": {"total": 1.0}, "n": 2, "as_of": "x",
    }
    monkeypatch.setattr(providers.holdings, "load", lambda url: fake)
    lt = providers.resolve("ANY", "name", "https://example.com/h.csv")
    assert lt.source == "name-level"
    assert "Holdings (security)" in lt.vectors
    assert lt.n_names == 2


# ---- Review #18 (fixed): name tier with no URL explains the blank provenance --- #
def test_name_tier_without_url_explains_itself():
    lt = providers.resolve(ISIN_FULL, "name", None)
    assert lt.note == "no source URL configured"
