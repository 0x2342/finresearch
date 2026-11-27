"""Financial Research -- prototype (blueprint v1).

Standalone pure-Python web app. Run with:  streamlit run app.py
Modules: resolver (core.registry) | store (core.store) | cache (core.prices) |
overlap engine (core.overlap) | look-through (core.exposures / core.holdings).

Multiple portfolios, each with a weight mode:
  research -> weights from the Weight column (hypothetical allocation)
  tracked  -> weights from Units x price (a real book)
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from core import exposures, overlap, prices, providers, registry, risk, store

st.set_page_config(page_title="Financial Research", layout="wide")

MODE_LABEL = {
    "research": "Research (weights from Weight column)",
    "tracked": "Tracked (weights from Units × price)",
}
EMPTY = pd.DataFrame(columns=["ISIN", "Name", "Ticker", "RiskProxy", "Weight", "Units"])
MIN_HISTORY_YEARS = 3  # covariance needs ~3y; shorter series get flagged
FREQ_PERIODS = {"daily": 252, "weekly": 52}      # periods/year for annualisation
FREQ_WINDOWS = {"daily": (252, 756), "weekly": (52, 156)}  # rolling-vol 12m/36m
TIER_LABEL = {
    "auto": "Auto — name-level, else factsheet",
    "name": "Name-level only",
    "factsheet": "Factsheet only",
}
DIMS = ["Sector", "Country", "Holdings (security)", "Holdings (issuer)"]


def _f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return default if pd.isna(v) else v
    except (TypeError, ValueError):
        return default


def _registry_seed() -> pd.DataFrame:
    rows = [
        {
            "ISIN": i.isin,
            "Name": i.name,
            # price_ticker is the registry's RISK PROXY, not necessarily the held
            # listing — seed it into RiskProxy and leave Ticker for the user's actual
            # holding, so a seeded tracked book never values units on a proxy.
            "Ticker": i.holding_ticker or "",
            "RiskProxy": i.price_ticker,
            "Weight": registry.DEFAULT_WEIGHTS.get(i.isin, 0.0),
            "Units": 0.0,
        }
        for i in registry.REGISTRY.values()
    ]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Portfolios index (bootstrap on first run)
# --------------------------------------------------------------------------- #
idx = store.load_index()
if idx is None:
    store.create_portfolio("Core", "research", _registry_seed())
    idx = store.load_index()

slugs = [p["slug"] for p in idx["portfolios"]]
name_by_slug = {p["slug"]: p["name"] for p in idx["portfolios"]}
active = idx.get("active") if idx.get("active") in slugs else slugs[0]
mode = store.mode_of(idx, active)

st.title("Financial Research")
st.caption(
    "Look-through overlap + price correlation. Track a real book (weights from "
    "units × price) or research a hypothetical one (weights from the Weight column)."
)

# --------------------------------------------------------------------------- #
# Sidebar: portfolio selector, mode, management, editor
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.subheader("Portfolio")
    sel = st.selectbox(
        "Active", slugs, index=slugs.index(active),
        format_func=lambda s: name_by_slug.get(s, s), key="active_sel",
    )
    if sel != active:
        store.set_active(sel)
        st.rerun()

    new_mode = st.radio(
        "Weight source", list(MODE_LABEL), index=list(MODE_LABEL).index(mode),
        format_func=lambda m: MODE_LABEL[m], key=f"mode::{active}",
    )
    if new_mode != mode:
        store.set_mode(active, new_mode)
        st.rerun()

    with st.expander("Manage portfolios"):
        nm = st.text_input("Name", key="new_name")
        c1, c2 = st.columns(2)
        if c1.button("New (empty)") and nm.strip():
            store.create_portfolio(nm, "research")
            st.rerun()
        if c2.button("Duplicate") and nm.strip():
            store.create_portfolio(nm, mode, store.load_portfolio(active))
            st.rerun()
        if st.button("Rename active") and nm.strip():
            store.rename(active, nm)
            st.rerun()
        if len(slugs) > 1 and st.button("Delete active"):
            store.delete_portfolio(active)
            for k in [k for k in st.session_state if "::" in k]:
                st.session_state.pop(k, None)
            st.rerun()

    period = st.selectbox("Price history", ["1y", "2y", "5y", "10y"], index=2)
    freq_label = st.selectbox(
        "Return frequency", ["Daily", "Weekly (Fri–Fri)"], index=0, key="freq_sel",
        help="Weekly returns damp the Epps effect from non-synchronous US / Asia / "
             "EU closes and holiday gaps — prefer them for globally diversified "
             "books. Affects the Correlation and Risk tabs only.",
    )
    freq = "weekly" if freq_label.startswith("Weekly") else "daily"

    # Editor seeded once per slug; its own widget key carries edits across reruns.
    seed_key = f"seed::{active}"
    if seed_key not in st.session_state:
        df0 = store.load_portfolio(active)
        st.session_state[seed_key] = EMPTY.copy() if (df0 is None or df0.empty) else df0
    tracked_mode = mode == "tracked"
    weight_cfg = (
        st.column_config.NumberColumn(
            "Weight", format="%.4f", disabled=True,
            help="Auto-computed from Units × price as a fraction of the book (sums to "
                 "1). Immutable in tracked mode — duplicate this book into a research "
                 "portfolio to explore the same weights with longer-history proxies.",
        )
        if tracked_mode
        else st.column_config.NumberColumn(
            "Weight", format="%.4f", min_value=0.0,
            help="Relative weight (any scale; normalised to sum to 1). Enter fractions, "
                 "e.g. 0.6 / 0.4.",
        )
    )
    edited = st.data_editor(
        st.session_state[seed_key],
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn(
                "Ticker", help="The actual held listing — used for valuation, weights "
                               "and allocation (e.g. your real ETF on Xetra)."),
            "RiskProxy": st.column_config.TextColumn(
                "RiskProxy", help="Optional long-history index proxy for covariance / "
                                  "correlation (e.g. a swap's index tracker). Blank = use "
                                  "Ticker. Leave blank when the held listing has enough history."),
            "Weight": weight_cfg,
            "Units": st.column_config.NumberColumn(format="%.4f", min_value=0.0),
        },
        column_order=["ISIN", "Name", "Ticker", "RiskProxy", "Weight", "Units"],
        key=f"editor::{active}",
    )
    st.caption(
        ("Units auto-save · Weight is computed from Units × price · "
         if tracked_mode else "Edits auto-save · ")
        + "Ticker = held listing · RiskProxy = optional risk series · "
        + MODE_LABEL[mode]
    )

# --------------------------------------------------------------------------- #
# Clean + persist the active portfolio
# --------------------------------------------------------------------------- #
pf = edited.copy()
pf = pf[pf["ISIN"].notna()]
pf["ISIN"] = pf["ISIN"].astype(str).str.strip()
pf = pf[pf["ISIN"] != ""]
pf["Name"] = pf.apply(
    lambda r: r["Name"] if isinstance(r["Name"], str) and r["Name"].strip() else r["ISIN"],
    axis=1,
)
pf["Ticker"] = pf["Ticker"].fillna("").astype(str).str.strip()
pf["RiskProxy"] = pf["RiskProxy"].fillna("").astype(str).str.strip()

_snap = pf[["ISIN", "Name", "Ticker", "RiskProxy", "Weight", "Units"]].to_csv(index=False)
if st.session_state.get(f"snap::{active}") != _snap:
    store.save_portfolio(active, pf)
    st.session_state[f"snap::{active}"] = _snap

ticker_of = {r["ISIN"]: r["Ticker"] for _, r in pf.iterrows()}          # held listing → valuation
risk_of = {r["ISIN"]: store.risk_ticker(r) for _, r in pf.iterrows()}   # proxy (or Ticker) → risk
name_of = {r["ISIN"]: r["Name"] for _, r in pf.iterrows()}


@st.cache_data(show_spinner=False)
def cached_panel(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    return prices.get_panel(list(tickers), period)


@st.cache_data(show_spinner=False)
def cached_lookthrough(isin: str, tier: str, url: str | None):
    return providers.resolve(isin, tier, url)


# Two panels: `panel` is the risk/correlation series (RiskProxy, fallback Ticker);
# `last` holds valuation prices from the actual held Ticker.
risk_tickers = tuple(dict.fromkeys(t for t in risk_of.values() if t))
panel = cached_panel(risk_tickers, period) if risk_tickers else pd.DataFrame()
hold_tickers = tuple(dict.fromkeys(t for t in ticker_of.values() if t))
hold_panel = cached_panel(hold_tickers, period) if hold_tickers else pd.DataFrame()
last = hold_panel.ffill().iloc[-1] if not hold_panel.empty else pd.Series(dtype=float)

weights = overlap.effective_weights(pf.to_dict("records"), mode, last.to_dict())

# Tracked books: Weight is DERIVED (Units × price, normalised %), not entered. Persist
# the computed value so the column is populated and a Duplicate → research copy inherits
# real weights — the whole point: explore those weights with longer-history proxies.
# The editor's Weight column is disabled, so refreshing it in the seed is edit-safe.
if mode == "tracked" and not pf.empty:
    wfrac = {i: round(weights.get(i, 0.0), 4) for i in pf["ISIN"]}  # fraction of book (sums to 1)
    pf["Weight"] = pf["ISIN"].map(wfrac).fillna(0.0)
    _snap_w = pf[["ISIN", "Name", "Ticker", "RiskProxy", "Weight", "Units"]].to_csv(index=False)
    if st.session_state.get(f"snap::{active}") != _snap_w:
        store.save_portfolio(active, pf)
        st.session_state[f"snap::{active}"] = _snap_w
    seed = st.session_state.get(seed_key)
    if seed is not None and "ISIN" in getattr(seed, "columns", []):
        new_w = seed["ISIN"].map(wfrac).fillna(0.0)
        if "Weight" not in seed or not new_w.equals(seed["Weight"]):
            st.session_state[seed_key] = seed.assign(Weight=new_w)

tab_px, tab_corr, tab_overlap, tab_value, tab_alloc, tab_risk = st.tabs(
    ["Prices", "Correlation", "Look-through overlap", "Portfolio value", "Allocation", "Risk"]
)

# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
with tab_px:
    priced = list(panel.columns) if not panel.empty else []
    srcs = panel.attrs.get("sources", {}) if not panel.empty else {}
    cached = panel.attrs.get("cached", set()) if not panel.empty else set()
    curr = panel.attrs.get("currencies", {}) if not panel.empty else {}
    conv = panel.attrs.get("converted", {}) if not panel.empty else {}
    assumed = panel.attrs.get("ccy_assumed", set()) if not panel.empty else set()

    def _ccy_label(tk: str) -> str:
        c = curr.get(tk, "?")
        if c in ("EUR", ""):
            return "EUR"
        if c == "?":
            return "?"
        base = f"{c}?" if tk in assumed else c  # '?' = assumed from a bare symbol
        return f"{base}→EUR" if conv.get(tk) else f"{base} (unconv)"

    cov = []
    for i in pf["ISIN"]:
        t = risk_of.get(i, "")                 # risk / correlation series (RiskProxy ∨ Ticker)
        hld = ticker_of.get(i, "")             # held listing (valuation)
        held_cell = hld if (hld and hld != t) else ""
        if t in priced:
            s = panel[t].dropna()
            yrs = round((s.index[-1] - s.index[0]).days / 365.25, 1)
            cov.append({
                "Name": name_of[i], "Risk series": t, "Held": held_cell, "Priced": "✓",
                "Ccy": _ccy_label(t),
                "Source": srcs.get(t, "?") + (" ·cached" if t in cached else ""),
                "From": str(s.index[0].date()), "Points": int(len(s)),
                "Years": yrs, "Flag": "⚠ short" if yrs < MIN_HISTORY_YEARS else "",
            })
        else:
            cov.append({"Name": name_of[i], "Risk series": t, "Held": held_cell, "Priced": "✗",
                        "Ccy": "—", "Source": "—", "From": "—", "Points": 0,
                        "Years": 0.0, "Flag": ""})
    st.markdown(
        "**Data coverage** — the series feeding correlation/risk (RiskProxy, else "
        "Ticker). **Held** shows the valuation listing when it differs."
    )
    st.dataframe(pd.DataFrame(cov), width="stretch", hide_index=True)
    st.caption(
        f"⚠ marks under {MIN_HISTORY_YEARS:g}y history — too short for stable covariance; "
        "use a longer proxy on the same index where one exists (bond sleeves often can't)."
    )
    if any(v == "stooq" for v in srcs.values()):
        stq = sorted(t for t, v in srcs.items() if v == "stooq")
        st.warning(
            "Source = **stooq** for: " + ", ".join(stq) + ". Stooq's raw close is not "
            "reliably dividend-adjusted, so returns/volatility can be overstated for "
            "distributing funds — yfinance series are total-return. Prefer an "
            "accumulating share class, or a ticker yfinance covers."
        )
    unconv = sorted(
        t for t in priced
        if curr.get(t) == "?" or (curr.get(t) not in ("EUR", "", "?") and not conv.get(t))
    )
    if unconv:
        st.warning(
            "Not converted to EUR: " + ", ".join(unconv) + ". Quote currency is "
            "unknown, or its EUR cross was unavailable — returns for these may mix "
            "currencies. Everything else is in EUR (non-EUR quotes × FX)."
        )
    guessed = sorted(t for t in priced if t in assumed)
    if guessed:
        st.caption(
            "⚠ Currency **assumed USD** (no registry pin, metadata or known suffix) "
            "for: " + ", ".join(guessed) + ". Converted as USD→EUR — verify, or pin "
            "it in `registry.PRICE_TICKER_CCY`."
        )
    unpriced = sorted({c["Risk series"] for c in cov if c["Priced"] == "✗" and c["Risk series"]})
    if unpriced:
        st.warning(
            "No data for: " + ", ".join(unpriced)
            + " — fix the ticker or use a longer-history proxy on the same index."
        )

    st.divider()
    pick = st.multiselect(
        "Chart", list(pf["ISIN"]), default=list(pf["ISIN"]),
        format_func=lambda i: f"{name_of.get(i, i)} ({risk_of.get(i, '')})",
        key=f"pxpick::{active}",
    )
    cols = [risk_of[i] for i in pick if risk_of.get(i) in priced]
    sub = panel[cols] if cols else pd.DataFrame()
    if sub.empty:
        st.info("No price data to chart.")
    else:
        st.line_chart(sub / sub.ffill().iloc[0] * 100.0, height=420)
        st.caption("Rebased to 100 at series start (adjusted close).")

# --------------------------------------------------------------------------- #
# Correlation (mode-independent: pairwise on returns)
# --------------------------------------------------------------------------- #
with tab_corr:
    st.caption(
        f"Pearson correlation of {freq} returns, inner-joined on common dates."
        + (" Weekly (Fri–Fri) sampling reduces the non-synchronous-close bias."
           if freq == "weekly" else "")
    )
    if panel.shape[1] < 2:
        st.info("Need at least two priced instruments. Fix tickers in the sidebar.")
    else:
        priced = list(panel.columns)
        missing = [(name_of[i], risk_of[i]) for i in pf["ISIN"]
                   if risk_of.get(i) and risk_of[i] not in priced]
        if missing:
            st.warning("Excluded (no price data): "
                       + ", ".join(f"{n} ({t})" for n, t in missing))
        rets = prices.to_frequency(panel, freq).pct_change().dropna(how="any")
        if len(rets):
            st.caption(
                f"{len(rets)} overlapping observations · {rets.index[0].date()} → "
                f"{rets.index[-1].date()} — window is set by the shortest-history series."
            )
        if len(rets) < 20:
            st.warning(f"Only {len(rets)} overlapping observations — correlation unreliable.")
        lab = {risk_of[i]: name_of.get(i, i) for i in pf["ISIN"] if risk_of.get(i)}
        corr = rets.corr().rename(index=lab, columns=lab)
        fig = px.imshow(
            corr, text_auto=".2f", color_continuous_scale="RdBu_r",
            zmin=-1, zmax=1, aspect="auto",
        )
        fig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- #
# Look-through overlap (weighted by the active mode's effective weights)
# --------------------------------------------------------------------------- #
with tab_overlap:
    # --- global look-through source tier ---
    tier = st.radio(
        "Source tier", ["auto", "name", "factsheet"],
        index=["auto", "name", "factsheet"].index(st.session_state.get("lt_tier", "auto")),
        format_func=lambda t: TIER_LABEL[t], horizontal=True, key="lt_tier",
    )
    if st.button("↻ Reload sources", key="reload_lt",
                 help="Re-read source URLs from disk and re-fetch all name-level "
                      "holdings. Use after a transient fetch failure."):
        cached_lookthrough.clear()
        st.session_state.pop("sources_seed", None)
        st.rerun()

    # --- per-fund holdings-source URLs (global; persisted to data/sources.csv) ---
    with st.expander("Holdings source URLs (iShares 'Detailed Holdings' CSV)"):
        st.caption("Paste a fund's CSV link to enable name-level look-through for it. Blank = factsheet only.")
        if "sources_seed" not in st.session_state:
            saved = store.load_sources()
            rws, seen = [], set()
            for i in pf["ISIN"]:
                seen.add(i)
                dflt = registry.source_for(i, name=name_of.get(i)) or ""
                rws.append({"ISIN": i, "Name": name_of.get(i, i), "Source URL": saved.get(i, dflt)})
            for i, u in saved.items():
                if i not in seen:
                    rws.append({"ISIN": i, "Name": i, "Source URL": u})
            st.session_state["sources_seed"] = pd.DataFrame(rws, columns=["ISIN", "Name", "Source URL"])
        sedit = st.data_editor(
            st.session_state["sources_seed"], num_rows="dynamic",
            width="stretch", hide_index=True, key="sources_editor",
        )

    sources_map = {}
    for _, r in sedit.iterrows():
        i, u = str(r.get("ISIN", "")).strip(), str(r.get("Source URL", "")).strip()
        if i and u and u.lower() != "nan":
            sources_map[i] = u
    if st.session_state.get("sources_snap") != str(sources_map):
        store.save_sources(sources_map)
        st.session_state["sources_snap"] = str(sources_map)

    def source_of(i):
        return registry.source_for(i, sources_map.get(i), name_of.get(i))

    dim = st.radio("Dimension", DIMS, horizontal=True, key=f"dim::{active}")

    if mode == "tracked" and not weights:
        st.info("Tracked mode: enter Units and make sure tickers price, to weight the look-through.")

    lts = {i: cached_lookthrough(i, tier, source_of(i)) for i in weights}
    held = {i: lts[i].vector(dim) for i in weights if lts[i].vector(dim)}
    uncovered = [name_of.get(i, i) for i in weights if not lts[i].vector(dim)]
    # ISIN keys -> display names for the security dimension (identity elsewhere)
    all_labels = {}
    for i in weights:
        all_labels.update(getattr(lts[i], "labels", {}) or {})

    def _ref_label(i):
        r = registry.resolve_reference(i, name_of.get(i))
        if not r:
            return "—"
        if r.ref_index:  # reference fund tracks a different (broader) index — a proxy
            return f"{r.index} · {r.how} — ref: {r.ref_index} (approx.)"
        return f"{r.index} · {r.how}"

    def _cov(i, key):
        c = getattr(lts[i], "coverage", None)
        if not c or not c.get("total"):
            return "—"
        return f"{c.get(key, 0.0) / c['total']:.0%}"

    prov = pd.DataFrame([
        {"Fund": name_of.get(i, i), "Reference": _ref_label(i), "Source": lts[i].source,
         "As of": lts[i].as_of or "—",
         "Names": lts[i].n_names if lts[i].n_names else "—",
         "Sec%": _cov(i, "security"), "Sector%": _cov(i, "sector"),
         "Country%": _cov(i, "country"),
         "Note": lts[i].note or ""}
        for i in weights
    ])
    if not prov.empty:
        st.caption("Look-through provenance (which tier served each weighted holding)")
        st.dataframe(prov, width="stretch", hide_index=True)

    if not held:
        st.info(f"No {dim} look-through for the weighted holdings under this tier.")
    else:
        st.markdown("**Pairwise overlap** — shared exposure (Σ min of weights).")
        lab = {i: name_of.get(i, i) for i in held}
        mat = overlap.pairwise(held).rename(index=lab, columns=lab)
        fig = px.imshow(mat, text_auto=".0%", color_continuous_scale="Blues",
                        zmin=0, zmax=1, aspect="auto")
        fig.update_layout(height=430, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Each vector is normalized to 100% of its invested exposure "
            "(cash/derivatives — and any uncovered factsheet tail — excluded from the "
            "base), so self-overlap reads 100%. Sector/Country overlap measures shared "
            "allocation *shape*, not shared securities — use **Holdings (security)** "
            "(ISIN-keyed) for true redundancy (equity vs bond ≈ 0 there), or "
            "**Holdings (issuer)** for common-issuer exposure."
        )

        st.markdown("**Portfolio look-through** — aggregate exposure by effective weight.")
        agg = overlap.portfolio_lookthrough(weights, held).rename(index=all_labels).head(20)
        covered = sum(weights[i] for i in held)
        bar = px.bar(agg.rename("weight").reset_index(), x="weight", y="index", orientation="h")
        bar.update_layout(
            height=max(260, 26 * len(agg)), yaxis=dict(autorange="reversed"),
            xaxis_tickformat=".0%", margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="", xaxis_title=f"% of portfolio (covered {covered:.0%}; top {len(agg)})",
        )
        st.plotly_chart(bar, width="stretch")
        if uncovered:
            st.caption(f"No {dim} data for: " + ", ".join(uncovered))

        st.markdown("**Compare two funds**")
        opts = list(held)
        c1, c2 = st.columns(2)
        a = c1.selectbox("Fund A", opts, format_func=lambda i: name_of.get(i, i), key=f"ova::{active}")
        b = c2.selectbox("Fund B", opts, index=min(1, len(opts) - 1),
                         format_func=lambda i: name_of.get(i, i), key=f"ovb::{active}")
        st.metric(f"Overlap ({dim})", f"{overlap.weight_overlap(held[a], held[b]):.0%}")
        comp = pd.DataFrame({name_of.get(a, a): held[a], name_of.get(b, b): held[b]}).fillna(0.0)
        comp = (comp * 100).round(1).sort_values(comp.columns[0], ascending=False).head(25)
        comp = comp.rename(index=all_labels)  # ISIN -> name for the security dimension
        st.dataframe(comp, width="stretch")

# --------------------------------------------------------------------------- #
# Portfolio value (Units × price, manual refresh)
# --------------------------------------------------------------------------- #
with tab_value:
    if st.button("Refresh prices"):
        cached_panel.clear()
        st.rerun()
    rows, total = [], 0.0
    for _, r in pf.iterrows():
        t = str(r["Ticker"]).strip()
        units = _f(r.get("Units"))
        price = float(last.get(t)) if t in getattr(last, "index", []) else None
        value = units * price if (price is not None and units) else None
        if value:
            total += value
        rows.append(
            {
                "Name": r["Name"], "Ticker": t, "Units": units,
                "Last": round(price, 2) if price is not None else None,
                "Value (EUR)": round(value, 2) if value is not None else None,
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.metric("Portfolio value (priced units)", f"€ {total:,.2f}")
    st.caption("Enter Units per holding to value from live prices. Manual refresh only.")

# --------------------------------------------------------------------------- #
# Allocation — contribution of each portfolio to the combined book
# --------------------------------------------------------------------------- #
with tab_alloc:
    st.caption(
        "Combine portfolios (e.g. core + satellite) and measure each one's share "
        "of total volume, so a satellite sleeve stays sensibly sized."
    )
    sel = st.multiselect(
        "Portfolios", slugs, default=slugs[:2],
        format_func=lambda s: name_by_slug.get(s, s), key="alloc_pick",
    )
    if len(sel) < 2:
        st.info("Select at least two portfolios to compare.")
    else:
        sel_modes = {store.mode_of(idx, s) for s in sel}
        if len(sel_modes) > 1:
            st.error(
                "All selected portfolios must use the same weight source "
                f"(all Tracked or all Research) — mixed: {', '.join(sorted(sel_modes))}. "
                "Volume isn't comparable across modes."
            )
        else:
            m = sel_modes.pop()
            c1, c2 = st.columns(2)
            core_sel = c1.selectbox(
                "Core portfolio", sel, format_func=lambda s: name_by_slug.get(s, s),
                key="alloc_core",
            )
            thr = c2.number_input(
                "Sensible max satellite (%)", min_value=1, max_value=100, value=25,
                key="alloc_thr",
            ) / 100.0

            rows_by = {}
            for s in sel:
                dfp = store.load_portfolio(s)
                rows_by[s] = dfp.to_dict("records") if dfp is not None else []

            lastd = {}
            if m == "tracked":
                tks = tuple({
                    str(r.get("Ticker", "")).strip()
                    for rs in rows_by.values() for r in rs
                    if str(r.get("Ticker", "")).strip()
                })
                pan = cached_panel(tks, period) if tks else pd.DataFrame()
                lastd = (pan.ffill().iloc[-1].to_dict() if not pan.empty else {})

            if m == "research":
                # Research weights only set allocation *within* a book and sum to 1,
                # so they can't size books against each other. Use an explicit
                # per-portfolio notional (relative capital) instead.
                st.caption(
                    "Research books size by an explicit **notional** (relative capital) — "
                    "their weights only allocate within a book. Set each size:"
                )
                vols = {}
                ncols = st.columns(len(sel))
                for col, s in zip(ncols, sel):
                    v = col.number_input(
                        name_by_slug.get(s, s), min_value=0.0, step=0.5,
                        value=store.notional_of(idx, s, 1.0), key=f"notional::{s}",
                    )
                    vols[s] = v
                    if v != store.notional_of(idx, s, 1.0):
                        store.set_notional(s, v)
            else:
                vols = {s: overlap.portfolio_volume(rows_by[s], m, lastd) for s in sel}
            flagged = {
                s: names for s in sel
                if (names := overlap.unpriced_positions(rows_by[s], m, lastd))
            }
            if flagged:
                lines = "; ".join(
                    f"**{name_by_slug.get(s, s)}**: {', '.join(names)}"
                    for s, names in flagged.items()
                )
                st.warning(
                    "Unpriced holdings are excluded from market value (tracked mode), "
                    "so these portfolios' share of the combined book is understated — "
                    f"{lines}. Fix the tickers in the sidebar to size the satellite correctly."
                )
            total = sum(vols.values())
            if total <= 0:
                st.warning(
                    "Total volume is zero — "
                    + ("enter Units and make sure tickers price (tracked mode)."
                       if m == "tracked" else "set a non-zero notional for at least one book.")
                )
            else:
                unit = "€" if m == "tracked" else "notional"
                sat = sum(v for s, v in vols.items() if s != core_sel) / total
                m1, m2 = st.columns(2)
                m1.metric(
                    "Satellite contribution", f"{sat:.1%}",
                    delta=f"{(sat - thr):+.1%} vs {thr:.0%} limit", delta_color="inverse",
                )
                m2.metric(
                    f"Combined volume ({unit})",
                    f"{total:,.0f}" if m == "tracked" else f"{total:,.2f}",
                )
                if sat > thr:
                    st.warning(
                        f"Satellite is {sat:.1%} of the combined book — above your "
                        f"{thr:.0%} limit. Trim the satellite or grow the core."
                    )
                else:
                    st.success(f"Satellite is {sat:.1%} — within your {thr:.0%} limit.")

                df = pd.DataFrame([
                    {"Portfolio": name_by_slug.get(s, s), "Volume": round(vols[s], 2),
                     "Contribution": vols[s] / total,
                     "Role": "core" if s == core_sel else "satellite"}
                    for s in sel
                ]).sort_values("Contribution", ascending=False)

                fig = px.bar(
                    df, x="Contribution", y="Portfolio", orientation="h", color="Role",
                    color_discrete_map={"core": "#1f4e79", "satellite": "#7fb3d5"},
                )
                fig.update_layout(
                    height=max(220, 46 * len(df)), xaxis_tickformat=".0%",
                    yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=10, b=0),
                    yaxis_title="", xaxis_title="share of combined volume",
                )
                st.plotly_chart(fig, width="stretch")

                show = df.copy()
                show["Contribution"] = (show["Contribution"] * 100).round(1)
                st.dataframe(show, width="stretch", hide_index=True)

# --------------------------------------------------------------------------- #
# Risk — annualized volatility & risk contribution (sleeve + holding)
# --------------------------------------------------------------------------- #
with tab_risk:
    st.caption(
        f"Annualized volatility ({freq} returns × √{FREQ_PERIODS[freq]}) and risk "
        "contribution by sleeve and holding. One portfolio for a single-book view, "
        "or several (same weight source) to split risk core vs satellite."
    )
    rsel = st.multiselect(
        "Portfolios", slugs, default=[active],
        format_func=lambda s: name_by_slug.get(s, s), key="risk_pick",
    )
    if not rsel:
        st.info("Select at least one portfolio.")
    elif len({store.mode_of(idx, s) for s in rsel}) > 1:
        st.error("All selected portfolios must use the same weight source.")
    else:
        rm = store.mode_of(idx, rsel[0])
        rrows = {}
        for s in rsel:
            dfp = store.load_portfolio(s)
            rrows[s] = dfp.to_dict("records") if dfp is not None else []
        # Covariance series come from the risk proxy (fallback Ticker); valuation and
        # weights come from the held Ticker — the two-ticker split.
        rtks = tuple({
            store.risk_ticker(r)
            for rs in rrows.values() for r in rs if store.risk_ticker(r)
        })
        rpanel = cached_panel(rtks, period) if rtks else pd.DataFrame()
        rpanel = prices.to_frequency(rpanel, freq)  # returns use chosen freq
        rhold = tuple({
            str(r.get("Ticker", "")).strip()
            for rs in rrows.values() for r in rs if str(r.get("Ticker", "")).strip()
        })
        rhold_panel = cached_panel(rhold, period) if rhold else pd.DataFrame()
        rlast = rhold_panel.ffill().iloc[-1].to_dict() if not rhold_panel.empty else {}
        # Portfolio size for combining books: market value (tracked) or the explicit
        # per-book notional (research) — the SAME basis the Allocation tab uses, so
        # core/satellite risk attribution respects intended research sizes.
        if rm == "research":
            vol = {s: store.notional_of(idx, s, 1.0) for s in rsel}
        else:
            vol = {s: overlap.portfolio_volume(rrows[s], rm, rlast) for s in rsel}
        tvol = sum(vol.values())

        if tvol <= 0 or rpanel.empty:
            st.info("Need priced holdings (and Units in tracked mode) to measure risk.")
        else:
            # tick_w aggregates weight by RISK proxy (the covariance key). tick_hold
            # keeps each proxy's underlying holdings + weights so proxy-level risk can
            # be split back to real holdings (several holdings may share one proxy).
            tick_w, tick_sleeve, tick_name, tick_hold = {}, {}, {}, {}
            for s in rsel:
                vshare = vol[s] / tvol
                eff = overlap.effective_weights(rrows[s], rm, rlast)
                tk = {r["ISIN"]: store.risk_ticker(r) for r in rrows[s]}  # covariance key
                nn = {r["ISIN"]: (r.get("Name") or r["ISIN"]) for r in rrows[s]}
                nm = name_by_slug.get(s, s)
                for isin, w in eff.items():
                    t, cw = tk.get(isin, ""), vshare * w
                    if not t or cw <= 0:
                        continue
                    tick_w[t] = tick_w.get(t, 0.0) + cw
                    tick_sleeve.setdefault(t, {})
                    tick_sleeve[t][nm] = tick_sleeve[t].get(nm, 0.0) + cw
                    tick_name.setdefault(t, nn.get(isin, t))
                    hname = nn.get(isin, isin)
                    tick_hold.setdefault(t, {})
                    tick_hold[t][hname] = tick_hold[t].get(hname, 0.0) + cw

            # Honest coverage: positioned holdings vs those we could actually price.
            # (effective_weights drops unpriced holdings in tracked mode, so dec's
            # weight `covered` reads ~100% — count the full book here instead.)
            priced_cols = set(rpanel.columns)
            positioned, excluded, seen = [], [], set()
            for s in rsel:
                for r in rrows[s]:
                    isin = r["ISIN"]
                    if isin in seen:
                        continue
                    has_pos = (_f(r.get("Units")) > 0) if rm == "tracked" else (_f(r.get("Weight")) > 0)
                    if not has_pos:
                        continue
                    seen.add(isin)
                    positioned.append(isin)
                    t = store.risk_ticker(r)  # priced if its risk series is in the panel
                    if not t or t not in priced_cols:
                        excluded.append(r.get("Name") or isin)
            n_tot = len(positioned)
            n_priced = n_tot - len(excluded)

            dec = risk.decompose(rpanel, tick_w, periods_per_year=FREQ_PERIODS[freq])
            if dec is None:
                st.warning("Not enough overlapping price history to compute risk.")
            else:
                tracked = rm == "tracked"
                eur_vol = dec["ann_vol"] * dec["covered"] * tvol   # € volatility of priced capital

                c1, c2, c3 = st.columns(3)
                c1.metric("Annualized volatility", f"{dec['ann_vol']:.1%}")
                if tracked:
                    c2.metric("± Annual € volatility", f"€ {eur_vol:,.0f}")
                else:
                    c2.metric(
                        "Value covered", f"{dec['covered']:.0%}",
                        help="Share of portfolio weight that is priced and enters the "
                             "risk estimate. Undefined in tracked mode — an unpriced "
                             "holding has no market value, so there is no denominator.",
                    )
                c3.metric(
                    "Diversification",
                    f"{dec['ann_vol']/dec['wavg_vol']:.2f}×" if dec["wavg_vol"] else "—",
                    help="portfolio volatility ÷ weighted-average standalone volatility (<1 = benefit)",
                )
                st.caption(
                    f"{dec['obs']} {freq} obs · {dec['start'].date()} → {dec['end'].date()} "
                    f"· priced {n_priced}/{n_tot} holdings. Window is set by the "
                    "shortest-history ticker; correlations rise toward 1 in a crash, so "
                    "realised drawdown risk can exceed this."
                )
                if excluded:
                    st.warning(
                        f"{len(excluded)} positioned holding(s) excluded — no price: "
                        + ", ".join(sorted(set(excluded)))
                        + f". Volatility and € figures cover the {n_priced} priced holding(s) only."
                    )
                # Why is the window short? Identify any late-listing holding that
                # caps the common window, and separate that from frequency × a short
                # price-history period (few observations by construction).
                tol = 7 if freq == "daily" else 31
                binding, latest_d, earliest_d = risk.binding_holdings(
                    rpanel, dec["tickers"], tol_days=tol
                )
                gap = 30 if freq == "daily" else 60
                truncated = (
                    latest_d is not None and earliest_d is not None
                    and (latest_d - earliest_d).days > gap
                    and len(binding) < len(dec["tickers"])
                )
                bnames = ", ".join(tick_name.get(t, t) for t in binding)

                if dec["obs"] < 60:
                    se = 1.0 / (2 * dec["obs"]) ** 0.5  # ≈ relative SE of a vol estimate
                    msg = (
                        f"Only {dec['obs']} {freq} observations "
                        f"(≈ ±{se:.0%} standard error on the volatility estimate). "
                    )
                    if truncated:
                        msg += (
                            f"The window is capped by **{bnames}** (history starts "
                            f"{latest_d.date()}), while the other holdings reach back to "
                            f"{earliest_d.date()}. Swap in a longer-history proxy of the "
                            "same index, or drop it from the risk view."
                        )
                    else:
                        msg += (
                            f"That is expected for {freq} sampling over this history "
                            f"({dec['start'].date()} → {dec['end'].date()}) — widen "
                            "**Price history** in the sidebar, or switch to daily "
                            "returns, for a tighter estimate."
                        )
                    st.warning(msg)
                elif truncated:
                    st.caption(
                        f"⚠ Window capped by **{bnames}** (from {latest_d.date()}); the "
                        f"other holdings reach back to {earliest_d.date()}. The estimate "
                        "uses only the overlapping period — swap a longer-history proxy "
                        "to extend it."
                    )

                if len(rsel) >= 2:
                    srisk = {}
                    for t in dec["tickers"]:
                        for sl, wv in tick_sleeve.get(t, {}).items():
                            srisk[sl] = srisk.get(sl, 0.0) + dec["rc_frac"][t] * (wv / tick_w[t])
                    srows = []
                    for s in rsel:
                        nm = name_by_slug.get(s, s)
                        rk = srisk.get(nm, 0.0)
                        row = {"Sleeve": nm, "Capital %": round(vol[s] / tvol * 100, 1),
                               "Risk %": round(rk * 100, 1)}
                        if tracked:
                            row["Risk € (ann)"] = round(rk * eur_vol, 0)
                        srows.append(row)
                    st.markdown("**Risk contribution by sleeve** — is the satellite taking more risk than capital?")
                    st.dataframe(pd.DataFrame(srows).sort_values("Risk %", ascending=False),
                                 width="stretch", hide_index=True)

                st.markdown("**Risk contribution by holding** (share of total portfolio risk).")
                # Split each risk proxy's weight / risk contribution back to its
                # underlying holdings in proportion to their weight on that proxy, so
                # two holdings sharing a proxy each get an honest row (not one swallowed).
                hrows = []
                for t in dec["tickers"]:
                    members = tick_hold.get(t, {tick_name.get(t, t): tick_w.get(t, 0.0)})
                    tw = tick_w.get(t, 0.0)
                    for hname, cw in members.items():
                        frac = (cw / tw) if tw else 0.0
                        hrows.append({
                            "Holding": hname, "Risk proxy": t,
                            "Weight %": round(dec["w"][t] * frac * 100, 1),
                            "Risk %": round(dec["rc_frac"][t] * frac * 100, 1),
                            "Standalone volatility": f"{dec['standalone'][t]:.0%}",
                        })
                hdf = pd.DataFrame(hrows).sort_values("Risk %", ascending=False)
                fig = px.bar(hdf.head(20), x="Risk %", y="Holding", orientation="h")
                fig.update_layout(height=max(240, 26 * min(len(hdf), 20)),
                                  yaxis=dict(autorange="reversed"),
                                  margin=dict(l=0, r=0, t=10, b=0),
                                  yaxis_title="", xaxis_title="% of total risk")
                st.plotly_chart(fig, width="stretch")
                st.dataframe(hdf, width="stretch", hide_index=True)

                st.markdown(
                    "**Rolling annualized volatility** — how the single number above "
                    "moves across regimes (constant current weights)."
                )
                rvol = risk.rolling_vol(
                    rpanel, tick_w,
                    windows=FREQ_WINDOWS[freq], periods_per_year=FREQ_PERIODS[freq],
                )
                if rvol is None or rvol.empty:
                    st.caption(
                        "Need ≥ 1 year of overlapping history for a rolling 12-month "
                        "volatility — the window here is too short."
                    )
                else:
                    rfig = px.line(rvol, labels={"value": "annualized volatility", "variable": "window"})
                    rfig.add_hline(
                        y=dec["ann_vol"], line_dash="dot", line_color="#888",
                        annotation_text="full-window σ", annotation_position="top left",
                    )
                    rfig.update_layout(
                        height=300, yaxis_tickformat=".0%", legend_title="",
                        margin=dict(l=0, r=0, t=10, b=0), xaxis_title="",
                    )
                    st.plotly_chart(rfig, width="stretch")
                    st.caption(
                        "The dotted line is the full-window σ (the headline figure); the "
                        "rolling lines show it is a blend of calmer and more turbulent "
                        "stretches. 36m is smoother, 12m reacts faster — if the recent 12m "
                        "sits well above the full-window line, current conditions are "
                        "riskier than the long-run average implies. **Note:** this applies "
                        "*today's* weights across all history — a 'how would my current "
                        "allocation have behaved' view, not the realised volatility of the "
                        "book as you actually held it (that needs position history)."
                    )
