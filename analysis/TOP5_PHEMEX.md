# Top 5 Phemex lead traders to copy

Same methodology as `analysis/TOP5_OKX.md` / `analysis/TOP5.md` (Binance), same metric:

```
alpha = de-leveraged price return − median of its cell (symbol × month × side),
        computed EXCLUDING the trader's own rows from that cell (leave-self-out)
```

reproducible with `analysis/phemex_flatten.py` + `analysis/phemex_top5.py` over the
existing `data/positions_all.jsonl` snapshot — **no re-scraping was done for this
report.** `realizedPnl` is Phemex's own field name for **NET of fees** (verified
exactly: `realizedPnl = closedPnl − exchangeFee − fundingFee`, SKILL.md line 32,
re-verified below as an aggregate-level cross-check); it is the field used
everywhere in this analysis.

## The universe, honestly

`data/positions_all.jsonl` holds **196 traders** (192 with ≥1 closed position, 4
with `n_pos: 0`) and **7,467 closed positions total**, all `finished: true` — every
row is a real close, none in flight. Closes span **2025-08-25 → 2026-08-25, a full
13 months**, one continuous slice (no gap), verified directly from `updatedTime`
across all 7,467 rows.

This file is **not** the full public leaderboard. `data/snapshots/2026-08-28/phemex_list.json`
— the separately-scraped `recommend` endpoint response that carries the
`showPosition` visibility flag SKILL.md documents — lists **305 traders total**,
of which **236 (77%) have `showPosition: true`**. Only **182 of those 236** overlap
with a userId present in `positions_all.jsonl` with actual position rows (the two
scrapes are ~3 days apart, so some drift is expected: traders can toggle history
visibility, rotate off the ranking, or the two crawls can simply have covered
different pages of it). A further **10 traders in `positions_all.jsonl`** have no
matching row in the 2026-08-28 list snapshot at all. Net: this dataset is **a
snapshot of a snapshot**, not a controlled census — the traders analyzed below are
whoever had visible history at whichever moment each scrape ran, not a stable
population. Treat every count in this document as "as observed in this file," not
as "true of the current Phemex leaderboard."

