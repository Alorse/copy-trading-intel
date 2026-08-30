# Top 5 OKX lead traders to copy

Same methodology as `analysis/TOP5.md` (Binance), same metric:

```
alpha = de-leveraged price return − median of its cell (symbol × month × side),
        computed EXCLUDING the trader's own rows from that cell (leave-self-out)
```

reproducible with `analysis/okx_flatten.py` + `analysis/okx_top5.py` over
`data/okx_positions.jsonl`. **`pnl` is NET of fees** (verified: reconstructing gross price
PnL from `ctVal` and diffing against the reported `pnl` over 558 closed BTC-USDT-SWAP rows
shows a positive fee residual — gross above net — in 96.6% of rows, median 6.5 bps of
notional; see `docs/okx_endpoint_facts.md` and `scripts/scrape_okx_positions.py`'s docstring).

## Adversarial audit corrections applied 2026-08-29

Two independent adversarial reviews of the first version of this pipeline (filters, alpha
computation, and the scraper's cap accounting) surfaced real defects. All corrections were
applied and the whole pipeline was re-run over the same local data (no re-scraping) — the Top
5 below is the corrected result, not the original one with caveats bolted on.

- **The "01014588 lesson": a hidden historical drawdown behind a pristine recent window.**
  `01014588`'s visible 100-closed-position window (2026-07-23 → 2026-08-29) shows +$89,364,
  wr=77%, 18 pairs — it was the original #2 pick. But `data/okx_traders.jsonl`'s disclosed
  weekly `pnlRatios[]` for this account bottoms out at **−40.95%** in the week of 2026-06-05 —
  *seven weeks before the visible window even starts*. Our own sample of this trader's trading
  never saw that drawdown; it was invisible to every filter that only looks at closed
  positions. New hard screen: reject any trader whose weekly `pnlRatios[]` shows a drawdown
  deeper than −20% that the visible closed-position window doesn't cover (window start ≤
  drawdown's deepest week = covered/safe; window start > drawdown's deepest week = hidden/
  reject). `01014588` fails this outright, and independently fails the corrected t-statistic
  too (see below) — its headline ranking `pnl` ($5,019 lifetime) vs. the $89,364 computed from
  the visible window (17.8×) is the same story from a third angle: most of this account's
  lifetime was underwater, and the 5 recent weeks we can see are not representative.
- **Self-inclusive alpha inflation (and occasionally deflation).** The original `compute_alpha`
  benchmarked each trader's positions against a symbol×month×side median that *included the
  trader's own rows*. For any trader who accounts for a large share of a benchmark cell, this
  either flatters them (their own winning trades pull the "market" median toward their own
  return, making mediocre performance look average) or — as it turns out, just as often —
  understates them (if a trader with a genuine edge dominates a cell, their own good trades
  drag the benchmark up, shrinking their measured alpha against a "market" that is mostly
  themselves). `compute_alpha` now measures each trader's alpha against the cell median
  **excluding their own rows** (leave-self-out); a cell with no other trader's rows at all is
  dropped for that trader (not treated as zero alpha). Both the old and new alpha/t are
  reported below so the shift is visible per trader, and each survivor's max single-cell
  ownership share is reported (>40% flagged, not hard-rejected — thin "leave-self-out"
  evidence is a real caveat, not by itself disqualifying).
- **The 100-row cap miscount.** The scraper flagged `closed_capped` off `len(closed) >= 100`.
  OKX's cap actually applies to the raw history *response* (closed + still-open-from-history
  rows combined), not the closed subset. Recomputed offline (`--recompute-caps`, no re-scrape):
  **37 of 142 traders (26%) are capped**, not 36 (25%) — one additional trader (`Kunpeng Plan`,
  97 closed + 3 still-open = 100 raw rows) was previously mis-flagged as uncapped. See
  `docs/okx_endpoint_facts.md`.
- **Binance's reference hard filters (`top5_final.py:48-56`) are now enforced in full**:
  `t≥2.5` (was 1.5), second-half alpha (`H2`) `>0`, leverage p90 ≤25x, median margin ≥$50,
  median holding duration ≥30min. All four of the previous picks whose weaknesses were only
  narrated in prose (`Powerful-Bubble-Rims` 100x leverage, `Monumental-DoS-Tiger` 100x
  leverage, `Cheap-Producer-Shrew` 50x leverage) now fail these as **hard** rejections instead
  of soft demotions.
