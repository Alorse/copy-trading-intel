# Combined ranking — all audited pools (updated 2026-09-23, fresh re-run)

> **Everything below was re-derived from scrapes taken on 2026-09-23.** No figure is
> carried over from the August tables. The August ranking is kept further down as
> history, not deleted.

Status per exchange after the re-run:

| Exchange | Universe (2026-09-23) | Survivors | Audited doc |
|---|---|---|---|
| Binance | 999 portfolios fetched, 951 with positions, 950 ranked | 5 in the pipeline roster | analysis/runs/2026-09-23/TOP_2026-09.md |
| OKX | 287 ranked, 158 with closed positions | **0** (was 5) | analysis/TOP5_OKX.md |
| Phemex / Bybit / Bitget / KuCoin | not re-scraped this run | **0** as of 2026-08-30 | their TOP5_*.md |

## Engine update (2026-09-23): the copier gate and the 20% cap

Everything below was written against an engine that could not see two things. Both
are now in the pipeline, and **the roster it produces is publishable as is** —
`analysis/runs/2026-09-23/roster.json` needs no hand editing. The standing rule holds:
the pipeline decides eligibility, humans may only remove.

**1. `copiers_losing` (disqualifying).** Realized lifetime copier PnL, from
`lead-portfolio/detail`, is now scraped for the ranked candidates and stored per
trader. ⚠️ The listing row carries a field of the same name and it is **not the same
number**: it is scoped to the request's `timeRange`, so 汤普猫 reads +$116 / +$147 /
+$242 / +$273 for 7D/30D/90D/180D while `detail` reads **−$6,117** lifetime. A gate
built on the listing figure would have passed exactly the lead it exists to stop.

The sign alone is not evidence: **346 of the 760 measured portfolios (45.5%)** have
negative lifetime copier PnL, and the median one is **−$11.43 per copier** — fees and
entry timing. So the rule asks for a measurement and for a material loss on one of two
independent scales:

| clause | threshold | why that number |
|---|---|---|
| enough copiers | `totalCopyCount >= 10` | below it the aggregate is one person's timing (再也不做空了: 2 copiers, −$11.79) |
| per head | `copierPnl / totalCopyCount <= -$50` | five platform-minimum copies ($10) wiped out per person; ~4× the median negative lead; reached by 12.4% of measured portfolios |
| **or** against the lead | `copierPnl <= -0.5 × lead realized PnL` | the scale-free clause: a lead whose copiers hold far more capital than it does can drown them while losing little per head |

Fires on **74 of the 950 ranked (7.8%)** and **45 of the 553 on the leaderboard
(8.1%)**. Of the six portfolios that survive every other disqualifier it removes
exactly two:

| removed | copiers | copier PnL | per head | vs the lead's own PnL |
|---|---|---|---|---|
| **汤普猫** | 47 | −$6,117 | −$130.15 | **1.28×** everything it earned |
| **重生之我在币圈捡垃圾-** | 1,862 | −$320,510 | −$172.13 | **10.25×** |

and keeps 梭哈到世界尽头 (+$19,426 over 112) and Cooma (+$1,876 over 218). That outcome
is **stable over the whole grid tested** — count 3…47, per head $25…$100, share
0.25…1.0 all remove the same two and keep the same two — so it does not rest on a
fitted threshold. copierPnl remains a veto only: it is raw PnL, it carries every Trap-2
problem, and it never enters the score.

**2. A 20% cap per trader.** The A pool is 70% of the book (100% with no B) split by
score, so one tier-A trader took all of it: 汤普猫 held **70%** on 84 trades, t=2.58 and
a $2,001 lead account. `MAX_WEIGHT = 0.20` — the most the 2026-08-28 hand ranking ever
gave one name, the most all five slots can hold at once, and the level at which one
lead's total loss costs a fifth of the book rather than most of it. The excess stays
**unallocated**, never moved to another trader; the old "B's leftovers go to A" spill
and the rounding top-up that forced the book to 1.0 are gone with it.

