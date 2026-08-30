# Top 5 KuCoin lead traders to copy — result: ZERO survivors (a valid outcome)

Same methodology as `analysis/TOP5_BITGET.md` / `TOP5_OKX.md` / `TOP5_BYBIT.md` /
`TOP5_PHEMEX.md`: leave-self-out de-leveraged alpha vs symbol×month×side cell
medians, full Binance hard-filter set, a drawdown screen built from the
exchange's own disclosed series, plus (new for KuCoin) an open-position upl
guard backed by REAL unrealized-PnL data. Reproducible:
`python3 scripts/scrape_kucoin_positions.py` (already run, data committed) →
`python3 analysis/kucoin_flatten.py` → `python3 analysis/kucoin_top5.py`.

**On 2026-08-30, no KuCoin copy trader in the scraped universe passes every
hard filter.** Filters were NOT relaxed to manufacture a Top 5. This is the
5th exchange in this project (of 6) to land at zero survivors — only Binance
has produced a Top 5 so far. This document explains what was scraped, the
filter breakdown, the four closest near-misses, and a real correctness bug
found and fixed mid-pipeline.

## The universe, honestly

- KuCoin's copy-trading leaderboard advertises **165 lead traders** live
  (`totalNum`/`totalPage`, both verified honest — unlike Bitget's leaderboard,
  which lies about `totals`). SKILL.md's brief said "~170"; 165 is the
  re-verified live count as of this run.
- **165/165 scraped to a terminal `ok` manifest status — 0 errors, 0
  `not_found`.** This is the smallest and cleanest universe of the six
  exchanges in this project: no protection flags, no truncation, no access
  quirks. The whole scrape took under 3 minutes.
- **137 of the 165 have at least one closed position** and reach the ranking
  funnel; **28 have zero closed positions ever recorded** on
  `positions/history` despite a comparable account age (median `daysAsLeader`
  for the zero-closed group is 165 days vs. 156 for the full universe — these
  are not simply brand-new accounts; the reason for the empty history is
  unknown and reported, not explained away).
- **14,414 closed positions** total (6 dropped later for `|pr|>3`, a bad-tick
  guard shared with every sibling pipeline) and **224 open positions** across
  **87 traders with at least one open position**.
- ⚠️ **Nicknames are not unique.** One collision found in the full 165-trader
  universe: two distinct `leadConfigId`s (1007643, 1008089) both display as
  `vol***@gmail.com` (KuCoin masks emails the same way for different accounts
  that happen to share a prefix). Every join in this pipeline is keyed by
  `leadConfigId`, never by nickname — this collision is called out because one
  of the two (`1007643`, n=116) reaches the ranking funnel and is discussed
  below; do not confuse it with its unrelated namesake (`1008089`, n=37).
- Data fingerprint, SHA-256 of the working data files as of this run:

  ```
  31235f84be81064362891f0d8deeb401ce6be31130e503c3bbf6a00a9ff214b5  data/kucoin_traders.jsonl
  79528d7fd90c82e774ff12a496f37129f4cbe1b06d87b6463c138a81781f12fe  data/kucoin_positions.jsonl
  8c902f046a59f9a2c8b44d3929b5e9d7dd7ce99d76e772fdc7ec5da80769d1fd  data/kucoin_open_positions.jsonl
  db52825e5f6f9a160b58fbf05a00fd5702a8ecab81678e6287da298926817252  data/kucoin_manifest.jsonl
  97b2ffc570de2ad58a4a989516e56212e3ddf56c60e900bcab96e7f9d6ac3835  analysis/kucoin_positions.csv
  ```

## Early verification, before building the full pipeline (checklist Phase 0/1)

Per the brief, five things were verified live against real endpoints before any
scraper code was written:

1. **`pnl` net vs. gross**: reconstructed gross PnL from
   `avgEntryPrice`×`closeQty`×`multiplier` (direction-adjusted) and diffed
   against the API's own `pnl` field. **Full-universe result (n=14,414):
   median residual −11.93 bps of notional, 94.7% negative** — the same
   fee-deducted signature as every other exchange here (Binance −7.85bps, OKX
   −6.5bps, Bitget −12bps self-consistent basis). **Declared: `pnl` is NET.**
