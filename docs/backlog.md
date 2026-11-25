# Backlog

Deferred work, roughly by priority. The data-quality / risk-engine items came out
of an external code review and are correctness issues, not just enhancements.

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
  FX vol is real risk in EUR; hedged-vs-unhedged exposure stays a look-through
  concern.) **Still open (optional):** auto-switch registry proxies to Acc classes
  interacts with this — a EUR-listed Acc proxy needs no conversion *and* no TR flag.

- **Honest coverage in tracked mode.** ✅ **Done — `67f2189`.**
  `overlap.effective_weights` drops no-price holdings *before* normalising, so
  `risk.decompose`'s `covered` read ~100% even when holdings were missing — the
  vol is correct for the priced subset but was mislabelled as the whole book.
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
  so the same ETF can have two different histories → different vol, overstated on
  distributing funds (worst for bond ETFs like IEAC). Shipped: `core.prices` tags
  each series with `.attrs["source"]`, `get_panel` exposes
  `panel.attrs["sources"]`, and the Prices tab shows a Source column + warns on
  any Stooq-sourced series. **Still open (optional):** auto-switch the registry
  proxies to **accumulating share classes** (price = TR regardless of source) so
  the flag rarely fires — currently SXR8/IS3N are Acc, EXSA/IQQJ/IEAC are Dist
  (fine while yfinance is the source; the flag catches the Stooq-fallback case).

### P2 — robustness

- **Trading-calendar alignment & weekly returns.** `pct_change().dropna(how="any")`
  keeps only the intersection of trading days (loses data) and compares
  non-synchronous closes across US/JP/EU/EM (downward-biased correlations, Epps
  effect). Add: explicit non-trading-day handling, a common valuation convention,
  and **weekly (e.g. Fri–Fri) returns as a robustness check** to damp holiday /
  closing-time mismatch.

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
