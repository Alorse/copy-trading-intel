# Top 5 Bybit lead traders to copy — result: ZERO survivors (a valid outcome)

Same methodology as `analysis/TOP5_OKX.md` (the corrected, audited reference) and
`analysis/TOP5_PHEMEX.md`: leave-self-out de-leveraged alpha vs symbol×month×side cell
medians, full Binance hard-filter set, drawdown screen from Bybit's own yield-trend
series. Reproducible: `analysis/bybit_flatten.py` + `analysis/bybit_top5.py` over
`data/bybit_positions.jsonl`.

**On 2026-08-30, no Bybit copy trader in the scraped universe passes every hard filter.**
Filters were NOT relaxed to manufacture a Top 5. This document explains what was
scraped, why the result is zero, and which traders came closest.

## The universe, honestly

- The `dynamic-leader-list` advertises **7,462 leaders**; this first run scraped the
  **top 295 by the list's default order** (first 15 pages).
- **140 of 295 (47%) have `openTradeInfoProtection=1`** — Bybit's history-hiding flag
  (the analogue of Phemex's `showPosition=false` and Bitget's protection). Their
  position history is simply not visible. Counted, skipped terminally.
- **155 traders** yielded **11,409 closed + 532 open positions**, closes spanning
  **2026-05-30 → 2026-08-30** (~3 months, population-level union). Zero scrape errors.
  ⚠️ **Per-trader history is capped at ~100 closed rows by the API** (88 of 155 traders
  sit at exactly 100; e.g. 2Moon shows 669 lifetime transactions vs 100 visible rows) —
  "3-month window" is a population union; per trader it is effectively "their last 100
  trades". More history will NOT accumulate on re-scrape while the cap holds.
  ⚠️ **`orderNetProfitE8` is POSITION-level**, shared across every order row of a
  scaled position, and the disclosed entry/close prices do NOT reconcile per-row with
  pnl (~16% sign flips; both adversarial reviewers measured this). The ranking basis
  is therefore `roi/leverage` (self-consistent, verified to 0.02% against
  pnl/margin), not raw prices.
  Data fingerprint: 11,409 closed / 532 open rows, 155 ok / 140 protected manifest
  entries (verify against `wc -l data/bybit_positions*.jsonl`).
- Selection bias, stated plainly: the 295 scraped are the list's front page, and the
  155 with visible history are a self-selected subset (traders confident enough to
  show their trades). The other ~7,167 listed leaders were not scraped this run.

## Rejection breakdown (155 traders with visible history)

| filter | rejected |
|---|---|
| t<2.5 (alpha not significant) | 46 |
| single-pair only (H1) | 27 |
| sample too small (<15 closed or <8 alpha rows) | 21 |
| concentration >30% (top-1 trade) | 21 |
| payoff <0.5 (left tail) | 18 |
| net-negative closed PnL | 8 |
| median margin <$50 (not copyable) | 6 |
| win rate >92% (Trampa 1) | 3 |
| leverage p90 >25x | 3 |
| alpha H2≤0 | 1 |
| yield-trend drawdown >20% uncovered by window | 1 |
| **survives every filter** | **0** |

46+27+21+21+18+8+6+3+3+1+1 = 155 — every trader accounted for.

## The eight who came closest (independently traced, filter by filter)

These are the top traders by alpha t-statistic on the CURRENT data (basis: roi/leverage;
regenerated post-audit — the pre-audit table's t-values were stale). Each dies on a
different, legitimate filter — which is itself evidence the filter set is doing
distinct work:

| trader | t (self-incl.) | killed by |
|---|---|---|
| safemoneymaker | 8.70 | leverage p90 = 50x |
| 'Slow and steady Banzai!' | 6.53 | payoff 0.42 (left tail) |
| LEVELEIGHT | 5.80 | leverage p90 = 55x |
| POMOGITE Invest Inc. | 5.30 | payoff 0.47 |
| Bullet | 5.16 | leverage p90 100x |
| 随风逐浪 | 5.38* | median margin $31 (<$50, not copyable) |
| BLAC_ROCK | 4.57 | win rate 93% (Trampa 1) |
| GoldenLiner | 4.44 | median margin $3 |

*t-values from the reviewers' independent recomputation on current data; killed-by
attributions verified by both reviewers and the orchestrator. Zero survivors holds on
BOTH bases (raw-price pr and roi/lev pr — re-verified after the basis change).

`sportsman-1` is the instructive case: it passes every closed-position filter cleanly
(t=3.23, H2 positive, moderate leverage, real margins, diversified) and is rejected
**only** by the drawdown screen — Bybit's own 90-day yield-trend series shows a −54%
drawdown that the visible 3-month position window does not cover. That is precisely
the "01014588 lesson" screen doing its job on the first Bybit run.

## Notes specific to this run

- **Open-position guard: untested, not clean.** Bybit's `position/list` exposes open
  positions but no verified unrealized-PnL field; the open-loss hard filter never had
  data to evaluate. Treat Trap 1 coverage as partial (win-rate/payoff/concentration
  only, plus the yield-trend screen which does see equity-level damage).
- **`pnl_usd` = `orderNetProfitE8`/1e8 is NET by field name** but has NOT yet been
  independently reconstructed against gross price return the way OKX/Binance were
  (open item from the scraper docstring). Fees ARE stored separately per row
  (open/close exec fee, funding) so the audit is possible later.
- **Access**: everything is browser-mediated (Akamai TLS-fingerprinting blocks
  curl_cffi from this VPS); scrape cost ~$0.10 of cloud-browser time for 295 traders.

## What would change this result

1. Scraping deeper into the 7,462-leader list (this run: front-page 295 only).
2. A future re-scrape — the protection flag population and the front page both churn.
3. Relaxing filters — explicitly NOT done, and NOT recommended: the near-miss table
   above shows the deaths are risk-profile deaths (leverage tails, uncopyable sizing,
   concentration, hidden drawdown), not methodology artifacts.

**Operational conclusion: do not copy anyone on Bybit today.** If a Bybit allocation
is ever desired, re-run this pipeline after scraping deeper into the leader list.
