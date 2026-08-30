# Top 5 Bitget lead traders to copy — result: ZERO survivors (a valid outcome)

Same methodology as `analysis/TOP5_OKX.md` / `analysis/TOP5_BYBIT.md` / `analysis/TOP5_PHEMEX.md`:
leave-self-out de-leveraged alpha vs symbol×month×side cell medians, full Binance
hard-filter set, a drawdown screen built from the exchange's own disclosed series.
Reproducible: `analysis/bitget_flatten.py` + `analysis/bitget_top5.py` over
`data/bitget_positions.jsonl`.

**On 2026-08-30, no Bitget copy trader in the scraped universe passes every hard
filter — including the one trader that survived a first, since-corrected pass of this
pipeline.** Filters were NOT relaxed to manufacture a Top 5. This document explains
what was scraped, the adversarial-audit corrections applied, and why the corrected
result is zero.

## The universe, honestly

- The leaderboard advertises **1,488 traders** live (`maxShowSizes`; `data.totals`
  lies — it echoes the page size). This run targeted the **top 400 by follower
  count**.
- **399/400 resolved** to a terminal `ok` manifest status; **1** (`b0b1467287b43955ad94`)
  is still stuck in `error` after repeated transport timeouts and was NOT repaired
  in this pass (out of the audit's named scope — see "What would change this
  result"). **0/399 (0%) show a protection flag on `historyList`** — unlike
  `currentList` (open positions), where **99/399 (24.8%)** ARE protected
  (`code 30066`) despite their closed history staying fully visible; the two
  protections are independent, confirming the module docstring's earlier ~35%
  40-trader sample at full-universe scale.
- **290 of the 399** have at least one closed position and reach the ranking
  funnel; **40,516 closed rows** total. Of those 290, **4 required a data repair**
  (see below) before they could be ranked at all.
- ⚠️ **The four repaired traders' `n_closed` figures look capped**: Low-Risk-Collat-Mgmt
  sits at exactly **2,000** rows — the checklist's documented 2,000-row
  `historyList` cap for hand-fetched pulls (this pipeline's own `paginate_history`
  has no such cap when it drives the pagination itself; the cap applies to the
  out-of-band fetch that produced these four traders' raw rows, not to the API's
  per-page pagination in general). Treat any of the four with `n_closed` near 2,000
  as a truncated, not complete, history.
- Data fingerprint: 40,516 closed / 2,013 open rows across 399 `ok` manifest
  entries, 0 `protected`. SHA-256 of the working data files (`data/*.jsonl`,
  `analysis/bitget_positions.csv`) as of this run:

  ```
  cc1c99e9228ceb2baea3c36610a7411edf13215f405122a32c8db7edbdb57807  data/bitget_positions.jsonl
  ed9d6f5136d25fefcb58ed807e96ecbbf83649f975d69e0839bf2ec399cdd541  data/bitget_manifest.jsonl
  792bceed5aa540cfd7d7f1db87781114b1b97403ff8e5e0a2410895a4458d474  data/bitget_cycle.jsonl
  c9fa7faa38a6f5803465247ceb6379a209845187c1664b0e910077dc4a093ed7  data/bitget_traders.jsonl
  98173854a5af0e0a3d47fcf1bd0797c4af1d38feaf613a44cdb2f04a6de60962  analysis/bitget_positions.csv
  ```

## Data-repair story: four traders were hand-fetched, and wrongly (Fable-2 / GLM-1)

Four traders (`bfb147758db13f57a294` Low-Risk-Collat-Mgmt, `bdb0467e8cb03a56a592`
kitawaraison, `b9b74e718db43155a093` 0xice, `bfb2487786b33f50ad97` TomFält) got stuck
on repeated `historyList` transport timeouts under the scraper's original bug (see
"Scraper hardening" below) and were hand-fetched straight from the API instead of
through `row_from_history`. Their rows in `data/bitget_positions.jsonl` carried the
**raw API shape**: `position` (1/0) instead of `side`, `returnRate` as a **PERCENT
string** (`"558"` == 558%, not 5.58 — the exact percent-encoding trap now covered by
a regression test), numeric fields as strings, and extra `teacherName`/`hm` keys a
normalized row never has.

