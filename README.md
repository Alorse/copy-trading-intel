# copy-trading-intel

Analysis of public copy-trading data from **Binance and Phemex**: who actually wins, who only
looks like it, and why almost every "top trader" isn't one.

Both platforms publish their lead traders' track records. This repo scrapes that data, audits it
against its own biases, and produces a reproducible roster of candidates to copy — along with a
record of the findings that fell apart once verified.

> ⚠️ **This is not financial advice or an investment recommendation.** Read
> [DISCLAIMER.md](DISCLAIMER.md) before using any of this.

## The idea in one line

**ROI and PnL in USD do not measure skill.** They reward leverage, account size and luck of
regime. The metric this repo uses is:

```
alpha = de-leveraged price return − median of its cell (symbol × month × side)
```

It neutralises all three unfairnesses at once. Going long in the August pump scores **zero** by
construction: the only thing that counts is beating everyone who did exactly the same.

The three highest-ROI traders in the audited snapshot, measured this way: **alpha −0.72%, −1.23%,
and 96.9% of PnL from a single trade at 145x.**

## What's here

| path | what it is |
|---|---|
| `pipeline/` + `pipeline.py` | the permanent pipeline: `scrape → SQLite → metrics → flags → trend → roster` |
| `SKILL.md` | living reference: both exchanges' endpoints, current findings, and the 6 traps in this data |
| `SKILL.v2.md` | previous version, **archived**: six of its findings turned out false against its own data |
| `analysis/FINDINGS_v2.md` | the full audit: what held, what collapsed, and on what evidence |
| `analysis/TOP5.md` | the 5 consensus traders, with the reasoning and the rejects |
| `analysis/RULES.md` | candidate rules for BTCUSDT and the 2019-2026 walk-forward result |
| `analysis/*.py` | the one-offs that reproduce every figure (see `analysis/README.md`) |
| `scripts/` | the original Binance/Phemex scrapers, the open-positions probe, and the phase-1 OKX/Bybit/Bitget/unify scripts (see below) |
| `docs/specs`, `docs/plans` | the pipeline's design and implementation (historical documents) |

## Requirements

- **Python ≥ 3.11** (the engine uses `datetime.UTC`).
- **Zero runtime dependencies**: stdlib only (`sqlite3`, `json`, `csv`, `urllib`, `statistics`).
- `pytest` for the tests only: `pip install -r requirements-dev.txt`.

## Quickstart

```bash
git clone https://github.com/Alorse/copy-trading-intel.git
cd copy-trading-intel
pytest                                    # 82 tests; the 4 regression ones are opt-in (see below)

python3 pipeline.py scrape  --date $(date +%F)   # ~600 Binance portfolios + Phemex (slow, resumable)
python3 pipeline.py analyze --date $(date +%F)   # -> analysis/runs/<date>/{TOP_YYYY-MM.md,roster.json,diff.json}
python3 pipeline.py publish --date $(date +%F)   # the only step that touches analysis/roster.json
```

`analyze` **validates before ingesting**: if the snapshot comes in ±50% off the previous one on
traders or positions, it exits with code 2 without touching the database. `--force` skips that;
an exchange that had a previous snapshot and brings no CSV today is not skippable.

Granular subcommands (`metrics`, `detect`, `trend`, `rank`, `report`) run in that mandatory order:
`metrics` resets flags and `trend_bonus`, so a `rank` without a preceding `detect` ranks with no
flags.

## The data is not in the repo

Raw dumps of the Binance/Phemex APIs are **not versioned** — we don't redistribute third-party
data. Generate your own with `pipeline.py scrape`. What *is* versioned are the analysis
aggregates (`data/SUMMARY.json`, `data/aggregate_*.json`) and each run's reports.

Consequence: the 4 tests in `tests/test_regression.py` — the ones verifying that the pipeline
reproduces the audited 2026-08-25 analysis — **skip** unless you place a snapshot in
`data/snapshots/2026-08-25/`. That particular snapshot is no longer obtainable: the APIs only
serve recent history.

## Unified trader pool (phase 1)

A separate, simpler effort from `pipeline/`: **discover and unify traders from more exchanges
into one pool**, no per-exchange ranking or classification yet. Three new public sources, each
with its own access quirk:

