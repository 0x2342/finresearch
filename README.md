# Financial Research

Standalone pure-Python web app (Streamlit). No node, no reverse proxy.
ISIN portfolio → price series + correlation, EUR-normalised risk decomposition,
and **look-through overlap** (the differentiator).

## Run

```bash
cd finresearch
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Opens on http://localhost:8501.

## Portfolios & persistence

Multiple named portfolios, each with a **weight mode**:

Weights are **fractions** on a 0–1 scale (sum to 1), consistent across both modes —
enter `0.6 / 0.4`, not `60 / 40` (any scale works; it's normalised either way).

- **Research** — effective weights come from the `Weight` column (a hypothetical
  allocation; no units needed).
- **Tracked** — effective weights come from `Units × last price` (a real book).
  The `Weight` column is then **auto-computed** (the fraction of book value, summing
  to 1) and **locked** — you edit Units, the weights follow. This makes a tracked
  book a clean source of real weights: **Duplicate** it and switch the copy to
  **Research** to explore those same weights with longer-history proxies (swap each
  `Ticker` for a longer-running tracker of the same index). Unpriced holdings
  compute to 0.

Correlation is mode-independent (pairwise by nature). The look-through overlap
(pairwise matrix, portfolio aggregate, A/B compare) uses the active portfolio's
effective weights.

Switch/create/duplicate/rename/delete portfolios in the sidebar. Everything
auto-saves to `data/portfolios/<slug>.csv` with a small `index.json`; plain CSV,
so hand-edit if you like. On first run the registry seeds a "Core" research
portfolio; a legacy single `data/portfolio.csv` is migrated into it automatically.

## What works where

- **Look-through overlap tab** — works offline. Sector/country vectors for the
  six core holdings are seeded from factsheet tags (`core/exposures.py`), so
  pairwise overlap, portfolio aggregate exposure, and A/B comparison render with
  no network.
- **Prices / Correlation / Value / Risk / Allocation** — need network. Series come
  from yfinance with a Stooq fallback, cached to `data/prices/*.parquet`. The
  registry ships verified EUR proxies (`SXR8.DE`, `EXSA.DE`, `IQQJ.DE`, `IS3N.DE`,
  `VAGF.DE`, `IEAC.AS`); fix any ticker that fails in the sidebar and the app
  re-fetches.

## Allocation (satellite sizing)

The **Allocation** tab combines two or more portfolios and measures each one's
share of the combined book, so a satellite sleeve stays sensibly sized. Each
portfolio's *volume* is `Σ Units × price` (tracked) or `Σ raw Weight` (research);
contribution = volume ÷ combined total. Pick the core; the rest count as
satellite, compared against a user "sensible max" (default 25%). All selected
portfolios **must share the same weight source** — mixing tracked and research is
blocked, since volume isn't comparable across modes.

## Risk (volatility & contribution)

The **Risk** tab computes annualized volatility from return covariance
(`√(wᵀΣw)`, annualized) and decomposes it. A sidebar **Return frequency** toggle
switches daily ↔ **weekly (Fri–Fri)** sampling: weekly absorbs the non-synchronous
US/Asia/EU close lag (Epps effect) and holiday gaps, with annualization by `√52`
instead of `√252` — prefer it for globally diversified books, keep daily as the
secondary view. It also drives the Correlation tab. Select one portfolio for a
single-book view or several (same weight source) to split risk **core vs
satellite**. It shows:

- **Annualized volatility** (%), and for tracked books the **± annual € volatility**
  (volatility × priced capital).
- **Diversification** = portfolio volatility ÷ weighted-average standalone volatility (<1 = benefit).
- **Risk contribution by sleeve** — capital % vs risk % (a 25%-capital satellite
  can be 40% of the risk).
- **Risk contribution by holding** — each holding's share of total risk, which
  sums to 100%, plus its standalone volatility.

Weights are `volatility-share × within-portfolio weight` (sleeve-tagged); the % split is
identical for tracked and research, tracked adds the € figures. `core/risk.py`
renormalizes over the priced subset and reports coverage two ways — **holding
count** (priced K/N, both modes) and, in research mode, **value covered** (% of
weight priced) — plus a list of any excluded (unpriced) holdings, so a missing
position is never hidden behind a 100% figure. (Tracked mode can't define value
coverage: an unpriced holding has no market value; its € volatility is scaled to
priced capital.) The window is set by the shortest-history ticker, and
correlations rise toward 1 in a crash — so realised drawdown risk can exceed this.

Returns are **simple** (`P_t/P_{t-1} − 1`), by design: a portfolio's simple return
is exactly the weighted sum of its holdings', which is what makes `wᵀΣw` and the
Euler decomposition exact — log returns are additive across time but not across
assets. At daily/weekly frequency the difference is negligible anyway. See
[docs/risk-methodology.md §1.1](docs/risk-methodology.md).

Because one full-window number averages across regimes, the tab also plots
**rolling 12-month and 36-month annualized volatility** (book return at constant
current weights) over a dotted full-window-σ reference — so a calm recent stretch
is distinguishable from a 2022-style shock. The rolling basis reconciles exactly
with the headline σ. Note it applies *today's* weights across all history — a
what-if on the current allocation, not the realised volatility of the book as held.

**Full derivations** (returns → covariance → portfolio volatility → Euler risk
contribution → sleeve/€ attribution), with the math mapped line-for-line to the
code, are in **[docs/risk-methodology.md](docs/risk-methodology.md)**.

## Price proxies & data coverage

The `Ticker` for each holding is an **index proxy** for the correlation series,
not necessarily the held listing — correlation depends on the index, not the
wrapper, so any liquid long-history tracker of the same index works. Prefer
Xetra (`.DE`) listings (better yfinance coverage than `.PA`/`.AS`) and avoid new
/ short share classes: the correlation window is the *intersection* of all
series, so one short series truncates everything.

The **Data coverage** panel in the Prices tab shows, per holding, whether it
priced, its **currency** (see below), its **source** (yfinance = total-return /
dividend-adjusted; stooq = raw close, flagged), start date, point count and
years; the Correlation tab shows the overlapping window and lists any excluded
(unpriced) instruments. Use these to vet a proxy, then set the ticker in the
sidebar editor (it persists).

**Common base currency (EUR).** A series *quoted* in USD/GBP/… is converted to
EUR (price × FX cross) **before** any returns are taken, so an unhedged fund's FX
move is captured in EUR and local-currency returns are never pooled into one
covariance. EUR-quoted series pass through untouched — a EUR-listed S&P 500 ETF
already embeds the USD move, so converting it would double-count. Quote currency
is resolved from an explicit, auditable per-instrument registry pin
(`registry.PRICE_TICKER_CCY` — the *listing* currency, distinct from the fund's
base/NAV `Instrument.currency`), then provider metadata, then a conservative
suffix map (`.DE`→EUR, `.SW`→CHF, …); a bare symbol is only *assumed* USD and
flagged. An unresolved currency or a missing cross leaves the series native and
**flagged** (`Ccy` column: `USD→EUR` converted, `USD?→EUR` assumed-then-converted,
`USD (unconv)` / `?` not converted). Pence-quoted LSE lines (`GBp`) are scaled ÷100
before the GBP cross.

Registry ships long-history EUR proxies: S&P 500 `SXR8.DE`, STOXX 600 `EXSA.DE`,
MSCI Japan `IQQJ.DE`, MSCI EM `IS3N.DE`.

### Bond sleeve proxies

Decision: keep the bond proxies **exact** (same index, hedge preserved) and
accept short history — the coverage panel flags anything under 3y with ⚠.
Never substitute an unhedged tracker for a hedged one: the FX leg would dominate
and wreck the correlation.

- **Global Aggregate, EUR-hedged** (`IE00BG47KH54`, currently `VAGF.DE` ~2022):
  the product class is young, so no long exact series exists. Longest *exact*
  option is iShares Core Global Aggregate Bond UCITS ETF EUR Hedged (Acc,
  `IE00BDBRDM35`, ~2017) — try its listing (e.g. `AGGH`) in the coverage panel.
  Rejected (recorded for the record): a duration-matched EUR-aggregate proxy
  (e.g. iShares € Aggregate Bond, ~2009) — longer, but it's a different index.
- **EUR Corp** (`IE00B3F81R35`, currently `IEAC.AS`): the fund itself is
  long-history (2009); only the Amsterdam listing is thin. Use a better-covered
  listing of the *same* fund — Xetra `EUN5.DE` or LSE `IEAC.L`.

## Look-through sources & tiers

Look-through for each holding comes from one of two tiers, chosen by a **global
Source tier** switch in the overlap tab:

- **Name-level** — a BlackRock/iShares "Detailed Holdings" CSV. Serves *every*
  dimension (Holdings names, and Sector/Country by aggregation) — strictly richer.
- **Factsheet** — the seeded sector/country vectors. The fallback; no names.

Tiers: **Auto** (name-level where a source resolves, else factsheet), **Name-level
only** (forces a common tier so cross-fund comparison stays valid), **Factsheet
only**. Each weighted holding's actual tier + as-of date + name count is shown in
the **provenance** panel.

**Normalization & interpretation.** Each look-through vector (sector/country/names)
is normalized to sum to 1 of its *invested* base — cash/derivatives are excluded
from name-level, and any uncovered tail from partial factsheet vectors — so the
pairwise overlap diagonal reads 100% rather than ~97-99%. Note that Σ-min sector/
country overlap measures shared allocation *shape*, not shared holdings or risk:
over ~11 GICS buckets any two diversified funds score high (e.g. a corporate-bond
fund vs equities lands ~55-67% because both spread across the same sectors —
same sectors, different instruments). For genuine redundancy use the **Holdings
(names)** dimension, where equity-vs-bond overlap is ~0.

Name-level data comes from the iShares `get-product-data` JSON API
(`component=holdings.all`), parsed from its column-oriented parallel arrays
(`issueName`, `holdingPercent`, `sectorName`, `countryOfRisk`, `asOfDate`); a
BlackRock "Detailed Holdings" CSV is also accepted as a fallback. The registry
carries each reference fund's **product id** and builds the URL automatically, so
the six core funds resolve to name-level with no manual input. The per-fund
"Holdings source URLs" editor (persisted to `data/sources.csv`) is an override —
paste a URL there to change the source for one fund.

Notes: for a **swap** holding the product id points at a *physical* reference
fund on the same index (a swap fund's own file is a substitute basket). Use the
`en_GB` / `uk-ishares` site for English labels; German-domiciled funds (STOXX 600
DE) need `de-ishares` with `en_DE`. `registry.source_for(isin, override)`
resolves the source: editor override → registry `holdings_url` → built API URL.

**Bond sector crosswalk:** the API returns Bloomberg bond-sector labels (Banking,
Treasuries, Capital Goods, …) for bond funds, not GICS, so cross-asset sector
overlap would collapse to ~0 without normalisation. `_SECTOR` in `holdings.py`
maps corporate bond sectors to GICS (Banking→Financials, Electric→Utilities, …),
matching the factsheet tagging, and buckets the non-corporate portion under
`Government` / `Securitized` (no equity analog, so they correctly don't overlap
equities). Result: name-level EUR Corp ≈ factsheet on Sector; a govt-heavy fund
like Global Aggregate stays low vs equities because it genuinely is government debt.

## Architecture (maps to the blueprint)

| Module | Role |
|---|---|
| `core/registry.py` | Resolver seed: ISIN → index + reference ticker/holdings; explicit quote-currency pins |
| `core/exposures.py` | Seeded factsheet look-through (sector/country), provenance-tagged |
| `core/prices.py` | Price cache (yfinance → Stooq → parquet) + EUR normalisation + daily/weekly resampling |
| `core/fx.py` | Currency normalisation: quote-currency resolution + price → EUR conversion |
| `core/risk.py` | Volatility, Euler risk decomposition, rolling 12m/36m volatility |
| `core/holdings.py` | Parse iShares Detailed Holdings CSV → names + aggregate sector/country |
| `core/providers.py` | Look-through providers + tier resolution (name-level ↔ factsheet) |
| `core/store.py` | Portfolios, per-fund source URLs, persistence |
| `core/overlap.py` | Overlap engine (weight overlap, pairwise, portfolio aggregate) |
| `app.py` | Streamlit UI |

## Reference-fund resolution

A held ISIN resolves to a physical iShares reference fund (whose holdings drive
name-level look-through) via `registry.resolve_reference`, in priority order:

1. **registry** — the curated `REGISTRY` entries (verified product ids).
2. **index hint** — an explicit canonical index name.
3. **name match** — the fund's own Name matched against `_INDEX_ALIASES`.

The matched index then maps to a reference fund through `INDEX_REF` (index →
verified iShares product id). So adding a new fund named e.g. "Xtrackers MSCI
Japan UCITS ETF" auto-resolves to the iShares MSCI Japan reference and enables
name-level with no registry edit. The provenance panel's **Reference** column
shows each fund's resolved index and how (`registry` / `index-hint` /
`name-match`), or `—` when unresolved (→ factsheet).

There is **no free `ISIN → index` feed** (index membership is licensed), so the
index comes from the registry, a hint, or the name — not the ISIN itself.
`INDEX_REF` currently covers the six core indices; extend it (and `_INDEX_ALIASES`)
to widen coverage. A future upgrade is to back this with the iShares
product-screener catalog, which would resolve any iShares ISIN directly and
auto-populate `INDEX_REF`.

## Next (deferred)

See **[docs/backlog.md](docs/backlog.md)**. The risk-engine correctness and
robustness items from two code reviews are **done**: EUR currency normalisation,
honest holding-count + value coverage, total-return source flagging,
calendar-aware weekly (Fri–Fri) returns, rolling 12m/36m volatility, and explicit
auditable currency resolution. Still open: an actual-weights *realised*-history
series (needs position history) and historical stress tests (2008 / 2020 / 2022);
the iShares product-screener catalog for the resolver; and constituent-level
correlation / optimisation / auto-refresh.