`scripts/bitget_repair_raw_rows.py` (one-shot, idempotent) normalizes these in place
by **reusing** `scrape_bitget_positions.row_from_history` (never reimplementing the
coercion), dedups `(trader_uid, order_no)` collisions with "shaped row always wins,"
then backfills the missing `cycleData`/`currentList`/`traderDetailPageV2` for these
four via the (now-fixed) scraper functions and appends `ok` manifest entries. Result:
**0 raw rows remain**; all four are now ranked normally and **all four still reject
on their own merits**, exactly as predicted before the fix:

| trader | n | killed by |
|---|---|---|
| Low-Risk-Collat-Mgmt | 2,000 | t=10.12 (would pass!) but median margin **$0.67** ≪ $50 — toy-sized bets, not copyable |
| kitawaraison | 820 | net-negative closed PnL (−$671.73) |
| 0xice | 260 | t=−1.11 (no significant alpha) |
| TomFält | 4 | sample too small (n<15) |

**The repair changed nothing about the final answer** — confirming the audit's own
prediction that the repair was a correctness fix, not a roster change.

## The drawdown-screen correction (GLM-2 / Fable-1) — the actual audit finding that mattered

The original `drawdown_screen` took `min()` of the raw CUMULATIVE `roiRows` curve.
That measures "how far below zero the curve ever got," not a drawdown. Re-scored
against the current 290-trader population:

