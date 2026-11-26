# Risk Methodology

How the **Risk** tab turns a set of price series and portfolio weights into
volatility and a per-sleeve / per-holding risk breakdown. The math below maps
line-for-line to [`core/risk.py`](../core/risk.py),
[`core/overlap.py`](../core/overlap.py), and the Risk tab in
[`app.py`](../app.py). Familiarity with vectors and matrices is assumed;
covariance, volatility, and the risk decomposition are built up from scratch.

---

## 1. Foundations

### 1.1 Returns, not prices

Given adjusted close prices $P_0, P_1, \dots, P_T$ for one instrument, the
**simple return** on day $t$ is

$$ r_t = \frac{P_t}{P_{t-1}} - 1 . $$

We model returns rather than price levels because prices trend and live on
incomparable scales, whereas returns are (approximately) stationary and
scale-free, so they can be pooled statistically and compared across instruments.

> **Code.** `rets = panel[tickers].pct_change().dropna(how="any")` — pandas
> `pct_change` is exactly $P_t/P_{t-1}-1$. The `dropna(how="any")` inner-joins
> the series, so the usable window is the **intersection** of all histories.

### 1.2 Volatility = standard deviation of returns

With sample mean $\hat\mu = \frac1T\sum_{t=1}^T r_t$, the **variance** measures
dispersion of returns around that mean, and **volatility** $\sigma$ is defined as
its square root:

$$ \mathrm{Var}(r) = \frac{1}{T-1}\sum_{t=1}^{T}\left(r_t-\hat\mu\right)^2,
\qquad
\sigma = \sqrt{\mathrm{Var}(r)}
= \sqrt{\frac{1}{T-1}\sum_{t=1}^{T}\left(r_t-\hat\mu\right)^2}. $$

(So $\sigma^2 = \mathrm{Var}(r)$; the $\sigma^2$ notation used elsewhere is
just shorthand for the variance.)

$\sigma$ is in the same units as the return (here, per day). The $T-1$ (Bessel)
denominator makes it an unbiased sample estimator; pandas `.cov()` uses it.
Volatility is a **symmetric** dispersion measure — it penalises upside and
downside equally, and is not itself a tail/drawdown measure.

### 1.3 Covariance and correlation

For two instruments $i, j$ the **covariance** of their returns is

$$ \Sigma_{ij} = \frac{1}{T-1}\sum_{t=1}^{T}
\left(r^{(i)}_t-\hat\mu_i\right)\left(r^{(j)}_t-\hat\mu_j\right), $$

which is positive when the two tend to move together and negative when they move
oppositely. Note the diagonal is just the variance, $\Sigma_{ii} = \sigma_i^2$.
The **correlation** rescales covariance to $[-1,1]$:

$$ \rho_{ij} = \frac{\Sigma_{ij}}{\sigma_i\sigma_j}. $$

Collecting every pair gives the **covariance matrix** $\Sigma \in
\mathbb{R}^{n\times n}$, which is symmetric ($\Sigma=\Sigma^\top$) and positive
semidefinite ($\mathbf{x}^\top\Sigma\mathbf{x}\ge 0$ for all $\mathbf{x}$).

> **Code.** `cov = rets[tickers].cov().values` is the daily $\Sigma$.

---

## 2. Portfolio volatility

Let $\mathbf{w}=(w_1,\dots,w_n)^\top$ be the portfolio weights (fractions of
capital, $\sum_i w_i = 1$). The portfolio return is the weighted sum
$r_p = \mathbf{w}^\top\mathbf{r} = \sum_i w_i r^{(i)}$, so its variance is

$$ \sigma_p^2 = \mathrm{Var}\!\left(\mathbf{w}^\top\mathbf{r}\right)
= \mathbf{w}^\top \Sigma \mathbf{w}
= \sum_{i=1}^{n}\sum_{j=1}^{n} w_i w_j \Sigma_{ij},
\qquad \sigma_p = \sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}. $$

The cross terms ($i\ne j$) are the heart of diversification: whenever
$\rho_{ij}<1$ they add less than if the assets moved in lockstep, so $\sigma_p$
is **below** the weighted average of the individual volatilities.

> **Code.** `sigma = sqrt(w @ cov @ w)` is $\sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}$
> (daily). Weights are renormalised over the priced subset first — see §6.

---

## 3. Annualisation

Under the standard **i.i.d.** assumption (returns independent and identically
distributed across days), variance adds across independent days, so over
$A = 252$ trading days variance scales by $A$ and volatility by $\sqrt{A}$:

$$ \Sigma_{\text{ann}} = A\Sigma_{\text{daily}},
\qquad \sigma_{\text{ann}} = \sqrt{A}\,\sigma_{\text{daily}}. $$

This is why we can keep everything in daily units and only scale at the end.

