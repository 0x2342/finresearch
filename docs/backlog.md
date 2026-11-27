# Backlog

Deferred work, roughly by priority. The data-quality / risk-engine items came out
of an external code review and are correctness issues, not just enhancements.

**Status (2026-11-27).** All seven correctness-focused review rounds are closed
— every P1 item is ✅, including R3.1 (the two-ticker model, merged `a143a05`),
round-6's tracked-coverage / stale-price / ISIN-attribution fixes (`65ac3d1`), and
round-7's absolute price-freshness check (`7d93b10`). A committed `tests/` pytest
suite now pins that behaviour (80 tests). A round-8 review by a second reviewer
(robustness / ops / security focus) is triaged below: its four correctness findings
are now fixed (the specs are live and green), and the robustness/ops items are being
worked or left optional / future.

## Open — optional / future

- **Configurable stale-price policy.** Stale valuation prices are currently
  flagged and carried forward (sensible default for a research tool; a universal
  exclusion cutoff misfires on exchange holidays). Offer a per-use policy: *warn &
  carry forward* (current) / *exclude stale from valuation* / *require manual
  confirmation*. Thresholds ideally per-market/calendar rather than one global
  number.
- **Automated regression test suite.** ✅ **Done.** Committed `tests/` pytest
  suite (80 passing) covering risk decomposition, FX
  resolution/conversion, overlap + per-mode effective weights, store persistence +
  two-ticker model, look-through accumulation, provider tiers, price freshness, and
  the seeded-vector transcription invariants. Pure/offline (no network). Run with
  `pip install -r requirements-dev.txt && pytest`. The round-8 correctness findings
  below were captured as strict xfail specs, then fixed — the specs are now live and
  green.
- Acc-share-class proxy swap (noted under EUR/total-return), the historical
  stress-test stretch goal, the optional simple↔log return toggle, the iShares
  resolver catalog, and the Analytics items (constituent-level correlation,
  optimisation, auto-refresh).

## Round-8 review (2026-11-27) — robustness / ops (second reviewer)

A different reviewer, robustness/security-focused (complements the quant rounds).
Verified in-code; the four correctness items are pinned as `strict` xfail specs in
the test suite. None change the risk maths — they're silent-failure and ops gaps.

### Correctness — ✅ fixed (specs live & green)
- **#7 Duplicate ISINs collapse.** ✅ All row→value dicts were ISIN-keyed, so a
  second row with the same ISIN overwrote the first — valuation/weights/risk
  silently lost it. Fixed: `overlap.effective_weights` now **aggregates** lots (sums
  Units × price / Weight) in both modes, since multiple purchase lots of one security
  is a real tracked-book case. Spec:
  `test_overlap.py::test_duplicate_isin_lots_aggregate_tracked`. *(A sidebar
  duplicate-ISIN warning — for an accidental same-ISIN/different-ticker typo — is a
  separate optional nicety; the weight maths is now correct regardless.)*
- **#8 `fx.to_eur` truncates history.** ✅ When the FX cross started later than the
  price series the pre-FX rows went NaN and were dropped, silently shortening the
  converted series (which then bound the covariance window). Fixed: the truncation is
  flagged in `attrs["fx_truncated"]` (like staleness) rather than back-filling FX.
  Spec: `test_fx.py::test_to_eur_short_fx_does_not_silently_truncate`.
- **#9 `last_prices` assumes a sorted index.** ✅ Fixed with a `sort_index()` guard
  before reading the newest obs / `data_age`. Spec:
  `test_prices.py::test_last_prices_handles_unsorted_index`.
- **#18 Resolver note blank when `name` tier has no URL.** ✅ Fixed:
  `note="no source URL configured"`. Spec:
  `test_providers.py::test_name_tier_without_url_explains_itself`.

### Robustness / ops
- **#11 Silent write failures.** ✅ **Done.** `save_portfolio` / `save_sources` now
  return a success bool; the app surfaces a persistent `st.error` and **does not
  advance the save snapshot** on failure, so a full disk / permission error is
  visible and the write keeps retrying until it succeeds (instead of the user
  believing an edit auto-saved). `prices._save` stays best-effort by design (it's a
  refetchable price cache, not user data — documented in-code). Tests cover both the
  success and failure returns.

### Open — pending triage
- **#10 Cache has no TTL.** Every cold `get_panel` refetches yfinance even on a
  minutes-old cache; the only refresh control is a nuclear `clear()`. Add a `max_age`
  (serve-if-fresh / refetch-if-stale) so the "Refresh prices" button means something.
- **#15 / #16 Server-side fetch of user URLs.** `holdings._read_text` GETs any pasted
  URL with no size cap (SSRF + unbounded-memory surface). Fine for local single-user;
  **note in README before any LAN exposure**, add a response-size cap, and consider
  blocking private-IP targets.
