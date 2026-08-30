# Top 5 OKX lead traders to copy

Same methodology as `analysis/TOP5.md` (Binance), same metric:

```
alpha = de-leveraged price return − median of its cell (symbol × month × side)
```

reproducible with `analysis/okx_flatten.py` + `analysis/okx_top5.py` over
`data/okx_positions.jsonl`. **`pnl` is NET of fees** (verified: reconstructing gross price
PnL from `ctVal` and diffing against the reported `pnl` over 558 closed BTC-USDT-SWAP rows
shows a positive fee residual — gross above net — in 96.6% of rows, median 6.5 bps of
notional; see `docs/okx_endpoint_facts.md` and `scripts/scrape_okx_positions.py`'s docstring).

## The universe, honestly

**261 SWAP lead traders total** (measured 2026-08-29, 27 ranking pages × 10/page — an order
of magnitude smaller than Binance's ~600). Of those:

- **79 (30%)** return `{"code":"60004","msg":"Trader doesn't exist"}` on both position
  endpoints, despite ranking and `public-stats` working for the same `uniqueCode`. Their
  position history is simply not obtainable via this API.
- **40** return zero closed positions (nothing traded, or a genuinely empty window).
- **142** have at least one closed position — **8,936 closed positions** total, spanning
  **2026-05-29 to 2026-08-30** (~3 months, one continuous slice, no wider than the Binance
  audit's own single-regime-cycle caveat).
- **36 of those 142 (25%)** hit OKX's **silent 100-row cap** on `public-subpositions-history`
  — no page/limit/cursor param gets past it (verified against 3+ traders returning exactly
  100 rows regardless of parameters tried). Their true track record is longer than what's
  visible; treat their sample as a recent tail, not a full history — the OKX analogue of the
  Binance `startTime` truncation (Trap 7 in `SKILL.md`), except here it's a row cap instead
  of a public-start date.

Hard filters applied (mirroring `top5_final.py`): min 15 closed + min 8 alpha-eligible
positions, **multi-pair only** (H1: single-pair estimator reliability ~0.13), win rate ≤92%
(Trampa 1), payoff ≥0.5, top-1 trade <30% of net PnL (concentration guard), t≥1.5, and an OKX
addition — **open unrealized loss (`upl`) worse than −50% of closed PnL** rejects, since OKX
exposes no portfolio-level `mdd` the way Binance/Phemex do; a large negative `upl` on
currently-open positions is the only direct signal available for "hiding a loser that just
hasn't been closed yet."

**Rejection breakdown** (of the 142 traders with ≥1 closed position; 110 clear the 15-position
minimum sample size before the other filters apply):

| filter | rejected |
|---|---|
| concentration >30% (top-1 trade) | 36 |
| sample too small | 32 |
| single-pair only (H1) | 17 |
| payoff <0.5 | 17 |
| win rate >92% (Trampa 1) | 13 |
| open unrealized loss > 50% of closed PnL | 8 |
| t <1.5 | 5 |
| no losers on either side | 2 |

**12 traders survive every hard filter.** Below are the 5 I'd actually copy, in the order I'd
weight them, followed by the reasoning for demoting/excluding higher-scoring candidates.

## The picks

| # | trader | n | pairs | alpha | t | payoff | wr% | lev (med/p90) | conc% | lead days | window | notional (med) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Mine13** | 56 | 9 | +4.22% | 3.01 | 1.27 | 82.1 | 10x/10x | 9.4% | 319 | full (not capped) | $31,578 |
| 2 | **01014588** | 100 | 18 | +1.78% | 2.87 | 1.93 | 77.0 | 10x/20x | 15.7% | 366 | **capped at 100** | $50,584 |
| 3 | **Algotoria** | 95 | 8 | +3.54% | 4.20 | 5.22 | 63.2 | 4x/4x | 23.4% | 859 | **3 weeks only** | $24,125 |
| 4 | **Monumental-DoS-Tiger** | 60 | 17 | +4.08% | 3.62 | 1.54 | 81.7 | 10x/**100x** | 7.4% | 273 | full (not capped) | $30,925 |
| 5 | **Powerful-Bubble-Rims** | 99 | 3 | +6.11% | 3.91 | 6.80 | 47.5 | **100x**/100x | 21.7% | 739 | full (not capped) | $1,725 |

**Suggested weights: 30/25/20/15/10**, not even — the order above is deliberately *not* the
raw score order (that would put Powerful-Bubble-Rims first; see "why not #1" below).

### Why each one

**1. Mine13** — the most trustworthy of the five. 9 pairs, payoff 1.27 with an 82% win rate
(wins by hit rate, not by tail size), leverage a flat 10x with **no tail** (p90 also 10x —
nobody scales into extreme risk), and the smallest open-position drag: `upl` on 3 open
positions is −$858 against $86,734 of closed PnL (~1%, immaterial). Their own window is
**not** cap-truncated (56 < 100), so this is the genuine, complete recent record, not a
truncated tail. Headline ranking `pnl` cross-checks closely: **$88,044 reported vs $86,734
computed from the visible window** — the two agree to within 1.5%. 160 real copiers, $864k
AUM. Monthly alpha: +2.93% → +6.42% → +5.21% — strong, not monotonic, but never negative.
*Risk:* only 3 months of visible history (leadDays=319, but the API only shows the recent
window) — same single-regime-cycle caveat as the whole dataset.

**2. 01014588** — the best-diversified candidate (18 pairs) with payoff 1.93 and a moderate
77% win rate, and the mildest leverage tail (p90 20x). *This is the one with the clearest
"the real history is longer than what we see" caveat*: exactly 100 closed rows returned — the
cap — so an unknown number of older positions are invisible. `AUM` and `copyTraderNum` both
read 0 in the current snapshot (no live copiers right now), which doesn't invalidate the
trading record (real notional, $50k median) but means this account is not presently
copyable through OKX's own product even if the analysis likes it. Open-position drag is mild:
−$6,775 against $89,364 closed (7.6%). Monthly alpha declines (+2.85% → +1.64%) over its
2 visible months — worth re-checking before committing real weight.

**3. Algotoria** — the best risk-adjusted numbers in the set: t=4.20 (highest), payoff 5.22,
and the safest leverage of any candidate (flat 4x, no tail at all). 8 pairs, $43k AUM, and the
headline `pnl` cross-checks reasonably ($84,856 reported vs $87,291 computed, 3% apart).
*The catch, and it's a big one:* **all 95 visible positions were opened between 2026-08-06 and
2026-08-27 — a single 3-week window** — despite `leadDays=859` (2.3 years old). Either they
are an extremely high-frequency trader who burns through the 100-row cap in three weeks, or
something changed recently; either way, monthly-trend and multi-regime checks are impossible
here by construction, and the whole sample sits inside one short stretch of August. Treat the
alpha as a snapshot, not a track record.

**4. Monumental-DoS-Tiger** — the most diversified of the five (17 pairs) and the lowest
concentration (7.4%), with a strong 81.7% win rate. Two real risk flags keep this at #4, not
higher: **leverage p90 is 100x** despite a 10x median (a real fat tail, not a rounding
artifact), and **open unrealized loss is −$17,622 against $86,318 of closed PnL (20%)** — under
the 50%-of-PnL hard-reject line, but large enough to flag per the Trampa 1 spirit ("closed
positions look fine, open ones are quietly bleeding"). `AUM`/`copyTraderNum` both read 0
currently. Monthly alpha: +4.10% → +5.26% → +1.70% (decelerating).

**5. Powerful-Bubble-Rims** — has the **highest raw score** of all 12 survivors (t=3.91,
alpha +6.11%, payoff 6.80, and a real, cross-checked $275k headline pnl against $46k AUM with
50 actual copiers) and is placed **last, at minimum weight, on purpose**: median leverage is
**100x**, and their worst single trade lost **42% on price alone** — at 100x that is not a
survivable drawdown on the same leverage; a naive "worst-loss × leverage" ruin estimate comes
out over −4,000% of margin, meaning their real position sizing must be far more conservative
than the leverage figure implies, which a copier cannot replicate blindly. Win rate is a coin
flip (47.5%) — they are right less than half the time and make it up on payoff, the same
profile as `SKILL.md`'s "Scalper King"/牛熊摆渡人 pattern: real skill, uncopyable risk profile
at face value. **Do not copy at their stated leverage.**

## Rejected despite high alpha

**无敌大鲤鱼 — the best alpha in the surviving set (+9.79%, t=2.42, payoff 2.34) and not
copyable.** AUM is **$0.23**, median notional **$91**, and they have exactly **1 follower**.
This is `SKILL.md`'s "Scalper King" story again: the edge may be real, but there is nothing to
copy — sizing this small evaporates into OKX's minimum order increments and any slippage.

**Cheap-Producer-Shrew — a near-miss, not included.** 89% win rate (close to the 92% Trampa 1
line), leverage p90 **50x**, and the largest notional in the survivor pool ($124k median). Their own
`pnlRatios` weekly series shows a long stretch of consecutive negative weeks (roughly −25% to
−8%, from `public-lead-traders`' own `pnlRatios[]` field) before a recent recovery to +4.7%
cumulative — a real, disclosed drawdown, not a hidden one, but the size × leverage combination
is not one to add weight to speculatively.

## The Trampa 1 signature, alive on OKX too

The same "closed record looks spotless, real risk is invisible" pattern documented for
Phemex/Binance shows up here, at a larger scale than either (win rate is a coarser signal with
OKX's ~100-row window): of the 110 traders with ≥15 closed positions, **13 have a closed win
rate above 92%**, including (100 closed positions each, unless noted): **Ail.Wang** (99%),
**好望角9999** (99%, 100 closed), **Bare-Payee-Fox** (98.7%, 78 closed), **RuiJie** (97%),
**chenyuan** (97.9%, 95 closed), **Busy-DID-Wombat** (96.9%, 98 closed). None of these appear
above — a 92%+ closed win rate with real sample size is the single strongest "don't copy this"
signal in the whole dataset, exactly as it was for Binance/Phemex.

## Rejected despite high PnL (Trampa 2 — never rank by PnL/ROI)

**KingoftheWORLD** — $196,897 total closed PnL over 60 positions, but **one trade is
$127,474 of it (64.7%)**. **liyuan-luo** — $236,969 over just 24 positions, **$153,228 (64.7%)
from one trade**. Both would top a naive PnL ranking; both fail the concentration guard for
the same reason DugEFresh failed it in the Binance audit.

## Confidence: low, lower than the Binance Top 5

- **Universe is 261, not ~600** — fewer candidates means a thinner margin against the
  winner's-curse effect `SKILL.md` already flags for Binance's larger pool.
- **~3 months, one regime slice**, same as the audited Binance snapshot, but with less
  redundancy per trader (many candidates are near the 100-row cap, meaning "3 months of
  history" often really means "however many weeks it took to accumulate 100 trades" —
  Algotoria at 3 weeks is the extreme case, not a unique one).
- **30% of the ranked universe (79/261) has no obtainable position history at all** — this
  Top 5 is drawn from a smaller, possibly non-representative subset of OKX's own leaderboard.
- **No portfolio-level `mdd` from OKX's public API.** The open-`upl` check is the best proxy
  available, but unlike Binance/Phemex's `mdd` it only sees positions open *right now*, not
  the worst historical drawdown.
- **fresh_start (leadDays <120): none of the 5 picks are flagged** — all have leadDays ≥273 —
  but `leadDays` measures account age, not visible-window length, and 3 of the 5 (01014588,
  Algotoria, and to a lesser extent Powerful-Bubble-Rims/Monumental) show a real gap between
  the two (see "window" column above).

**Suggested operation:** the same discipline as the Binance Top 5 — weights 30/25/20/15/10 in
the order given, review monthly alpha as more data accumulates (all 5 have fewer than 4 months
of visible history, so "two consecutive negative months" is barely checkable yet), and treat
Powerful-Bubble-Rims's leverage as a hard cap to override, not a parameter to copy verbatim.