### The roster this produces

| # | trader | tier | weight | alpha · t | copier PnL | copiers (cur/total) | lead equity |
|---|---|---|---|---|---|---|---|
| 1 | **梭哈到世界尽头** (suoha) | B | 10% | +3.19% · 7.88 | **+$19,426** | 13 / 112 | $5,316 |
| 2 | **Cooma** | B | 10% | +1.75% · 4.67 | **+$1,876** | 53 / 218 | $11,425 |
| 3 | **黑袍小分队** | B | 10% | +1.65% · 2.66 | −$189 | 0 / 19 | $4,135 |
| 4 | **狱萝** | B | 10% | +1.94% · 2.98 | +$41 | 0 / 14 | **$620** |
| — | ~~汤普猫~~ | X | — | +2.90% · 2.58 | **−$6,117** | 2 / 47 | $2,001 |
| — | ~~重生之我在币圈捡垃圾-~~ | X | — | +0.60% · 3.85 | **−$320,510** | 214 / 1,862 | $11,640 |

**60% of the book is unallocated.** The two names the House view wants are #1 and #2.

Every copier figure in this section is the one the pipeline stored, i.e. what the gate
actually read. `copierPnl` is live and drifts within the day — the audit below quotes
−$322,314 for 重生之我在币圈捡垃圾- and +$19,440 for suoha from a fetch a few hours
earlier. Neither figure is wrong; they are not the same instant, and nothing in the
rule turns on the difference.

⚠️ **Two survivors the audit above would not have kept are still in, and the evidence
does not remove them.** Reporting this rather than fitting a threshold to it:

- **黑袍小分队** — 19 copiers, −$188.54, i.e. **−$9.92 each** and 3.8% of the lead's own
  +$4,961. That is below every noise floor the gate can honestly draw; the universe's
  median *negative* lead loses $11.43 per copier, so condemning this shape condemns half
  the leaderboard. What the audit actually rejected it on — September alpha negative on a
  handful of trades, mdd 64.2, last opening 2026-09-08, nobody currently copying it — is
  a bundle of weak signals, none of them disqualifying on its own, and none of them
  encoded.
- **狱萝** — its copiers are **up** $41, so no copier rule touches it. Its defect is the
  秋高看山势 defect: the lead's entire account is **$620.09**, median position margin $60,
  and `not_copyable` only reads per-position margin (threshold $50), never account equity.
  A $1,000 copier would run at 161% of the lead's own book.

**The next rule, proposed and NOT implemented:** a lead-equity floor, now measurable for
the first time (`marginBalance` from `detail`; the listing's `aum` is no use — it
includes copier capital, $14,116 vs $5,316 of actual equity for suoha). Costs, measured
on this snapshot:

| floor | flags (of 950 / of 553 listed) | removes |
|---|---|---|
| $500 | 58 / 30 | nobody |
| **$1,000** | 154 / 88 | 狱萝 |
| $2,000 | 304 / 199 | 狱萝 |
| $5,000 | 482 / 349 | 狱萝, 黑袍小分队 — and suoha clears it by $316 |

$1,000 is the defensible one (it is Binance's own maximum platform minimum-copy size,
and the floor below which a $1,000 copier out-sizes the lead). $5,000 would deliver the
House view's two-name roster and would also disqualify 63% of the leaderboard on a
threshold picked to produce that answer. **That is a decision, not a measurement, and it
is not taken here.**

One more thing `detail` bought for free: **190 of the 950 ranked portfolios (20%) return
code 11012028 — they no longer exist.** All 190 are already off the listing, so
`no_listing_data` was catching them and the new signal costs nothing today; it is now
stored per trader (`trader_snapshot.retired`) rather than inferred.

## The ranking now