| exchange | script | output | quirk |
|---|---|---|---|
| OKX | `scripts/scrape_okx.py` + `scripts/scrape_okx_positions.py` | `data/okx_traders.jsonl`, `data/okx_trader_stats.jsonl`, `data/okx_positions.jsonl`, `data/okx_open_positions.jsonl` | clean public JSON, but **do not** pass `sortType` (any value → error 51000); `public-stats`' `lastDays` only accepts `{1, 2, 3}`; position history caps silently at 100 rows/trader; a minority of ranked traders 404 with `"Trader doesn't exist"` on the position endpoints specifically |
| Bybit | `scripts/scrape_bybit.py` | `data/bybit_traders.jsonl` | Akamai TLS-fingerprints the listing endpoint; needs `curl_cffi` (`impersonate='chrome'`), and even that 403s intermittently from some hosts |
| Bitget | `scripts/scrape_bitget.py` | `data/bitget_orders.jsonl` (best effort) | **superseded 2026-08-30** by `scripts/scrape_bitget_positions.py` (see "Bitget position history" below) — the leaderboard turned out to exist after all, and none of these endpoints need session tokens from `curl_cffi`; this script is kept only as a record of the 2026-08-29 dead end |

Run each one directly (all resumable — safe to re-run):

```bash
python3 scripts/scrape_okx.py --pages 30          # ~10 rows/page, capped at OKX's totalPage
python3 scripts/scrape_bybit.py --pages 20        # needs curl_cffi (in .venv/); prints a clear
                                                   # warning and writes 0 rows if Akamai blocks it
python3 scripts/scrape_bitget.py                  # needs data/bitget_session.json (gitignored,
                                                   # see the script's docstring); exits 1 with a
                                                   # clear message if missing or the tokens are stale
python3 scripts/unify.py                          # -> data/unified_traders.csv
```

`unify.py` reads every `data/*_traders.jsonl` it recognizes (currently OKX and Bybit — Bitget has
no leaderboard to rank by, so its output isn't named `*_traders.jsonl` and doesn't feed into the
unified pool) into one CSV: `exchange, trader_id, nickname, pnl_usd, roi, aum_usd, followers,
win_rate, extra_json`. Everything an exchange doesn't map to a named column goes into
`extra_json` verbatim. Bybit rows have no `aum_usd` — the listing endpoint doesn't expose it.

If Bybit's `dynamic-leader-list` 403s from your host under `curl_cffi` (it does from at least one
VPS at the time of writing), `scrape_bybit.py --input <file>` will replay a JSONL of pre-fetched
page responses instead — capture them with a browser's same-origin `fetch()` on bybit.com, one
page's JSON per line. The script does not drive a browser itself.

### OKX position history (phase 1.5)

`scripts/scrape_okx_positions.py` walks the full OKX SWAP lead-trader universe — measured
2026-08-29 at **261 traders** (27 pages × 10/page) — and fetches each one's position history:

```bash
python3 scripts/scrape_okx_positions.py --pages 50 --stats  # ~5-6 min for the full universe
python3 analysis/okx_flatten.py                              # -> analysis/okx_positions.csv
python3 analysis/okx_top5.py                                 # -> ranked candidate table
```

Writes `data/okx_positions.jsonl` (one row per **closed** position), `data/okx_open_positions.jsonl`
(one row per **open** position, with unrealized `upl`), and `data/okx_positions_manifest.jsonl` (a
resumability ledger — needed because a trader with zero closed positions writes nothing to the
first file, so "already processed" can't be derived from it alone). Quirks discovered scraping the
full universe (see `docs/okx_endpoint_facts.md` for the evidence):

- `public-subpositions-history` **caps silently at 100 rows** per trader — no `page`/`limit`/
  `before`/`after` param changes the result. `okx_positions_manifest.jsonl` flags `closed_capped`
  (as of the 2026-08-29 adversarial-audit correction, this is `n_hist >= 100` — closed **+**
  still-open-from-history rows combined, not just the closed count — since that's what the
  100-row cap actually applies to).
- A minority of ranked traders return `{"code":"60004","msg":"Trader doesn't exist"}` on the
  position endpoints specifically, despite ranking and `public-stats` working fine for the same
  `uniqueCode`. Treated as terminal (not retried), not a scrape error.
- Some "history" rows have `closeTime == ""` — a realized-PnL event on a lot that's still open.
  These are excluded from "closed" and folded into `okx_open_positions.jsonl` instead.
- **`pnl` is NET of fees** — verified over 558 closed BTC-USDT-SWAP rows by reconstructing gross
  price PnL from `ctVal`: 96.6% show a positive fee residual, median 6.5 bps of notional (same
  order of magnitude as Binance's 7.85 bps).

`analysis/okx_top5.py` mirrors `top5_final.py`'s methodology (alpha vs the symbol×month×side
median, concentration guard, Trampa 1 filter) — see `analysis/TOP5_OKX.md` for the results.

### Bitget position history (phase 1.5)

`scripts/scrape_bitget_positions.py` fetches the full Bitget copy-trading leaderboard
(measured 2026-08-30 at **1,488 traders**, live `maxShowSizes` — `data.totals` on that
endpoint lies, it echoes the page size) and, for the top N by follower count (default
400), each trader's closed positions, open positions, and 90-day drawdown/native-MDD
series:

```bash
python3 scripts/scrape_bitget_positions.py --traders 400   # ~1-2h at polite pacing;
                                                             # background it, it's resumable
python3 analysis/bitget_flatten.py                          # -> analysis/bitget_positions.csv
python3 analysis/bitget_top5.py                              # -> ranked candidate table
```

Unlike Bybit or Bitget's own now-superseded v1 web endpoints (session tokens that
expire), **every** endpoint here (leaderboard, closed history, open positions, trader
detail, `cycleData`) answers plain `curl_cffi` (`impersonate='chrome'`) with no auth,
no cookies, no tokens — see `scripts/scrape_bitget_positions.py`'s docstring and the
checklist appendix for the full quirk list. Writes `data/bitget_traders.jsonl` (full
leaderboard), `data/bitget_positions.jsonl` (closed, one row per order/fill),
`data/bitget_open_positions.jsonl` (open, no verified unrealized-PnL field — same
blind spot as Bybit), `data/bitget_cycle.jsonl` (90-day ROI/PnL curves + native MDD),
and `data/bitget_manifest.jsonl` (resumability ledger with a headline cross-check
snapshot folded in per trader).