Of the 192 traders with positions, **159 have ≥15 closed positions** (this
pipeline's minimum sample-size gate, matching the OKX/Bybit threshold).

## Hard filters applied (identical to OKX/Bybit, plus Phemex-specific notes)

| filter | source | Phemex-specific note |
|---|---|---|
| min 15 closed + min 8 leave-self-out-alpha-eligible positions | shared | — |
| multi-pair only (H1: single-pair estimator reliability ~0.13) | shared | — |
| win rate ≤92% (Trampa 1) | shared | — |
| payoff ≥0.5 (left tail) | shared | — |
| net-negative closed PnL rejects before concentration | shared | — |
| top-1 trade <30% of net PnL (concentration guard) | shared | — |
| t≥2.5 | shared | — |
| second-half alpha (H2) >0 | shared | — |
| leverage p90 ≤25x | shared | **leverage is derived**, not a reported field: `openPositionVal / margin` per row (sanity-checked over all 7,467 rows: p50=10x, p90=51x, p99=101x, max=112x — no outliers, no extra capping needed) |
| median margin per position ≥$50 | shared | — |
| median holding duration ≥30min | shared | — |
| open unrealized loss > 50% of closed PnL | **inapplicable, not skipped** | no open-position data exists for Phemex anywhere in this dataset — see below |
| independent pre-window drawdown screen (>20%, uncovered) | **downgraded to a coarse proxy** | no independent disclosure series exists for Phemex here — see below |

**Open-position guard — genuinely inapplicable, not just missing.** OKX's
`data/okx_open_positions.jsonl` and Bybit's `data/bybit_open_positions.jsonl` have
no Phemex counterpart in this dataset: `positions_all.jsonl` contains only
`finished: true` rows, and no other file in `data/` carries open Phemex positions.
Concretely, this means **Trap 1 (traders who hide losers by never closing them)
has zero direct coverage from this run** — the closed win-rate/payoff filters below
are the *only* defense, and by construction they cannot see a position that is
still open. A trader sitting on a large unrealized loss behind a spotless closed
record would pass every filter here undetected. The report-only `mdd30` field from
the recommend-list snapshot (a portfolio-level max-drawdown-30d, which *would*
reflect an open loss if Phemex computes it that way) is used below wherever a
survivor happens to still be present in that snapshot, but it is a 30-day window
against multi-month closed histories in general — not a substitute, just the best
available scrap.

**Drawdown screen — downgraded to a coarse, self-referential proxy.** OKX's weekly
`pnlRatios[]` and Bybit's `totalYieldRateE4` trend both extend *before* the visible
closed-position window, so they can catch a drawdown the window itself doesn't
cover (the "01014588 lesson"). Phemex has no such independent series in this
dataset. `phemex_top5.monthly_drawdown_proxy()` instead builds each trader's own
cumulative net `realizedPnl` by month **from the same rows already used for
alpha**, and measures the largest peak-to-trough drop as a fraction of the running
peak. This can flag a real realized-money swing *inside* the window, but by
construction it can **never** reveal anything hidden before the window starts — it
is strictly weaker than the OKX/Bybit versions and is reported as such.

## Rejection breakdown (192 traders with ≥1 closed position)

| filter | rejected |
|---|---|
| net-negative closed PnL | 57 |
| sample too small (n<15, or <8 with a defined leave-self-out alpha) | 47 |
| payoff <0.5 | 35 |
| concentration >30% (top-1 trade) | 28 |
| single-pair only (H1) | 17 |
| win rate >92% (Trampa 1) | 5 |
| leverage p90 >25x | 1 |
| no losers on either side | 1 |
| **survives every filter** | **1** |

57 + 47 + 35 + 28 + 17 + 5 + 1 + 1 + 1 = 192 — accounts for every trader with
position data. `t<2.5`, `alpha H2≤0`, `median margin<$50`, `median
duration<30min`, and the drawdown proxy rejected **0** traders each as the first
blocking filter — every trader that would have failed them had already failed an
earlier, cruder check (net-negative PnL and payoff alone eliminate 92 of 191
rejections). That does not make them dead weight: `biglongshort` (t=2.71, wr=66%,
payoff=2.47, $343 net PnL over 50 positions, 11 pairs) clears every other filter
and is caught **only** by leverage p90=36.9x>25x — the single case this run where
the leverage filter is load-bearing rather than redundant.

## Only 1 trader survives every hard filter

This is a much thinner result than OKX's 5 or a typical Binance run, and it is
consistent with what SKILL.md already found about this population before this
report: *"The Phemex crowd loses consistently (expectancy −190 USD/trade)."* Per
the brief, filters were **not** relaxed to manufacture a Top 5 — there is exactly
one trader in this 192-trader, 7,467-position dataset whose de-leveraged,
leave-self-out-benchmarked track record clears every screen.

### The pick: **achilles**

| metric | value |
|---|---|
| n (closed positions) | 50 |
| pairs | 10 (BTCUSDT dominant at 28/50, plus XAGUSDT, XTIUSDT, XAUUSDT, ZECUSDT, MUXUSDT, SPCXUSDT, ETHUSDT, XRPUSDT, SOLUSDT) |
| alpha (leave-self-out) | **+1.11%**, t=3.75 |
| alpha (old, self-inclusive) | +1.09%, t=3.66 — barely moved by the correction |
| alpha H2 (second half) | +0.89% — still positive, trend intact |
| win rate | 74.0% |
| payoff | 3.53 |
| leverage (median / p90) | 22x / 22x |
| median margin | $225 |
| median duration | 15.93h |
| concentration (top-1 trade) | 16.8% |
| window | 2026-07-29 → 2026-08-25 (**~4 weeks**) |
| max single-cell ownership share | 44.4% (below the 40% *flag* threshold... just over it — one of ten pairs' benchmark cell is nearly half achilles' own volume) |
| monthly drawdown proxy | 0.0% (monotonic, no proxy drawdown detected) |
| recommend-list cross-check (2026-08-28 snapshot) | `mdd30`=17.9%, `pnl30`=$1,168.63, `roi30`=61.5%, `wr30`=67.2%, `aum`=$0, `followers`=4 |

**Internal consistency cross-check** (no external headline PnL exists per trader in
`positions_all.jsonl` itself, so this checks the field-level identity SKILL.md
verified holds at the aggregate level too): `sum(realizedPnl) = $1,122.01` vs
`sum(closedPnl − exchangeFee − fundingFee) = $1,122.01` — **exact match (1.0000×)**,
as expected from a verified per-row identity.

**Opportunistic cross-check against the recommend-list snapshot:** achilles'
visible window (2026-07-29 → 2026-08-25) happens to be almost exactly the
recommend list's trailing 30-day window (scraped 2026-08-28), so `pnl30` ($1,168.63)
is roughly comparable to the closed-window sum computed here ($1,122.01) — **within
4%**, a genuine (if coincidental) agreement, unlike OKX/Bybit's cross-checks which
generally cover mismatched windows.

**Why this pick, and why to stay cautious about it:**
- The alpha barely moved between the self-inclusive and leave-self-out corrections
  (+1.09%→+1.11%), meaning this trader's edge is not an artifact of dominating a
  thin benchmark cell — except in the BTCUSDT cell specifically, where the 44.4%
  ownership share means roughly half the "other trader" evidence backing that one
  cell's alpha is thin. Across the other 9 pairs the picture is more independently
  verified.
- Payoff of 3.53 with a 74% win rate (not the suspicious ≥92% "hides losers"
  region) is a healthy combination — wins are both frequent and large relative to
  losses.
- **Caveats, not hidden:** `aum=$0` and `followers=4` (per the recommend-list
  snapshot) — essentially no one is currently copying this account and it reports
  zero self-funded capital, both signals this is a small, thinly-observed track
  record, not a proven copy-trading product. The visible window is **4 weeks**,
  the shortest kind of evidence this pipeline accepts (it clears the 15-position /
  8-alpha-eligible minimums, nothing more). `mdd30=17.9%` is below the 20% Trap 1
  threshold but not far below it, and it is a 30-day figure being read against a
  window that is itself ~30 days — there is no independent longer-history check
  behind it (see "open-position guard" above).
- **This is one trader, not five.** Suggested allocation: 100% of whatever weight
  this report's own audit assigns to "Phemex," and treat it as provisional —
  re-run this pipeline as more history accumulates for `achilles` (or for anyone
  else, since the population and visibility both shift between scrapes) before
  increasing confidence.

## Rejected despite high alpha or high PnL (Trap 2 — never rank by PnL/ROI)

**PhemexRwoVXg** — the highest raw PnL in the sample-size-eligible population
(**$42,661** over 50 positions, 8 pairs), and the corrected leave-self-out alpha is
**negative**: **−2.20%, t=−1.78**. Concentration is **127.7%** — the single best
trade alone exceeds the account's *entire* net PnL, meaning every other position
nets to a loss underneath it. Only 5 of 50 positions retain a defined leave-self-out
alpha (most sit in benchmark cells this trader dominates alone) — this account is
a single lucky trade wearing a large-PnL headline, the exact pattern Trap 2 warns
against.

**PhemexlcRAIXjPGj** — second-highest raw PnL ($40,265 over 50 positions), but
**single-pair only** (BTCUSDT, its actual rejection bucket) with concentration
**166.9%** — again, the top trade alone exceeds total net PnL. Same instance
opened this report's first data preview (see `phemex_flatten.py`'s docstring
example): a −$19,131/+$8,933/−$17,926/+$34,228/−$2,950 sequence of large BTC
swings, not a repeatable edge.

