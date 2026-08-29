# copy-trading-refresh — Design

**Date:** 2026-08-28 · **Status:** design approved, implementation plan pending
**Prior context:** adversarial audit of the copy-trading-intel v2 skill, `analysis/FINDINGS_v2.md`, `analysis/TOP5.md`, `SKILL.md`.

## Goal

Keep an up-to-date list of the best copy-trading lead traders (Binance primarily; **Phemex is
archived but NOT ranked in v1** — see Phemex scope) with a manual run 1–2 times a month, via a
repeatable pipeline that: scrapes fresh data, analyses it with the already-audited statistical
engine, detects traders inflating their numbers, measures who improves/worsens between runs, and
publishes a machine-readable roster plus a human report. The mirroring bot consumes the roster
when the operator points it there — the pipeline does **not** execute or configure trading by
itself.

## Decisions taken (with the operator)

1. **Output:** `TOP_YYYY-MM.md` (human report) + `roster.json` (machine-readable). The operator wires up the mirror bot manually.
2. **Trend:** dated snapshots + a diff between runs, **and** intra-snapshot monthly buckets (works from run #1).
3. **Engine:** always deterministic; the adversarial LLM council (Fable/Kimi/GLM via the `adversarial-review` skill) **only** if the roster changes materially.
4. **Execution:** local, manual, via an agent skill. Future portability to a server is desirable → **zero dependencies**: Python stdlib + **SQLite** (DuckDB explicitly rejected for footprint/deps on a small host).
5. **Approach:** A+C combined — stage orchestration (A) with a SQL analytics layer (C, SQLite).

## Architecture

### Data layers

```
data/
  snapshots/YYYY-MM-DD/            ← RAW LAYER (immutable, re-ingestable)
    binance_raw.jsonl              ← raw Binance scrape
    phemex_raw.jsonl               ← raw Phemex scrape
    binance.csv  phemex.csv        ← flatten output
  copytrade.sqlite                 ← ANALYTICS LAYER (history of every run)
analysis/
  runs/YYYY-MM-DD/
    TOP_YYYY-MM.md                 ← human report
    roster.json                    ← that run's roster
    diff.json                      ← changes vs the previous run (the gate's input)
  roster.json                      ← "latest" copy of the published roster
```

- The DB is **derived**: it can be rebuilt entirely by re-ingesting `data/snapshots/`.
- Idempotent ingest: keyed on `(snapshot_date, exchange)`; re-running an ingest replaces that snapshot, never duplicates it.
- The trader universe is the **historical union** of every snapshot (individuals are followed over time, not just the current top-600). **Implementation:** `scrape` receives the known historical `trader_id`s (distinct from the DB) and also downloads the history of those no longer in the live listing — so de-copy sees a trader decay exactly as they drop out of the ranking.

### Phemex scope (v1)

Phemex is **scraped, flattened and ingested** (historical archive + the open-positions spike), but
`metrics/detect/trend/rank/report` operate on **Binance only** in v1. Reasons: Phemex's real side
lives in `pos_side` (`Long/Short/Merged` — 453 unclassifiable `Merged` rows) and its `side` is
`Buy/Sell`, so ranking it requires its own mapping, which is deferred. The Phemex `ingest` already
stores `side` mapped from `pos_side` so a future analysis does not inherit the inverted sign.

### SQLite schema

| table | grain | key columns |
|---|---|---|
| `snapshots` | run × exchange | `snapshot_date, exchange, n_traders, n_positions, notes` |
| `positions` | 1 trade | `snapshot_date, exchange, trader_id, nick, symbol, side, opened_ms, closed_ms, notional, leverage, margin, closing_pnl, price_return, alpha, dur_h, partial` |
| `open_positions` | 1 open position (if the spike works) | `snapshot_date, exchange, trader_id, symbol, side, notional, unrealized_pnl` |
| `trader_metrics` | trader × snapshot | `snapshot_date, exchange, trader_id, nick, n, alpha, t_stat, payoff, wr, conc_top1, ruin, mdd, lev_med, lev_p90, marg_med, dur_med, months_active, trend_bonus, score, tier, weight, flags` (flags = JSON array) |

Trend: SQLite window functions (`LAG ... OVER (PARTITION BY trader_id ORDER BY snapshot_date)`).
Heavy stats (t-stat, medians, per-cell benchmark) are computed in Python (as `top5_final.py` does today), not in SQL.

### Stages

```
scrape → flatten → ingest → metrics → detect → trend → rank → report → [council]
         └── RAW LAYER ───┘ └───────────── on top of SQLite ──────────┘
```

A single `pipeline.py` entrypoint with subcommands; each stage a module in `pipeline/`:

| stage | does | network | notes |
|---|---|---|---|
| `scrape` | Reuses the logic of `scripts/scrape_binance.py` and `scripts/scrape_positions.py`, adapted to write into `data/snapshots/<today>/` (NOT appending to a global jsonl). Resumable within the day's snapshot. | yes | Includes an attempt at **open** positions (spike, see below). |
| `flatten` | Refactor of `analysis/flatten.py`: nested jsonl → flat CSV in the snapshot dir. | no | |
| `ingest` | CSV → SQLite, idempotent per snapshot. | no | |
| `metrics` | Refactor of `top5_final.py` into a module: `price_return`, per-cell benchmark by symbol×month×side (median, n≥20), **alpha**, t-stat, payoff, wr, conc, ruin, lev, marg, dur, monthly buckets. Writes `trader_metrics`. | no | Core metric untouched: alpha = de-leveraged return − the cell median. |
| `detect` | The flag battery (see Criteria). Writes `flags` into `trader_metrics`. | no | |
| `trend` | Diff vs the previous snapshot(s): Δrank, Δalpha, entries/exits, de-copy rule (2 consecutive snapshots with alpha<0 → out), `style_drift`. Computes `trend_bonus`. Produces `diff.json`. | no | Run #1: intra-snapshot only (based on monthly alpha). |
| `rank` | Score + tiers + weights → `roster.json`. | no | |
| `report` | `TOP_YYYY-MM.md` with the roster, ▲▼ changes, notable exclusions with reasons, standing caveats. | no | |
| `council` | Not code: orchestrated by the agent via the `adversarial-review` skill when the gate asks for it. | LLMs | |

`pipeline.py analyze` = flatten+ingest+metrics+detect+trend+rank+report in one pass (seconds, no network).

## Detection criteria (stage `detect`)

Each criterion emits one flag per trader × snapshot. Thresholds calibrated against the real cases of the 2026-08-25 audit.

### Disqualifying (out of the roster)

| flag | signal | reference case |
|---|---|---|
| `loss_hider` | closed WR >92% with n≥20, or zero losers with n≥20 (no wr condition — a break-even does not excuse it), or (payoff <0.5 and mdd >35) | GGbond哦 (98.5% wr, mdd 50.5), Una躺平记_ (0 losers/174) |
| `open_loss_divergence` | *(if open-position data exists)* unrealised heavily negative vs realised | direct detection of the above |
| `lottery` | the BEST trade (top-1) >30% of total PnL — the audited threshold from `top5_final.py`. (Top-3>30 was rejected in adversarial review: it disqualified 5 of the 6 audited survivors, 梭哈 top-3=59.4% but top-1=26.1%.) | 龟兔赛跑985 (96.9% in 1 trade at 145x) |
| `roi_artifact` | high headline ROI with alpha ≤0 or t<2 | VickyKaushal (+5,436% ROI, alpha −0.72%) |
| `ruin_risk` | lev p90 >25x, or worst loss × median lev < −500% of margin | 牛熊摆渡人 (−1173%) |
| `not_copyable` | median marg <$50 or median duration <30 min | Scalper King ($50), 秋高看山势 ($41) |
| `insufficient` | n<60, or <40 with alpha, or <3 months active | |
| `no_alpha` | t-stat <2.5 | winner's curse: communicate "expect half the alpha shown" |

### Warnings (penalise the score, do not expel)

| flag | signal |
|---|---|
| `alpha_decay` | intra-snapshot alpha H2<H1, or the current snapshot's alpha < the previous snapshot's (applied by `trend`) |
| `inactive` | no closes in 30 days |
| `style_drift` | median lev or median marg changes >2× vs the previous snapshot |
| `regime_onesided` | alpha positive in only one sub-regime of the window |
| `mdd_high` | mdd 35–60 |

⚠️ **Binance's mdd scale: PERCENTAGE, not fractional** — median ~30.15, max ~102.7
(GGbond哦=50.5, 牛熊摆渡人=74.85). This is "Trap 5" in `SKILL.md`; the 35/60 thresholds are on
that scale. A regression test must assert the scale (snapshot median ∈ [10,60]).

### De-copy rule (lives in `trend`)
Two consecutive snapshots with negative alpha → out of the roster, regardless of other flags.

## Scoring, tiers and weights (stage `rank`)

```
score = 0.40·t_stat + 0.25·alpha·100 + 0.20·payoff + 0.15·trend_bonus
        − 10% of the score per warning flag
```

`trend_bonus`: the normalised slope of the monthly alpha (intra-snapshot on run #1; combined with the between-snapshot diff from #2 onwards).

The roster (tiers A+B) is capped at **5 traders** — the 5 highest scores among those surviving the
disqualifiers; the rest go to W.

| tier | criterion | weight |
|---|---|---|
| A — Copy | inside the top-5 by score, 0 warnings, seen in ≥2 snapshots (or n>300 on the 1st) | ~70% of the total, proportional to score |
| B — Minimum weight | passes the filters, 1–2 warnings or a short history | ~30%, capped at 10% per trader |
| W — Watchlist | promising but insufficient or mixed signals | 0% |
| X — Excluded | a disqualifying flag | 0%, reason recorded |

Weights rounded to 5%.

Edge cases: if the roster is **all tier B** (typical of run #1), the 10% cap is respected anyway
and the remainder stays **unallocated** (the sum may be <1.0; the report says so) — the excess is
never dumped onto a single trader. Only scores >0 enter the roster.
The "n>300" criterion for tier A applies only when the pipeline has a single snapshot (the first
run); afterwards, tier A requires being seen in ≥2 snapshots. `insufficient` as the sole
disqualifying flag goes to tier **W** (not X): W = newcomers/promising, X = frauds.

## Output formats

### roster.json
```json
{ "generated": "YYYY-MM-DD", "snapshot": "YYYY-MM-DD", "engine": "v1.0",
  "traders": [
    { "exchange": "binance", "portfolio_id": "…", "nick": "…",
      "tier": "A", "weight": 0.25, "score": 4.12,
      "metrics": { "alpha": 0.016, "t": 6.11, "payoff": 1.04, "lev_med": 5, "mdd": 20 },
      "warnings": ["alpha_decay"],
      "trend": { "rank_prev": 2, "rank_now": 1, "alpha_delta": -0.002 } } ],
  "removed": [ { "nick": "…", "reason": "2 snapshots alpha<0" } ] }
```

### TOP_YYYY-MM.md
The roster table with metrics · **Changes vs the previous run** (▲▼, entries/exits with reasons) ·
**Notable exclusions** (what the engine rejected and why) · **Standing caveats** (single regime
window, top-600 survivorship, winner's curse ≈ half the alpha, only closed positions visible
unless the spike works).

### diff.json (the gate's input)
Entries/exits by tier, Δweight per incumbent, new flags on incumbents, and a `material` boolean
computed by the stage itself.

## Orchestrating skill — `/copy-trading-refresh`

A personal skill living outside the repo. Runbook for the agent:

1. `cd` into the project root.
2. `python3 pipeline.py scrape` — if it fails midway, re-run (resumable). A trader whose history failed on the network is NOT marked as done (it is retried on resume).
3. `python3 pipeline.py analyze` — validates **BEFORE ingesting** (straight from the CSVs): the snapshot dir exists and is not empty, and n_traders/n_positions are within ±50% of the previous snapshot (an exchange with a previous snapshot that brings no CSV today also fails). If validation fails → exit 2 **without touching the DB**; report to the operator, `--force` only with their approval. `analyze` NEVER writes `analysis/roster.json` (the latest).
4. Read `analysis/runs/<today>/diff.json`.
5. **Gate**: `material == true` → convene the council (the `adversarial-review` skill: Fable, Kimi, GLM; each receives the diff + CSVs + a concrete question, with a mandate to refute and re-derive numbers). `material == false` → publish directly (step 7).
6. Merge the council's verdicts into `TOP_*.md` (a confirms/objects column). If the council objects to a promotion to tier A, **do not publish** that change without the operator's decision.
7. **Publish**: `python3 pipeline.py publish --date <today>` — copies the run's roster to `analysis/roster.json`. This is the ONLY step that touches the latest, and it runs only after passing the gate (or after the operator's decision if there were objections).
8. Present to the operator: the table, ▲▼, entries/exits, and the council's objections if any.

### Material change (triggers the council) — any of:
- An entry or exit in tier A.
- **Any incumbent (A or B) leaving the roster** (dropping to W/X or disappearing from the universe).
- A new disqualifying flag on a roster incumbent.
- An incumbent's weight moving by >10 points (an exit counts as prev→0).
- The first run against a new universe (e.g. a new exchange).

Incumbent↔run matching is done by **`portfolio_id`** (stable), never by nick (renameable).

## Spike included in the implementation

Probe endpoints for **open** positions:
- Binance: look for `position/current` (or similar) in the `/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/` family.
- Phemex: `position/current/v2` (confirmed to exist in SKILL.md).

If it works → `open_positions` gets filled and `open_loss_divergence` becomes a direct measurement.
If not → the WR/mdd proxy remains the headline. The spike's result is documented in the project's SKILL.

## Error handling

- Interrupted scrape → resumable within the day's snapshot.
- Broken endpoint (Binance rotates APIs without notice) → the stage fails loudly with the HTTP status; the skill reports to the operator instead of publishing a roster from partial data.
- `analyze` never touches the network; always reproducible from the raw layer.

## Out of scope (explicit YAGNI)

- Automatic cron execution (designed to be portable to a server, but not installed now).
- Direct integration with the mirror bot (the operator wires the roster up by hand).
- More exchanges than Binance + Phemex.
- A web dashboard (the report is Markdown).
- DuckDB / any dependency outside the Python stdlib.

## Testing

- Unit tests per stage with small fixtures (synthetic CSVs with known cases: a fabricated loss_hider, a lottery, a clean trader) — the detectors must flag exactly what is expected.
- Engine regression test: run `metrics`+`detect`+`rank` against the existing 2026-08-25 snapshot and verify it reproduces the known Top 5 and exclusions (VickyKaushal, GGbond哦, etc.).
- `ingest` idempotency test (double ingest = same state).
- `trend` test with two synthetic snapshots (de-copy rule, style_drift).
