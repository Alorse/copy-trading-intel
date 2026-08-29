---
name: copy-trading-intel
description: "Scrape Phemex+Binance copy-trading public data for patterns."
version: 2.0.0
author: Alfredo Ortegón Sepúlveda — with LLM agent assistance
license: MIT
---

> # ⚠️ SUPERSEDED VERSION — HISTORICAL RECORD ONLY
>
> The current version is `SKILL.md` (3.0.0). This file is kept because the 2026-08-25 audit
> proved that **six of its findings are false against its own data** (time range, XRP
> concentration, "the elite flips with the regime", duration buckets, the leverage effect and
> the fixed-stop recommendation). The diff is in the "What v2 claims and the data denies" table
> in `SKILL.md`.
>
> **Do not use these findings.** They are here to show what was believed before the audit.

# copy-trading-intel

## When to Use
- Analysing public copy-trading on Phemex or Binance (traders, PnL, best pairs).
- Finding/validating patterns for the single-pair (XRP) strategy.
- Re-scraping newly closed positions before an analysis.

Multi-exchange public copy-trading intelligence: which traders exist, which positions they
opened/closed, which pair they won on, and which patterns survive analysis.
(Successor to `phemex-copy-intel`, absorbed when Binance was added.)

## Phemex endpoints (public, GET, no auth)

⚠️ **Use `api.phemex.com`** — `api10.phemex.com` returns 403 (CloudFront) from some hosts.
Headers: browser `User-Agent`, `Origin: https://phemex.com`, `Referer: https://phemex.com/`, `Accept: application/json`.

- **Trader listing:** `GET /phemex-lb/public/data/v3/user/recommend?hideFullyCopied=false&keyword=&pageNum=1&pageSize=50&showChart=false&sortBy=PnlRate30d`
  - `data.rows[]`: `userId`, `nickName`, `pnlRate30d`, `pnl30d`, `tradeWinRate30d`, `mdd30d`, `aum`, `followerCount`, **`showPosition`** (true = history visible → the only scrapeable ones).
- **Closed positions:** `GET /phemex-lb/public/data/position/closed/v2?pageNum=1&pageSize=100&userId=<id>`
  - `data.rows[]`: `symbol`, `side`, `size`, `openPositionVal`, `margin`, `roi`, `closedPnl`, `realizedPnl` (net), `openedTime`/`updatedTime` (ms), `fundingFee`, `exchangeFee`. Paginate until `rows < pageSize`.
- Others: `/phemex-lb/public/data/v3/user/symbol-metric`, `user/pnl-chart`, `user/pnl-rate-chart`, `position/current/v2`, `v3/user/leaders` (found in the JS chunks at `phemex.com/p-114/js/chunk-676ef36f.js`, `CT_*` consts).

## Binance endpoints (public, POST JSON, no auth)

Headers: browser `User-Agent`, `Content-Type: application/json`, `clienttype: web`, binance.com `Origin`/`Referer`.

- **Portfolio listing:** `POST /bapi/futures/v1/friendly/future/copy-trade/home-page/query-list`
  - Body: `{"pageNumber":1,"pageSize":30,"timeRange":"90D","dataType":"ROI","favoriteOnly":false,"hideFull":true,"nickname":"","order":"DESC","userAsset":0,"portfolioType":"PUBLIC"}`
  - `data.list[]`: `leadPortfolioId`, `nickname`, `roi`, `pnl`, `aum`, `winRate`, `mdd`, `copierPnl`. ⚠️ pageSize is ignored (cap of 30/page); paginate with `pageNumber`. `total` ~8,520 portfolios.
  - `dataType`: ROI/PNL/AUM/SHARP_RATIO/WIN_RATE; `timeRange`: 30D/90D/180D/365D — combining them widens coverage.
- **Position history:** `POST /bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history`
  - Body: `{"portfolioId":"<leadPortfolioId>","pageNumber":1,"pageSize":50}`
  - ⚠️ The `/public/` variant returns 0 rows — use `/friendly/`.
  - `data.list[]`: `symbol`, `side`, **`leverage`**, `isolated` (Cross/Isolated), `avgCost`, `avgClosePrice`, `closingPnl`, `roi`, `maxOpenInterest`, `closedVolume`, `opened`/`closed` (ms). **Includes real leverage and margin — better than Phemex.**
- Others: `lead-portfolio/order-history`, `transfer-history`, `copy-traders`, `lead-portfolio/detail`, `lead-data/positions` (mapped from the GitHub repo doppelganger237/gendan).

## Scripts

- `scripts/scrape_positions.py` — Phemex: listing + history (resumable). `python3 scripts/scrape_positions.py [--refresh]`.
- `scripts/scrape_binance.py` — Binance: listing + history (resumable). `python3 scripts/scrape_binance.py [--refresh]`. Widen coverage by editing `fetch_portfolios()` (pages/timeRange/dataType).

## Dataset (data/)

2026-08-25 snapshot:
- `positions_all.jsonl` — Phemex raw: 192 traders, 7,467 positions (2023-03-03 → 2026-08-25)
- `all_traders.json` — Phemex: 250 traders from the listing (196 with showPosition)
- `binance_portfolios.json` — Binance: 600 portfolios, top 90D ROI (out of ~8,520)
- `binance_positions.jsonl` — Binance raw: history per portfolioId
- `best_pair_by_trader.json`, `aggregate_by_symbol.json`, `aggregate_no_lottery.json`, `pattern_focus.json`, `SUMMARY.json` — Phemex analysis, 2026-08-25

## Binance findings (2026-08-25, 594 portfolios / 108,616 positions / Dec-2024→Aug-2026)

⚠️ Sample bias: the top-600 portfolios by 90D ROI = **survivors** (not the crowd). Data with real leverage and margin.

