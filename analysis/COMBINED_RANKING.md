# Combined ranking — all audited pools (updated 2026-08-30)

Status per exchange (all pipelines audited, adversarially reviewed, corrected):

| Exchange | Universe | Survivors | Audited TOP-N doc |
|---|---|---|---|
| Binance | ~600 portfolios | 5 | analysis/TOP5.md |
| OKX | 261 lead traders | 5 (2 recommended) | analysis/TOP5_OKX.md |
| Phemex | 192 with history | **0** | analysis/TOP5_PHEMEX.md |
| Bybit | 155 visible (of 295 scraped) | **0** | analysis/TOP5_BYBIT.md |
| Bitget | ~1,489 (endpoints verified) | — | pending pipeline |
| KuCoin | 170 (screening-only data) | — | pending decision |

Net effect: **the investable universe is Binance (5) + OKX (2 real: Mine13, Algotoria)**.
Phemex and Bybit contribute nothing today — their strongest candidates fail on
risk-profile grounds (leverage tails, uncopyable sizing, concentration, hidden or
intra-window drawdowns). That is the methodology working, not a data problem.

## The combined ranking (unchanged picks, refreshed context)

| Rank | Trader | Exchange | Weight | Alpha | t | Track record | Status |
|---|---|---|---|---|---|---|---|
| 1 | **Mine13** | OKX | 20% | +5.05% | 3.44 | ~3 months, uncapped | ✅ copy |
| 2 | **Cooma** | Binance | 15% | +1.75% | 5.01 | 5 months, both regimes | ✅ copy |
| 3 | **Algotoria** | OKX | 15% | +3.57% | 4.23 | 3 weeks (snapshot) | ⚠️ copy small |
| 4 | **秋高看山势** | Binance | 12% | +1.08%* | 3.14 | improves monthly | ⚠️ $41/trade |
| 5 | **重生之我在币圈捡垃圾-** | Binance | 12% | +0.60%* | 3.36 | 5 months | ⚠️ mdd 64% |
| 6 | **梭哈到世界尽头** | Binance | 8% | +1.60%* | 6.11 | decaying, history deleted | ⚠️ structural doubts |
| 7 | **牛熊摆渡人** | Binance | 8% | +6.89% | 4.15 | 66 days | ⚠️ mdd 75%, ruin −1173% |
| 8 | BestMax | OKX | 4% | +1.11% | 7.74 | 5 days, capped | transparency only |
| 9 | Kunpeng Plan | OKX | 3% | +0.66% | 5.03 | 1 day, capped | transparency only |
| 10 | 對不起我騙了你... | OKX | 3% | +0.68% | 2.93 | 1 day | transparency only |

*Binance alphas pre-date the leave-self-out re-audit (verified robust: shifts ≤0.09pp).

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

## House view

Concentrate on Mine13 + Cooma (35%), keep Algotoria small, treat Binance #4-7 as a
watchlist rather than allocations, ignore the OKX thin-window entries. Re-run all
pipelines on fresh scrapes before any new allocation; Bitget (1,489 traders, richest
per-trade data of any exchange we've mapped — native MDD + daily curves + net fees)
is the next universe to audit and may well beat Phemex/Bybit's zero.
