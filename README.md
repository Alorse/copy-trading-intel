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
| `scripts/` | the original scrapers + the open-positions probe |
| `docs/specs`, `docs/plans` | the pipeline's design and implementation (historical documents) |

## Requirements

- **Python ≥ 3.11** (the engine uses `datetime.UTC`).
- **Zero runtime dependencies**: stdlib only (`sqlite3`, `json`, `csv`, `urllib`, `statistics`).
- `pytest` for the tests only: `pip install -r requirements-dev.txt`.

## Quickstart

```bash
git clone https://github.com/Alorse/copy-trading-intel.git
cd copy-trading-intel
pytest                                    # 46 tests; the 4 regression ones are opt-in (see below)

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
