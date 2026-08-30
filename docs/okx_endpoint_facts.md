# OKX endpoint facts (verified live by Ramona, 2026-08-29 ~20:50)

- Ranking universe: SWAP lead traders = **261 total** (last page with data = 27, first empty = 28; 10/page).
- `public-subpositions-history`: NO pagination params work (tried page, limit, before,
  subPosIdAfter — all return identical 58 rows for the busiest trader probed). Fixed window
  cap (~58 most-recent positions). In analysis: check openTime distribution of those rows
  to estimate how far back the visible window reaches per trader, and say so in TOP5_OKX.md.
- `uniqueCode` IS present in `ranks[]` entries of public-lead-traders.
- `public-stats` REQUIRES `lastDays` param (e.g. lastDays=90).
- All responses: code is STRING "0" on success.

## Correction + additions (verified live, same day, second pass — full-universe probe)

- **The 100-row cap, not 58.** Probing `public-subpositions-history` for all 10 traders on
  ranking page 1 (plus a handful more): 3 of them return **exactly 100 rows**, others return
  fewer (17, 26, 56, 58...). 58 was that one trader's true total, not a cap. Re-confirmed no
  page/limit/before/after/subPosId param changes the result on a 100-row trader. The real
  cap is **100**, and it silently truncates history for any trader with more than 100
  closed+still-open sub-positions in the window OKX serves.
- **`public-current-subpositions?uniqueCode=<code>`** (open positions): same shape family,
  same apparent 100-row cap observed once (one trader returned exactly 100). Rows carry
  `upl`/`uplRatio` (unrealized PnL) and `markPx`, no fee field.
- **Some rows in `public-subpositions-history` have `closeTime == ""`.** These are NOT
  closed positions — they are a realized-PnL event on a sub-position lot that is still
  open (partial close / funding settlement). Must be filtered out of "closed" and folded
  into the open-positions view instead; `scrape_okx_positions.py` does this.
- **`{"code":"60004","msg":"Trader doesn't exist"}`**: first seen on 2 of ~30 uniqueCodes
  probed (`97AA186B7559E35E`, `FF48C5939FE6119F`), on BOTH `public-subpositions-history`
  and `public-current-subpositions`, while `public-stats` for the same uniqueCode works
  fine. **Full-universe run (261 traders): 79 (30%) return this on both endpoints.** Of
  the remaining 182, 40 return `code:"0"` with zero closed positions (nothing to show, not
  an error) and 142 have at least one closed position. Treat 60004 as terminal/non-retryable
  per trader, not a scrape failure.
- **The 100-row cap bites often in practice**: 36 of the 142 traders with closed history
  (25%) return exactly 100 rows — a real, non-rare truncation, not an edge case.
- **`public-stats?lastDays=N` only accepts N in {1, 2, 3}**, with or without `instType=SWAP`
  alongside it. 7, 30, 90 and 180 all return `{"code":"51000","msg":"Parameter lastDays
  error"}`. The "e.g. lastDays=90" example above does not work; `scrape_okx.py` already
  uses `lastDays=3` (the max of the three).
- **NET vs GROSS: `pnl` on `public-subpositions-history` is NET of fees.** Reconstructed
  gross price PnL as `subPos × ctVal × (closeAvgPx − openAvgPx) × side` (ctVal pulled from
  `/api/v5/public/instruments?instType=SWAP&instId=<id>`, e.g. 0.01 for BTC-USDT-SWAP) and
  diffed against the reported `pnl` over 558 closed BTC-USDT-SWAP rows across the first 5
  ranking pages: residual is positive (gross > net) in 96.6% of rows, median 6.5 bps of
  notional — same order of magnitude as Binance's 7.85 bps.