The single biggest data-quality finding: reconstructing a de-leveraged return from
`(close_avg_price/open_avg_price - 1)` disagrees in **sign** with the trader's own
`netProfit` on **10.1%** of a 455-row live sample — the same failure mode found on
Bybit (there ~16%), because `historyList` is one row per order/fill and a scaled
position's simultaneous multi-fill close doesn't split PnL proportional to each
fill's own price delta. `analysis/bitget_top5.py` uses `returnRate / openLevel`
instead (verified self-consistent against `netProfit / margin` to a median 0.8
percentage point deviation, p90 6.0pp).

**Post-audit correction (adversarial review, Fable + GLM):** the original drawdown
screen took `min()` of the raw cumulative `roiRows` curve instead of measuring an
actual peak-to-trough drawdown — 199/290 ranking-eligible traders have a genuine
>20pp drawdown the old screen missed. Fixed to three explicit hard filters (90d
peak-to-trough, 90d native MDD, lifetime `detail_mdd` on an uncovered-window basis);
four traders whose scrape got stuck on repeated timeouts and were hand-fetched with
a raw, un-normalized row shape are repaired by `scripts/bitget_repair_raw_rows.py`;
`scripts/scrape_bitget_positions.py`'s transport retry now survives a mid-page
timeout without discarding already-fetched pages. **Result: zero survivors** — see
`analysis/TOP5_BITGET.md` for the full ranking, the repair story, and the
drawdown-screen correction in detail.

## The traps in this data

Six documented ways to fool yourself, each with real cases in `SKILL.md`:

1. **Loss hiders.** Only **closed** positions are visible. Someone who never closes a loser shows
   a 98-100% hit rate and tops any naive ranking. A real case from the snapshot: **0 losers in
   174 closes**, with a 63.7% portfolio drawdown.
2. **ROI doesn't measure skill.** See above.
3. **Ranking pairs by profitability is circular.** De-leveraged, 188/197 pairs (95%) show a
   positive median return: the universe is the top-600 by ROI, they win at everything.
4. **Aggregating in USD lets account size decide.** SOL aggregates to −32,229 but its median per
   trader is **+21.2**.
5. **Binance's `mdd` is a percentage**, not a fraction (median ~30). And its headline `winRate`
   is not comparable to the win rate of closed positions: it measures a different window.
6. **Survivorship with no control group.** The universe is selected on recent performance.

And three more, of method: a row is **not** an atomic trade (13.4% are scale-in/scale-out
aggregates); never rank a trader on a single pair (within-pair estimator reliability is ~0.13,
noise); any rule with expectancy below 0.10% of notional is unusable, fees eat it (~8 bps
round-trip).

## Known limits

- **A single regime cycle.** The audited snapshot covers ~5 months: the May-June crash, the
  July-August pump. No prolonged sideways or bear market. Every "this is stable" means, at most,
  "consistent within one cycle".
- **Winner's curse.** With hundreds of candidates filtered down, expect ~half the alpha shown.
- **v1 ranks Binance only.** Phemex is scraped and ingested as a historical archive, but does not
  enter `metrics`/`rank`.
- **The real forward test is missing**, as is a validated exit rule.

## Licence

MIT — see [LICENSE](LICENSE).