**DugEFresh** — the skill's own named XRP-concentration exhibit (see below):
**$33,790 PnL, but corrected alpha is essentially flat-to-negative (−0.09%,
t=−0.20)**. High PnL, no real skill once benchmarked properly.

**CryptoBoss** — the highest de-leveraged alpha among sample-eligible traders at
**+20.57% (t=3.96)**, 44 pairs — and still a **hard reject**: net closed PnL is
**−$8,371** and leverage p90 is **68x**. A trader can show a genuine positive
price-return edge over peers and still lose real money once fees, leverage, and
losing-side sizing are accounted for; alpha alone is not "would have made money."

**PhemexTmsyChOcUopITikFqKVazJjyfcEfVO** — alpha **+8.38%, t=3.72** (would clear
the t and alpha-H2 filters) but net closed PnL is **−$614,168**, the worst loss in
the dataset by a wide margin (next-worst is −$73,529) — rejected on net-negative
PnL alone. By far the largest reminder in this dataset that a positive de-leveraged
alpha measures being *right more often on a price-return basis*, not "safe to
copy with real capital": whatever sizing or leverage pattern produced this loss
overwhelms a genuinely positive alpha signal.

## The Trampa 1 signature — partially reproducible in this snapshot

SKILL.md names five Phemex "hides losers" exhibits: **DugEFresh** (cited there for
XRP concentration, not Trap 1), **GGbond哦**, **无人在稻**, **Una躺平记_**, and
**NepNeptune** (all four cited for Trap 1: high closed win rate alongside a high
portfolio `mdd`).

**Verified: only DugEFresh is present in this dataset.** A direct nick lookup
against all 196 traders in `positions_all.jsonl`, and separately against the 305
traders in `data/snapshots/2026-08-28/phemex_list.json`, and separately against
both files in `data/snapshots/2026-08-25/`, found **zero matches** for GGbond哦,
无人在稻, Una躺平记_, or NepNeptune in any of them. These four must come from a
different (likely earlier, and possibly larger) Phemex crawl than the one behind
`positions_all.jsonl` — they are referenced in `analysis/TOP5.md`, a document that
predates this dataset's current 192/196-trader form. **Their signatures cannot be
reproduced from the data this report was run over; this is stated rather than
fabricated.**

