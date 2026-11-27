"""Look-through accumulation: ISIN keying, sector crosswalk, cash exclusion."""
from __future__ import annotations

import math

from core import holdings


def test_accumulate_keys_securities_by_isin():
    out = holdings._accumulate(
        names=["Apple", "JPMorgan"],
        weights=[10.0, 6.0],
        sectors=["Information Technology", "Banking"],
        locations=["United States", "United States"],
        assets=["Equity", "Equity"],
        isins=["US0378331005", "US46625H1005"],
    )
    assert math.isclose(out["securities"]["US0378331005"], 0.10)
    assert out["labels"]["US0378331005"] == "Apple"
    assert out["n"] == 2


def test_accumulate_crosswalks_bond_sector_to_gics():
    out = holdings._accumulate(
        names=["JPM Bond"], weights=[5.0], sectors=["Banking"],
        locations=["United States"], assets=["Fixed Income"], isins=["X"],
    )
    # Banking (Bloomberg BCLASS) must map to the GICS "Financials" bucket
    assert "Financials" in out["sectors"]
    assert "Banking" not in out["sectors"]


def test_accumulate_excludes_cash_rows():
    out = holdings._accumulate(
        names=["Apple", "USD Cash"], weights=[10.0, 4.0],
        sectors=["Information Technology", "Cash and/or Derivatives"],
        locations=["United States", "United States"],
        assets=["Equity", "Cash"], isins=["US0378331005", "-"],
    )
    assert "USD Cash" not in out["issuers"]
    # coverage total reflects only the real security
    assert math.isclose(out["coverage"]["total"], 0.10)


def test_accumulate_maps_country_names():
    out = holdings._accumulate(
        names=["Samsung"], weights=[5.0], sectors=["Information Technology"],
        locations=["Korea (South)"], assets=["Equity"], isins=["KR"],
    )
    assert "KR" in out["countries"]


def test_parse_csv_fixture(holdings_csv):
    out = holdings._parse_csv(holdings_csv)
    assert out is not None
    assert out["as_of"] == "Nov 25, 2026"
    assert math.isclose(out["securities"]["US0378331005"], 0.10)
    assert "Financials" in out["sectors"]       # JPMorgan "Banking" crosswalked
    assert "US46625H1005" in out["securities"]  # cash row excluded, bond kept


def test_load_returns_error_for_missing_file():
    out = holdings.load("/nonexistent/path/holdings.csv")
    assert "error" in out


def test_load_parses_local_csv(tmp_path, holdings_csv):
    f = tmp_path / "h.csv"
    f.write_text(holdings_csv)
    out = holdings.load(str(f))
    assert "error" not in out
    assert out["n"] == 2