| # | Trader | Exchange | Verdict | Alpha | t | Sept-only alpha / t | copier PnL | Why |
|---|---|---|---|---|---|---|---|---|
| 1 | **梭哈到世界尽头** (suoha) | Binance | ✅ **keep** | +3.19% | 7.88 | **+4.29% / 5.03** (39 trades) | **+$19,440** (112 copiers) | the only lead whose September beats its August |
| 2 | **Cooma** | Binance | ✅ **keep, reduced** | +1.75% | 4.67 | +0.68% / 0.54 (20 trades) | **+$1,827** (218 copiers) | cleanest risk profile; September too thin to confirm |
| 3 | **秋高看山势** (qiugao) | Binance | ⚠️ **drop → watch** | +1.28% | 3.67 | **+1.62% / 3.54** (76 trades) | −$97 (10 copiers) | edge held, but it is an edge on a **$604** account |
| 4 | **重生之我在币圈捡垃圾-** | Binance | ❌ **drop** | +0.60% | 3.85 | +0.64% / 2.13 (43 trades) | **−$322,314** (1,862 copiers) | alpha real, does not survive being copied |
| 5 | **Mine13** | OKX | ❌ **drop → watch** | +5.11% | 2.91 | −0.43% / −0.79 (**4** trades) | n/a | almost no new evidence; −$6,083 open unrealized |
| 6 | **Algotoria** | OKX | ❌ **drop** | +0.08% | 0.23 | +0.08% / 0.23 (98 trades) | n/a | whole book rolled over; no measurable edge |
| — | ~~牛熊摆渡人~~ | Binance | ☠️ **dead, confirmed** | — | — | no opening since 2026-08-28 | n/a | `lead-portfolio/detail` → code 11012028 |

Sept-only = positions **opened on or after 2026-08-29**, benchmarked inside the same
snapshot, so it is a like-for-like comparison against the trader's own earlier months.

**Replacement for the retired 8% slot: none.** See "No replacement" below.

## Goal 3 — the six leads, re-audited on fresh data

Every number below comes from the 2026-09-23 snapshot (`data/copytrade.sqlite`,
`analysis/okx_positions.csv`) or from Binance's `lead-portfolio/detail` endpoint,
fetched the same day.

| | suoha | Cooma | qiugao | zhshengsheng |
|---|---|---|---|---|
| portfolio | 5082101648817857024 | 4993536743184078592 | 5016123555802443776 | 5088110611707352576 |
| n / n_alpha | 331 / 231 | 137 / 110 | 270 / 253 | 294 / 292 |
| alpha · t | +3.19% · 7.88 | +1.75% · 4.67 | +1.28% · 3.67 | +0.60% · 3.85 |
| alpha H1 → H2 | +3.68% → +2.70% | +1.88% → +1.62% | +1.28% → +1.27% | +0.14% → +1.06% |
| payoff · win rate | 1.31 · 85.8% | 0.61 · 84.7% | 1.97 · 71.1% | 1.10 · 88.8% |
| mdd | **12.97** | 31.92 | unknown (off listing) | **60.79** |
| ruin (worst loss × med lev) | −64% | −92% | **−346%** | −63% |
| leverage med / p90 | 5x / 20x | 10x / **10x** | 15x / 20x | 5x / 20x |
| median margin | $102 | $216 | **$35** | $1,521 |
| median hold | 22.6h | 38.7h | 5.5h | **0.85h** |
| months active | 4 | 5 | 5 | 4 |
| flags | alpha_decay, fresh_start | alpha_decay | **not_copyable**, alpha_decay | **mdd_high**, fresh_start, alpha_decay |
| tier / weight | B / 10% | B / 10% | **X / 0%** | B / 5% |
| **September trades** | 39 | 20 | 76 | 43 |
| **September alpha · t** | **+4.29% · 5.03** | +0.68% · 0.54 | **+1.62% · 3.54** | +0.64% · 2.13 |
| **September realized PnL** | **+$2,808** | +$1,056 | +$257 | **−$3,259** |
| lead margin balance | $5,309 | $11,505 | **$604** | $11,622 |
| lifetime copier PnL | **+$19,440** | **+$1,827** | −$97 | **−$322,314** |
| current / lifetime copiers | 13 / 112 | 53 / 218 | 2 / 10 | 214 / 1,862 |
| platform min copy | $10 | $10 | $10 | **$1,000** |