- **#12 `_ccy.json` read-modify-write race.** Concurrent Streamlit reruns can lose a
  cache entry; use an `os.replace` atomic write (applies to `_write_index` too).
- **#17 429 treated as final.** `_read_text` breaks on any `<500`; give 429 one
  retry with a longer backoff.
- **#19 Post-delete session cleanup too broad.** The `"::" in k` filter nukes all
  namespaced widget state, not just the deleted portfolio's. Scope to the active slug.
- **#20 `exposures.vectors()` silent default.** Returns COUNTRIES for any non-"Sector"
  string; a typo'd dimension behaves wrongly. Internal constants only, but cheap to
  harden.
- **#13 Weekly `max_stale` comment.** The 5-row cap is trading rows (applied pre-
  resample); docstring reads "weeks". Semantically fine — clarify the comment.

### Nits
- **#22** `overlap.portfolio_volume` research branch is vestigial (documented) —
  delete it / return `0.0` explicitly so callers can't misuse it.
- **#23** `app.py` is a 900+-line monolith; tab bodies would be happier as a `ui/`
  module. Not urgent for a prototype (overlaps the general refactor).

## Round-3 review (2026-11-26) — data-model correctness

Third external review (published main, code checked against docs). Every point
below was verified in-code. Two are regressions we introduced (⚠).

### P1 — correctness
- **R3.1 Split holding ticker from risk-proxy ticker.** ✅ **Done — merged `a143a05`**
  (branch `feature/two-ticker-model`, kept). One `Ticker` previously served both
  valuation (Units × price) and the risk/correlation proxy, so an index proxy in a
  tracked book silently corrupted market value and the derived weights. Implemented
  as **Option B**: keep `Ticker` as the held listing (valuation/weights/allocation)
  and add an optional `RiskProxy` (covariance/correlation; blank falls back to
  `Ticker`) — less churn than two always-on columns, backward-compatible (existing
  CSVs migrate with a blank `RiskProxy`). `store.risk_ticker()` resolves
  proxy∨ticker; the app fetches two panels (risk series vs held prices); Prices
  "Data coverage" shows the risk series with a "Held" column when it differs.
  Round-4/5 review follow-ups, all merged:
    - registry seeds `price_ticker` into `RiskProxy`, leaves `Ticker` blank (no
      proxy masquerading as a holding); `Instrument.holding_ticker` added for
      known listings.
    - Risk tab sizes research books by explicit notional (was Σ weights ≈ 1), same
      basis as Allocation.
    - proxy-level risk split back to holdings proportionally; the shared-proxy
      limitation (holdings on one proxy ride the same series, ρ=1) is flagged in a
      UI tooltip/caption and methodology §4.
    - RiskProxy persists across portfolio switches (stale-seed overwrite fixed);
      delete gated behind a confirm checkbox that re-arms unticked after each delete.
- **R3.2 EM reference is the IMI index, not plain MSCI EM.** ✅ **Done — `47dc646`.** Registry maps ISIN
  IE000S3N6R34 (benchmark *MSCI Emerging Markets*) → product 264659 = iShares Core
  MSCI EM **IMI** (large+mid+small). IMI ≠ standard EM (large+mid): ~0.99-correlated
  for risk, but security-level look-through pulls in small caps not in the target.
  Fix: relabel the registry to the truth (it is the IMI fund) now; swap to an exact
  standard-EM physical tracker later if one with good history + holdings API exists.
- **R3.3 Global Agg benchmark mismatch.** ✅ **Done — `47dc646`.** Vanguard IE00BG47KH54 tracks Bloomberg
  Global Agg *Float Adjusted & Scaled*; registry points to iShares 291770 (Bloomberg
  Global Agg, not float-adjusted). Close, not identical. Fix: qualify the label as a
  proxy now; exact physical reference later.
- **R3.4 Use ISIN, not issuer name, as the overlap key.** ✅ **Done — `292eb07`.** `holdings._accumulate`
  aggregates by the `issueName` string, so a bond ETF's distinct bonds from one
  issuer (different maturities) collapse → issuer-level, not security-level, overlap
  — wrong exactly when comparing a corp-bond ETF to the global agg. Fix: key by ISIN
  (the iShares JSON exposes it); keep three levels — security (ISIN), issuer
  (name/LEI), sector.

### P2 — data quality
- **R3.5 Stale-price max age for weekly sampling.** ✅ **Done — `292eb07`.** `ffill().resample("W-FRI").last()`
  has no age cap — a missing Friday close is filled by an arbitrarily old price with
  no staleness flag. Add a maximum observation age; reject/flag stale weekly prices.
  (Raised in round 2, deferred; now due.)
