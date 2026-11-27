"""Currency resolution + EUR normalisation."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from core import fx


def test_resolve_precedence_registry_wins():
    ccy, src = fx.resolve_currency(
        "ANY", meta_lookup=lambda t: "USD", registry_lookup=lambda t: "CHF"
    )
    assert (ccy, src) == ("CHF", "registry")


def test_resolve_falls_through_to_metadata():
    ccy, src = fx.resolve_currency("ANY", meta_lookup=lambda t: "USD", registry_lookup=lambda t: None)
    assert (ccy, src) == ("USD", "metadata")


def test_resolve_suffix_map():
    assert fx.resolve_currency("CBK.DE") == ("EUR", "suffix")
    assert fx.resolve_currency("NESN.SW") == ("CHF", "suffix")
    assert fx.resolve_currency("7203.T") == ("JPY", "suffix")


def test_resolve_bare_symbol_is_flagged_assumed_usd():
    assert fx.resolve_currency("AAPL") == ("USD", "assumed-usd")


def test_resolve_unknown_for_fx_or_dotted_unmapped():
    assert fx.resolve_currency("EURUSD=X") == (None, "unknown")
    assert fx.resolve_currency("FOO.XYZ") == (None, "unknown")


def test_resolver_exceptions_are_swallowed():
    def boom(_):
        raise RuntimeError("provider down")

    # a failing lookup must not propagate — it falls through to the suffix map
    assert fx.resolve_currency("CBK.DE", meta_lookup=boom, registry_lookup=boom) == ("EUR", "suffix")


def test_fx_base_gbp_pence():
    assert fx.fx_base("GBp") == ("GBP", 0.01)
    assert fx.fx_base("USD") == ("USD", 1.0)
    assert fx.fx_base(None) == ("EUR", 1.0)


def test_to_eur_passthrough_for_eur():
    s = pd.Series([1.0, 2.0], name="X.DE")
    out, converted = fx.to_eur(s, "EUR", None)
    assert converted is False
    assert out is s


def test_to_eur_noop_without_cross():
    s = pd.Series([1.0, 2.0], name="AAPL")
    out, converted = fx.to_eur(s, "USD", None)
    assert converted is False  # a missing FX cross must never silently rescale


def test_to_eur_converts_with_full_overlap():
    idx = pd.date_range("2026-01-01", periods=4)
    price = pd.Series([100.0, 110.0, 120.0, 130.0], index=idx, name="AAPL")
    fxr = pd.Series([0.90, 0.90, 0.95, 0.95], index=idx)  # EUR per USD
    out, converted = fx.to_eur(price, "USD", fxr)
    assert converted is True
    assert math.isclose(out.iloc[0], 90.0)
    assert math.isclose(out.iloc[-1], 123.5)
    assert out.name == "AAPL"


def test_to_eur_applies_pence_scale():
    idx = pd.date_range("2026-01-01", periods=2)
    price = pd.Series([500.0, 600.0], index=idx, name="VOD.L")  # pence
    fxr = pd.Series([1.15, 1.15], index=idx)  # EUR per GBP
    out, converted = fx.to_eur(price, "GBp", fxr)
    assert converted is True
    # 500 pence -> 5.00 GBP -> 5.75 EUR
    assert math.isclose(out.iloc[0], 5.75)


# ---- Known bug, captured as an executable spec (review #8) ------------------- #
@pytest.mark.xfail(
    reason="review #8: to_eur truncates history to the FX window instead of "
    "flagging it; the shortened series then silently binds the covariance window.",
    strict=True,
)
def test_to_eur_short_fx_does_not_silently_truncate():
    idx = pd.date_range("2026-01-01", periods=10)
    price = pd.Series(range(100, 110), index=idx, dtype=float, name="AAPL")
    # FX cross only covers the last 4 days — the first 6 converted rows are dropped
    fxr = pd.Series([0.9, 0.9, 0.9, 0.9], index=idx[-4:])
    out, converted = fx.to_eur(price, "USD", fxr)
    assert converted is True
    # desired: full window preserved, or an explicit truncation flag raised
    assert len(out) == len(price) or out.attrs.get("fx_truncated")