**Did the edge hold in September?** September was not the August pump, so this is the
question the August table could not answer. Three of the four Binance leads still show
positive alpha on trades opened after the August snapshot; only one of them shows it on
enough trades *and* enough profit to matter.

- **suoha — keep, highest conviction.** 39 new trades at **+4.29% alpha, t=5.03**, its
  best month in the visible window (monthly series +3.56 → +2.89 → +2.67 → **+4.38%**).
  Its `alpha_decay` flag is an artifact of the H1/H2 split falling inside the older data;
  the month-by-month series is flat-to-rising. mdd improved 20.1 → 12.97. Copiers are up
  $19,440. Nothing in this run argues against him.
- **Cooma — keep, reduced.** The full-sample t is still 4.67 and the risk profile is the
  cleanest of the six (flat 10x with no tail, worst loss −92% of margin, 168 days of
  record). But September is only 14 alpha-eligible trades at t=0.54: that neither
  confirms nor refutes the edge. Monthly alpha +0.86 → +1.87 → +2.65 → **+0.68%**. Hold
  at reduced weight until the next run gives a verdict.
- **qiugao — drop from allocation, keep on the watchlist.** Statistically this is the
  *best-evidenced* September of the six: 76 new trades, **+1.62% alpha, t=3.54**, and its
  monthly series has been positive every month since May. The edge is real and it held.
  It is also uninvestable: the lead's entire account is **$604.42** (AUM $768.58 — this
  confirms Ramona's ~770 figure independently), median position margin $35, and its
  76 September trades produced **$257**. A $1,000 copier would run at **165% of the
  lead's own equity**. `not_copyable` is the right call and the 2026-08 table was wrong
  to override it.
- **zhshengsheng — drop.** This is the run's most important finding and it is not about
  alpha. The alpha held (+0.64%, t=2.13 on 43 September trades) and the headline ROI is
  **+617%** — while **1,862 lifetime copiers are collectively down $322,314** and the
  lead's own September realized PnL is **−$3,259**. The mechanism is visible in the table:
  a **0.85h median hold** at a $1,521 median margin. The August audit flagged exactly this
  ("sensitive to copy latency"); three months and 1,862 copiers have now priced it. An
  edge that exists in the lead's fills and disappears in the copier's is not an edge we
  can buy.

**OKX — both picks drop.** Full detail in `analysis/TOP5_OKX.md`. Algotoria's entire
visible book rolled over to September: 98 fresh trades, **+0.08% alpha, t=0.23**, net
**−$82**. Mine13 produced only **4** new trades since 08-29 (−$1,103) and carries
**−$6,083** unrealized on 3 open positions. Mine13's formal rejection (`alpha H2 ≤ 0`)
is a measurement artifact, not evidence of decay — see the rolling-window trap in
TOP5_OKX.md — but four trades is not evidence of anything, and the open drawdown is real.

### Copyable at what capital?

Binance scales a copier's position by (copier capital ÷ lead margin balance) and rounds
any sub-minimum order **up** to the pair's exchange minimum (5 USDT on 897 of 907 USDT-M
perps, re-derived from `fapi/v1/exchangeInfo` on 2026-09-23). Below the floor in the
table, a copier does not get a smaller position — they get an **over-sized** one.