| measure | count |
|---|---|
| OLD screen would have hard-rejected (min < −20%, uncovered) | **7 / 290** |
| TRUE peak-to-trough drawdown > 20pp on the same series (any coverage) | **199 / 290** |
| ...of which actually uncovered by the trader's own closed-position window | 5 / 290 |
| `native_mdd` (Bitget's own `statisticsDTO.maxRetracement`, same 90d window) > 20% | 214 / 290 |
| `detail_mdd` (lifetime) > 20% AND closed span > the 90d cycle window | 114 / 290 |

The old screen was catching **7** where a real peak-to-trough measurement finds
**199** — the exact GLM-2/Fable-1 finding, reproduced on this exchange's own data.
Fixed:

1. **Screen 1 — peak-to-trough of `roiRows`, 90d window.** `computed_mdd_pct`'s
   formula (previously report-only) is now the actual walk `drawdown_screen`
   performs; rejects a >20pp drop the trader's own visible window doesn't cover. A
   **missing series now REJECTS** (`covered=False`) instead of silently passing
   (`covered=True`, the old default) — a trader with no drawdown data used to be
   treated as pre-verified clean.
2. **Screen 2 — `native_mdd_pct`, same 90d window.** Bitget's own MDD figure for the
   identical series; simple `>20%` reject, no coverage clause needed (same window as
   screen 1).
3. **Screen 3 — `detail_mdd`, lifetime, uncovered case only.** `traderDetailPageV2`'s
   `max_retracement` is an all-time figure. Empirically pinning its semantics:
   fetching `cycleData` at `cycleTime=180` for a 36-trader sample and computing ITS
   OWN peak-to-trough gave values in the **hundreds to thousands** of percentage
   points (unbounded cumulative-ROI compounding under leverage — e.g. the eventual
   survivor's 180d curve peak-to-trough came out at **4,634pp**), while `detail_mdd`
   for the same traders sat in the **tens to low hundreds** (survivor: 45.07%). This
   is not a window difference — it's a different metric, almost certainly
   equity/AUM-based rather than ROI-curve-based, and the two cannot be reconciled by
   picking a longer window. Given that ambiguity, the checklist's OKX-precedent
   fallback applies: reject when `detail_mdd > 20%` AND the trader's own closed-
   position span exceeds the 90d cycle window — i.e. only when the visible history
   plausibly extends further back than what `cycleData` covers.

### The survivor that didn't survive: 带我一个

The pipeline's first pass (pre-audit) produced exactly one survivor, **带我一个**
(`bbb0477e8eb53a5fa392`, n=18, t=2.54, alpha_H2=+1.20%). Re-run under the corrected
screens:

| metric | window | value | verdict |
|---|---|---|---|
| peak-to-trough drawdown | 90d cycleData | 10.4pp | ✅ passes (< 20pp) |
| `native_mdd` | 90d cycleData | 11.2% | ✅ passes (< 20%) |
| `detail_mdd` | lifetime | **45.07%** | ❌ **> 20%** |
| closed-position span | — | **297 days** | uncovers the 90d cycle window |

**Killed by: `detail_mdd=45.1%>20%, uncovered (span 297d>90d)`.** Both 90d-windowed
metrics (screens 1 and 2) look clean specifically BECAUSE this trader's damage
happened outside the 90-day window `cycleData` covers — exactly why the lifetime
`detail_mdd` check exists. Consistent with this: the trader's own alpha is
front-loaded (H1 vs H2 split inside the 18-row sample: full-sample alpha 4.47% but
`alpha_H2` only 1.20%), i.e. its edge decayed within even the SHORT window we can
see, well before the lifetime drawdown the 90d metrics can't see at all. This is the
Bitget-specific instance of the "01014588 lesson" (OKX's uncovered-drawdown rule),
generalized to a metric whose scale can't otherwise be reconciled with the tested
window.

The captured-but-previously-ignored number here is the headline: `detail_mdd` was
fetched into the manifest for all 399 traders from the very first scrape and printed
in a cross-check line — but never enforced. It sat there the whole time.

## Rejection breakdown (290 traders reaching the ranking funnel)

| filter | rejected |
|---|---|
| sample too small (<15 closed or <8 alpha rows) | 93 |
| concentration >30% (top-1 position, order-aggregated) | 53 |
| net-negative closed PnL | 45 |
| single-pair only (H1) | 33 |
| payoff <0.5 (left tail) | 28 |
| t<2.5 (alpha not significant) | 14 |
| win rate >92% (Trampa 1) | 13 |
| no losers on either side (Trampa 1) | 6 |
| median margin <$50 (not copyable) | 3 |
| leverage p90 >25x | 1 |
| `detail_mdd` (lifetime) >20%, uncovered (closed span >90d) | 1 |
| **survives every filter** | **0** |

93+53+45+33+28+14+13+6+3+1+1 = 290 — every trader accounted for. Note the new
drawdown screens (peak-to-trough uncovered, native MDD) show **zero** rejections
here even though the table above shows 199/290 and 214/290 respectively would fail
them in isolation — every one of those traders was already rejected by an earlier
filter (win rate, payoff, concentration, t-stat...) before reaching the drawdown
check. Only 带我一个 survived far enough to be caught by a drawdown screen at all,
and it was the lifetime `detail_mdd` rule — not the two 90d-windowed ones — that
caught it.

## The ten closest, independently traced

Ranked by alpha t-statistic (self-included basis), each dies on a different,
legitimate filter:

| trader | n | t | killed by |
|---|---|---|---|
| LongShort_SmartDCA | 1,980 | 36.35 | win rate 95%>92% (Trampa 1) |
| muhammadali874 | 260 | 16.46 | net-negative closed PnL |
| 定投哥 | 236 | 14.41 | win rate 94%>92% (Trampa 1) |
| FourK—欧阳静松 | 196 | 13.07 | leverage p90=40x>25x |
| LuRo | 61 | 10.24 | win rate 95%>92% (Trampa 1) |
| Low-Risk-Collat-Mgmt † | 2,000 | 10.12 | median margin $0.67<$50 |
| -ZNUWKB6H49990 | 91 | 5.94 | win rate 99%>92% (Trampa 1) |
| Octagon | 399 | 5.73 | concentration 46%>30% |
| SpotAcademy | 33 | 5.59 | win rate 94%>92% (Trampa 1) |
| InfliacijusTaupys | 394 | 5.12 | median margin $6.08<$50 |

† one of the four data-repaired traders (see above).

Six of the top ten die on win-rate>92% (Trampa 1) alone — the single clearest signal
in this universe is that the traders with the loudest apparent alpha are the ones
hiding their losers.

## Trampa exhibits (real, this run)

- **Trampa 1 (hidden losers).** `LongShort_SmartDCA`: t=36.35, wr=95.1%, but
  `native_mdd`=111.9% and `detail_mdd`=202.8% — the highest apparent alpha in the
  entire universe belongs to a trader whose own disclosed drawdown exceeds 100% of
  peak equity (i.e. leverage/compounding artifacts big enough to imply near-total
  wipeouts along the way). Textbook Trampa 1 signature: near-spotless win rate paired
  with catastrophic disclosed drawdown.
- **Trampa 2 (t-stat / PnL ≠ skill).** `muhammadali874`: t=16.46 (would rank #2 on
  raw significance) but net-negative overall — a large, statistically "significant"
  alpha computed leave-self-out can still sit on top of a trader who lost money
  lifetime, because alpha measures relative skill against the symbol×month×side
  median, not absolute profitability.
- **Trampa 5 analogue (percent vs fraction).** The four repaired traders' raw rows
  carried `returnRate` as a bare percent number (`"558"`) that a naive `/100` skip
  would have silently treated as a 55,800% return instead of 558% — exactly the
  Binance `mdd`-is-percent trap, replicated on a different field and a different
  exchange. Caught here by reusing `row_from_history`'s own division, not
  reimplementing it.

## Cross-checks, with explicit window labels

- **Leaderboard `total_pnl` is NOT lifetime** (GLM finding, re-verified here): across
  261 traders with both a leaderboard `total_pnl` and a 90d `cycleData` cumulative-
  pnl curve, `total_pnl` sits closer to the **90d curve's endpoint** (median ratio
  0.77, 16.9% of traders within 5%) than to the **lifetime `sum(net_profit)`** over
  every scraped closed row (median ratio 0.62, 9.5% within 5%). Neither is an exact
  match — treat `total_pnl` as "roughly 90d," and never cite the computed/headline
  ratio as a red flag on its own until a tighter basis is found. (For 带我一个
  specifically: computed lifetime $793.39 vs headline $95.68, ratio 8.29x — a large
  gap, but per the above, not diagnostic on its own; this trader's degenerate
  `followCount=0`/`aum=0` state likely makes even the 90d figure unreliable.)
- **`total_income`** (`traderDetailPageV2`'s `itemVoList` `income` column, "Total
  profit," lifetime USD) is now captured in `detail_summary` — previously this
  number existed nowhere in the repo despite being fetched from a live endpoint.
- **MDD, three bases, one trader (带我一个):** native_mdd(90d)=11.2%,
  computed_p2t(90d)=10.4pp, detail_mdd(lifetime)=45.07% — a **34.7pp gap** between
  the lifetime figure and the 90d peak-to-trough. Across the broader 395-trader
  manifest population (all traders with both a `detail_mdd` and a 90d cycle series,
  independent of ranking-funnel status): **362/395 (91.6%)** have `detail_mdd` >
  their 90d computed peak-to-trough, median gap **~74pp** — the two bases disagree
  almost universally, at a scale far too large to be explained by the window
  difference alone (see the 180d empirical check above).

## Scraper hardening (Fable-5)

`session.post`'s transport call used to sit outside `make_post_fn`'s retry loop: a
single 20s timeout raised straight through `paginate_history`, discarding every page
already fetched for that trader, and the manifest's `error` status made a resumed run
restart from page 1 into the same slow path — the mechanism that produced the four
raw-shape traders in the first place. Now caught and retried with backoff *inside*
`make_post_fn`, and `historyList`'s timeout raised from 20s to 30s (its own known
slowest endpoint). One trader (`b0b1467287b43955ad94`) is still stuck in `error` as
of this run — a future re-scrape, now protected by this fix, should resolve it.

## What would change this result

1. Re-scraping the remaining ~1,088 leaderboard traders beyond this run's top-400
   cutoff.
2. Resolving the one still-erroring trader (`b0b1467287b43955ad94`), now that the
   transport-retry bug that produced this whole repair episode is fixed.
3. Relaxing filters — explicitly NOT done, and NOT recommended: six of the ten
   closest traders die on win-rate>92% (Trampa 1) alone, and the one trader that
   passed every OTHER filter died on a lifetime drawdown figure sitting entirely
   outside the window this pipeline can otherwise see.

**Operational conclusion: do not copy anyone on Bitget today.** If a Bitget
allocation is ever desired, re-run this pipeline after scraping deeper into the
leaderboard and resolving the one outstanding scrape error.