- **Net-negative closed PnL is its own rejection bucket**, checked before the concentration
  guard — previously a trader with `total_pnl <= 0` fell through to the concentration check via
  a `999` sentinel score and was silently counted as a "concentration" rejection even when
  concentration wasn't the real problem.
- **The open-unrealized-loss hard filter uses net `upl_sum`** (matching this doc's own prose,
  which always described it as a net figure) instead of `upl_neg_sum` (sum of losing legs
  only, ignoring any offsetting open gains). `upl_neg_sum` is now only a soft flag
  (`hidden_loss_flag`).
- **The headline-vs-computed PnL cross-check is now printed for every survivor, unconditionally**
  — the previous version of this doc only quoted the cross-check for the picks where it was
  flattering (Mine13's 1.5% gap). See the picks table below; two of the five current survivors
  have cross-check ratios that should worry you (`Kunpeng Plan` at 0.003×, `BestMax` at 0.20×).

## The universe, honestly

**261 SWAP lead traders total** (measured 2026-08-29, 27 ranking pages × 10/page — an order
of magnitude smaller than Binance's ~600). Of those:

- **79 (30%)** return `{"code":"60004","msg":"Trader doesn't exist"}` on both position
  endpoints, despite ranking and `public-stats` working for the same `uniqueCode`. Their
  position history is simply not obtainable via this API.
- **40** return zero closed positions (nothing traded, or a genuinely empty window).
- **142** have at least one closed position — **8,936 closed positions** total, spanning
  **2026-05-29 to 2026-08-30** (~3 months, one continuous slice, no wider than the Binance
  audit's own single-regime-cycle caveat). **110 of the 142** clear the 15-position minimum
  sample size before any other filter applies.
- **37 of those 142 (26%)** hit OKX's **silent 100-row cap** on `public-subpositions-history`
  (recomputed count post-audit — see "corrections" above). Their true track record is longer
  than what's visible; treat their sample as a recent tail, not a full history.

Hard filters applied (Binance's `top5_final.py` reference filters, adopted in full 2026-08-29,
plus OKX-specific additions):

| filter | source |
|---|---|
| min 15 closed + min 8 leave-self-out-alpha-eligible positions | OKX-specific (smaller universe) |
| multi-pair only (H1: single-pair estimator reliability ~0.13) | OKX-specific |
| win rate ≤92% (Trampa 1) | shared |
| payoff ≥0.5 (left tail) | shared |
| **net-negative closed PnL rejects before concentration is even computed** | corrected 2026-08-29 |
| top-1 trade <30% of net PnL (concentration guard) | shared |
| **open unrealized loss (net `upl_sum`) worse than −50% of closed PnL** | OKX-specific, corrected to use net 2026-08-29 |
| **t≥2.5** (was 1.5) | adopted from Binance 2026-08-29 |
| **second-half alpha (H2) >0** | adopted from Binance 2026-08-29 |
| **leverage p90 ≤25x** | adopted from Binance 2026-08-29 |
| **median margin per position ≥$50** | adopted from Binance 2026-08-29 |
| **median holding duration ≥30min** | adopted from Binance 2026-08-29 |
| **weekly `pnlRatios[]` drawdown >20% not covered by the visible window** | new 2026-08-29, the "01014588 lesson" |

**Rejection breakdown** (of the 142 traders with ≥1 closed position):

| filter | rejected |
|---|---|
| sample too small (n<15 closed, or <8 with a defined leave-self-out alpha) | 33 |
| concentration >30% (top-1 trade) | 18 |
| net-negative closed PnL | 18 |
| single-pair only (H1) | 17 |
| payoff <0.5 | 17 |
| win rate >92% (Trampa 1) | 13 |
| t <2.5 | 9 |
| open unrealized loss > 50% of closed PnL (net) | 7 |
| leverage p90 >25x | 3 |
| no losers on either side | 2 |

Alpha H2, median margin, median duration, and the weekly-drawdown screen rejected **0** traders
each as the *first* blocking filter this round — every trader that would have failed them had
already failed an earlier check (t<2.5 caught `01014588` before its drawdown screen got a
chance to; leverage p90 caught `Powerful-Bubble-Rims` and `Monumental-DoS-Tiger` before
concentration or anything downstream). That doesn't mean these filters are dead weight — they
are exactly what stopped `Cheap-Producer-Shrew` (levp90=50x) from re-entering as a false
positive under the new methodology, and they are load-bearing for future runs where the
population shifts.

**Only 5 traders survive every hard filter — down from the original 12.** Not five confident
picks: two of the five (`Mine13`, `Algotoria`) are trustworthy by the same standard as the
original audit; the other three pass the numeric filters on razor-thin windows (2 days to 6
days of visible history) and, in `Kunpeng Plan`'s case, a headline-vs-computed PnL mismatch
large enough to distrust outright. Per the brief: filters are not relaxed to fill slots, and
none needed to be — but "survives the hard filters" and "I would copy this with real money" are
not the same claim for 3 of these 5, and the sections below say so explicitly.

## The picks

Ranked by trustworthiness, not raw score (raw score would rank `BestMax` #1 — see below for why
it isn't). **α%** and **t** are the corrected (leave-self-out) numbers; **α_old%/t_old** are the
original self-inclusive numbers, shown so the correction's effect is visible.

| # | trader | n | pairs | α% | t | α_old%/t_old | αH2% | wr% | payoff | lev (med/p90) | margin$ (med) | dur (med) | conc% | window | ranking pnl vs computed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Mine13** | 56 | 9 | +5.05% | 3.44 | +4.22% / 3.01 | +7.34% | 82.1 | 1.27 | 10x/10x | $3,290 | 219h | 9.4% | full, not capped (2026-06-02 → 08-25) | $88,044 vs $86,734 (0.99×) |
| 2 | **Algotoria** | 95 | 8 | +3.57% | 4.23 | +3.54% / 4.20 | +3.68% | 63.2 | 5.22 | 4x/4x | $6,031 | 40h | 23.4% | **3 weeks** (2026-08-06 → 08-27), not capped despite n≥95 | $84,856 vs $87,291 (1.03×) |
| 3 | **BestMax** | 100 | 2 | +1.11% | 7.74 | +0.42% / 3.07 | +1.14% | 86.0 | 1.58 | 20x/20x | $82 | 0.95h | 7.4% | **capped, 5 days** (2026-08-24 → 08-29) | $11,729 vs $2,329 (**0.20×**) |
| 4 | **Kunpeng Plan** | 97 | 4 | +0.66% | 5.03 | +0.30% / 2.42 | +0.48% | 78.4 | 1.72 | 3x/3x | $231 | 5.2h | 13.4% | **capped, ~1 day** (2026-08-27 → 08-28) | $490,566 vs $1,353 (**0.003×**) |
| 5 | **對不起我騙了你捲煙的煙草不來自後山** | 48 | 2 | +0.68% | 2.93 | +0.59% / 2.57 | +0.67% | 66.7 | 3.41 | 10x/20x | $392 | 2.1h | 10.1% | not capped, **1 day** (2026-08-28 only), leadDays=1 | $654 vs $2,060 (3.15×) |

**Suggested weights: 45/30/15/7/3.** Heavily front-loaded on purpose — this is not the same
confidence distribution as the Binance Top 5, because 3 of these 5 have windows too short to
call a track record. Full reasoning below.

### Why each one

**1. Mine13** — the only pick with a real multi-month window (2026-06-02 → 2026-08-25, not
capped: 56 < 100) and the most trustworthy of the five for exactly that reason. 9 pairs, payoff
1.27 with an 82% win rate, leverage a flat 10x with no tail (p90 also 10x). Corrected alpha is
*higher* than the original self-inclusive number (+5.05% vs +4.22%, t 3.44 vs 3.01) — this
trader was previously understated by the self-inclusive benchmark. **Flag:** max single-cell
ownership share is **67%** (over the 40% report threshold) — one of Mine13's benchmark cells is
mostly Mine13's own trades, so the leave-self-out alpha in that cell rests on thin "other
trader" evidence; the overall picture across 9 pairs is still the most diversified of the five.
Headline ranking pnl ($88,044) and the computed sum from the visible window ($86,734) agree to
within 1.5% — the closest cross-check of any survivor. Monthly (leave-self-out) alpha:
+4.19% → +6.50% → +5.72% — consistently positive, aH2 (+7.34%) confirms the trend isn't fading.
Open-position drag is immaterial (+$1,980 net across 3 open positions against $86,734 closed).
*Risk, same as before:* only 3 months of visible history — the whole dataset's single-regime
caveat applies here too.

**2. Algotoria** — the best risk-adjusted numbers in the set: t=4.23, payoff 5.22, and the
safest leverage of any candidate (flat 4x, no tail). 8 pairs, and the corrected alpha is
essentially unchanged from the original (+3.57% vs +3.54%) — this trader's cells are diverse
enough that self-inclusion barely mattered. Headline cross-check is close ($84,856 vs $87,291,
3% apart). *The catch, unchanged from the original finding:* all 95 visible positions were
opened between **2026-08-06 and 2026-08-27 — a single 3-week window** — despite `leadDays=859`
(2.3 years old). The recomputed cap flag confirms this is **not** cap truncation (95 raw
history rows, under the 100-row limit) — this trader genuinely only shows 3 weeks of activity in
OKX's copy-trading product, for reasons the API doesn't explain. Treat the alpha as a recent
snapshot, not a multi-month track record.

**3. BestMax** — has the **highest raw score** of all 5 survivors (t=7.74, the strongest
t-statistic in the set) and is placed **third, not first, on purpose**: the visible window is
**5 calendar days** (2026-08-24 → 2026-08-29, 100 closed positions — capped, so the true history
is longer but invisible), and max single-cell ownership share is **95%** — almost the entire
BTC/ETH benchmark cell this trader trades in is BestMax's own volume, meaning the leave-self-out
alpha (+1.11%, more than double the self-inclusive +0.42%) is measured against a tiny sliver of
genuinely independent "other trader" evidence. The headline-vs-computed cross-check is the
second-worst of the five: ranking pnl **$11,729** lifetime vs. **$2,329** computed from the
visible window (0.20×) — five days of trading account for a fifth of this account's entire
recorded PnL, which is plausible for a high-frequency scalper (durmed=0.95h, ~20 trades/day) but
is not evidence of a durable edge the way a multi-month window would be. A strong t-statistic
computed from 5 days of one symbol pair, one trader's own dominant volume, is exactly the kind
of number this audit exists to be suspicious of.

**4. Kunpeng Plan** — passes every hard filter (t=5.03, wr=78.4%, payoff 1.72, leverage a flat
3x, margin filter cleared at $231 median) and is placed **fourth anyway**: this is the trader
the cap-miscount correction was written for. 97 closed + 3 still-open lots = **100 raw history
rows, newly confirmed capped** by the recomputed manifest (the pre-correction manifest missed
this). The visible window spans **2026-08-27 → 2026-08-28 — about one day** — and the headline
ranking pnl is **$490,566** against **$1,353** computed from that one-day window (ratio
**0.003×**). Whatever this account's real track record is, essentially none of it is visible
here; the $490k figure implies either a much longer and very different trading history, or
activity this pipeline cannot see (a different instrument mix, a prior copy-trading product
version, etc.). Passing the numeric filters on a fragment this small is not evidence of
copyability.

**5. 對不起我騙了你捲煙的煙草不來自後山** — barely clears t≥2.5 (2.93) and is included only for
completeness at minimum weight. `leadDays=1` (the account is **one day old** by OKX's own
field), `aum=$0`, `copyTraderNum=0` (zero real copiers), and the entire 48-position visible
window falls on a **single calendar day** (2026-08-28). `hidden_loss_flag` is **True** (open
positions show meaningful net unrealized loss against a small closed-PnL base). There is
functionally no track record here — 48 trades in one day from a brand-new account is not
distinguishable from noise passing a threshold by chance. **Do not allocate real weight to
this pick**; it is listed to be transparent about what "5 survivors" actually contains, not as
a recommendation.

## Rejected despite high alpha

**无敌大鲤鱼 — previously the best alpha in the surviving set (+9.79%, t=2.42) under the old
self-inclusive methodology; now fails the sample-size gate outright.** Under leave-self-out
alpha, only **4 of its 26 closed positions** retain a defined alpha (the rest sit in benchmark
cells this trader dominates alone) — below the `min_alpha_n=8` threshold, so it's rejected as
"sample too small" before alpha even factors into a filter decision. This is the correction
working as intended: the original +9.79% alpha was measured almost entirely against this
trader's own trades. (Also still uncopyable regardless: ranking pnl $401.90, notional in the
tens of dollars — `SKILL.md`'s "Scalper King" pattern.)

**Cheap-Producer-Shrew — a near-miss in the original doc, now a formal hard rejection.**
89% win rate, payoff fine, t=4.08 (would have passed the old 1.5 threshold easily) — but
**leverage p90 is 50x**, which the newly-adopted Binance filter (≤25x) rejects outright. The
original doc flagged this qualitatively ("not one to add weight to speculatively") without a
hard filter behind it; now there's a hard filter, and it does exactly what the prose said it
should.

## The Trampa 1 signature, alive on OKX too

Of the 110 traders with ≥15 closed positions, **21 show a closed win rate above 92%**; **6 of
those have zero losers at all** (100% win rate). Of those 6, 4 are single-pair traders caught
earlier by the H1 filter and 2 (`Yawning-Curve-Cactus`, `Brief-Swap-Gearshift`) are multi-pair
and caught by the dedicated "no losers" filter. Of the remaining **15** with a real (non-100%)
win rate above 92%: **Ail.Wang** (99%, 100 closed), **好望角9999** (99%, 100 closed), **Bare-Payee-Fox**
(98.7%, 78 closed), **TieGuanYin** (97.9%, 47 closed), **chenyuan** (97.9%, 95 closed),
**RuiJie** (97%, 100 closed), **Busy-DID-Wombat** (96.9%, 98 closed), plus 8 more between 92.8%
and 96.7%. None of these appear above — a 92%+ closed win rate with real sample size remains
the single strongest "don't copy this" signal in the dataset.

## Rejected despite high PnL (Trampa 2 — never rank by PnL/ROI)

**KingoftheWORLD** — $196,897 total closed PnL over 60 positions, but it trades a **single
pair** (its actual rejection bucket) and **one trade is $127,474 of it (64.7% concentration)**
underneath that. The corrected leave-self-out alpha for this trader is also **negative**
(−0.10%, t=−0.63): once benchmarked properly against peers rather than partly against its own
volume, this account shows no edge at all, concentration and single-pair caveats aside.
**liyuan-luo** — $236,969 over just 24 positions, **single-pair only** (its actual rejection
bucket) with a **100% win rate** (zero losers) and 64.7% concentration in one trade underneath
that. Both would top a naive PnL ranking; both fail
on multiple independent grounds now, not just concentration.

## Confidence: low, and lower than the original version of this doc

- **Only 5 survivors, and 3 of the 5 are marginal on window length alone** (1–6 days of visible
  history vs. Mine13/Algotoria's weeks-to-months). This audit corrected the methodology; it
  did not — and structurally cannot — manufacture a longer track record for traders OKX's API
  only shows a sliver of.
- **Universe is 261, not ~600** — fewer candidates means a thinner margin against the
  winner's-curse effect `SKILL.md` already flags for Binance's larger pool, and a thinner
  margin means short-window false positives (BestMax, Kunpeng Plan) are more likely to clear
  the bar simply because there are fewer competing candidates to be beaten by.
- **~3 months, one regime slice**, same as the audited Binance snapshot, and per-trader
  windows are frequently much shorter than that (see the picks table's "window" column).
- **30% of the ranked universe (79/261) has no obtainable position history at all.**
- **No portfolio-level `mdd` from OKX's public API.** The open-`upl` check and the new weekly
  `pnlRatios[]` drawdown screen are the best proxies available, but neither is as complete as
  Binance/Phemex's `mdd`.
- **fresh_start (leadDays <120): 1 of 5 picks is flagged** — 對不起我騙了你捲煙的煙草不來自後山
  (`leadDays=1`) — a new addition to this Top 5 that the original didn't have to contend with.

**Suggested operation:** weights 45/30/15/7/3 in the order given — heavily concentrated on
Mine13 and Algotoria, the two picks with windows wide enough to trust. Treat picks #3–5 as
"passed the filters, not yet trustworthy" rather than "recommended" — re-run this pipeline as
more history accumulates for them before increasing their weight, and re-check `Kunpeng Plan`
specifically once (if ever) more than a one-day window becomes visible for it.
