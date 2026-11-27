"""Portfolio persistence + the two-ticker (Ticker / RiskProxy) model."""
from __future__ import annotations

import pandas as pd

from core import store


def test_risk_ticker_prefers_proxy():
    assert store.risk_ticker({"Ticker": "CBK.DE", "RiskProxy": "^GDAXI"}) == "^GDAXI"
    assert store.risk_ticker({"Ticker": "CBK.DE", "RiskProxy": ""}) == "CBK.DE"
    assert store.risk_ticker({"Ticker": "CBK.DE", "RiskProxy": "  "}) == "CBK.DE"
    assert store.risk_ticker({"Ticker": "  CBK.DE ", "RiskProxy": None}) == "CBK.DE"


def test_slugify():
    assert store.slugify("My Core Book!") == "my-core-book"
    assert store.slugify("   ") == "portfolio"


def test_read_csv_migrates_missing_riskproxy_column(store_tmp, tmp_path):
    legacy = tmp_path / "old.csv"
    # a pre-two-ticker CSV with no RiskProxy column
    legacy.write_text("ISIN,Name,Ticker,Weight,Units\nX,Alpha,X.DE,0.5,0\n")
    df = store_tmp._read_csv(str(legacy))
    assert list(df.columns) == store_tmp.COLUMNS
    assert df.loc[0, "RiskProxy"] == ""  # added, blank
    assert df.loc[0, "Ticker"] == "X.DE"


def test_read_csv_coerces_types(store_tmp, tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("ISIN,Name,Ticker,RiskProxy,Weight,Units\nX,Alpha,X.DE,,notnum,3\n")
    df = store_tmp._read_csv(str(p))
    assert df.loc[0, "Weight"] == 0.0  # bad number -> 0.0
    assert df.loc[0, "Units"] == 3.0


def test_create_load_and_active(store_tmp):
    rows = pd.DataFrame(
        [{"ISIN": "X", "Name": "Alpha", "Ticker": "X.DE", "RiskProxy": "", "Weight": 1.0, "Units": 0}]
    )
    slug = store_tmp.create_portfolio("Core", "research", rows)
    idx = store_tmp.load_index()
    assert idx["active"] == slug
    assert store_tmp.mode_of(idx, slug) == "research"
    loaded = store_tmp.load_portfolio(slug)
    assert loaded.loc[0, "Ticker"] == "X.DE"


def test_unique_slugs_for_same_name(store_tmp):
    a = store_tmp.create_portfolio("Book", "research")
    b = store_tmp.create_portfolio("Book", "research")
    assert a != b


def test_delete_reassigns_active(store_tmp):
    a = store_tmp.create_portfolio("A", "research")
    b = store_tmp.create_portfolio("B", "research")
    store_tmp.set_active(a)
    store_tmp.delete_portfolio(a)
    idx = store_tmp.load_index()
    assert idx["active"] == b
    assert store_tmp.load_portfolio(a) is None


def test_set_mode_and_notional_roundtrip(store_tmp):
    slug = store_tmp.create_portfolio("Sat", "research")
    store_tmp.set_mode(slug, "tracked")
    store_tmp.set_notional(slug, 2.5)
    idx = store_tmp.load_index()
    assert store_tmp.mode_of(idx, slug) == "tracked"
    assert store_tmp.notional_of(idx, slug) == 2.5
    # invalid mode is ignored
    store_tmp.set_mode(slug, "bogus")
    assert store_tmp.mode_of(store_tmp.load_index(), slug) == "tracked"


def test_sources_roundtrip(store_tmp):
    assert store_tmp.save_sources({"IE00X": "https://example.com/h.csv", "": "skip", "Z": ""}) is True
    out = store_tmp.load_sources()
    assert out == {"IE00X": "https://example.com/h.csv"}


def test_save_portfolio_reports_success(store_tmp):
    ok = store_tmp.save_portfolio("p", pd.DataFrame(columns=store_tmp.COLUMNS))
    assert ok is True


def test_save_portfolio_reports_failure(store_tmp, tmp_path, monkeypatch):
    # make the target directory uncreatable: its parent is a regular file (#11 —
    # a write failure must be reported, not silently swallowed)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(store_tmp, "_DIR", str(blocker / "sub"))
    assert store_tmp.save_portfolio("p", pd.DataFrame(columns=store_tmp.COLUMNS)) is False


def test_save_sources_reports_failure(store_tmp, tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(store_tmp, "_SOURCES", str(blocker / "sub" / "sources.csv"))
    assert store_tmp.save_sources({"IE00X": "https://example.com/h.csv"}) is False
