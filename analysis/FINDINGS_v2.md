# `copy-trading-intel` audit — v2, after adversarial review

Supersedes `FINDINGS.md`. Four independent reviewers (Fable, Kimi, Qwen, GLM) plus first-hand
verification of my own. **Every number here was re-derived by me after a reviewer flagged it** —
no reviewer's finding is reported as fact without checking.

Snapshot: the root of this repo. Nothing was re-scraped.
The only authorised download: BTCUSDT OHLC (`ohlc/`, via `fetch_ohlc.py`).

---

## Corrections to my own v1

**C1 — R6 was badly framed and its headline was untenable.**
v1 said *"skill does not persist"* with rho(expectancy)=+0.136 on BTC.
Fable and Kimi **separately** computed that test's noise ceiling: **0.13 / 0.137**.
That is: with PERFECT persistence, that test would have returned ~0.13. It measured its own
noise. I declared the limitation (L2) and still headlined against it — exactly the bias I was
charging the SKILL with.

**C2 — Persistence DOES exist, measured over the full track record.**
Verified by me, own implementation, calendar split, NET return:

| pooled test (all symbols) | n | rho | 95% CI | p |
|---|---|---|---|---|
| raw | 193 | +0.422 | [+0.281, +0.549] | 0.0001 |
| **demeaned symbol × side × half** | 190 | **+0.361** | [+0.213, +0.497] | 0.0001 |

After controlling for which pair, which side and which period: the top tercile in H1 →
**+0.855%/position** in H2 vs **−0.116%** for the bottom tercile. And selection by 90D ROI biases
rho **downwards** (Berkson), so +0.36 is a floor. Kimi concluded "not identifiable" but never ran
the pooled test. **Fable was right; my R6 falls.**

**C3 — I omitted the correlation that contradicted my thesis.** I reported
corr(winrate, payoff)=−0.497 and concluded "the style that persists does not pay", without
reporting **corr(winrate, expectancy)=+0.554** (verified, n=108), which was printed in my own
script's output. Both reviewers caught it. Kimi further showed the −0.497 is largely an
**accounting identity**: if expectancy≈0 then payoff≈(1−wr)/wr. It was evidence of nothing.

**C4 — `closing_pnl` is NET, not gross.** Verified: `closing_pnl − gross_price_pnl` =
**−7.84 bps** of notional (p25 −10.0, p75 −4.2), **93% negative** — the order of magnitude of
taker fees + funding. L6 closes **the opposite way** to my speculation: the expectancies were not
inflated.

**C5 — Altcoin leverage is 10x, not 5x.** Verified: BTC 30x, ETH 30x, SOL 20x, XRP 20x, the rest
**10x**. The 5x only appears in the subgroup of pairs with the highest median return.

**C6 — Phemex is 192 traders, not 196.** I marked "196 ✅ exact"; there are 192 unique
`trader_id` (196 is the count of the listing with `showPosition`). A false positive of my audit.

**C7 — My finding "bear+Long is the only bad cell" does NOT survive out-of-sample.**
In period 1 it gave −0.033%; in period 2 it gave **+0.281%**. It flipped sign. Withdrawn.

---

## What holds against the SKILL

**R1 — Phemex's "XRP pattern" is a single man.** DugEFresh = **91.3%** of the PnL (using
`realized_pnl`; 85.9% with `closed_pnl`), median per trader **−1.5**, 27/64 win.
The SKILL still publishes *"XRP the exception: 64 traders, +38k distributed"* in its "Phemex
findings" despite correcting it in a later section. Confirmed by all 3 reviewers.

**R2 — "12-24h ALWAYS loses (XRP, BTC, ETH)" is false.** It is the **best** bucket on Phemex-XRP
(+41.1k) and on Binance-XRP (+5.0k). It only loses on BTC and ETH. The SKILL overcorrected its own
"12-24h sweet spot": neither of its two versions is true.

**R3 — Aggregating in USD lets account size decide.** SOL: aggregate −32,229 but median per trader
**+21.2**. XRP: −3,966 with a median of **+3.0**. The typical trader won; a few enormous accounts
sank the aggregate.

