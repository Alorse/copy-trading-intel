---
name: copy-trading-intel
version: 3.0.0
author: Alfredo Ortegón Sepúlveda — with LLM agent assistance and adversarial audit
license: MIT
description: "Scrape Phemex+Binance copy-trading public data for patterns. v3: findings corrected after audit."
---

> **Version 3.0.0 — current.** Supersedes `SKILL.v2.md`, kept as a record: it contains six claims
> the 2026-08-25 audit proved false against its own data. The table "What v2 claims and the data
> denies" (below) is the diff between the two.
>
> Everything here is reproducible with the scripts in `analysis/` over your own snapshot.
> Full evidence in `analysis/FINDINGS_v2.md`, `analysis/RULES.md` and `analysis/TOP5.md`.

# copy-trading-intel

## When to Use
- Analysing public copy-trading on Phemex or Binance (traders, PnL, best pairs).
- Finding/validating patterns for a single-pair strategy.
- Selecting traders to copy (see `analysis/TOP5.md`).

## Phemex endpoints (public, GET, no auth)

⚠️ **Use `api.phemex.com`** — `api10.phemex.com` returns 403 (CloudFront) from some hosts.
Headers: browser `User-Agent`, `Origin: https://phemex.com`, `Referer: https://phemex.com/`, `Accept: application/json`.

- **Trader listing:** `GET /phemex-lb/public/data/v3/user/recommend?hideFullyCopied=false&keyword=&pageNum=1&pageSize=50&showChart=false&sortBy=PnlRate30d`
  - `data.rows[]`: `userId`, `nickName`, `pnlRate30d`, `pnl30d`, `tradeWinRate30d`, `mdd30d`, `aum`, `followerCount`, **`showPosition`** (true = history visible → the only scrapeable ones).
- **Closed positions:** `GET /phemex-lb/public/data/position/closed/v2?pageNum=1&pageSize=100&userId=<id>`
  - `data.rows[]`: `symbol`, `side`, `size`, `openPositionVal`, `margin`, `roi`, `closedPnl`, `realizedPnl` (**net**), `openedTime`/`updatedTime` (ms), `fundingFee`, `exchangeFee`. Paginate until `rows < pageSize`.
  - ✅ Verified: `realizedPnl = closedPnl − exchangeFee − fundingFee`, exactly.
- Others: `/phemex-lb/public/data/v3/user/symbol-metric`, `user/pnl-chart`, `user/pnl-rate-chart`, `position/current/v2`, `v3/user/leaders`.
- **OPEN positions (probed 2026-08-28):** `GET /phemex-lb/public/data/position/current/v2?userId=<id>` — ✅ **AVAILABLE** (`code:0`, `data.total`, `data.rows[]`).
  - Fields: `symbol`, `side` (Buy/Sell), `posSide` (Long/Short), `size`, `value` (notional), `positionMargin`, `avgEntryPrice`, `leverage`, `liquidationPrice`, `realizedPnl`, `positionId`, `transactTime`.
  - ⚠️ **No unrealised PnL and no mark price** → `open_loss_divergence` cannot be computed without a price feed. That is why it is NOT wired into pipeline v1 (which ranks Binance only anyway).

## Binance endpoints (public, POST JSON, no auth)

Headers: browser `User-Agent`, `Content-Type: application/json`, `clienttype: web`, binance.com `Origin`/`Referer`.

- **Portfolio listing:** `POST /bapi/futures/v1/friendly/future/copy-trade/home-page/query-list`
  - Body: `{"pageNumber":1,"pageSize":30,"timeRange":"90D","dataType":"ROI","favoriteOnly":false,"hideFull":true,"nickname":"","order":"DESC","userAsset":0,"portfolioType":"PUBLIC"}`
  - ⚠️ pageSize is ignored (cap of 30/page). `total` ~8,520 portfolios.
- **Position history:** `POST /bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history`
  - Body: `{"portfolioId":"<leadPortfolioId>","pageNumber":1,"pageSize":50}`
  - ⚠️ The `/public/` variant returns 0 rows — use `/friendly/`.
  - ⚠️ **Returns CLOSED positions only.** Open ones (and their latent losses) are invisible. See "Trap 1".
  - ✖ **OPEN positions: verified NOT available on 2026-08-28.** The `scripts/probe_open_positions.py` probe against `/friendly/future/copy-trade/lead-portfolio/{positions,position-list,current-position,open-positions}` with a real `portfolioId`: **HTTP 404 on all 4 candidates** (with and without pagination). There is no public per-lead-trader open-positions endpoint.
  - ✅ `closingPnl` is **NET** of fees. Verified over 96,994 complete closes: residual against the price PnL = **−7.85 bps of notional**, 93.7% negative (≈ taker in and out). Fees ≈ **8 bps per round-trip**.