- **⚠ R3.6 Persist price-source provenance in the cache.** ✅ **Done — `27bd973`.** Regression in the round-2
  #4 work: the parquet cache stores only `close`, so a reload tags the series
  `source="cache"` and loses whether it came from yfinance (total-return) or Stooq
  (raw) — the Stooq-unadjusted warning silently vanishes after a cache reload.
  Persist source + retrieval timestamp + adjustment + currency + period with the cache.
- **R3.7 Report sector/country data coverage.** ✅ **Done — `292eb07`.** `_accumulate` drops unclassified
  holdings then normalises to 100%, hiding incomplete source data. Report
  per-dimension coverage (name / sector / country) before normalisation.
- **R3.8 Preserve Hong Kong separately from China.** ✅ **Done — `47dc646`.** `holdings._COUNTRY` maps
  "Hong Kong"→"CN"; consolidation should be an analytical view, not forced at
  ingestion. Keep HK; offer optional consolidation.

### P3 — usability & methodology
- **⚠ R3.9 Explicit Research-portfolio notional.** ✅ **Done — `27bd973`.** Allocation's research "volume" =
  Σ raw Weight. Our fraction convention (weights sum to 1) makes every research
  portfolio's volume ≈ 1, so each reads as an equal share of a combined book
  regardless of intended size → satellite sizing misleading. Fix: an explicit
  per-portfolio notional / allocation multiplier (preferred over relying on raw
  weight mass).
- **R3.10 Sync daily/weekly in the methodology.** ✅ **Done — `47dc646`.** §annualisation, the code map
  (√252) and §9 rolling (252/756) still read daily-only though the code is
  frequency-aware (52/156, √52) — generalise the notation. Epps wording fixed
  (weekly *reduces*, not *absorbs*) done in this commit.

## Risk engine & data quality (from code review)

### P1 — correctness

- **Common base currency (EUR total returns).** ✅ **Done — `a28ea33`.**
  `get_panel` now normalises every series to EUR *before* returns are taken:
  `core.fx` resolves each ticker's quote currency (provider metadata → conservative
  suffix map → bare symbol = USD → unknown), fetches each `<base>EUR=X` cross once,
  and converts (price × FX; `GBp` pence scaled ÷100). EUR-quoted series are left
  untouched (their EUR price already embeds the cross). An unresolved currency or a
  missing cross leaves the series native and **flags** it — never a silent rescale.
  Surfaced via the Prices `Ccy` column (`USD→EUR` / `USD (unconv)` / `?`) and a
  warning; README + risk-methodology.md §8 updated. (As noted: unhedged ≠ a bug —
  FX volatility is real risk in EUR; hedged-vs-unhedged exposure stays a look-through
  concern.) **Still open (optional):** auto-switch registry proxies to Acc classes
  interacts with this — a EUR-listed Acc proxy needs no conversion *and* no TR flag.

- **Honest coverage in tracked mode.** ✅ **Done — `67f2189`.**
  `overlap.effective_weights` drops no-price holdings *before* normalising, so
  `risk.decompose`'s `covered` read ~100% even when holdings were missing — the
  volatility is correct for the priced subset but was mislabelled as the whole book.
  Fixed: the Risk tab now counts the full positioned book, reports coverage by
  holding count (priced K/N), and lists any excluded (unpriced) holdings in a
  warning; caption and research-mode metric relabelled; README and
  risk-methodology.md §8 reconciled with the implementation. Follow-up (`6a16372`):
  the Allocation tab's `portfolio_volume` had the same silent-drop — unpriced
  tracked holdings fell out of market value, understating a sleeve's share of the
  combined book. `overlap.unpriced_positions` now surfaces them and the tab warns.

- **Total-return consistency across providers.** ✅ **Done (flagging) — `67f2189`.**
  yfinance (`auto_adjust=True`) returns dividend-adjusted (total-return) prices;
  the Stooq fallback takes raw `Close` (split- but not reliably dividend-adjusted),
  so the same ETF can have two different histories → different volatility, overstated on
  distributing funds (worst for bond ETFs like IEAC). Shipped: `core.prices` tags
  each series with `.attrs["source"]`, `get_panel` exposes
  `panel.attrs["sources"]`, and the Prices tab shows a Source column + warns on
  any Stooq-sourced series. **Still open (optional):** auto-switch the registry
  proxies to **accumulating share classes** (price = TR regardless of source) so
  the flag rarely fires — currently SXR8/IS3N are Acc, EXSA/IQQJ/IEAC are Dist
  (fine while yfinance is the source; the flag catches the Stooq-fallback case).

### P2 — robustness

Second review (re-checked code vs docs) reaffirmed the calendar item as the top
remaining weakness, and added three refinements + a stretch goal. Ordered.