**R4 — Picking a pair by profitability within this dataset is circular.** De-leveraged,
**188/197 pairs (95%)** have a positive median return per trader. They are the top-600 by ROI:
they win at everything. The ranking measures survival, not the pair's edge.

**R5 — The ROI ranking rewards leverage arithmetically** (ROI is on margin).
Corrected: majors 30x vs the rest at 10x, not 5x.

**R7 (new) — "The elite flips with the regime" does not hold.** The side matches the trend (price
vs MA200h, computed from the real OHLC) on **50.9%** of BTC positions — a coin flip. Kimi further
showed the SKILL spliced two different months: the "+235k shorts" is May and the "−186k longs" is
June, and the side mix barely moves (48% → 47% → 48% → 42%). Shorts winning in a crash is
mechanical beta.

**R8 (new) — A row is NOT an atomic trade.** Contrasting `avg_cost` against the 1h candle of its
own opening: 86.6% falls inside the range, 13.4% does not. And the ones falling outside have a
median duration of **54.2h vs 3.8h** and **42.1% partial closes vs 5.2%**. They are
scale-in/scale-out aggregates. Any "win rate per row" measures the partial-close policy as much as
being right.

---

## R6 reformulated (the conclusion that matters)

**Skill persists, but is only measurable with the trader's full track record.**

- Within a single pair, the per-trader estimator has ~0.13 reliability: useless for ranking.
- Pooling all their pairs: rho ≈ **+0.36 to +0.42**, p=0.0001, robust to controls for symbol,
  side, period and fees.

**But — and no reviewer produced this — the advantage does NOT carry over to BTC as mean return.**
Selecting the elite tercile by multi-pair expectancy in P1 and measuring their BTC in P2:

| BTC out-of-sample | ELITE | REST | test |
|---|---|---|---|
| **median** return/pos | +0.277% | −0.138% | MWU z=**+8.28** ✅ |
| **mean** return/pos | +0.261% | +0.284% | permutation **p=0.881** ❌ |
| win rate | 75.0% | 40.6% | |
| payoff | 0.57 | 2.21 | |
| median leverage | 25x | 50x | z=−2.75 ✅ |

Selecting the elite buys **consistency**, not mean return. They are right far more often for
smaller gains; in expectation per position they tie. That changes the shape of the equity curve
and enables more aggressive sizing — it is not free alpha.

---

**R9 (new, found by GLM and verified) — The SKILL's time range is false.**
The SKILL says "Dec-2024→Aug-2026". **Zero** positions closed before April 2026: all 107,812 close
within 5 months (Apr 996, May 12,171, Jun 21,751, Jul 29,417, Aug 43,477). The long range comes
from the *opening* dates of a few swings. Consequence: **every temporal-stability claim — the
SKILL's and mine — degrades to "consistency within a single regime cycle"**.

**Contradiction between reviewers, resolved.** GLM concluded `closing_pnl` is GROSS; Fable and Kimi
that it is NET. I verified over 96,994 complete closes: the residual against the price-derived PnL
is −7.85 bps (93.7% negative). If it were gross the residual would be ~0. **GLM measured the same
thing (−0.079%) and inverted the inference.** Fable and Kimi are right: it is NET. Phemex's ground
truth confirms it (`closed_pnl − fee − funding = realized_pnl`, exactly).

## Limitations still standing

- **Survivorship with no control**: the 594 portfolios are the top-600 by 90D ROI. There is no
  group of failed Binance traders. It biases persistence downwards (good for C2), but invalidates
  any absolute level of profitability.
- **Trader identity**: the nick does not identify humans; one person with several portfolios
  inflates the effective n.
- **A row ≠ a trade** (R8): every win rate and every duration is contaminated by the partial-close
  policy.
- **A single regime window (R9)**: 5 months, a crash followed by a pump. No sideways or prolonged
  bear regime. This is the gravest limitation of all.
- **Without OHLC there are no technical entry rules.** BTC's has now been downloaded; the entry
  rules are still timing proxies, not validated signals.
