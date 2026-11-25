# Backlog

Deferred work, roughly by priority. The data-quality / risk-engine items came out
of an external code review and are correctness issues, not just enhancements.

## Risk engine & data quality (from code review)

### P1 — correctness

- **Common base currency (EUR total returns).** Don't rely on picking EUR-listed
  proxies; **enforce** a base currency. Convert any non-EUR series to EUR (price ×
  FX) before computing returns, so FX exposure of unhedged funds is captured
  consistently and local-currency returns are never pooled. (Note: for the *risk*
  engine, unhedged ≠ a bug — FX vol is real risk measured in EUR; hedged vs
  unhedged matters for look-through/exposure, handled separately.)

- **Honest coverage in tracked mode.** ✅ **Done — `67f2189`.**
  `overlap.effective_weights` drops no-price holdings *before* normalising, so
  `risk.decompose`'s `covered` read ~100% even when holdings were missing — the
  vol is correct for the priced subset but was mislabelled as the whole book.
  Fixed: the Risk tab now counts the full positioned book, reports coverage by
  holding count (priced K/N), and lists any excluded (unpriced) holdings in a
  warning; caption and research-mode metric relabelled; README and
  risk-methodology.md §8 reconciled with the implementation.

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

- **Estimator stability / regime awareness.** A single full-window covariance
  blends regimes (COVID, 2022 rate shock, AI concentration). Keep the historical
  estimator but also show **rolling 12-month and 36-month volatility** so current
  conditions are distinguishable from the long-run average.

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