- **[1] Trading-calendar alignment & weekly returns.** ✅ **Done — `af53b4b`.**
  `pct_change().dropna(how="any")` keeps only the intersection of trading days
  (loses data) and compares non-synchronous closes across US/JP/EU/EM. Mechanism
  (corrected): complete-case `dropna` *drops* misaligned days rather than keeping
  mismatched-horizon returns, so the damage is (a) sample loss from every market's
  holidays and (b) the Epps effect — a US close (~21:00 UTC) and a Tokyo close
  (~06:00 UTC) on the same calendar day sit ~15h apart, so cross-market co-movement
  shows up a day late and daily correlations are biased **down**. Shipped: a
  sidebar **Return frequency** toggle (Daily / Weekly Fri–Fri); `prices.to_frequency`
  resamples on a Friday valuation convention; `decompose`/`rolling_vol` take
  `periods_per_year` (252↔52) so annualisation and rolling windows (252/756 ↔
  52/156) track the frequency. Drives both Correlation and Risk; daily stays the
  default/secondary view; risk-methodology.md §8 documents it. Not done (deliberate):
  an explicit stale-price staleness rule beyond ffill — weekly ffill is the
  convention; revisit only if a specific illiquid holding misbehaves.

- **[2] Market-value coverage (not just holding count).** ✅ **Done — `b098a21`.**
  Research mode already computed it — relabelled the metric **"Value covered"**
  (= `dec['covered']`, priced ÷ total weight, e.g. 85%) with help, so count (K/N,
  caption) and value (%) sit together. Tracked mode is **undefined** (an unpriced
  holding has no market value → no denominator); documented, with € vol scaled to
  priced MV as before.

- **[3] Explicit, auditable currency per instrument.** ✅ **Done — `b098a21`.**
  Added `registry.PRICE_TICKER_CCY` + `quote_currency_for()` — the *quote*/listing
  currency, explicitly distinct from the fund base `Instrument.currency` (using the
  base would re-introduce double-counting). `fx.resolve_currency` returns
  `(ccy, source)` with precedence registry > metadata > suffix > **assumed-usd** >
  unknown; the bare-symbol USD case is flagged (`USD?→EUR` in the Ccy column + a
  caption), not asserted.

- **[4] Constant-weight vs actual-weight history.** ✅ **Done — `b098a21`.**
  `rolling_vol` applies today's weights to all history (a documented "how would my
  current allocation have behaved" what-if). Caption + methodology §9 now state
  plainly it is **not** the realised volatility of the book as held. A true
  actual-weights series needs transaction/valuation history we don't yet store
  (future, gated on that data).

- **[stretch] Historical stress tests.** Replay 2008 (systemic credit/liquidity),
  2020 (sudden shock), 2022 (rate/inflation repricing) windows against current
  weights — three genuinely different stress sources. Natural extension once weekly
  sampling lands.

- **[optional] Simple ↔ log return toggle.** Decided (2026-11-26) to keep **simple
  returns by design** — they're additive across assets, which is what makes
  `wᵀΣw` and the Euler decomposition exact (log returns are additive across time,
  not assets; rationale now in risk-methodology.md §1.1). The daily/weekly
  numerical difference is negligible, so this is optionality/rigor, not a fix. Two
  future shapes if revisited: **(A)** a global `return_method` toggle threaded like
  `frequency`, simple staying default, with a documented note that log mode makes
  the portfolio aggregation a (negligible) approximation; **(B)** the pure split —
  log for the Correlation tab and standalone volatilities (where it's cleanly
  valid), simple kept for the portfolio decomposition (fiddlier UX: two
  conventions on one screen).

- **Estimator stability / regime awareness.** ✅ **Done — `87a61f0`.** A single
  full-window covariance blends regimes (COVID, 2022 rate shock, AI
  concentration). Shipped: the Risk tab plots **rolling 12-month (252d) and
  36-month (756d) annualised volatility** of the book at constant current weights,
  over a dotted full-window σ reference. `risk.portfolio_returns` +
  `risk.rolling_vol`; the rolling basis reconciles exactly with the headline σ
  (full-window std = `decompose['ann_vol']`). Each window renders only once its
  history exists; risk-methodology.md §9 documents it. The full-window estimator
  is unchanged — this is an added lens, not a replacement.

## Resolver & look-through

- **iShares product-screener catalog.** Back `resolve_reference` with the iShares
  product catalog so any iShares ISIN resolves directly (ISIN → index → ref fund)
  and `INDEX_REF` auto-populates, instead of the curated name/index map.

## Analytics

- **Constituent-level price correlation** (needs per-stock price series for ETF
  constituents — the large data pull deferred in the blueprint).
- **Optimisation / efficient frontier** (feed weights + Σ to riskfolio-lib /
  PyPortfolioOpt).
- **Auto-refresh** of prices.