> **Code.** `ann = sqrt(252)`; `ann_vol = sigma * ann`; each standalone volatility
> is `sqrt(cov[i,i]) * ann`. If returns are **autocorrelated** (serial dependence
> in the returns themselves), $\sqrt{252}$ over- or under-states the true annual
> figure — positive autocorrelation inflates multi-period variance, negative
> deflates it. This is distinct from *volatility clustering* (time-varying
> conditional variance), which a single $\Sigma$ also misses but which does not by
> itself bias the $\sqrt{252}$ scaling; see §8. Daily sampling with $\sqrt{252}$ is
> a convention, not an exact identity.

---

## 4. Risk contribution (Euler decomposition)

We want each holding's *share* of total portfolio risk. The key fact is that
$\sigma_p(\mathbf{w}) = \sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}$ is **positively
homogeneous of degree 1**: scaling all weights by $c$ scales volatility by $c$, i.e.
$\sigma_p(c\mathbf{w}) = c\,\sigma_p(\mathbf{w})$. **Euler's theorem** for such
functions gives an *exact additive* split into per-asset terms:

$$ \sigma_p = \sum_{i=1}^{n} w_i\,\frac{\partial \sigma_p}{\partial w_i}. $$

The **marginal risk contribution** of asset $i$ is that partial derivative.
Differentiating (using $\Sigma=\Sigma^\top$):

$$ \text{MRC}_i = \frac{\partial \sigma_p}{\partial w_i}
= \frac{\partial}{\partial w_i}\sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}
= \frac{1}{2\sigma_p}\cdot 2(\Sigma\mathbf{w})_i
= \frac{(\Sigma\mathbf{w})_i}{\sigma_p}. $$

The **component risk contribution** is weight × marginal, and these sum back to
total volatility:

$$ \text{RC}_i = w_i\text{MRC}_i = \frac{w_i(\Sigma\mathbf{w})_i}{\sigma_p},
\qquad \sum_{i=1}^{n}\text{RC}_i = \sigma_p. $$

So the **percentage risk contribution** $\text{RC}_i/\sigma_p$ sums to 1. Note
that $\text{RC}_i$ depends on $(\Sigma\mathbf{w})_i$ — the covariance of asset
$i$ with the *whole book* — not just its own weight: a small position in an asset
that co-moves strongly with everything else can carry outsized risk, and a
position that hedges the book can even have **negative** risk contribution.

> **Code.** `rc = w * (cov @ w / sigma)` is $\dfrac{w_i(\Sigma\mathbf{w})_i}{\sigma_p}$;
> `rc_frac[t] = rc_i / sigma` is the percentage contribution. In the Risk tab the
> *Risk %* column is `rc_frac` and sums to 100%.

---

## 5. Diversification ratio

To quantify the benefit from §2, compare the portfolio volatility to the
capital-weighted average of the holdings' standalone volatilities $\sigma_i=\sqrt{\Sigma_{ii}}$:

$$ \text{DR} = \frac{\sigma_p}{\sum_{i} w_i\sigma_i}. $$

$\text{DR}\le 1$ always, with equality **iff** every pairwise correlation is 1
(nothing to diversify). The smaller it is, the more the correlations are working
in your favour.

> **Code.** `wavg_vol = Σ w_i · standalone_i`; the tab shows `ann_vol / wavg_vol`.

---

## 6. From portfolios to weights (and sleeves)

### 6.1 Within-portfolio weights

A holding's weight *inside* one portfolio comes from the active weight source
(`overlap.effective_weights`):

$$ w^{(P)}_i =
\begin{cases}
\dfrac{u_i\,p_i}{\sum_k u_k\,p_k} & \text{tracked (units × price)}\\[2ex]
\dfrac{\text{weight}_i}{\sum_k \text{weight}_k} & \text{research (manual weight)}
\end{cases}
\qquad \sum_i w^{(P)}_i = 1 .$$

### 6.2 Combining portfolios

Each portfolio $P$ has a **volume** $V_P$ (`overlap.portfolio_volume`):
$V_P=\sum_i u_i p_i$ for tracked, $V_P=\sum_i \text{weight}_i$ for research. Its
**volume share** of the combined book is $s_P = V_P / \sum_Q V_Q$, and a holding
$i$ belonging to sleeve $P$ receives combined weight

$$ w_i = s_P \cdot w^{(P)}_i, \qquad \sum_i w_i = 1 . $$

All risk maths in §2–§5 then run on this combined $\mathbf{w}$. Both portfolios
must share a weight source, since $V_P$ is not comparable across modes.

### 6.3 Sleeve attribution