2. **History depth**: no cap found. `positions/history` returned exactly
   `pageSize` rows up to `pageSize=500` in a live probe (a 213-row and a
   260-row trader each came back in a single page once `pageSize` exceeded
   their total), and `totalPage`/`totalNum` matched actual row counts across
   the full scrape (no trader silently truncated). The busiest trader in the
   full scrape had 2,628 closed positions (`Butterfly04`), paginated cleanly.
3. **`pnlRatio` semantics**: verified `pnlRatio == pnl / posMargin` over the
   full universe (n=14,414): **median absolute difference 4.9e-5, p90 9.0e-5**
   — `pnlRatio` is the LEVERAGED return on margin, not a de-leveraged price
   return. The ranking pipeline derives its de-leveraged return as
   `pr = pnlRatio / leverage`.
4. **`startTime`/`endTime` units**: milliseconds, verified (`1787421965000` →
   `2026-08-22 18:06:05 UTC`, a sane recent date).
5. **Leaderboard series granularity**: the leaderboard inlines FOUR series per
   trader. `totalPnlDate` (30 points) is **misleadingly named** — its last
   point matches `thirtyDayPnl` exactly (200/200 sampled rows), i.e. it is the
   **30-day** cumulative-$ series, not lifetime. `ninetyDayPnlDate` (~89-91
   points) is the longest disclosed series and matches `ninetyDayPnl` at its
   endpoint in 188/200 sampled rows. `thirtyDayPnlRatioDate` is a cumulative
   FRACTION series but only covers 30 days — no 90d ratio series is
   disclosed. `leadShow/pnl/history`'s daily `ratio` field was probed and
   rejected as a drawdown-screen basis: naively compounding it produces a
   6.7×10¹⁴-fold "equity curve" on a real trader (Sanfa), i.e. it is not a
   sane per-day return to compound. **Decision: the 90d screen uses the $
   series (`ninetyDayPnlDate`, renamed `pnl_series_90d`), normalized by
   `leadPrincipal`** — an approximation (current-principal snapshot, not a
   point-in-time equity value), documented as such everywhere it's used. See
   `scripts/scrape_kucoin_positions.py`'s docstring for the full trace.

## A genuine bug found and fixed mid-pipeline: the `leadConfigId` type round-trip