- **The elite wins on majors**: BTC +1.18M (7,204 pos, wr 56%), ETH +299k. Most frequent best pair: BTC (91×), ETH (76×).
- **Semiconductor tokenized stocks = a real seam**: SOXL +411k (wr 68%), SKHYNIX +380k, SNDK +220k, MU +149k, SPCX +135k, SAMSUNG +108k (wr 82%). Spread across many traders, not a lottery.
- **SOL loses** (−32k, 2,150 pos) — consistent with Phemex (−125k).
- Median leverage 10x (p90 51x, max 150x); **94% cross** (only 6% isolated).
- **XRP on Binance LOSES** (−4k, 760 pos): longs −12k, shorts +6.7k. wr 59% but avg_loss 1.61× avg_win. The 1-3d bucket is the worst (−14.8k); 12-24h the best (+5k). Hourly PnL unstable.
- **Phemex-vs-Binance conclusion**: Phemex's "XRP pattern" was DugEFresh (a 50x outlier), not the pair. Among the Binance elite XRP generates no edge and the long crowd loses.

### Validating the elite BTC/ETH pattern (2026-08-25, deep dive)
- **Genuinely distributed but top-heavy**: BTC 282/429 traders win (top-5 = 47% of the PnL); ETH 259/414 (top-5 = 128% — the rest is net negative). Not a one-man show (like SUI/ONDO), but not a uniform edge either.
- **The side follows the regime**: long in bullish months (Jul-Aug +163k/+826k BTC), short in the May crash (BTC shorts +235k with longs −186k). The elite has NO static bias: it flips with the regime. Without regime context, "just buy" does not replicate their edge.
- **Duration**: the money is in 1-3d (+255k/+178k) and 7-30d (+566k BTC). Sub-1h scalps and 12-24h swings ALWAYS lose (every table: XRP, BTC, ETH). Paradox of the initial Phemex analysis's "12-24h sweet spot": that was DugEFresh's bucket, not a universal pattern.
- **Leverage**: 6-20x concentrates the PnL (BTC +752k, ETH +320k); >50x is neutral to negative (ETH −80k) — the elite does not win through extreme leverage but through management.
- **Stability ex-August**: BTC +405k without August (the edge does not depend on the pump). ETH only +11.5k without August — **ETH's edge is mostly THE August event**.
- **Verdict**: BTC is the only pair with a broad, distributed and temporally stable edge. ETH is a BTC beta with a sample contaminated by the event.

### Phemex re-analysis without DugEFresh (2026-08-25, anti-bias filters)
Criteria: ≥10 positions, ≥5 traders, ≥3 independent winners, top trader <60% of the PnL, trader median >0.
- **Result: 0 of 15 positive pairs pass.** All fail on concentration (SUI top=95%, TAO 101%, XRP 111%) or a negative median.
- Without DugEFresh, XRP on Phemex sits at +3.3k but with top-trader=111% of the PnL and a NEGATIVE trader median: most who touched XRP lost; 2 outliers (Rocky +3.7k, Number1 +3.6k on 1 trade each) paint the aggregate.
- Less biased "near misses": XLM (1.5k, 10/15 win, but 24 trades and 1.3k from the top one) and SNDK (1k, 5/7) — samples far too small to trade.
- The Phemex crowd loses consistently on BTC −173k, SOL −79k, ETH −25k, ZEC −19k.
- **Conclusion**: on Phemex there is NO tradeable pair once outliers are removed — every "winning pair" was 1-2 men. Phemex's useful signal is the INVERSE (where the crowd loses). The real positive signal is in the Binance elite (BTC).

## Phemex findings (2026-08-25)

- Crowd expectancy: **−190 USD/trade** (wr 46%, avg_loss 2.6× avg_win). Net PnL −1.4M.
- Worst pairs: BTC (−368k excluding lotteries), SOL (−125k), POPCAT (−602k).
- "Best pairs" are almost always a lottery: SUI/ONDO = 1 trader with 127-157 day shorts; TAO, XBR = 1 trader each.
- **XRP the exception**: 64 traders, +38k distributed.

## XRPUSDT patterns (Phemex, 299 positions) — the single-pair base

1. **LONG bias**: longs +39.4k vs shorts −1.3k.
2. **EVENT-DRIVEN**: nearly all the PnL from the 19-23 Aug 2026 pump (DugEFresh: 9 trades +35.8k wr 78% on the breakout; outside the event wr 24%, −1k).
3. **12-24h sweet spot** (+40k); `<1h` and `4-12h` lose (noise/exiting mid-move).
4. **Asymmetry**: avg_loss/avg_win 0.21; longest loser 76h; never a martingale.
5. **Pyramiding into strength**: 10× size only after the pump is confirmed (~50x leverage — NOT replicable).
6. Sunday the only clearly negative day; time of day shows no stable pattern.

### Single-pair (XRP) strategy — to be validated in a forward test
- Confirmed breakouts/momentum only, long bias. Ride 12-24h. Early SL + trailing.
- No active event → do NOT trade. ⚠️ Never copy the 50x: what transfers is timing + management at 2-3x.

## Rules

- ⚠️ **NEVER rename/move/delete this tree (or any dataset) while a background scraper is writing**: run `process(list)` first, then wait or kill and relaunch (the scrapers are resumable). Incident 2026-08-25: a rename with the scraper running → 440 portfolios lost and a 45 min re-scrape. A `cp` saves nothing: it creates new inodes, and whatever the process writes afterwards dies with the original.
- Re-scrape before any new analysis.
- ALWAYS check per-trader concentration before declaring a "winning pair" (the SUI/ONDO lesson).
- Copy-trading ROI includes high leverage: a position's ROI ≠ a replicable edge.
