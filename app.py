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

from core import exposures, overlap, prices, providers, registry, store

st.set_page_config(page_title="Financial Research", layout="wide")

MODE_LABEL = {
    "research": "Research (weights from Weight column)",
    "tracked": "Tracked (weights from Units × price)",
}
EMPTY = pd.DataFrame(columns=["ISIN", "Name", "Ticker", "Weight", "Units"])
MIN_HISTORY_YEARS = 3  # covariance needs ~3y; shorter series get flagged
TIER_LABEL = {
    "auto": "Auto — name-level, else factsheet",
    "name": "Name-level only",
    "factsheet": "Factsheet only",
}
DIMS = ["Sector", "Country", "Holdings (names)"]


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
            "Ticker": i.price_ticker,
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

    # Editor seeded once per slug; its own widget key carries edits across reruns.
    seed_key = f"seed::{active}"
    if seed_key not in st.session_state:
        df0 = store.load_portfolio(active)
        st.session_state[seed_key] = EMPTY.copy() if (df0 is None or df0.empty) else df0
    edited = st.data_editor(
        st.session_state[seed_key],
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "Weight": st.column_config.NumberColumn(format="%.3f", min_value=0.0),
            "Units": st.column_config.NumberColumn(format="%.4f", min_value=0.0),
        },
        key=f"editor::{active}",
    )
    st.caption(f"Edits auto-save · {MODE_LABEL[mode]}")

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

_snap = pf[["ISIN", "Name", "Ticker", "Weight", "Units"]].to_csv(index=False)
if st.session_state.get(f"snap::{active}") != _snap:
    store.save_portfolio(active, pf)
    st.session_state[f"snap::{active}"] = _snap

ticker_of = {r["ISIN"]: r["Ticker"] for _, r in pf.iterrows()}
name_of = {r["ISIN"]: r["Name"] for _, r in pf.iterrows()}


@st.cache_data(show_spinner=False)
def cached_panel(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    return prices.get_panel(list(tickers), period)


@st.cache_data(show_spinner=False)
def cached_lookthrough(isin: str, tier: str, url: str | None):
    return providers.resolve(isin, tier, url)


all_tickers = tuple(t for t in ticker_of.values() if t)
panel = cached_panel(all_tickers, period) if all_tickers else pd.DataFrame()
last = panel.ffill().iloc[-1] if not panel.empty else pd.Series(dtype=float)

weights = overlap.effective_weights(pf.to_dict("records"), mode, last.to_dict())

tab_px, tab_corr, tab_overlap, tab_value = st.tabs(
    ["Prices", "Correlation", "Look-through overlap", "Portfolio value"]
)

# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
with tab_px:
    priced = list(panel.columns) if not panel.empty else []
    cov = []
    for i in pf["ISIN"]:
        t = ticker_of.get(i, "")
        if t in priced:
            s = panel[t].dropna()
            yrs = round((s.index[-1] - s.index[0]).days / 365.25, 1)
            cov.append({
                "Name": name_of[i], "Ticker": t, "Priced": "✓",
                "From": str(s.index[0].date()), "Points": int(len(s)),
                "Years": yrs, "Flag": "⚠ short" if yrs < MIN_HISTORY_YEARS else "",
            })
        else:
            cov.append({"Name": name_of[i], "Ticker": t, "Priced": "✗",
                        "From": "—", "Points": 0, "Years": 0.0, "Flag": ""})
    st.markdown("**Data coverage** — check each proxy actually pulls and has enough history.")
    st.dataframe(pd.DataFrame(cov), width="stretch", hide_index=True)
    st.caption(
        f"⚠ marks under {MIN_HISTORY_YEARS:g}y history — too short for stable covariance; "
        "use a longer proxy on the same index where one exists (bond sleeves often can't)."
    )
    unpriced = sorted({c["Ticker"] for c in cov if c["Priced"] == "✗" and c["Ticker"]})
    if unpriced:
        st.warning(
            "No data for: " + ", ".join(unpriced)
            + " — fix the ticker or use a longer-history proxy on the same index."
        )

    st.divider()
    pick = st.multiselect(
        "Chart", list(pf["ISIN"]), default=list(pf["ISIN"]),
        format_func=lambda i: f"{name_of.get(i, i)} ({ticker_of.get(i, '')})",
        key=f"pxpick::{active}",
    )
    cols = [ticker_of[i] for i in pick if ticker_of.get(i) in priced]
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
    st.caption("Pearson correlation of daily returns, inner-joined on common dates.")
    if panel.shape[1] < 2:
        st.info("Need at least two priced instruments. Fix tickers in the sidebar.")
    else:
        priced = list(panel.columns)
        missing = [(name_of[i], ticker_of[i]) for i in pf["ISIN"]
                   if ticker_of.get(i) and ticker_of[i] not in priced]
        if missing:
            st.warning("Excluded (no price data): "
                       + ", ".join(f"{n} ({t})" for n, t in missing))
        rets = panel.pct_change().dropna(how="any")
        if len(rets):
            st.caption(
                f"{len(rets)} overlapping observations · {rets.index[0].date()} → "
                f"{rets.index[-1].date()} — window is set by the shortest-history series."
            )
        if len(rets) < 20:
            st.warning(f"Only {len(rets)} overlapping observations — correlation unreliable.")
        lab = {ticker_of[i]: name_of.get(i, i) for i in pf["ISIN"] if ticker_of.get(i)}
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
                dflt = registry.source_for(i) or ""
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
        return registry.source_for(i, sources_map.get(i))

    dim = st.radio("Dimension", DIMS, horizontal=True, key=f"dim::{active}")

    if mode == "tracked" and not weights:
        st.info("Tracked mode: enter Units and make sure tickers price, to weight the look-through.")

    lts = {i: cached_lookthrough(i, tier, source_of(i)) for i in weights}
    held = {i: lts[i].vector(dim) for i in weights if lts[i].vector(dim)}
    uncovered = [name_of.get(i, i) for i in weights if not lts[i].vector(dim)]

    prov = pd.DataFrame([
        {"Fund": name_of.get(i, i), "Source": lts[i].source,
         "As of": lts[i].as_of or "—",
         "Names": lts[i].n_names if lts[i].n_names else "—",
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

        st.markdown("**Portfolio look-through** — aggregate exposure by effective weight.")
        agg = overlap.portfolio_lookthrough(weights, held).head(20)
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