`leadConfigId` is a JSON **integer** in every scraped source
(`kucoin_traders.jsonl`, `kucoin_open_positions.jsonl`, `kucoin_manifest.jsonl`).
`analysis/kucoin_flatten.py` writes it into the CSV as a plain column, and
`csv.DictReader` reads every field back as a **string**. `analysis/
kucoin_top5.load_positions()` originally used that string verbatim as `uid`,
which meant `load_traders(...).get(uid)`, `load_open_upl(...).get(uid)` and
`load_manifest(...).get(uid)` — all keyed by the JSONL's native int — **silently
missed on every single lookup**, returning `{}`. Live symptom: the drawdown
screen (which treats a missing series as "reject, don't silently pass") ended
up rejecting **100% of the universe** at that filter, even the traders whose
real 90d series were perfectly clean. The existing unit tests didn't catch
this because every fixture in `tests/test_kucoin_top5.py` builds rows directly
as dicts with string uids (`'A'`, `'GOOD'`, `'T'`) — never through an actual CSV
round-trip. Fixed by casting `uid = int(r['lead_config_id'])` in
`load_positions`; two regression tests now exercise the real CSV round-trip
end-to-end (`test_load_positions_casts_lead_config_id_to_int_matching_jsonl_types`,
`test_rank_traders_integration_finds_traders_info_after_real_csv_round_trip`).
**Consequence for this run's final numbers: none** — every trader that reaches
the drawdown screen in the strict, production-threshold pipeline was already
rejected by an earlier filter (win rate, payoff, concentration, net-negative
PnL, or the t-stat), so the zero-survivors result is unchanged. It DID corrupt
an earlier diagnostic pass (a "closest traders" report built before the fix
showed every candidate's drawdown data as missing) — caught before publication,
not after.

## Rejection breakdown (137 traders reaching the ranking funnel)

| filter | rejected |
|---|---|
| sample too small (<15 closed or <8 alpha rows) | 57 |
| net-negative closed PnL | 29 |
| concentration >30% (top-1 position) | 21 |
| win rate >92% (Trampa 1) | 10 |
| payoff <0.5 (left tail) | 8 |
| single-pair only (H1) | 8 |
| t<2.5 (alpha not significant) | 3 |
| median margin <$50 (not copyable) | 1 |
| open unrealized loss >50% of closed PnL | 0 |
| 90d drawdown screen, uncovered | 0 |
| **survives every filter** | **0** |

57+29+21+10+8+8+3+1 = 137 — every trader accounted for
(`load_positions`'s own accounting check, `len(rows)+sum(drops)==n_csv`,
also passed: 14,408 loaded + 6 dropped = 14,414 CSV rows).

Note the drawdown screen and the open-upl guard both show **zero** rejections
in this table even though real data exists for both (87 traders have open
positions; every trader with ≥1 closed position has a `pnl_series_90d`) —
every trader that would reach those checks was already rejected earlier
(win rate, payoff, concentration, net-negative PnL, or t-stat). This is the
same "already dead before reaching the drawdown screen" pattern documented in
`TOP5_BITGET.md`.

## The four closest, independently traced

Only **4 of the 137** traders pass win rate ≤92%, payoff ≥0.5, net-positive
PnL, concentration ≤30% AND the open-upl guard — i.e. reach the t-stat and
beyond. All four still reject, on four different filters:

| trader (leadConfigId) | n | t | alpha H2% | levp90 | margin (median) | dur (median) | killed by |
|---|---|---|---|---|---|---|---|
| BullishOx (1012112) | 34 | **2.52** | +25.30% | 19x | **$12.12** | 93.8h | median margin <$50 (not copyable) |
| ~VCTUS~ (1008052) | 102 | 2.30 | +1.14% | 25x | $100.14 | 4.4h | t<2.5 |
| LEADER_ONE (1019106) | 32 | 1.80 | +1.08% | 125x | $2.66 | 2.2h | t<2.5 |
| vol\*\*\*@gmail.com (1007643) | 116 | 1.25 | +0.24% | 3x | $3,839.34 | 46.0h | t<2.5 |

**BullishOx is the single closest miss** — its t-stat (2.52) clears the 2.5
significance bar and its H2 alpha is strongly positive (+25.3%), but its
median position margin is **$12.12**, an order of magnitude under the $50
copyability floor: whatever edge it has is being expressed in bets too small
to mirror with real money, not a red flag about skill.

**LEADER_ONE is worth a second look for a different reason.** It only has 32
closed positions across 10 days as a leader (`daysAsLeader=10`) and its
`pnl_series_90d` is **empty** (KuCoin has not accumulated 90 days of history
for this account yet). Under production thresholds it is killed by `t<2.5`
before the drawdown screen is ever reached — but if the t-stat filter were
relaxed, this trader would fall straight into the **missing-series rejects**
rule (`drawdown_screen` returns `covered=False` for a genuinely empty series,
never a silent pass). Confirmed by explicitly disabling the t/leverage/margin/
duration filters: exactly one trader (LEADER_ONE) then dies on
`90d pnl_series peak-to-trough drawdown >20pp, uncovered by window` with
`dd_pct=None` — i.e. the "no data" case, not an actual large drawdown. This is
the KuCoin instance of the "01014588 lesson": a young, thin track record
cannot be waved through just because nothing bad shows up yet.

## Trampa exhibits (real, this run)

- **Trampa 2 analogue — self-inclusive alpha inflation, KuCoin edition.**
  `mak***@gmail.com` (leadConfigId 1008516, n=1,071 — the second-busiest trader
  in the universe) has a self-inclusive t-stat of **+3.58** (would look like a
  strong signal) but a **leave-self-out t-stat of −3.29** — the sign flips
  entirely once the trader's own 1,071 rows are excluded from the benchmark
  cells they dominate. `max_cell_share=1.0`: at least one cell is **100%**
  this trader's own trades, and 233 of its 1,071 rows had to be dropped from
  the alpha calculation entirely for exactly that reason
  (`n_alpha_dropped_self_dominated=233`). This is the textbook case the
  leave-self-out methodology (checklist Phase 2, adopted from the Mine13/CRCL
  finding on OKX) exists to catch — a naive self-inclusive ranking would have
  shortlisted this trader.
- **Trampa 1 (hidden losers) — headline cross-check catches what closed
  positions can't.** `Sanfa` (leadConfigId 1004009, n=260, wr=75.4%,
  payoff=0.79 — nothing alarming in the closed-position stats alone) has a
  computed closed-PnL sum of **+$385.84**, but its leaderboard headline
  `totalPnl` (genuinely lifetime — `daysAsLeader=416`) is **−$6,809.63**: a
  **massive, real divergence** (ratio −0.057) explained by this project's
  first verified real open-position unrealized-loss data — Sanfa's open book
  included a single AAVEUSDTM long carrying **−$2,833 unrealized PnL** at
  scrape time (leverage 5.7x, entry $210.58 vs. mark $129.63, a −38.4% adverse
  move), on top of other underwater positions. Sanfa is separately rejected on
  concentration (171% — its best closed position alone exceeds its entire net
  closed PnL), so the upl guard's hard threshold (open loss >50% of closed
  PnL) never gets to fire for this specific trader — but the headline
  cross-check alone would have been reason enough to reject it, an OKX-style
  "01014588" hidden-loss signature reproduced end-to-end on KuCoin.