Each position keeps its sleeve tag. Let $w_{t}$ be the combined weight on ticker
$t$ and $w_{t,P}$ the part of it from sleeve $P$ (so $\sum_P w_{t,P}=w_t$). A
ticker's risk contribution is split across sleeves in proportion to their weight
in it, and a sleeve's risk is the sum:

$$ \text{RC}_{P} = \sum_{t}\; \frac{\text{RC}_t}{\sigma_p}\cdot\frac{w_{t,P}}{w_t}
\qquad\Big(\text{as a fraction; } \sum_P \text{RC}_P = 1\Big). $$

> **Code.** The Risk tab builds `tick_w` ($w_t$) and `tick_sleeve` ($w_{t,P}$),
> then `srisk[P] = Σ_t rc_frac[t] · (w_{t,P} / tick_w[t])`. This is what makes the
> *Capital % vs Risk %* comparison meaningful — a 25%-capital satellite can be
> 40% of the risk.

---

## 7. Absolute € risk (tracked only)

The percentage decomposition (§2–§6) is identical for tracked and research — it
depends only on $\mathbf{w}$ and $\Sigma$. Tracked books additionally have a real
monetary scale: with **priced capital** $C = \text{covered}\cdot\sum_P V_P$, the
annual € volatility and each sleeve/holding's € risk are

$$ \sigma^{\text{€}}_{\text{ann}} = \sigma_{p,\text{ann}}\cdot C,
\qquad \text{RC}^{\text{€}}_i = \frac{\text{RC}_i}{\sigma_p}\cdot \sigma^{\text{€}}_{\text{ann}} . $$

> **Code.** `eur_vol = ann_vol * covered * tvol`; sleeve € = `rk * eur_vol`.
> Research weights carry no absolute size, so only percentages are defined there.

---

## 8. Coverage, estimation, and caveats

- **Priced subset & renormalisation.** Only tickers with price data enter
  $\Sigma$; the remaining weight is renormalised to 1
  (`covered = raw.sum(); w = raw/covered`). In **tracked** mode a holding with no
  price cannot be valued ($u_i p_i$ needs $p_i$), so it is dropped when weights
  are built — which makes the *weight-based* `covered` read ~100%. The Risk tab
  therefore reports coverage by **holding count** (priced $K$ of $N$) and lists
  any excluded holdings, so a missing position is never hidden behind a 100%
  figure. The reported volatility then honestly describes the priced subset.
  Two coverage numbers matter: **count** (priced $K$ of $N$ holdings, shown in
  both modes) and **value** (share of portfolio weight priced). In **research**
  mode the value figure is exactly `covered` and is shown ("Value covered", e.g.
  85%). In **tracked** mode it is **undefined**: an unpriced holding has units but
  no price, so neither its market value nor its weight is known — there is no
  denominator — and the € volatility is instead scaled to the priced market value.
- **Total-return inputs.** Volatility is measured on *total-return* series
  (price + reinvested distributions). yfinance (`auto_adjust=True`) delivers
  this; the Stooq fallback is raw close (not reliably dividend-adjusted), so a
  Stooq-sourced distributing fund can show inflated volatility — the Prices tab flags
  any Stooq series, and accumulating share classes avoid the issue entirely.
- **Common base currency (EUR).** Returns are taken on EUR series. A non-EUR
  *quote* is converted first ($p^{\text{EUR}}_t = p^{\text{ccy}}_t \cdot
  \mathrm{FX}^{\text{ccy}\to\text{EUR}}_t$), so an unhedged holding's FX return is
  part of its measured volatility and local-currency returns are never pooled in one
  $\Sigma$. EUR-quoted series are unchanged (their EUR price already embeds the
  cross; converting would double-count). The quote currency is resolved
  authoritatively from an explicit, auditable per-instrument pin
  (`registry.PRICE_TICKER_CCY` — the *listing* currency, distinct from the fund's
  base/NAV `Instrument.currency`), then provider metadata, then a conservative
  suffix map; a bare symbol is only *assumed* USD and flagged as such in the UI
  rather than asserted. This normalises the *quote* currency —
  hedged-vs-unhedged *exposure* is a separate look-through concern. A series whose
  currency can't be resolved, or whose cross is unavailable, is left native and
  flagged rather than silently rescaled. *Approximation:* the FX cross is
  forward-filled onto the price dates, so a converted point pairs an ETF close with
  the most recent available FX quote, not necessarily the same instant — tolerable
  at daily frequency, and a further reason the §9 calendar caveat matters.
- **Estimation window.** $\Sigma$ is a *sample* estimate over a finite window —
  noisy, especially short histories. A volatility estimate from $N$ observations
  has relative standard error $\approx 1/\sqrt{2N}$ (≈ ±10% at $N=50$), which the
  tab reports when it warns (under 60 observations). The window is the
  **intersection** of all series (§1.1), so one short-history ticker truncates the
  estimate for everything; the warning separates the two causes — a **late-listing
  holding** that caps the window (named, with its start date, via
  `risk.binding_holdings`) versus **frequency × a short price-history period**
  (weekly over ~1y is ~52 obs by construction; widen the history or use daily). A
  holding that truncates the window well below the others is flagged even when the
  observation count itself is adequate, so a short overlap is never silent.
