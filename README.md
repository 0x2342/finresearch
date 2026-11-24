# Financial Research — Prototype

Standalone pure-Python web app (Streamlit). No node, no reverse proxy.
Implements blueprint v1: ISIN portfolio → price series + correlation, and
**look-through overlap** (the differentiator).

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

- **Research** — effective weights come from the `Weight` column (a hypothetical
  allocation; no units needed).
- **Tracked** — effective weights come from `Units × last price` (a real book).

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
- **Prices / Correlation / Value** — need network. Series come from yfinance with
  a Stooq fallback, cached to `data/prices/*.parquet`. Seed `Ticker`s are best
  guesses (two are confirmed: `ESWP.AS`, `FUJI.PA`); fix any that fail in the
  sidebar and the app re-fetches.

## Price proxies & data coverage

The `Ticker` for each holding is an **index proxy** for the correlation series,
not necessarily the held listing — correlation depends on the index, not the
wrapper, so any liquid long-history tracker of the same index works. Prefer
Xetra (`.DE`) listings (better yfinance coverage than `.PA`/`.AS`) and avoid new
/ short share classes: the correlation window is the *intersection* of all
series, so one short series truncates everything.

The **Data coverage** panel in the Prices tab shows, per holding, whether it
priced, its start date, point count and years; the Correlation tab shows the
overlapping window and lists any excluded (unpriced) instruments. Use these to
vet a proxy, then set the ticker in the sidebar editor (it persists).

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

To enable name-level for a fund, paste its iShares Detailed Holdings CSV link in
the overlap tab's "Holdings source URLs" expander (persists to `data/sources.csv`).
Get the link from the fund's iShares product page → Portfolio Characteristics →
Holdings → Detailed Holdings download. For a **swap** holding, point it at a
*physical* reference fund on the same index (a swap fund's own file is a
substitute basket). `source_of` resolves the URL from this editor first, then any
`holdings_url` default in `registry.py`.

## Architecture (maps to the blueprint)

| Module | Role |
|---|---|
| `core/registry.py` | Resolver seed: ISIN → index + reference ticker/holdings |
| `core/exposures.py` | Seeded factsheet look-through (sector/country), provenance-tagged |
| `core/prices.py` | Price cache layer (yfinance → Stooq → parquet) |
| `core/holdings.py` | Parse iShares Detailed Holdings CSV → names + aggregate sector/country |
| `core/providers.py` | Look-through providers + tier resolution (name-level ↔ factsheet) |
| `core/store.py` | Portfolios, per-fund source URLs, persistence |
| `core/overlap.py` | Overlap engine (weight overlap, pairwise, portfolio aggregate) |
| `app.py` | Streamlit UI |

## Next (deferred per blueprint)

- Automatic `ISIN → index-variant → reference-fund` resolution (today the
  reference fund's holdings URL is supplied per fund, not derived).
- Cross-portfolio comparison (tracked book vs research candidate).
- Constituent-level price correlation; optimisation; auto-refresh.
