# Combined ranking — all audited pools (updated 2026-09-23)

Status per exchange (all pipelines audited, adversarially reviewed, corrected):

| Exchange | Universe | Survivors | Audited TOP-N doc |
|---|---|---|---|
| Binance | ~600 portfolios | 5 | analysis/TOP5.md |
| OKX | 261 lead traders | 5 (2 recommended) | analysis/TOP5_OKX.md |
| Phemex | 192 with history | **0** | analysis/TOP5_PHEMEX.md |
| Bybit | 155 visible (of 295 scraped) | **0** | analysis/TOP5_BYBIT.md |
| Bitget | 400 scraped of 1,488 (290 ranked) | **0** | analysis/TOP5_BITGET.md |
| KuCoin | 165 (137 ranked) | **0** | analysis/TOP5_KUCOIN.md |

All six exchanges are now audited. Net effect: **the investable universe is
Binance (5) + OKX (2 real: Mine13, Algotoria)**. Phemex, Bybit, Bitget and KuCoin
contribute nothing — their strongest candidates fail on risk-profile grounds
(leverage tails, uncopyable sizing, concentration, hidden or intra-window
drawdowns). Four of six at zero is the methodology working, not a data problem.

## The combined ranking (unchanged picks, refreshed context)

| Rank | Trader | Exchange | Weight | Alpha | t | Track record | Status |
|---|---|---|---|---|---|---|---|
| 1 | **Mine13** | OKX | 20% | +5.05% | 3.44 | ~3 months, uncapped | ✅ copy |
| 2 | **Cooma** | Binance | 15% | +1.75% | 5.01 | 5 months, both regimes | ✅ copy |
| 3 | **Algotoria** | OKX | 15% | +3.57% | 4.23 | 3 weeks (snapshot) | ⚠️ copy small |
| 4 | **秋高看山势** | Binance | 12% | +1.08%* | 3.14 | improves monthly | ⚠️ $41/trade |
| 5 | **重生之我在币圈捡垃圾-** | Binance | 12% | +0.60%* | 3.36 | 5 months | ⚠️ mdd 64% |
| 6 | **梭哈到世界尽头** | Binance | 8% | +1.60%* | 6.11 | decaying, history deleted | ⚠️ structural doubts |
| 7 | ~~牛熊摆渡人~~ | Binance | ~~8%~~ | +6.89% | 4.15 | 66 days | ❌ retired 2026-09-23 (see below) |
| 8 | BestMax | OKX | 4% | +1.11% | 7.74 | 5 days, capped | transparency only |
| 9 | Kunpeng Plan | OKX | 3% | +0.66% | 5.03 | 1 day, capped | transparency only |
| 10 | 對不起我騙了你... | OKX | 3% | +0.68% | 2.93 | 1 day | transparency only |

*Binance alphas pre-date the leave-self-out re-audit (verified robust: shifts ≤0.09pp).

## Retired: 牛熊摆渡人 (2026-09-23)

The fragility flag on row 7 (66 days of history, 75% max drawdown, ruin −1173%) came
true. Portfolio `5096968193101811713`, verified against the live position history:

- Last opening **2026-08-28 16:33 UTC** — two days before the shadow books were born,
  so it never produced a single mirrored fill. That was the birth rule working, not a bug.
- **2026-09-02 21:44:14 UTC: 14 positions closed in the same second for −15,295 USDT**,
  −14,397 of it a single AKEUSDT short held since July. The 84 visible closes before that
  day summed to +8,671; net over the whole visible history, −6,624.
- No opening and no open position since. The portfolio no longer appears in the public
  leaderboard search, so it cannot be copied either.

This is Trap 1 (the loser nobody closes) arriving from the other side: a high-alpha
closed-position record paired with a portfolio drawdown that said the risk was still
open. Its 8% is **not** reassigned here. The ranking dates from a single-regime
snapshot, so a replacement comes out of a fresh re-run of the pipelines, not from
promoting the next row.

## What changed in this update (2026-08-30)

- **Phemex added: zero survivors.** The sole candidate (achilles, alpha +1.11% t=3.75)
  was rejected post-audit by the trade-granularity drawdown screen: −33.7% real
  intra-window drawdown that the original monthly proxy (0.0%) hid. The audit also
  fixed dead cross-check code (int/str keying).
- **Bybit added: zero survivors** (295 scraped, 140 hide history, 155 analyzed, 11,409
  positions). Top-8 near-misses each die on a distinct filter; the zero is robust on
  two independent return bases (raw-price and roi/leverage). Notable: sportsman-1
  passed every closed-position filter and was killed ONLY by the yield-trend drawdown
  screen (−54% uncovered) — the 01014588 lesson paying for itself.
- Bybit quirks now on record (checklist appendix): 100-row/trader API cap,
  position-level E8 pnl, unreliable price fields, browser-only access.
- **Bitget added: zero survivors** (400 of 1,488 scraped, 290 ranked, 40,516 closed
  rows). The leaderboard's `data.totals` lies; open positions are protected for 24.8%
  of traders while their closed history stays fully visible. One trader survived a
  first pass and was removed by the corrected pipeline.
- **KuCoin added: zero survivors** (165/165 scraped clean, 137 ranked) — the smallest
  and cleanest universe of the six, and the first with real unrealized-PnL data, which
  bought an open-position upl guard the other five could not support.

## House view

Concentrate on Mine13 + Cooma (35%), keep Algotoria small, treat Binance #4-6 as a
watchlist rather than allocations, ignore the OKX thin-window entries. Re-run all
pipelines on fresh scrapes before any new allocation. With the six-exchange sweep
closed, the next gain is depth, not breadth: widen Bitget beyond the top-400 slice
and re-scrape the four zero-survivor pools before trusting their zeros a second time.
