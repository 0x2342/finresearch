"""Overlap engine + per-mode effective weights — the app's reason to exist."""
from __future__ import annotations

import math

from core import overlap


def test_weight_overlap_identical_is_one():
    v = {"IT": 0.5, "Fin": 0.5}
    assert math.isclose(overlap.weight_overlap(v, v), 1.0)


def test_weight_overlap_disjoint_is_zero():
    assert overlap.weight_overlap({"IT": 1.0}, {"Energy": 1.0}) == 0.0


def test_weight_overlap_partial():
    a = {"IT": 0.6, "Fin": 0.4}
    b = {"IT": 0.3, "Energy": 0.7}
    # shared = min over union = min(.6,.3)+min(.4,0)+min(0,.7) = 0.3
    assert math.isclose(overlap.weight_overlap(a, b), 0.3)


def test_cosine_orthogonal_and_identical():
    assert overlap.cosine({"a": 1.0}, {"b": 1.0}) == 0.0
    assert math.isclose(overlap.cosine({"a": 1.0, "b": 1.0}, {"a": 2.0, "b": 2.0}), 1.0)


def test_portfolio_lookthrough_stacks_exposure():
    """Two sleeves both holding IT ⇒ aggregate IT exposure is the weighted sum —
    the stacked-concentration signal the tool exists to surface."""
    weights = {"EM": 0.5, "US": 0.5}
    vectors = {
        "EM": {"Information Technology": 0.4, "Financials": 0.6},
        "US": {"Information Technology": 0.3, "Health Care": 0.7},
    }
    agg = overlap.portfolio_lookthrough(weights, vectors)
    assert math.isclose(agg["Information Technology"], 0.5 * 0.4 + 0.5 * 0.3)
    # sorted descending
    assert list(agg.index)[0] == agg.idxmax()


def test_portfolio_lookthrough_uncovered_fund_not_renormalised():
    weights = {"COV": 0.5, "UNCOV": 0.5}
    vectors = {"COV": {"IT": 1.0}}  # UNCOV has no vector
    agg = overlap.portfolio_lookthrough(weights, vectors)
    # covered sleeve contributes its real 0.5 share, not renormalised to 1.0
    assert math.isclose(agg["IT"], 0.5)


def test_normalise():
    assert overlap.normalise({"a": 1.0, "b": 3.0}) == {"a": 0.25, "b": 0.75}
    assert overlap.normalise({}) == {}


def test_effective_weights_research_uses_manual_weight():
    rows = [
        {"ISIN": "X", "Ticker": "X.DE", "Weight": 0.3, "Units": 0},
        {"ISIN": "Y", "Ticker": "Y.DE", "Weight": 0.1, "Units": 0},
    ]
    ew = overlap.effective_weights(rows, "research", {})
    assert math.isclose(ew["X"], 0.75)
    assert math.isclose(ew["Y"], 0.25)


def test_effective_weights_tracked_uses_units_times_price():
    rows = [
        {"ISIN": "X", "Ticker": "X.DE", "Weight": 0, "Units": 10},
        {"ISIN": "Y", "Ticker": "Y.DE", "Weight": 0, "Units": 5},
    ]
    last = {"X.DE": 20.0, "Y.DE": 20.0}  # MV 200 vs 100
    ew = overlap.effective_weights(rows, "tracked", last)
    assert math.isclose(ew["X"], 2 / 3)
    assert math.isclose(ew["Y"], 1 / 3)


def test_unpriced_positions_flagged_in_tracked_only():
    rows = [
        {"ISIN": "X", "Ticker": "X.DE", "Name": "Priced", "Units": 10},
        {"ISIN": "Y", "Ticker": "Y.DE", "Name": "No price", "Units": 5},
    ]
    last = {"X.DE": 20.0}
    assert overlap.unpriced_positions(rows, "tracked", last) == ["No price"]
    assert overlap.unpriced_positions(rows, "research", last) == []


def test_portfolio_volume_tracked_is_market_value():
    rows = [{"ISIN": "X", "Ticker": "X.DE", "Units": 10, "Weight": 0}]
    assert math.isclose(overlap.portfolio_volume(rows, "tracked", {"X.DE": 20.0}), 200.0)


# ---- Review #7 (fixed): duplicate-ISIN lots aggregate instead of overwriting --- #
def test_duplicate_isin_lots_aggregate_tracked():
    # same security bought in two lots, plus a second holding
    rows = [
        {"ISIN": "X", "Ticker": "X.DE", "Units": 5, "Weight": 0},
        {"ISIN": "X", "Ticker": "X.DE", "Units": 5, "Weight": 0},
        {"ISIN": "Y", "Ticker": "Y.DE", "Units": 10, "Weight": 0},
    ]
    last = {"X.DE": 10.0, "Y.DE": 10.0}  # X lots: 50+50=100 MV; Y: 100 MV
    ew = overlap.effective_weights(rows, "tracked", last)
    # desired: X aggregates both lots → 0.5, not 0.333 from a single surviving lot
    assert math.isclose(ew["X"], 0.5)