- **Trampa 1 (spotless win rate), volume edition.** `LongShort`-style
  patterns repeat here too: 10 traders reject on win rate >92%, including
  several with hundreds of trades (e.g. `sel***@hotmail.com`, n=305, wr=97.0%,
  payoff=0.20 — wins are frequent and tiny, losses are rare and large, the
  exact left-tail signature payoff<0.5 exists to catch independently).
- **The nickname-collision trap.** Documented above under "the universe,
  honestly" — two distinct accounts render as the identical masked nickname
  `vol***@gmail.com`. Every computation in this pipeline keys by
  `leadConfigId`; a nickname-keyed join (as some ad-hoc analysis scripts do
  when eyeballing results) would have silently merged two unrelated traders'
  histories.

## Cross-checks, with explicit window labels

- **Headline `totalPnl` vs. computed `sum(pnl)` over every closed row
  scraped**, for the four closest traders (window label: `totalPnl` is
  genuinely LIFETIME once `daysAsLeader>90` — verified by construction in
  `scrape_kucoin_positions.py` — and identical to the 90d figure for younger
  accounts):

  | trader | daysAsLeader | computed | headline totalPnl | ratio |
  |---|---|---|---|---|
  | BullishOx | 63 | $163.35 | $154.54 | 1.057x |
  | ~VCTUS~ | 164 | $1,571.75 | $1,571.75 | 1.000x |
  | LEADER_ONE | 10 | $74.15 | $95.55 | 0.776x (90d-equivalent window, account is 10 days old) |
  | vol\*\*\*@gmail.com (1007643) | 203 | $16,601.31 | $16,844.16 | 0.986x |

  All four ratios sit close to 1.0× (no hidden lifetime loss behind a
  favorable recent window, unlike Sanfa above) — printed uniformly, not
  cherry-picked, per the checklist's "01014588" cross-check rule.
- **`pnlRatio == pnl / posMargin`**, full universe (n=14,414): median absolute
  difference **4.9×10⁻⁵**, p90 **9.0×10⁻⁵** — confirms `pnlRatio` is exactly
  self-consistent, the basis `analysis/kucoin_top5.py` relies on for the
  de-leveraged return.
- **Open-position upl guard**, per near-survivor (all four have `n_open=0` at
  scrape time — none currently hold an open position, so `has_upl_data=False`
  for all four specifically, even though the guard is real and populated for
  87/165 traders universe-wide, including the Sanfa exhibit above).

## What would change this result

1. **BullishOx crossing the $50 margin floor.** It is the only trader in this
   universe with a statistically significant, economically positive alpha
   (t=2.52, alpha H2=+25.3%) whose sole disqualifier is copyability, not
   skill. If its bet sizing grows (or if the margin floor were judged too
   strict for a still-young leaderboard), it is the first candidate to
   re-check.
2. **LEADER_ONE accumulating a real 90-day track record.** At 10 days old with
   an empty drawdown series, it cannot be cleared today under the
   missing-series-rejects rule regardless of how its t-stat evolves.
3. **Relaxing filters — explicitly NOT done, and not recommended.** The
   universe here is small (137 traders reach the funnel) and clean (0 scrape
   errors), so this is not a data-coverage problem the way Bitget's was; the
   filters are doing exactly what they're designed to do — net-negative PnL
   (29) and concentration (21) alone account for the majority of rejections,
   and the closest survivor (BullishOx) fails on a real copyability
   constraint, not a borderline statistical call.

**Operational conclusion: do not copy anyone on KuCoin today.** Re-run this
pipeline periodically — the universe is small enough (165 traders, ~3 minutes)
that a full re-scrape is cheap — watching specifically for BullishOx's margin
sizing and LEADER_ONE's accumulating track record.