| lead | min copy capital | at $500 | at $1,000 | ceiling |
|---|---|---|---|---|
| suoha | **~$500** | 6/331 positions below minimum, worst **8.9× intended** | 3/331, worst 4.4× | none |
| Cooma | **~$500** | 3/137 below minimum, worst 3.7× | 1/137, worst 1.9× | none |
| zhshengsheng | $1,000 (platform floor) | — | 0/294 clean | none |
| qiugao | ~$50 | 0/270 clean | 0/270 clean | **~$600** — above that you outsize the lead |

Ramona's concern about suoha's micro-adds is confirmed in direction and bounded in size:
his smallest visible position is **$6** of notional, and at a $200 copier 19 of 331
positions (5.7%) round up, the worst arriving at **22.2× intended**. Total exposure
inflation stays negligible (+0.3%), so this is a per-trade concentration risk on a
handful of trades, not a systematic drag. **Copy him with at least $1,000.** Caveat:
the position-history endpoint exposes only each closed position's peak size, not the
individual adds inside it, so intra-position adds smaller than $6 cannot be ruled out
from public data.

qiugao's open ZEC short **could not be verified**: Binance publishes no per-lead
open-position endpoint (`scripts/probe_open_positions.py`, 404 on all four candidates),
and `positionShow=False` on all six audited leads. That figure is Ramona's, unverified here.

## Goal 4 — replacement candidates: **none**

The fresh Binance run put two traders in the top-5 that were not in the August table.
Neither is a replacement, and the slot stays empty rather than being filled by the next
row of anything.

| candidate | alpha · t | n | Sept alpha · t | mdd | lead equity | copier PnL | current copiers | why not |
|---|---|---|---|---|---|---|---|---|
| **汤普猫** (4113397127009634560) | +2.90% · **2.58** | 84 | +5.29% · 2.12 (24) | 23.8 | **$2,001** | **−$6,117** (47) | **2** | t barely clears 2.5; 47 people have copied it and lost money; a $5,000 copier would run at 250% of the lead's own equity |
| **黑袍小分队** (5065357423393074433) | +1.65% · 2.66 | 158 | **−4.62% · −1.12** (4) | **64.2** | $4,255 | −$189 (19) | **0** | September alpha is negative, last opening 2026-09-08, mdd 64%, nobody currently copies it |
| ~~再也不做空了~~ (4563197729960674304) | +0.34% · 2.63 | 111 | +2.29% (3 trades) | unknown | $1,528 | −$12 (2) | 1 | reached tier A and 30% weight with an **empty flag list** only because its listing row was missing — now caught by `no_listing_data` |

**OKX contributes nothing:** 0 survivors of 158 ranked traders. Its best near-miss
(`To the Moon Merchant`, alpha +5.52%, t=8.30) is stopped by the hidden-drawdown screen.

**Recommendation: leave the retired 8% unallocated.** Of ~950 ranked Binance portfolios
and 158 OKX traders re-measured today, not one clears the bar that 牛熊摆渡人 was let
through on. That is the answer, not a failure to find one.

## Goal 5 — post-mortem of 牛熊摆渡人, and the new guard

**Which signal would have caught it before 2026-09-02, and did the pipeline have it?
Yes — the pipeline already had it, and the hand ranking overrode it.**

On the 2026-08-28 snapshot the engine had already classified portfolio
`5096968193101811713` as **tier X**, flags `["ruin_risk","mdd_high","fresh_start"]`:
worst loss × median leverage = **−1,173% of margin**, disclosed **mdd 74.85**, 20x flat
leverage, 66 days of history. No new signal was needed. `COMBINED_RANKING.md` ranked it
#7 at 8% anyway, on a 2-of-4 vote from the Fable/Kimi/GLM consensus, and the report even
called it "the most dangerous of the five" in prose while allocating to it.

So the honest answer to "what would have caught it" is: **nothing the engine lacked.**
The failure was governance, not detection.

