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

- **Honest coverage in tracked mode.** `overlap.effective_weights` drops
  no-price holdings *before* normalising, so `risk.decompose`'s `covered` reads
  ~100% even when holdings are missing — the vol is correct for the priced subset
  but mislabelled as the whole book. Research mode is honest (<100%) because
  manual weights pass the filter. Fix: track the full holding set, surface the
  count/identity of unpriced (hence excluded) holdings, and report coverage
  against the full book. Reconcile the README wording with the implementation.

- **Total-return consistency across providers.** yfinance (`auto_adjust=True`)
  returns dividend-adjusted (total-return) prices; the Stooq fallback takes raw
  `Close` (split- but not reliably dividend-adjusted), so the same ETF can have
  two different histories → different vol. Price-only series overstate vol on
  distributing funds (worst for bond ETFs like IEAC). Fix: guarantee total-return
  input everywhere — prefer **accumulating share classes** (distributions
  reinvested, price = TR) and/or a source that returns TR; flag when a series
  isn't adjusted.

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