- **Trading calendars & sampling frequency.** Daily complete-case returns
  (`pct_change().dropna(how="any")`) drop any day a series didn't trade, and —
  because a US close (~21:00 UTC) and a Tokyo close (~06:00 UTC) on the same
  calendar date sit ~15h apart — cross-market co-movement surfaces a day late,
  biasing daily correlations **down** (the Epps effect). The app's **weekly
  (Fri–Fri)** sampling (`prices.to_frequency`: forward-fill to the latest close,
  then take the week-ending value) absorbs that one-day lag and the
  holiday-intersection loss; annualisation then uses $\sqrt{52}$ instead of
  $\sqrt{252}$. Daily is the default and remains available as a secondary view.
- **Stationarity / i.i.d.** A single $\Sigma$ and $\sqrt{252}$ scaling assume
  returns are roughly stationary and serially uncorrelated. Real returns show
  volatility clustering and fat tails.
- **Correlations → 1 in a crash.** Correlations estimated over calm periods
  understate co-movement in drawdowns, so realised tail risk can exceed this
  Gaussian-flavoured volatility. Treat $\sigma_p$ as a *normal-times* figure.
- **Symmetric measure.** Volatility is not Value-at-Risk, Expected Shortfall, or
  max drawdown; those are separate (and would be future additions).

---

## 9. Rolling volatility (regime lens)

The headline $\sigma_p$ is one number over the whole window — it blends every
regime in that window into a single average (§8, *Stationarity*). To see how risk
has actually moved, the Risk tab also plots **rolling annualised volatility** at
12-month (252-day) and 36-month (756-day) windows:

$$\sigma^{(k)}_t \;=\; \sqrt{252}\,\cdot\,\mathrm{std}\!\big(r_{p,\,t-k+1},\dots,r_{p,\,t}\big),
\qquad r_{p,t} = \mathbf{w}^\top \mathbf{r}_t$$

where $r_{p,t}$ is the book's daily return at the **current, fixed** weights.
Holding weights constant isolates the effect of *market* conditions rather than
past rebalancing. By construction the std of $r_p$ over the full window equals the
headline $\sigma_p$, so the flat reference line and the rolling lines are the same
measure at different horizons: 36m is smoother, 12m reacts faster. A recent 12m
reading well above the full-window line says current conditions are riskier than
the long-run average implies. Each window renders only once enough history exists
($\geq$ 1y / $\geq$ 3y).

This is a **counterfactual on today's allocation** — "how would the weights I hold
*now* have behaved through past regimes" — **not** the realised volatility of the
book as it was actually held. If the allocation was 80/20 two years ago and is
60/40 today, this applies 60/40 retrospectively. A true realised-history series
would need position/transaction history over time, which the app does not yet
store (a future addition).

---

## 10. Code map

| Quantity | Formula | Where |
|---|---|---|
| Daily returns | $r_t = P_t/P_{t-1}-1$ | `risk.decompose` → `pct_change` |
| Covariance $\Sigma$ | §1.3 | `risk.decompose` → `rets.cov()` |
| Portfolio volatility $\sigma_p$ | $\sqrt{\mathbf{w}^\top\Sigma\mathbf{w}}$ | `risk.decompose` → `sqrt(w @ cov @ w)` |
| Annualise | $\times\sqrt{252}$ | `risk.decompose` → `ann` |
| Component RC | $w_i(\Sigma\mathbf{w})_i/\sigma_p$ | `risk.decompose` → `rc`, `rc_frac` |
| Standalone volatility | $\sqrt{\Sigma_{ii}}\cdot\sqrt{252}$ | `risk.decompose` → `standalone` |
| Diversification | $\sigma_p/\sum_i w_i\sigma_i$ | `risk.decompose` → `wavg_vol` |
| Within-weights | §6.1 | `overlap.effective_weights` |
| Volume / share | §6.2 | `overlap.portfolio_volume`, Risk tab |
| Sleeve RC | §6.3 | Risk tab → `srisk` |
| € risk | §7 | Risk tab → `eur_vol` |
| Portfolio returns | $r_{p,t}=\mathbf{w}^\top\mathbf{r}_t$ | `risk.portfolio_returns` |
| Rolling volatility (12m/36m) | §9 | `risk.rolling_vol` → Risk tab |
| Weekly (Fri–Fri) sampling | §8 | `prices.to_frequency` → Correlation & Risk tabs |