## Scripts

- `scripts/scrape_positions.py` — Phemex (resumable).
- `scripts/scrape_binance.py` — Binance (resumable).
- `analysis/flatten.py` — **start here.** Flattens the nested `.jsonl` into flat CSVs. No network, ~10s.
- `analysis/*.py` — 14 scripts reproducing every figure in `FINDINGS_v2.md` and `RULES.md`.
- `pipeline.py` — the permanent pipeline (see `docs/specs/2026-08-28-copy-trading-refresh-design.md`).

## Dataset (data/) — 2026-08-25 snapshot

- `positions_all.jsonl` — Phemex: **192 traders** (not 196), 7,467 positions.
- `binance_positions.jsonl` — Binance: 594 portfolios with positions (600 lines), 108,616 positions.
- `analysis/ohlc/` — BTCUSDT candles: `btcusdt_1h.csv` (the dataset's window) and `btcusdt_1h_long.csv` (2019-2026, for the walk-forward).

⚠️ **REAL TIME RANGE: 5 MONTHS, NOT 20.** v2 says "Dec-2024→Aug-2026". **Zero** positions closed
before April 2026. Closes per month: Apr 996 · May 12,171 · Jun 21,751 · Jul 29,417 ·
Aug 43,477. v2's long range comes from the *opening* dates of a handful of long swings.
**There is a single regime cycle**: the May–June crash, the July–August pump (BTC +25.8% in 7
weeks). No sideways or prolonged bear regime. Every "temporal stability" claim is, at most,
"consistency within one cycle".

---

# Corrected findings (2026-08-25)

## What v2 claims and the data denies

| v2's claim | verified reality |
|---|---|
| "XRP the exception: 64 traders, +38k **distributed**" | DugEFresh = **91.3%** of the PnL; median per trader **−1.5**; 27/64 win |
| "12-24h **always** loses (XRP, BTC, ETH)" | It is the **best** bucket on Phemex-XRP (+41.1k) and Binance-XRP (+5.0k). It only loses on BTC/ETH |
| "The elite **flips with the regime**" | The side matches the trend (MA200h) **50.9%** of the time — a coin flip. The side mix barely moves: 48→47→48→42% |
| "BTC shorts +235k with longs −186k" | Those are **two different months** spliced together: +235k is May, −186k is June |
| "**6-20x** concentrates the PnL; >50x neutral" | An artefact of ranking by ROI, which rewards leverage arithmetically. Majors 30x, the rest **10x** (v2 says 5x) |
| "Dec-2024 → Aug-2026" | 5 real months (see above) |

## What does hold from v2

- Semiconductor tokenized stocks concentrate real, distributed PnL (SKHYNIX, MU, SNDK).
- BTC is the least concentrated pair: 437 traders, top-1 only 15.8% of the PnL.
- The Phemex crowd loses consistently (expectancy −190 USD/trade).
- A trader's "best pair" is usually a lottery: always check concentration.

## New findings

**H1 — Skill DOES persist, but only measured over the full multi-pair track record.**
Calendar split, net return, demeaned by symbol×side×half: **rho = +0.36 to +0.42, p=0.0001**.
Within a single pair the estimator's reliability is **~0.13** — pure noise. **Never rank a trader
on their trades in one pair.**

**H2 — Selecting the elite buys consistency, not mean return.** Top vs bottom tercile on BTC
out-of-sample: median +0.277% vs −0.138% (MWU z=+8.28), but **mean +0.261% vs +0.284%
(p=0.881)**. They are right more often, for smaller gains.

**H3 — A row is NOT an atomic trade.** Contrasting `avgCost` against the 1h candle of its
opening: 13.4% falls outside the range, and those have a median duration of **54.2h vs 3.8h** and
**42.1% partial closes vs 5.2%**. They are scale-in/scale-out aggregates. Any "win rate per row"
measures the partial-close policy as much as being right.

**H4 — High leverage is ruin risk, not management.** % of positions that consumed >80% of margin:
≤10x **2.4%** · 11-25x **5.7%** · 26-60x **18.6%** · >60x **46.7%**. The median MAE is ~0.7% in
every band: the leveraged trader does not risk less per trade.

**H5 — Fixed stops subtract.** Walk-forward 2019-2026 (7 years, 3 cycles): no stop level improves
the return; a 5% one is worse in 6 of 8 years. **This invalidates the "early SL + trailing" that
v2 recommends.** Risk control comes from leverage (H4), not from stops. A very tight stop (2%)
does cut the drawdown from 55% to 43%, paying for it in return: a trade-off, not an improvement.

**H6 — Entering on momentum is NOT an edge.** The "long on strong momentum + above MA200h" rule
appeared to work within the dataset. In the 2019-2026 walk-forward: **p=0.244 against random
entries**, equity ×5.59 against **×7.72 for buy and hold**, and +0.966%/trade in BTC bull years
against **−0.322% in bear years**. It is directional beta. It looked like an edge because the
dataset is a single bull cycle.

---

# Traps (read before any new analysis)

**Trap 1 — Traders who hide their losers.** The record shows **closed** positions only. A trader
who never closes a loser looks perfect while accumulating unrealised loss.
**Signature: closed-position win rate ≥95% alongside a high portfolio `mdd`.**
Real examples: GGbond哦 (98.5% hit rate, mdd 50.5%), 无人在稻 (98.9%, payoff 0.39),
Una躺平记_ (**0 losers in 174 closes**, mdd 63.7%), NepNeptune (0 in 43, mdd 42.4%).
**They top any naive ranking.** Filter `closed_win_rate ≤ 92%` and `payoff ≥ 0.5`.

**Trap 2 — ROI and PnL in USD do not measure skill.** The dataset's three best by ROI:
VickyKaushal (**+5,436%** → alpha **−0.72%**, t=−2.88), Omofun (+4,844% → alpha **−1.23%**),
龟兔赛跑985 (+2,382% → **96.9% of its PnL is ONE trade** at 145x). By absolute PnL:
道亦有道 1994 ($551k → alpha +0.11%, t=0.46), 风雪哥 ($207k → alpha −0.16%, top-3 = 93% of the PnL),
geddong ($228k → alpha **−1.50%, t=−12.11**).
**Use de-leveraged alpha against the median of the same symbol×month×side.**

**Trap 3 — Ranking pairs by profitability is circular.** De-leveraged, **188/197 pairs (95%)**
have a positive median return per trader: the dataset is the top-600 by ROI, they win at
everything. The ranking measures survival, not the pair's edge.

**Trap 4 — Aggregating in USD lets account size decide.** SOL: aggregate −32,229 but median per
trader **+21.2**. XRP: −3,966 with a median of **+3.0**. The typical trader won.

**Trap 5 — `mdd` is a percentage, not a fraction** (median 30.2, max 102.7). And Binance's
`win_rate` field is **not** comparable with the win rate of closed positions: it measures a
different window.

**Trap 6 — Survivorship with no control.** Top-600 by 90D ROI. The selection is on recent
performance, which **attenuates** the H1→H2 correlations (working in H1's favour, against any
absolute level).

---

# Operating rules

- ⚠️ **NEVER rename/move/delete this tree while a background scraper is writing.**
  Run `process(list)` first; wait, or kill and relaunch (they are resumable). Incident 2026-08-25:
  a rename with the scraper running → 440 portfolios lost and 45 min of re-scraping. A `cp` does
  not save you: it creates new inodes, and whatever the process writes afterwards dies with the
  original.
- **Do NOT re-scrape by default.** v2 said "re-scrape before any new analysis"; that would destroy
  the reproducible base of `analysis/`. Re-scrape only when you need **new** data, and into a new
  directory. To reproduce what exists: `python3 analysis/flatten.py`.
- **ALWAYS check concentration** before declaring a pair **or a trader** a winner (the SUI/ONDO
  and DugEFresh lessons). Threshold used: top-1 trade < 30% of net PnL.
- **Never rank by ROI or by PnL in USD.** See Trap 2.
- **Never judge a trader on a single pair.** See H1.
- **Always state whether a figure is net or gross**, and which column was used.
- Any rule with expectancy **below 0.10-0.15% of notional is unusable**: fees eat it
  (8 bps round-trip). That is why sub-1h scalps (+0.04%) are not viable.

# Project status

- `analysis/FINDINGS_v2.md` — the full audit, with what holds and what collapses.
- `analysis/RULES.md` — candidate rules for BTCUSDT + the walk-forward result.
- `analysis/TOP5.md` — 5 traders to copy, the consensus of 4 independent analyses, with the rejects.
- **What is missing**: a real forward test on new data (everything above lives in a single regime
  cycle), a validated exit rule, and observing the candidates through a prolonged bear market.