What the engine genuinely lacked is a way to notice a lead has *stopped existing* — every
pre-existing rule reads the shape of the closed trades. `inactive` (30 days on closes)
stayed silent, because a dying portfolio keeps closing for weeks after it stops opening:
on 2026-09-23 this one was **26.2 days past its last opening** and only **21.0 days past
its last close**. Three new disqualifying flags in `pipeline/detect.py`:

| flag | rule | fires (all 950) | fires (553 on the leaderboard) | **marginal** |
|---|---|---|---|---|
| `went_dark` | nothing **opened** in 21 days, universe-relative clock | 202 (21.3%) | 104 (18.8%) | **0** |
| `mass_close_loss` | ≥5 closes in the same second whose net loss erases ≥50% of everything the trader ever earned | 10 (1.1%) | 2 (0.4%) | **0** |
| `no_listing_data` | no row in the scraped leaderboard listing, so `mdd`/`roi`/`startTime` are absent and three screens silently cannot fire | 398 (41.9%) | 0 (0.0%) | **1** |

**"Marginal" is the number that matters**: traders excluded that no pre-existing
disqualifier already caught, out of the 7 that survive everything else. The two liveness
flags cost **nothing** today — every trader they flag was already out on another rule —
so they are a safety net, not a tax. Their value is forward-looking: had 牛熊摆渡人 been on
a published roster, it would now be removed for two independent reasons rather than
waiting on a risk flag that had already been overridden once.

`no_listing_data`'s single marginal exclusion is the point of the flag: **再也不做空了**
had been placed in **tier A with 30% of the weight and an empty flag list**, because its
missing listing row meant `mdd_high`, `roi_artifact` and `fresh_start` never ran.

21 days is the largest N that still catches the reference case; N=30 would have missed it.

⚠️ `no_listing_data` is named after what it can prove. Falling out of the top-600 does
**not** mean retired: of the three off-listing portfolios checked by hand, two
(秋高看山势 and 再也不做空了) are still `status=ACTIVE` and copyable — only 牛熊摆渡人
returns code **11012028** from `lead-portfolio/detail`. That endpoint is the
real delisting signal and is now documented in `SKILL.md`; wiring it into the scrape
stage is the recommended next step.

## Pipeline vs hand ranking: trust the pipeline

The August ranking overrode the engine twice. Both overrides are now resolved, and the
engine was right both times:

| | 牛熊摆渡人 | 秋高看山势 |
|---|---|---|
| engine, 2026-08-28 | tier **X** — `ruin_risk`, `mdd_high`, `fresh_start` | tier **X** — `not_copyable` |
| hand ranking | **#7, 8% weight** | **#4, 12% weight** |
| outcome | liquidated 2026-09-02 (−15,295 USDT in one second), portfolio gone | edge held (+1.62%, t=3.54) but on a **$604** account; copiers down $97 |
| verdict | override was wrong, expensively | override was wrong, harmlessly |

The engine's picks needed no override: its two clean 2026-08-28 survivors (suoha, Cooma)
are the two leads still worth keeping today, and its one B-tier holdout
(zhshengsheng, flagged `mdd_high`) is the one whose copiers lost $322k. **Going forward
the deterministic pipeline decides who is eligible; the council and the hand ranking may
only *remove* from that set, never add to it.** A disqualifying flag is not a vote to
be outweighed 2-to-4.

The one thing the pipeline does *not* yet see is on this page: **realized copier PnL.**
It is published per lead (`lead-portfolio/detail.copierPnl`) and it is the only direct
measurement of whether an edge survives being copied.

### Proposed, NOT implemented — `copier_pnl_negative`

> **Superseded: shipped on 2026-09-23 as `copiers_losing`.** See "Engine update" at the
> top of this page for the rule that was actually calibrated and the universe numbers
> behind it. The section below is the original proposal, kept because its mechanism
> evidence (the holding-period gradient) still stands and because the rule that shipped
> is stricter than what it suggested: `totalCopyCount >= 50` would have spared 汤普猫,
> whose 47 copiers are down $6,117.