**DugEFresh's own signature, re-verified against this dataset:** 50 closed
positions across 11 pairs, total net PnL **$33,790.02**. Trading XRPUSDT alone
accounts for **$34,738.99 — 102.8% of the total** (every non-XRP position nets to
a loss underneath it), and the single best trade (XRP, +$16,341.57) is **48.4%**
of total net PnL by itself. Zoomed out to the whole dataset: **64 traders traded
XRPUSDT** in this snapshot, for a combined net PnL of **$38,063.15** — and
**DugEFresh alone accounts for $34,738.99 of it, 91.3%** — an exact match to
SKILL.md's own cited figure ("DugEFresh = 91.3% of the PnL; ... 27/64 win"),
confirming this dataset is the same one that finding was drawn from.

**A live, current-dataset illustration of the same Trap 1 mechanism** (high win
rate ≠ safe, and a high t-statistic doesn't fix it): among the 5 Phemex traders
with ≥15 closed positions and a closed win rate above 92% in this snapshot,
**PhemexxKiTwYCgMNlmtZWfUpNhTWepFHw** shows the **highest t-statistic of any
trader in the entire dataset (t=12.09, alpha +7.47%)** — a number that would beat
every other candidate on a naive "rank by t" basis — yet fails outright: win rate
96.0%, payoff **0.20** (losses are 5× the size of wins on average), leverage p90
**95x**, and net closed PnL is **−$649**. A large, statistically confident alpha
measured on a "wins small and often, loses catastrophically and rarely" return
distribution is exactly the shape Trap 1 warns about — and here it produces the
single highest t-statistic in the population, not the lowest.

Of the other 4 traders with ≥15 positions and win rate >92%: **Wolfi** (94.0%,
payoff 0.18, net PnL **−$3,350**), **PhemexgzAeXky** (94.0%, payoff 0.11, net PnL
**−$2,386**), **cremebean** (94.1%, payoff 0.37, net PnL +$316, n=17 — smallest
sample of the five), and **EagleTrader** (96.0%, payoff 1.23, net PnL **+$2,563**,
`mdd30`=6.3% — the one exception that is both high-win-rate *and* profitable *and*
low-drawdown by the recommend-list proxy, though it is separately rejected here on
leverage p90=99.5x). Four of these five combine a high win rate with a **losing**
account — on this dataset, "closed win rate >92%" is less often "hiding a future
loss" and more directly "already losing on a small-loss/frequent-win asymmetry,"
which the `payoff≥0.5` filter catches before any drawdown signal is even needed.

## Confidence: low

- **Exactly one survivor**, on a 4-week window, from a population SKILL.md already
  characterized as losing on average. This is the honest output of the
  methodology on this population, not a result to treat as five separate
  independent bets the way OKX's picks were.
- **The open-position guard is not implemented, it is absent** — this dataset
  cannot support it. Trap 1 coverage rests entirely on closed win-rate/payoff and
  a report-only 30-day `mdd` proxy that doesn't even apply to most of the
  population (only 182 of 192 traders with positions appear in the recommend-list
  snapshot at all).
- **The drawdown screen is a coarse, self-referential proxy** — it cannot catch
  anything hidden before the visible window starts, unlike the OKX/Bybit versions.
- **13 months of closes (2025-08 → 2026-08), longer than the Binance/OKX windows
  audited elsewhere in this repo, but still a single scrape's worth of survivors** —
  no control group, no re-scrape comparison, and (per the universe section above)
  the population itself is not stable between the two nearby snapshots this report
  draws on.
- **Leverage is derived** (`openPositionVal / margin`), not a field Phemex reports
  directly on closed positions — sanity-checked for outliers, but still a
  computed quantity, one more link in the chain than OKX's/Bybit's own leverage
  fields.
- **`achilles` reports `aum=$0` and `followers=4`** in the recommend-list
  snapshot — essentially unobserved by real copiers. Passing every numeric filter
  is not the same claim as "a proven copy-trading product."

**Suggested operation:** copy `achilles` at whatever fraction of book this
pipeline's overall Phemex allocation calls for, and re-run this exact pipeline
(no re-scrape needed beyond a fresh `positions_all.jsonl` and recommend-list pull)
before increasing weight — 4 weeks of visible history is the minimum this
methodology accepts, not a track record to size confidently against yet.
