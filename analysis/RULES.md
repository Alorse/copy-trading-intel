# Soft rules for BTCUSDT — derived and validated out of sample

> ## ⚠️ READ THIS FIRST
>
> **These are NOT validated rules. They are hypotheses with preliminary evidence.**
>
> The dataset does **not** cover Dec-2024 → Aug-2026 as the SKILL claims. **Zero** positions
> closed before April 2026: all 107,812 close within a **5-month** window (Apr–Aug 2026), 40% of
> them in August alone. The SKILL's long range comes from the *opening* dates of a few long
> swings.
>
> So my "two calendar periods" **are not two independent samples**. They are the two phases of
> one cycle:
>
> | | P1 | P2 |
> |---|---|---|
> | median opening | 5 Jun 2026 | 3 Aug 2026 |
> | real window | ~May–June (crash) | **7 weeks** (Jul–Aug) |
> | BTC move | +2.6% | **+25.8%** |
>
> Validating "long on strong momentum" across a +25.8% stretch is close to tautological. **There
> is no sideways or prolonged bear regime in the data at all.** That R-1 also holds in P1 (which
> contains the crash) is the only thing saving it from being pure beta — and that is a thin base.
>
> **Treat them as forward-test candidates, not as rules ready to risk capital on.**


Everything here was fixed looking at **period 1 only** (up to 2026-07-06) and evaluated on
**period 2**. Metric: net return on notional (`closing_pnl/notional`, fees included), equal weight
per position. Scripts: `entry_rules.py`, `exit_rules.py`, `rule_backtest.py`.

**What these rules are.** A context filter, not a trading system. They say *when conditions
resemble those in which this universe of traders won*, not *what trade to open*. There is no
precise entry signal and no price target.

---

## R-1 · Entry: long only, and only in a strong trend ✅ validated

Open long only when **all three** hold at once, measured on 1h candles:

| condition | threshold (fixed on P1) |
|---|---|
| 24h momentum | > +0.55% |
| 72h momentum | > +0.63% |
| price vs MA200h | > −0.02% (i.e. above the average) |

| | filtered | rest | p |
|---|---|---|---|
| P1 Long | **+0.492%** | −0.099% | 0.0092 |
| P2 Long | **+1.048%** | +0.539% | 0.0004 |

It works in both periods, **including the May-June crash that falls in P1** — which is why it is
not simply "the price went up". The effect also shows up across five independent windows (4h, 24h,
72h, distance to MA200h, position in the 7-day range), all in the same direction.

⚠️ **There is no validated short rule.** The same filter applied to shorts adds nothing (p=0.62
on P1, p=0.51 on P2). The correct mirror would require negative momentum, and that was not
tested. Until it is, the rule is long-only.

⚠️ **The thresholds must be ABSOLUTE, not relative.** I tested the same rule with rolling
percentiles (momentum in the ≥67th percentile of the last 30 days): the effect **disappears on
P1** (p=0.534) and survives only on P2 (p=0.0002). With absolute thresholds it holds in both
(p=0.0092 and p=0.0004). Reading: the edge lies in the **absolute** strength of the trend — being
in the top tercile of a bad month is worthless. The practical consequence is that in a bear regime
the rule almost never fires, and that is precisely what makes it work. The trade-off: the
thresholds carry information about BTC's volatility regime and would need recalibrating if that
regime changed materially.

⚠️ The **middle** trend tercile is consistently the worst (z between −2.8 and −4.2), worse even
than the bottom tercile. The enemy is the **directionless range**, not the fall.

## R-2 · Leverage ≤ 25x ✅ validated (to survive, not to perform)

| leverage | median MAE | % that consumed >80% of margin |
|---|---|---|
| ≤10x | 0.78% | 2.4% |
| 11-25x | 0.79% | **5.7%** |
| 26-60x | 0.71% | 18.6% |
| >60x | 0.63% | **46.7%** |

The median MAE is practically identical across bands (~0.7%): high leverage does **not** come with
better risk management, it only multiplies the probability of ruin. Nearly half the positions
above 60x brushed liquidation.

Consistent with observed behaviour: elite traders use a **25x** median; the rest, **50x**.

