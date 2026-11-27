"""Seeded factsheet vectors — dispatch + transcription invariants.

A sum/sign invariant on the hand-transcribed vectors is cheap insurance against
a fat-fingered weight (a sign flip, a misplaced decimal) silently skewing every
overlap number downstream."""
from __future__ import annotations

import pytest

from core import exposures


def test_vectors_dispatch():
    assert exposures.vectors("Sector") is exposures.SECTORS
    assert exposures.vectors("Country") is exposures.COUNTRIES


@pytest.mark.parametrize("isin", list(exposures.SECTORS))
def test_sector_vectors_well_formed(isin):
    v = exposures.SECTORS[isin]
    assert all(0.0 < w <= 1.0 for w in v.values())
    # full GICS sector vectors should be ~complete (allow minor rounding)
    assert 0.98 <= sum(v.values()) <= 1.02


@pytest.mark.parametrize("isin", list(exposures.COUNTRIES))
def test_country_vectors_well_formed(isin):
    v = exposures.COUNTRIES[isin]
    assert all(0.0 < w <= 1.0 for w in v.values())
    # country vectors may be top-N truncated, so only bound them above
    assert 0.0 < sum(v.values()) <= 1.02


def test_every_sector_isin_has_an_as_of():
    for isin in exposures.SECTORS:
        assert isin in exposures.AS_OF