Per the brief this is a proposal, not a silent change; the score formula is untouched.
Measured on the 120 highest-scoring listed Binance portfolios with n≥60:

- **77 have ≥5 lifetime copiers. 39 of them (51%) have net-negative copier PnL**, and the
  median such lead's copiers are down $3. Half of the best-scoring leads on Binance have
  lost money for the people who copied them.
- Sorted by the lead's median holding period, the share of leads whose copiers lost money
  falls monotonically from **64% under 1h** → 57% (1–4h) → 56% (4–12h) → **22% (12–24h)**,
  then breaks to 33% at ≥24h. Directionally this supports latency as the mechanism, but
  with 9–27 traders per band it is suggestive, not a threshold.
- copierPnl is **not** a skill metric and must never enter the score: it is raw PnL, with
  every Trap-2 problem this project documents (`穩定暴擊` has t=0.71 and +$472k;
  zhshengsheng has t=3.85 and −$322k). Its value is as a **warning on a specific
  incumbent**, not as a cross-sectional ranker.

Suggested shape: report `copierPnl`, `currentCopyCount` and `totalCopyCount` in the
roster, and raise a **warning** (not a disqualifier) when `copierPnl < 0` with
`totalCopyCount >= 50`. On today's six leads that fires on exactly one: zhshengsheng.

## What changed in this update (2026-09-23)

- **Everything was re-scraped.** Binance: 999 portfolios, 951 with positions, 150,165
  closed positions. OKX: 287 ranked, 158 with history, 9,653 closed + 3,081 open. The
  August OKX raw data is archived under `data/archive/2026-08-okx/`.
- **OKX went from 5 survivors to 0**, both recommended picks included.
- **A new OKX trap:** its 100-row history cap is a *rolling* window, so a past month's
  benchmark cell shrinks over time and keeps only the traders who have traded little
  since. Alpha is **not comparable across two OKX snapshots**. Details in TOP5_OKX.md.
- **Binance's `lead-portfolio/detail` endpoint** is now on record (SKILL.md): it is what
  separates a retired portfolio (code 11012028) from a merely unranked one, and it
  publishes `copierPnl`, `marginBalance`, `aumAmount` and the platform minimum copy size.
- **Three new disqualifying flags** — `went_dark`, `mass_close_loss`, `no_listing_data`.
- **The engine's historical-union universe ran for the first time** (399 portfolios that
  have dropped out of the top-600 but still serve history). This is what made
  `no_listing_data` necessary: without it the union feeds unaudited traders into the roster.
- **Phemex, Bybit, Bitget and KuCoin were not re-scraped** this run. Their zeros are as of
  2026-08-30 and are now stale.

## House view (2026-09-23)

suoha and Cooma are the portfolio: they are the only two leads with a surviving edge,
an acceptable risk profile **and** a positive realized copier record. qiugao goes to the
watchlist on merit but cannot take capital. zhshengsheng comes off regardless of its
alpha. Both OKX positions come off. The retired 8% and the freed weight stay
**unallocated** until a future run produces something that clears the bar on its own —
`analysis/roster.json` has deliberately **not** been republished; the candidate roster
sits in `analysis/runs/2026-09-23/`.

The next gain is not another exchange. It is wiring `copierPnl` and `lead-portfolio/detail`
into the pipeline, and re-scraping the four zero-survivor pools before trusting their
zeros a second time.

> **Done (2026-09-23, same day):** `copierPnl` and `lead-portfolio/detail` are in the
> pipeline — see "Engine update" at the top. The engine's own roster now leads with
> suoha and Cooma and caps every name at 10-20%; it still carries two traders this
> House view would not fund, for reasons stated there. Re-scraping the four
> zero-survivor pools remains open.

## The combined ranking (2026-08-28 snapshot) — SUPERSEDED, kept as history

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