This rule **does not improve mean return per trade** — it is pure ruin control. And it is what
makes R-3 viable.

## R-3 · No fixed stop-loss ✅ validated (counterintuitive)

| stop | P2 mean | vs no stop |
|---|---|---|
| **no stop** | **+0.317%** | — |
| 10.0% | +0.297% | −0.019 pp |
| 5.0% | +0.255% | −0.062 pp |
| 3.0% | +0.156% | −0.161 pp |
| 2.4% | +0.111% | −0.206 pp |
| 1.0% | −0.001% | −0.318 pp |

Monotonic: **the tighter the stop, the worse the outcome**, in both periods. A stop at 2.4%
preserves 90% of the winners (p90 of the winners' MAE = 2.38%) but the 10% it kills, plus the
recoveries it turns into realised losses, cost more than it saves.

This contradicts the *"early SL + trailing"* the current SKILL recommends.

**Risk control comes from R-2 (leverage), not from stops.** The two rules are a package: no stop
at 50x and you get liquidated; no stop at ≤25x and you survive the drawdown.

⚠️ Caveat: the simulation assumes any touch of the level closes the position — the pessimistic
case. And the observed positions already include each trader's own risk management.

## R-4 · Minimum duration 1h; the money is in 1-3 days ✅ validated

| bucket | P1 med | P2 med | z (P2) |
|---|---|---|---|
| <1h | −0.000% | +0.041% | **−9.80** |
| 1-4h | +0.150% | +0.221% | +1.24 |
| 4-12h | +0.197% | +0.262% | +0.84 |
| 12-24h | +0.182% | +0.318% | +1.83 |
| **1-3d** | +0.415% | +0.379% | **+4.29** |
| 3-7d | +0.666% | +0.378% | +3.04 |
| >7d | +1.073% | +0.449% | +2.92 |

Sub-hour scalps are the worst bucket and the most populated (~25% of positions). This **confirms**
half the SKILL's claim ("sub-1h scalps lose") and **refutes** the other half ("12-24h always
loses" — it is positive and consistent).

MFE/MAE stays around 1.4 in every bucket except >3d (1.15): the favourable excursion is
consistently ~40% larger than the adverse one.

## R-5 · Exit: the largest available margin for improvement ⚠️ diagnosis, not a rule

Median capture of the favourable excursion (MFE): **24.7%** (p25 = −38%, p75 = 57%).
That is: they leave three quarters of the move on the table, and in the bottom quartile they turn
a favourable move into a loss.

I did not derive a validated exit rule — **do not invent one**. What the data says is that room
exists, not how to capture it. It requires testing trailing rules against the OHLC, which is
pending work.

---

## What must NOT make it into the rules

- **Anything derived from DugEFresh** or from XRP on Phemex: it is one man (91.3% of the PnL).
- **The SKILL's "12-24h sweet spot"**: that was DugEFresh's bucket, not a pattern.
- **Flipping side with the regime**: the side matches the trend 50.9% of the time — a coin flip.
  The SKILL's claim splices two different months.
- **Day of week and hour of day**: an isolated z>2 survives here and there, but that is test
  multiplicity, not signal. Do not use them.
- **Copying anyone's leverage**: see R-2.
- **Selecting the pair by profitability**: 95% of pairs "win" in this dataset (survivors).
- **Any price target**: there is nothing in the data supporting one.

## How to choose who to copy (if you are going to copy)

Skill **does** persist (rho +0.36 with controls, p=0.0001), but it is only measured well over the
trader's **full multi-pair track record**, never over their trades in a single pair (there the
estimator's reliability is ~0.13: pure noise).

**But selecting the elite on BTC buys consistency, not mean return**: median +0.277% vs −0.138%
(z=+8.28), yet **mean +0.261% vs +0.284% (p=0.881)**. They are right far more often for smaller
gains. Useful for the shape of the equity curve and for sizing; it is not free alpha.

## What is missing before risking money

1. **A forward test — not optional.** All the evidence lives in a 5-month window with a single
   regime cycle, over a snapshot of survivors. Without a forward test in sideways and bear
   regimes, these rules are unproven.
2. **A real exit rule** (R-5 only says room exists).
3. **Your own execution costs**: your account's slippage and fees, not theirs. Measured reference:
   these traders' fees are ~**8 bps of notional** per round-trip (taker in and out). They are
   already inside the returns I report (`closing_pnl` is NET, verified over 96,994 complete
   closes). Hard implication: **any rule whose expectancy is below 0.10-0.15% of notional is
   unusable** — which is why R-4 discards sub-1h scalps (+0.04%).
4. **A validated short side**, or explicitly assuming long-only.
5. **Recalibrating R-1's thresholds if BTC's volatility regime changes.** I already verified that
   expressing them as rolling percentiles does NOT work (the effect collapses on P1): they have to
   be absolute. That ties them to the 2025-2026 volatility range.

---

# FORWARD-TEST RESULT (2019-2026, 61,036 candles, 6.9 years)

R-1, R-3 and R-4 were tested as standalone price rules on `ohlc/btcusdt_1h_long.csv`, which covers
three full cycles including the 2022 bear (−64%) and 2025 (−6%).
8 bps round-trip fees included (measured over 96,994 real closes). Script: `forward_test.py`.

## ❌ R-1 DOES NOT SURVIVE — it is directional beta, not alpha

| | result |
|---|---|
| vs 200 random-entry simulations | beats 152/200, **p ≈ 0.244 (not significant)** |
| 6.9-year equity | ×5.59 against **×7.72 for buy and hold** |
| maximum drawdown | 54.7% (buy & hold: 77.2%) |
| mean/trade in BTC **bull** years (2020, 21, 23, 24) | **+0.966%** |
| mean/trade in BTC **bear** years (2019, 22, 25, 26) | **−0.322%** |

It loses money in **every** bear year and underperforms buy and hold. What looked like an edge was
the reflection of having been derived inside a single 7-week bull cycle.

**R-1 is withdrawn as a strategy.** It may still have value as a *filter* over copied positions
(the intra-trader test showed 67% of traders improve under filtered conditions against their own
unfiltered ones), but it is **not a source of return on its own** and must not be used to decide
when to enter the market by yourself.

## ✅ R-3 SURVIVES — fixed stops subtract, and not only in 2026

| stop | mean/trade | equity | MDD |
|---|---|---|---|
| **no stop** | **+0.485%** | **5.59** | 54.7% |
| 2% | +0.376% | 4.37 | **42.8%** |
| 3% | +0.331% | 3.23 | 56.3% |
| 5% | +0.432% | 4.77 | 59.6% |
| 8% | +0.397% | 3.74 | 56.6% |
| 12% | +0.407% | 3.79 | 54.2% |
| 20% | +0.434% | 4.14 | 59.4% |

No stop level improves the return, across 7 years and three regimes. Compared year by year, a 5%
stop is worse in **6 of 8 years**. The 2026 window's result was not an artefact.

Honest nuance: a **very tight stop (2%)** does cut the drawdown from 54.7% to 42.8%. That is a
real trade-off — you pay return for sleeping better — not an improvement. Choose it with your
eyes open.

## ✅ R-2 needs no forward test

It is arithmetic, not a market hypothesis: leverage multiplies the MAE against the margin. With a
median MAE of ~0.7% identical across bands, going from 25x to 60x triples the probability of
touching liquidation (5.7% → 18.6% → 46.7% above 60x). It stands on its own.

## ~ R-4 partially confirmed

Holding sensitivity over 7 years (mean per trade): 24h +0.128%, 48h +0.286%, **72h +0.485%**,
120h +0.816% but with a median of **−0.313%** (a few large wins). Short holdings perform worse,
consistent with what was observed in the copy-trading data. 72h (≈3 days) is the best point by
mean with a positive median.

---

## What stands, honestly

1. **There is no validated entry rule.** R-1 died in the forward test. Entering on momentum is
   trend-following that underperforms buy and hold.
2. **There are validated management rules**: leverage ≤25x (R-2) and no fixed stops (R-3), plus
   holdings of days rather than minutes (R-4).
3. **Trader skill does persist** (rho +0.36) — but measured over their full multi-pair track
   record, and it buys consistency more than mean return.

The practical reading: **the value is not in finding when to enter, but in whom to copy and how to
manage the position once you are in.**
