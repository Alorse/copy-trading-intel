# copy-trading-refresh — Implementation Plan

> **Historical document.** This is the implementation plan that was executed (task by task,
> TDD) to build `pipeline/`. It is kept as a design record: the code and tests it describes are
> already in the repo. The `- [ ]` checkboxes are from the original tracking format.

**Goal:** A repeatable pipeline (scrape → SQLite → metrics → anti-inflation detection → trend → roster) keeping the list of lead traders to copy up to date, invocable from the `/copy-trading-refresh` skill.

**Architecture:** An immutable raw layer in `data/snapshots/YYYY-MM-DD/` + a SQLite analytics layer (`data/copytrade.sqlite`) rebuildable from the raw one. A single `pipeline.py` entrypoint with subcommands; each stage a module in `pipeline/`. The adversarial council is NOT code: the agent orchestrates it via the skill.

**Tech Stack:** Python 3 stdlib only (`sqlite3`, `json`, `csv`, `urllib`, `statistics`, `argparse`). Tests with `pytest` (dev-only). **Zero runtime dependencies** (portable to any host).

**Spec:** `docs/specs/2026-08-28-copy-trading-refresh-design.md`

## Global Constraints

- Runtime = pure stdlib. `pytest` for tests only. DuckDB explicitly rejected.
- The DB is derived: everything must be rebuildable by re-ingesting `data/snapshots/`.
- Ingest idempotent per `(snapshot_date, exchange)` — re-running replaces, never duplicates.
- `analyze` (flatten→report) never touches the network.
- The audited engine's core metric, untouched: `alpha = price_return − cell median (symbol, month, side, n≥20)`.
- Score: `0.40·t + 0.25·alpha·100 + 0.20·payoff + 0.15·trend_bonus`, −10% per warning. Only scores >0 enter the roster.
- The roster (A+B) is capped at 5 traders.
- **Binance's mdd scale: PERCENTAGE** — median ~30.15, max ~102.7 (GGbond哦=50.5). mdd thresholds ALWAYS on that scale (35/60). Verified against real data in adversarial review.
- **Concentration = top-1** (best trade / total PnL), threshold >30% — the audited criterion from `top5_final.py`. Top-3>30 was refuted: it disqualified 5/6 of the audited survivors (梭哈 top-3=59.4%, top-1=26.1%).
- **v1 analyses Binance ONLY.** Phemex is scraped/flattened/ingested (historical archive) but does not enter metrics/detect/trend/rank/report. On Phemex the real side is `pos_side` (Long/Short/Merged), not `side` (Buy/Sell) — ingest maps it for the future.
- Incumbents are matched across runs by `portfolio_id`, never by nick.
- `analyze` does not publish the latest (`analysis/roster.json`); `publish` does that, after the gate.
- All paths relative to the project root: the root of this repo.
- Exact endpoints/headers: those in `SKILL.md` (Binance `/friendly/`, Phemex `api.phemex.com`).
- Conventional-format commits, with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
pipeline.py                  ← CLI (argparse subcommands)
pipeline/
  __init__.py                ← vacío
  db.py                      ← schema, conexión, helpers
  scrape.py                  ← Binance+Phemex → data/snapshots/<date>/*_raw.jsonl (resumable)
  flatten.py                 ← *_raw.jsonl → binance.csv / phemex.csv (in the snapshot dir)
  ingest.py                  ← CSV → SQLite (idempotente)
  metrics.py                 ← price_return, alpha, t, payoff, … → trader_metrics
  detect.py                  ← flags descalificantes + warnings
  trend.py                   ← diff vs the previous snapshot, trend_bonus, diff.json
  rank.py                    ← score, tiers, weights → roster.json
  report.py                  ← TOP_YYYY-MM.md
scripts/probe_open_positions.py   ← open-positions spike (throwaway until confirmed)
tests/
  conftest.py                ← fixtures sintéticas
  test_db.py test_flatten.py test_ingest.py test_metrics.py
  test_detect.py test_trend.py test_rank.py test_report.py test_cli.py
  test_regression.py         ← against the real 2026-08-25 snapshot (marked slow)
(outside the repo)            ← runbook of the agent that invokes it
```

The historical scripts (`scripts/scrape_*.py`, `analysis/*.py`) are NOT touched or deleted: they are the reproducible evidence behind FINDINGS_v2. The new pipeline copies their logic, it does not import them.

---

### Task 1: SQLite schema + db module

**Files:**
- Create: `pipeline/__init__.py`, `pipeline/db.py`
- Test: `tests/test_db.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `db.connect(path) -> sqlite3.Connection` (creates the schema if missing, `row_factory=sqlite3.Row`, FKs ON); `db.clear_snapshot(con, snapshot_date, exchange)` (deletes that snapshot from every table); the `db.SCHEMA` constant (SQL str).

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest
from pipeline import db as dbmod

@pytest.fixture
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.sqlite")
    yield c
    c.close()
```

```python
# tests/test_db.py
from pipeline import db as dbmod

def test_connect_creates_schema(con):
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"snapshots", "positions", "trader_snapshot",
            "open_positions", "trader_metrics"} <= tables

def test_clear_snapshot_is_scoped(con):
    con.execute("INSERT INTO snapshots VALUES ('2026-01-01','binance',1,1,'')")
    con.execute("INSERT INTO snapshots VALUES ('2026-02-01','binance',1,1,'')")
    dbmod.clear_snapshot(con, "2026-01-01", "binance")
    rows = con.execute("SELECT snapshot_date FROM snapshots").fetchall()
    assert [r[0] for r in rows] == ["2026-02-01"]
```

- [ ] **Step 2: Verify it fails** — from the project root, `python3 -m pytest tests/test_db.py -v` → FAIL (`ModuleNotFoundError: pipeline`).

- [ ] **Step 3: Minimal implementation**

```python
# pipeline/db.py
"""SQLite analytics layer. The DB is derived: rebuilt from data/snapshots/."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_date TEXT NOT NULL, exchange TEXT NOT NULL,
  n_traders INTEGER, n_positions INTEGER, notes TEXT,
  PRIMARY KEY (snapshot_date, exchange));
CREATE TABLE IF NOT EXISTS trader_snapshot (
  snapshot_date TEXT NOT NULL, exchange TEXT NOT NULL,
  trader_id TEXT NOT NULL, nick TEXT,
  roi REAL, pnl REAL, aum REAL, win_rate REAL, mdd REAL,
  PRIMARY KEY (snapshot_date, exchange, trader_id));
CREATE TABLE IF NOT EXISTS positions (
  snapshot_date TEXT NOT NULL, exchange TEXT NOT NULL,
  trader_id TEXT NOT NULL, nick TEXT, symbol TEXT, side TEXT,
  opened_ms INTEGER, closed_ms INTEGER, dur_h REAL,
  notional REAL, leverage REAL, margin REAL, closing_pnl REAL,
  partial INTEGER DEFAULT 0, avg_cost REAL, avg_close REAL,
  price_return REAL, alpha REAL);
CREATE INDEX IF NOT EXISTS idx_pos_trader
  ON positions (snapshot_date, exchange, trader_id);
CREATE TABLE IF NOT EXISTS open_positions (
  snapshot_date TEXT NOT NULL, exchange TEXT NOT NULL,
  trader_id TEXT NOT NULL, symbol TEXT, side TEXT,
  notional REAL, unrealized_pnl REAL);
CREATE TABLE IF NOT EXISTS trader_metrics (
  snapshot_date TEXT NOT NULL, exchange TEXT NOT NULL,
  trader_id TEXT NOT NULL, nick TEXT,
  n INTEGER, n_alpha INTEGER, alpha REAL, t_stat REAL, payoff REAL,
  wr REAL, conc_top1 REAL, ruin REAL, mdd REAL,
  lev_med REAL, lev_p90 REAL, marg_med REAL, dur_med REAL,
  months_active INTEGER, alpha_h1 REAL, alpha_h2 REAL,
  monthly_alpha TEXT, trend_bonus REAL DEFAULT 0,
  score REAL, tier TEXT, weight REAL, flags TEXT DEFAULT '[]',
  PRIMARY KEY (snapshot_date, exchange, trader_id));
"""

TABLES = ["snapshots", "trader_snapshot", "positions",
          "open_positions", "trader_metrics"]

def connect(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con

def clear_snapshot(con, snapshot_date, exchange):
    for t in TABLES:
        con.execute(f"DELETE FROM {t} WHERE snapshot_date=? AND exchange=?",
                    (snapshot_date, exchange))
    con.commit()
```

`pipeline/__init__.py`: an empty file.

- [ ] **Step 4: Verify it passes** — `python3 -m pytest tests/test_db.py -v` → 2 PASS.

- [ ] **Step 5: Commit** — `git add pipeline/ tests/ && git commit -m "feat(db): sqlite schema and connection module"`

---

### Task 2: flatten — raw jsonl → CSV in the snapshot dir

**Files:**
- Create: `pipeline/flatten.py`
- Test: `tests/test_flatten.py`

**Interfaces:**
- Consumes: `data/snapshots/<date>/binance_raw.jsonl` and `phemex_raw.jsonl` (same line format as the current `data/binance_positions.jsonl` / `data/positions_all.jsonl`: `{"portfolioId"/"userId", "nick", ..., "positions": [...]}`).
- Produces: `flatten.flatten_snapshot(snap_dir) -> dict` with `{"binance": n_rows, "phemex": n_rows}`; writes `binance.csv` and `phemex.csv` into `snap_dir`. Binance columns: `portfolio_id,nick,p_roi,p_pnl,aum,win_rate,mdd,symbol,side,leverage,isolated,avg_cost,avg_close,closing_pnl,roi,max_oi,closed_volume,opened_ms,closed_ms,dur_h,notional,margin_est` (identical to `analysis/flatten.py`). Phemex columns: `trader_id,nick,symbol,side,pos_side,size,open_price,close_price,open_val,margin,roi,closed_pnl,realized_pnl,exchange_fee,funding_fee,opened_ms,closed_ms,dur_h`.

- [ ] **Step 1: Failing test** (with a minimal jsonl fixture)

```python
# añadir a tests/conftest.py
import json

@pytest.fixture
def snap_dir(tmp_path):
    d = tmp_path / "2026-09-01"
    d.mkdir()
    brec = {"portfolioId": "P1", "nick": "alice", "roi": 100.0, "pnl": 50.0,
            "aum": 1000.0, "winRate": 60.0, "mdd": 0.2, "n_pos": 1,
            "positions": [{"symbol": "BTCUSDT", "side": "Long", "leverage": "5",
                           "isolated": "Cross", "avgCost": "100", "avgClosePrice": "110",
                           "closingPnl": "10", "roi": "0.5", "maxOpenInterest": "2",
                           "closedVolume": "2", "opened": 1756000000000,
                           "closed": 1756003600000}]}
    prec = {"userId": 7, "nick": "bob", "n_pos": 1,
            "positions": [{"symbol": "ETHUSDT", "side": "Sell", "posSide": "Short",
                           "size": "1", "openPrice": "2000", "closePrice": "1900",
                           "openPositionVal": "2000", "margin": "200", "roi": "0.5",
                           "closedPnl": "100", "realizedPnl": "99", "exchangeFee": "1",
                           "fundingFee": "0", "openedTime": 1756000000000,
                           "updatedTime": 1756007200000}]}
    (d / "binance_raw.jsonl").write_text(json.dumps(brec) + "\n")
    (d / "phemex_raw.jsonl").write_text(json.dumps(prec) + "\n")
    return d
```

```python
# tests/test_flatten.py
import csv
from pipeline import flatten

def test_flatten_writes_both_csvs(snap_dir):
    counts = flatten.flatten_snapshot(snap_dir)
    assert counts == {"binance": 1, "phemex": 1}
    rows = list(csv.DictReader(open(snap_dir / "binance.csv")))
    assert rows[0]["portfolio_id"] == "P1"
    assert float(rows[0]["notional"]) == 200.0          # 2 * 100
    assert float(rows[0]["margin_est"]) == 40.0         # 200 / 5
    assert abs(float(rows[0]["dur_h"]) - 1.0) < 1e-9
    prows = list(csv.DictReader(open(snap_dir / "phemex.csv")))
    assert prows[0]["trader_id"] == "7"

def test_flatten_missing_file_is_zero(snap_dir):
    (snap_dir / "phemex_raw.jsonl").unlink()
    counts = flatten.flatten_snapshot(snap_dir)
    assert counts["phemex"] == 0
```

- [ ] **Step 2: Verify FAIL** — `python3 -m pytest tests/test_flatten.py -v`.

- [ ] **Step 3: Implement** — port `analysis/flatten.py` into a parameterised function:

```python
# pipeline/flatten.py
"""Flattens a snapshot's *_raw.jsonl into flat CSVs. No network."""
import json, csv, os

def _f(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

BCOLS = ['portfolio_id','nick','p_roi','p_pnl','aum','win_rate','mdd','symbol','side',
         'leverage','isolated','avg_cost','avg_close','closing_pnl','roi','max_oi',
         'closed_volume','opened_ms','closed_ms','dur_h','notional','margin_est']
PCOLS = ['trader_id','nick','symbol','side','pos_side','size','open_price','close_price',
         'open_val','margin','roi','closed_pnl','realized_pnl','exchange_fee','funding_fee',
         'opened_ms','closed_ms','dur_h']

def _flatten_binance(src, dst):
    n = 0
    with open(dst, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(BCOLS)
        for line in open(src):
            d = json.loads(line)
            for p in d['positions']:
                o, c = p.get('opened'), p.get('closed')
                dur = (c - o) / 3600000 if (o and c) else ''
                lev = _f(p.get('leverage'), 1.0) or 1.0
                notional = _f(p.get('maxOpenInterest')) * _f(p.get('avgCost'))
                w.writerow([d['portfolioId'], d.get('nick'), _f(d.get('roi')),
                            _f(d.get('pnl')), _f(d.get('aum')), _f(d.get('winRate')),
                            _f(d.get('mdd')), p.get('symbol'), p.get('side'), lev,
                            p.get('isolated'), _f(p.get('avgCost')),
                            _f(p.get('avgClosePrice')), _f(p.get('closingPnl')),
                            _f(p.get('roi')), _f(p.get('maxOpenInterest')),
                            _f(p.get('closedVolume')), o, c, dur, notional,
                            notional / lev]); n += 1
    return n

def _flatten_phemex(src, dst):
    n = 0
    with open(dst, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(PCOLS)
        for line in open(src):
            d = json.loads(line)
            for p in d['positions']:
                o = p.get('openedTime') or p.get('createdAt')
                c = p.get('updatedTime') or p.get('closedTime')
                dur = (c - o) / 3600000 if (o and c) else ''
                w.writerow([d['userId'], d['nick'], p.get('symbol'), p.get('side'),
                            p.get('posSide'), _f(p.get('size')), _f(p.get('openPrice')),
                            _f(p.get('closePrice')), _f(p.get('openPositionVal')),
                            _f(p.get('margin')), _f(p.get('roi')), _f(p.get('closedPnl')),
                            _f(p.get('realizedPnl')), _f(p.get('exchangeFee')),
                            _f(p.get('fundingFee')), o, c, dur]); n += 1
    return n

def flatten_snapshot(snap_dir):
    snap_dir = str(snap_dir)
    out = {}
    for ex, fn in (('binance', _flatten_binance), ('phemex', _flatten_phemex)):
        src = os.path.join(snap_dir, f'{ex}_raw.jsonl')
        dst = os.path.join(snap_dir, f'{ex}.csv')
        out[ex] = fn(src, dst) if os.path.exists(src) else 0
    return out
```

- [ ] **Step 4: Verify PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(flatten): raw jsonl to csv per snapshot"`

---

### Task 3: ingest — CSV → SQLite, idempotent

**Files:**
- Create: `pipeline/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `db.connect`, `db.clear_snapshot`, the CSVs from Task 2.
- Produces: `ingest.ingest_snapshot(con, snap_dir, snapshot_date) -> dict {"binance": n, "phemex": n}`. Fills `snapshots`, `trader_snapshot`, `positions`. `price_return`/`alpha` stay NULL (`metrics` sets them). Binance: `margin = margin_est`, `partial = 1 if closed_volume < max_oi`, `avg_cost/avg_close` from the CSV. Phemex: `notional = open_val`, `leverage = open_val/margin` (0 if margin=0), `closing_pnl = realized_pnl` (net), `avg_cost/avg_close` = `open_price/close_price`, and **`side` = `pos_side`** (`Long`/`Short`/`Merged` — the CSV's Buy/Sell `side` is NOT the position side; storing the right one avoids an inverted sign if Phemex is analysed later). In Phemex's `trader_snapshot`: roi/pnl/aum/win_rate/mdd = NULL. **`clear_snapshot` runs for each exchange BEFORE checking the CSV exists** — if the CSV vanished on a re-ingest, that exchange's old data must not survive.

- [ ] **Step 1: Failing test**

```python
# tests/test_ingest.py
from pipeline import flatten, ingest

def _load(con, snap_dir, date="2026-09-01"):
    flatten.flatten_snapshot(snap_dir)
    return ingest.ingest_snapshot(con, snap_dir, date)

def test_ingest_counts_and_rows(con, snap_dir):
    counts = _load(con, snap_dir)
    assert counts == {"binance": 1, "phemex": 1}
    r = con.execute("SELECT * FROM positions WHERE exchange='binance'").fetchone()
    assert r["trader_id"] == "P1" and r["notional"] == 200.0
    assert r["margin"] == 40.0 and r["partial"] == 0
    assert r["price_return"] is None
    assert r["avg_cost"] == 100.0
    p = con.execute("SELECT * FROM positions WHERE exchange='phemex'").fetchone()
    assert p["leverage"] == 10.0            # 2000/200
    assert p["closing_pnl"] == 99.0         # realized (net)
    assert p["side"] == "Short"             # pos_side, NOT the CSV's Buy/Sell
    ts = con.execute("SELECT * FROM trader_snapshot WHERE exchange='binance'").fetchone()
    assert ts["mdd"] == 0.2 and ts["nick"] == "alice"
    snaps = con.execute("SELECT * FROM snapshots ORDER BY exchange").fetchall()
    assert [(s["exchange"], s["n_traders"], s["n_positions"]) for s in snaps] == \
        [("binance", 1, 1), ("phemex", 1, 1)]

def test_ingest_is_idempotent(con, snap_dir):
    _load(con, snap_dir)
    _load(con, snap_dir)   # re-ingest of the same snapshot
    n = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert n == 2          # 1 binance + 1 phemex, no duplication
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/ingest.py
"""Snapshot CSVs -> SQLite. Idempotent per (snapshot_date, exchange)."""
import csv, os
from pipeline import db as dbmod

def _f(x, default=None):
    try: return float(x)
    except (TypeError, ValueError): return default

def _i(x):
    try: return int(float(x))
    except (TypeError, ValueError): return None

def ingest_snapshot(con, snap_dir, snapshot_date):
    snap_dir = str(snap_dir)
    counts = {}
    for ex in ('binance', 'phemex'):
        # ALWAYS clear: if the CSV vanished on a re-ingest, that exchange's old
        # data must not survive in the DB
        dbmod.clear_snapshot(con, snapshot_date, ex)
        path = os.path.join(snap_dir, f'{ex}.csv')
        if not os.path.exists(path):
            counts[ex] = 0
            continue
        traders, pos_rows, trader_rows = set(), [], {}
        for r in csv.DictReader(open(path)):
            if ex == 'binance':
                tid = r['portfolio_id']
                max_oi, cv = _f(r['max_oi'], 0), _f(r['closed_volume'], 0)
                pos_rows.append((snapshot_date, ex, tid, r['nick'], r['symbol'],
                                 r['side'], _i(r['opened_ms']), _i(r['closed_ms']),
                                 _f(r['dur_h']), _f(r['notional']), _f(r['leverage']),
                                 _f(r['margin_est']), _f(r['closing_pnl']),
                                 1 if (max_oi and cv < max_oi) else 0,
                                 _f(r['avg_cost']), _f(r['avg_close'])))
                trader_rows[tid] = (snapshot_date, ex, tid, r['nick'], _f(r['p_roi']),
                                    _f(r['p_pnl']), _f(r['aum']), _f(r['win_rate']),
                                    _f(r['mdd']))
            else:
                tid = r['trader_id']
                marg, oval = _f(r['margin'], 0), _f(r['open_val'], 0)
                lev = oval / marg if marg else 0
                # the REAL side of the position is pos_side (Long/Short/Merged);
                # the CSV's side is Buy/Sell and is NOT the position side
                pos_rows.append((snapshot_date, ex, tid, r['nick'], r['symbol'],
                                 r['pos_side'], _i(r['opened_ms']), _i(r['closed_ms']),
                                 _f(r['dur_h']), oval, lev, marg,
                                 _f(r['realized_pnl']), 0,
                                 _f(r['open_price']), _f(r['close_price'])))
                trader_rows[tid] = (snapshot_date, ex, tid, r['nick'],
                                    None, None, None, None, None)
            traders.add(tid)
        con.executemany(
            "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
            "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
            "avg_cost,avg_close) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pos_rows)
        con.executemany(
            "INSERT INTO trader_snapshot VALUES (?,?,?,?,?,?,?,?,?)",
            list(trader_rows.values()))
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?,'')",
                    (snapshot_date, ex, len(traders), len(pos_rows)))
        con.commit()
        counts[ex] = len(pos_rows)
    return counts
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): idempotent snapshot load into sqlite"`

**Note:** the `avg_cost`/`avg_close` columns are already in Task 1's schema — there is no migration to do here.

---

### Task 4: metrics — alpha, t-stat and per-trader metrics

**Files:**
- Create: `pipeline/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: the `positions` and `trader_snapshot` tables.
- Produces: `metrics.compute(con, snapshot_date, exchange='binance', min_cell=20) -> int` (the number of traders with metrics). Effects: (1) `UPDATE positions SET price_return, alpha` (over ALL rows); (2) inserts rows into `trader_metrics` with: `n, n_alpha, alpha` (mean of the alphas), `t_stat, payoff, wr, conc_top1, ruin, mdd, lev_med, lev_p90, marg_med, dur_med, months_active, alpha_h1, alpha_h2, monthly_alpha` (JSON `{"2025-04": 0.012, ...}`, months with ≥5 alphas). **Per-trader metrics are computed ONLY over valid rows (`pr` not NULL)** — same as `top5_final.py`, which drops invalid ones before counting; `n` = valid rows. `tier/weight/score/flags/trend_bonus` are filled by later stages.
- Formulas (identical to `analysis/top5_final.py`, with conc over top-3 per the spec):
  - `price_return = (avg_close/avg_cost − 1) · (+1 Long / −1 Short)`; row invalid if `avg_cost≤0 or avg_close≤0 or notional≤0 or leverage≤0 or |pr|>3` → pr/alpha NULL.
  - cell = `(symbol, month_of_opened_ms_UTC, side)`; benchmark = the cell's median pr if `n≥min_cell`; `alpha = pr − benchmark` (NULL with no benchmark).
  - `t_stat = mean(alphas) / (pstdev(alphas)/√n_alpha)` (0 if pstdev=0).
  - `payoff = mean(pr>0) / |mean(pr<0)|`; no winners or no losers → NULL (`detect` reads it).
  - `conc_top1 = best closing_pnl / total_pnl · 100` (**NULL if total ≤ 0** — a losing trader is not a "lottery"; they fall via `no_alpha`/score, not via a conc=999 that mislabels the reason) — **top-1, the audited criterion** (`top5_final.py`'s `best/tot` line); top-3 was refuted in adversarial review.
  - `ruin = min(pr) · median(leverage) · 100` (only if there are losers, otherwise NULL).
  - `alpha_h1/alpha_h2`: the mean of the first/second half of the alphas ordered by `opened_ms`.

- [ ] **Step 1: Failing test** — a synthetic fixture straight into the DB (no CSV):

```python
# tests/test_metrics.py
import json
from pipeline import metrics

D, EX = "2026-09-01", "binance"

def _pos(con, tid, sym, side, opened, cost, close, pnl, lev=5.0, nick=None):
    con.execute(
        "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
        "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
        "avg_cost,avg_close) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        (D, EX, tid, nick or tid, sym, side, opened, opened + 3600000, 1.0,
         1000.0, lev, 1000.0 / lev, pnl, cost, close))

def _seed(con):
    # 21 "crowd" traders in the cell (BTCUSDT, 2025-04, Long): pr = 0 → benchmark 0
    base = 1743500000000            # 2025-04-01 UTC (CAREFUL: 2025, not 2026)
    for i in range(21):
        _pos(con, f"m{i}", "BTCUSDT", "Long", base + i, 100, 100, 0.0)
    # trader objetivo: 5 trades, pr = +2%,+2%,+2%,+2%,-1% → alpha igual (bench 0)
    for j, (c, pnl) in enumerate([(102, 20)] * 4 + [(99, -10)]):
        _pos(con, "T", "BTCUSDT", "Long", base + 1000 + j, 100, c, pnl)
    con.execute("INSERT INTO trader_snapshot VALUES (?,?,?,?,?,?,?,?,?)",
                (D, EX, "T", "T", 50.0, 50.0, 1000.0, 75.0, 25.0))
    con.commit()

def test_alpha_and_stats(con):
    _seed(con)
    n = metrics.compute(con, D, EX, min_cell=20)
    assert n >= 1
    m = con.execute("SELECT * FROM trader_metrics WHERE trader_id='T'").fetchone()
    assert m["n"] == 5 and m["n_alpha"] == 5
    assert abs(m["alpha"] - 0.014) < 1e-9           # (.02*4 - .01)/5
    assert abs(m["payoff"] - 2.0) < 1e-9            # .02 / .01
    assert abs(m["wr"] - 80.0) < 1e-9
    assert abs(m["ruin"] - (-5.0)) < 1e-9           # -0.01 * 5 * 100
    assert m["mdd"] == 25.0                         # PERCENTAGE scale
    mo = json.loads(m["monthly_alpha"])
    assert abs(mo["2025-04"] - 0.014) < 1e-9        # month with >=5 alphas present
    pr = con.execute(
        "SELECT price_return, alpha FROM positions WHERE trader_id='T' "
        "ORDER BY opened_ms").fetchall()
    assert abs(pr[0]["price_return"] - 0.02) < 1e-9
    assert abs(pr[0]["alpha"] - 0.02) < 1e-9        # cell benchmark = 0

def test_invalid_rows_get_null_pr_and_dont_count(con):
    _seed(con)
    _pos(con, "T", "BTCUSDT", "Long", 1743500000000, 0, 110, 5)   # avg_cost 0 → invalid
    con.commit()
    metrics.compute(con, D, EX, min_cell=20)
    r = con.execute("SELECT price_return FROM positions WHERE trader_id='T' "
                    "AND avg_cost=0").fetchone()
    assert r["price_return"] is None
    m = con.execute("SELECT n FROM trader_metrics WHERE trader_id='T'").fetchone()
    assert m["n"] == 5                               # the invalid one does NOT count in n
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/metrics.py
"""Per-trader metrics engine. Mirrors top5_final.py on top of SQLite.
alpha = de-leveraged price_return - median of its cell (symbol, month, side)."""
import json, statistics as st, collections, datetime as dt

def _month(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime('%Y-%m')

def compute(con, snapshot_date, exchange='binance', min_cell=20):
    rows = con.execute(
        "SELECT rowid, trader_id, nick, symbol, side, opened_ms, avg_cost, avg_close,"
        " notional, leverage, margin, closing_pnl, dur_h FROM positions"
        " WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange)).fetchall()
    R = []
    for r in rows:
        ok = (r['avg_cost'] and r['avg_cost'] > 0 and r['avg_close'] and
              r['avg_close'] > 0 and r['notional'] and r['notional'] > 0 and
              r['leverage'] and r['leverage'] > 0 and r['opened_ms'])
        pr = None
        if ok:
            pr = (r['avg_close'] / r['avg_cost'] - 1) * \
                 (1 if r['side'] == 'Long' else -1)
            if abs(pr) > 3:
                pr = None
        R.append({'rowid': r['rowid'], 'tid': r['trader_id'], 'nick': r['nick'],
                  'sym': r['symbol'], 'side': r['side'], 'o': r['opened_ms'],
                  'pr': pr, 'pnl': r['closing_pnl'] or 0, 'lev': r['leverage'] or 0,
                  'marg': r['margin'] or 0, 'dur': r['dur_h'] or 0,
                  'month': _month(r['opened_ms']) if r['opened_ms'] else None})
    cell = collections.defaultdict(list)
    for x in R:
        if x['pr'] is not None:
            cell[(x['sym'], x['month'], x['side'])].append(x['pr'])
    bench = {k: st.median(v) for k, v in cell.items() if len(v) >= min_cell}
    upd = []
    for x in R:
        b = bench.get((x['sym'], x['month'], x['side']))
        x['alpha'] = (x['pr'] - b) if (x['pr'] is not None and b is not None) else None
        upd.append((x['pr'], x['alpha'], x['rowid']))
    con.executemany("UPDATE positions SET price_return=?, alpha=? WHERE rowid=?", upd)

    # per-trader metrics ONLY over valid rows (pr not NULL) — same as top5_final.py,
    # which drops the invalid ones before counting (n<60, cells, pnl, months)
    T = collections.defaultdict(list)
    for x in R:
        if x['pr'] is not None:
            T[x['tid']].append(x)
    snap = {r['trader_id']: r for r in con.execute(
        "SELECT * FROM trader_snapshot WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    out = []
    for tid, v in T.items():
        v.sort(key=lambda z: z['o'] or 0)
        al = [z['alpha'] for z in v if z['alpha'] is not None]
        prs = [z['pr'] for z in v if z['pr'] is not None]
        w = [p for p in prs if p > 0]; l = [p for p in prs if p < 0]
        wr = len(w) / len(prs) * 100 if prs else None
        payoff = (st.mean(w) / abs(st.mean(l))) if (w and l) else None
        tot = sum(z['pnl'] for z in v)
        best = max(z['pnl'] for z in v)
        # top-1 (the audited criterion); NULL if the trader is net negative — a
        # loser is not a "lottery", it fails via no_alpha/score
        conc = (best / tot * 100) if tot > 0 else None
        t_stat = 0.0
        if len(al) >= 2 and st.pstdev(al) > 0:
            t_stat = st.mean(al) / (st.pstdev(al) / len(al) ** .5)
        levs = sorted(z['lev'] for z in v if z['lev'])
        lev_med = st.median(levs) if levs else None
        lev_p90 = levs[int(.9 * len(levs))] if levs else None
        ruin = (min(l) * lev_med * 100) if (l and lev_med) else None
        k = len(al) // 2
        h1 = st.mean(al[:k]) if k else None
        h2 = st.mean(al[k:]) if al[k:] else None
        mo = collections.defaultdict(list)
        for z in v:
            if z['alpha'] is not None:
                mo[z['month']].append(z['alpha'])
        monthly = {m: st.mean(a) for m, a in sorted(mo.items()) if len(a) >= 5}
        s = snap.get(tid)
        out.append((snapshot_date, exchange, tid, v[0]['nick'], len(v), len(al),
                    st.mean(al) if al else None, t_stat, payoff, wr, conc, ruin,
                    s['mdd'] if s else None, lev_med, lev_p90,
                    st.median(z['marg'] for z in v) if v else None,
                    st.median(z['dur'] for z in v) if v else None,
                    len(set(z['month'] for z in v if z['month'])), h1, h2,
                    json.dumps(monthly)))
    con.executemany(
        "INSERT OR REPLACE INTO trader_metrics (snapshot_date,exchange,trader_id,nick,"
        "n,n_alpha,alpha,t_stat,payoff,wr,conc_top1,ruin,mdd,lev_med,lev_p90,marg_med,"
        "dur_med,months_active,alpha_h1,alpha_h2,monthly_alpha) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.commit()
    return len(out)
```

- [ ] **Step 4: PASS.** If an assert fails, the bug is in the implementation or in the fixture's arithmetic — fix the CAUSE, never weaken the assert.
- [ ] **Step 5: Commit** — `git commit -m "feat(metrics): per-cell alpha, t-stat, payoff and per-trader metrics"`

---

### Task 5: detect — disqualifying flags and warnings

**Files:**
- Create: `pipeline/detect.py`
- Test: `tests/test_detect.py`

**Interfaces:**
- Consumes: `trader_metrics` (Task 4), `open_positions` (may be empty).
- Produces: `detect.run(con, snapshot_date, exchange='binance') -> dict {trader_id: [flags]}`; writes `trader_metrics.flags` (JSON array). Exported constants: `detect.DISQUALIFYING = {"loss_hider","open_loss_divergence","lottery","roi_artifact","ruin_risk","not_copyable","insufficient","no_alpha"}` y `detect.WARNINGS = {"alpha_decay","inactive","style_drift","regime_onesided","mdd_high"}`.
- Rules (threshold → flag), evaluated in this order; a trader can accumulate several:
  - `insufficient`: `n<60 or n_alpha<40 or months_active<3`
  - `loss_hider`: `(wr>92 and n≥20) or (payoff is NULL and n≥20) or (payoff<0.5 and mdd>35)` — the zero-losers branch does NOT require `wr==100` (a break-even trade gives wr<100 with zero real losers; the Una躺平记_ case must still be caught)
  - `open_loss_divergence`: the trader has rows in `open_positions` with `sum(unrealized_pnl) < −2 × max(1, total_realised_pnl)` (only if open-position data exists)
  - `lottery`: `conc_top1 > 30` (top-1, the audited criterion)
  - `roi_artifact`: `headline_roi > 300` (%) and (`alpha ≤ 0 or t_stat < 2`) — roi from `trader_snapshot.roi`
  - `ruin_risk`: `lev_p90 > 25 or ruin < −500`
  - `not_copyable`: `marg_med < 50 or dur_med < 0.5`
  - `no_alpha`: `t_stat < 2.5`
  - `mdd_high` (warning): `35 ≤ mdd ≤ 60` — **PERCENTAGE scale** (real median ~30.15, GGbond哦=50.5; "Trap 5" in SKILL.md). No loss_hider guard (the spec does not ask for one).
  - `alpha_decay` (warning): `alpha_h2 < alpha_h1` (neither NULL). The cross-snapshot half is applied by `trend` (Task 6).
  - `inactive` (warning): no positions with `closed_ms` within the last 30 days of the snapshot's maximum `closed_ms`
  - `style_drift` does NOT go here — it lives in `trend` (Task 6); `regime_onesided`: monthly alpha (from `monthly_alpha`) positive in <50% of the months with data, with ≥2 months.

- [ ] **Step 1: Failing test**

```python
# tests/test_detect.py
import json
from pipeline import detect

D, EX = "2026-09-01", "binance"

def _tm(con, tid, **kw):
    # mdd on a PERCENTAGE scale (like Binance's real data)
    base = dict(n=100, n_alpha=80, alpha=0.01, t_stat=3.0, payoff=1.2, wr=70.0,
                conc_top1=20.0, ruin=-100.0, mdd=20.0, lev_med=5, lev_p90=10,
                marg_med=500.0, dur_med=4.0, months_active=4, alpha_h1=0.01,
                alpha_h2=0.012, monthly_alpha='{"2025-04":0.01,"2025-05":0.012}')
    base.update(kw)
    cols = ",".join(base)
    con.execute(
        f"INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,{cols}) "
        f"VALUES (?,?,?,?,{','.join('?'*len(base))})",
        (D, EX, tid, tid, *base.values()))
    con.execute("INSERT INTO trader_snapshot VALUES (?,?,?,?,?,?,?,?,?)",
                (D, EX, tid, tid, 50.0, 0, 0, 0, base["mdd"]))
    # a recent position so `inactive` is not triggered
    con.execute(
        "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
        "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
        "avg_cost,avg_close) VALUES (?,?,?,?, 'BTCUSDT','Long',1,1000,1,1,1,1,0,0,1,1)",
        (D, EX, tid, tid))
    con.commit()

def test_clean_trader_no_flags(con):
    _tm(con, "clean")
    flags = detect.run(con, D, EX)
    assert flags["clean"] == []

def test_loss_hider_high_wr(con):
    _tm(con, "gg", wr=98.5, mdd=50.5)               # GGbond哦 case, % scale
    assert "loss_hider" in detect.run(con, D, EX)["gg"]

def test_loss_hider_zero_losers_with_breakeven(con):
    # Una躺平记_ case: zero losers (payoff NULL) but wr<100 because of a break-even
    _tm(con, "una", payoff=None, wr=99.4)
    assert "loss_hider" in detect.run(con, D, EX)["una"]

def test_lottery(con):
    _tm(con, "rabbit", conc_top1=96.9)              # 龟兔赛跑985: top-1 96.9%
    assert "lottery" in detect.run(con, D, EX)["rabbit"]

def test_roi_artifact(con):
    _tm(con, "vicky", alpha=-0.007, t_stat=-2.88)
    con.execute("UPDATE trader_snapshot SET roi=5435.9 WHERE trader_id='vicky'")
    con.commit()
    f = detect.run(con, D, EX)["vicky"]
    assert "roi_artifact" in f and "no_alpha" in f

def test_ruin_risk(con):
    _tm(con, "bull", lev_p90=40, ruin=-1173.0)
    assert "ruin_risk" in detect.run(con, D, EX)["bull"]

def test_not_copyable(con):
    _tm(con, "scalper", marg_med=41.0)
    assert "not_copyable" in detect.run(con, D, EX)["scalper"]

def test_insufficient(con):
    _tm(con, "newbie", n=30, n_alpha=20)
    assert "insufficient" in detect.run(con, D, EX)["newbie"]

def test_warnings(con):
    _tm(con, "decay", alpha_h1=0.0195, alpha_h2=0.0137, mdd=40.0)
    f = detect.run(con, D, EX)["decay"]
    assert "alpha_decay" in f and "mdd_high" in f
    assert not (set(f) & detect.DISQUALIFYING)

def test_flags_persisted(con):
    _tm(con, "gg", wr=98.5, mdd=50.5)
    detect.run(con, D, EX)
    row = con.execute(
        "SELECT flags FROM trader_metrics WHERE trader_id='gg'").fetchone()
    assert "loss_hider" in json.loads(row["flags"])
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/detect.py
"""Anti-inflation battery. Each rule emits one flag per trader.
Reference cases: FINDINGS_v2.md / TOP5.md (GGbond, VickyKaushal, etc.)."""
import json

DISQUALIFYING = {"loss_hider", "open_loss_divergence", "lottery", "roi_artifact",
                 "ruin_risk", "not_copyable", "insufficient", "no_alpha"}
WARNINGS = {"alpha_decay", "inactive", "style_drift", "regime_onesided", "mdd_high"}

def run(con, snapshot_date, exchange='binance'):
    ms = con.execute("SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
                     (snapshot_date, exchange)).fetchall()
    roi = {r['trader_id']: r['roi'] for r in con.execute(
        "SELECT trader_id, roi FROM trader_snapshot WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    maxclose = con.execute(
        "SELECT MAX(closed_ms) FROM positions WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange)).fetchone()[0] or 0
    last_close = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, MAX(closed_ms) FROM positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    unreal = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, SUM(unrealized_pnl) FROM open_positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    realized = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, SUM(closing_pnl) FROM positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    out = {}
    for m in ms:
        f = []
        tid = m['trader_id']
        n, na = m['n'] or 0, m['n_alpha'] or 0
        if n < 60 or na < 40 or (m['months_active'] or 0) < 3:
            f.append('insufficient')
        wr, payoff, mdd = m['wr'], m['payoff'], m['mdd']
        # mdd en escala PORCENTUAL (mediana ~30, GGbond=50.5) — Trampa 5 de SKILL.md
        if n >= 20 and ((wr is not None and wr > 92) or
                        payoff is None or
                        (payoff is not None and payoff < 0.5
                         and mdd is not None and mdd > 35)):
            f.append('loss_hider')
        u = unreal.get(tid)
        if u is not None and u < -2 * max(1.0, realized.get(tid) or 0):
            f.append('open_loss_divergence')
        if (m['conc_top1'] or 0) > 30:
            f.append('lottery')
        r = roi.get(tid)
        if r is not None and r > 300 and ((m['alpha'] or 0) <= 0 or (m['t_stat'] or 0) < 2):
            f.append('roi_artifact')
        if (m['lev_p90'] or 0) > 25 or (m['ruin'] is not None and m['ruin'] < -500):
            f.append('ruin_risk')
        if (m['marg_med'] is not None and m['marg_med'] < 50) or \
           (m['dur_med'] is not None and m['dur_med'] < 0.5):
            f.append('not_copyable')
        if (m['t_stat'] or 0) < 2.5:
            f.append('no_alpha')
        # warnings
        if mdd is not None and 35 <= mdd <= 60:
            f.append('mdd_high')
        if m['alpha_h1'] is not None and m['alpha_h2'] is not None \
           and m['alpha_h2'] < m['alpha_h1']:
            f.append('alpha_decay')
        lc = last_close.get(tid)
        if lc is not None and maxclose and lc < maxclose - 30 * 86400000:
            f.append('inactive')
        monthly = json.loads(m['monthly_alpha'] or '{}')
        if len(monthly) >= 2:
            pos = sum(1 for v in monthly.values() if v > 0)
            if pos / len(monthly) < 0.5:
                f.append('regime_onesided')
        con.execute("UPDATE trader_metrics SET flags=? WHERE snapshot_date=? "
                    "AND exchange=? AND trader_id=?",
                    (json.dumps(f), snapshot_date, exchange, tid))
        out[tid] = f
    con.commit()
    return out
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(detect): anti-inflation flags (loss_hider, lottery, roi_artifact, ...)"`

---

### Task 6: trend — diff between snapshots, de-copy and trend_bonus

**Files:**
- Create: `pipeline/trend.py`
- Test: `tests/test_trend.py`

**Interfaces:**
- Consumes: `trader_metrics` from ≥1 snapshots; `detect.DISQUALIFYING`.
- Produces: `trend.run(con, snapshot_date, exchange='binance', prev_roster=None) -> dict` (the contents of `diff.json`). Effects: updates `trader_metrics.trend_bonus` and adds `style_drift` / decopy flags to `flags`. `prev_roster` = a dict loaded from the previous run's `roster.json`, or None.
- Logic:
  - `prev_date` = the greatest `snapshot_date < snapshot_date` in `snapshots` for that exchange (None if there is none).
  - **trend_bonus**: least-squares slope of `monthly_alpha` (ordered by month, index 0..k-1), `slope·100` clamped to [−2, +2]; 0 with <3 months of data. If there is a `prev_date`, the simple average of that value and `sign(alpha_now − alpha_prev)` (+1/−1/0, clamped the same): `bonus = clamp((slope·100 + sign)/2, −2, 2)`.
  - **de-copy** (disqualifying flag `decopy_2neg` — do NOT add it to `detect.DISQUALIFYING`: it is treated as trend's own disqualifier; `rank` excludes `DISQUALIFYING | {"decopy_2neg"}`): `alpha<0` in this snapshot **and** in `prev_date`.
  - **cross-snapshot alpha_decay** (the half of the spec detect does not cover): `alpha_now < alpha_prev` → adds the `alpha_decay` warning if absent.
  - **style_drift** (warning): `lev_med` or `marg_med` changes >2× or <0.5× vs `prev_date` (neither NULL nor 0).
  - **Fresh flags**: `newly_disq` is computed from the flags ALREADY updated in this run (an in-memory dict), never from the initial fetch — otherwise the very `decopy_2neg` that trend adds would be invisible to the gate.
  - **Matching by `portfolio_id`** against `prev_roster` (the nick can be renamed).
  - **diff.json**: `{"snapshot": date, "prev": prev_date, "added_a": [], "removed_a": [], "new_disqualified_incumbents": [{"nick","flags"}], "weight_moves": [{"nick","prev","now"}], "material": bool}` — the roster fields (`added_a`, `removed_a`, `weight_moves`) are filled by `rank` after assigning tiers (trend leaves empty lists and a provisional `material`); `material = true` if `prev_date is None` (first run) or if any `prev_roster` incumbent picked up a new disqualifying flag. `rank` re-evaluates `material` with the tier/weight changes.

- [ ] **Step 1: Failing test**

```python
# tests/test_trend.py
import json
from pipeline import trend

EX = "binance"

def _tm(con, date, tid, alpha, lev=5.0, marg=500.0,
        monthly='{"2026-04":0.002,"2026-05":0.015,"2026-06":0.017}', flags='[]'):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,n_alpha,"
        "alpha,t_stat,lev_med,marg_med,monthly_alpha,flags) "
        "VALUES (?,?,?,?,100,80,?,3.0,?,?,?,?)",
        (date, EX, tid, tid, alpha, lev, marg, monthly, flags))
    con.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,1,1,'')", (date, EX))
    con.commit()

def test_first_run_is_material(con):
    _tm(con, "2026-09-01", "A", 0.01)
    d = trend.run(con, "2026-09-01", EX)
    assert d["prev"] is None and d["material"] is True

def test_trend_bonus_from_monthly_slope(con):
    _tm(con, "2026-09-01", "A", 0.01)   # positive slope in monthly
    trend.run(con, "2026-09-01", EX)
    tb = con.execute("SELECT trend_bonus FROM trader_metrics "
                     "WHERE trader_id='A'").fetchone()[0]
    assert tb > 0

def test_decopy_two_negative_snapshots_and_gate_sees_it(con):
    _tm(con, "2026-08-01", "B", -0.005)
    _tm(con, "2026-09-01", "B", -0.003)
    prev_roster = {"traders": [{"portfolio_id": "B", "nick": "B",
                                "tier": "B", "weight": 0.1}]}
    d = trend.run(con, "2026-09-01", EX, prev_roster=prev_roster)
    flags = json.loads(con.execute(
        "SELECT flags FROM trader_metrics WHERE trader_id='B' "
        "AND snapshot_date='2026-09-01'").fetchone()[0])
    assert "decopy_2neg" in flags
    # the gate sees the flag ADDED IN THIS RUN (not stale flags from the initial fetch)
    assert d["new_disqualified_incumbents"][0]["portfolio_id"] == "B"
    assert d["material"] is True

def test_alpha_decay_between_snapshots(con):
    _tm(con, "2026-08-01", "E", 0.020)
    _tm(con, "2026-09-01", "E", 0.012)     # positive but declining
    trend.run(con, "2026-09-01", EX)
    flags = json.loads(con.execute(
        "SELECT flags FROM trader_metrics WHERE trader_id='E' "
        "AND snapshot_date='2026-09-01'").fetchone()[0])
    assert "alpha_decay" in flags

def test_style_drift(con):
    _tm(con, "2026-08-01", "C", 0.01, lev=5.0)
    _tm(con, "2026-09-01", "C", 0.01, lev=12.0)   # 2.4x
    trend.run(con, "2026-09-01", EX)
    flags = json.loads(con.execute(
        "SELECT flags FROM trader_metrics WHERE trader_id='C' "
        "AND snapshot_date='2026-09-01'").fetchone()[0])
    assert "style_drift" in flags

def test_incumbent_disqualified_is_material(con):
    _tm(con, "2026-08-01", "D", 0.02)
    _tm(con, "2026-09-01", "D", 0.02, flags='["loss_hider"]')
    prev_roster = {"traders": [{"portfolio_id": "D", "nick": "D",
                                "tier": "A", "weight": 0.3}]}
    d = trend.run(con, "2026-09-01", EX, prev_roster=prev_roster)
    assert d["material"] is True
    assert d["new_disqualified_incumbents"][0]["portfolio_id"] == "D"
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/trend.py
"""Compares snapshots: who improves, who decays, de-copy and style_drift."""
import json
from pipeline import detect as det

def _clamp(x, lo=-2.0, hi=2.0):
    return max(lo, min(hi, x))

def _slope(monthly):
    ys = [v for _, v in sorted(monthly.items())]
    k = len(ys)
    if k < 3:
        return None
    xs = list(range(k))
    mx, my = sum(xs) / k, sum(ys) / k
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0

def run(con, snapshot_date, exchange='binance', prev_roster=None):
    prev = con.execute(
        "SELECT MAX(snapshot_date) FROM snapshots WHERE exchange=? AND snapshot_date<?",
        (exchange, snapshot_date)).fetchone()[0]
    cur = {r['trader_id']: r for r in con.execute(
        "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    old = {}
    if prev:
        old = {r['trader_id']: r for r in con.execute(
            "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
            (prev, exchange))}
    updated = {}                      # FRESH post-update flags (avoids reading stale)
    for tid, m in cur.items():
        flags = json.loads(m['flags'] or '[]')
        s = _slope(json.loads(m['monthly_alpha'] or '{}'))
        bonus = _clamp(s * 100) if s is not None else 0.0
        o = old.get(tid)
        if o is not None:
            if m['alpha'] is not None and o['alpha'] is not None:
                sign = (m['alpha'] > o['alpha']) - (m['alpha'] < o['alpha'])
                bonus = _clamp((bonus + sign) / 2)
                if m['alpha'] < 0 and o['alpha'] < 0 and 'decopy_2neg' not in flags:
                    flags.append('decopy_2neg')
                # cross-snapshot half of alpha_decay (spec): alpha fell vs prev
                if m['alpha'] < o['alpha'] and 'alpha_decay' not in flags:
                    flags.append('alpha_decay')
            for col in ('lev_med', 'marg_med'):
                a, b = m[col], o[col]
                if a and b and (a / b > 2 or a / b < 0.5) and 'style_drift' not in flags:
                    flags.append('style_drift')
        updated[tid] = flags
        con.execute("UPDATE trader_metrics SET trend_bonus=?, flags=? "
                    "WHERE snapshot_date=? AND exchange=? AND trader_id=?",
                    (bonus, json.dumps(flags), snapshot_date, exchange, tid))
    con.commit()
    newly_disq = []
    if prev_roster:
        # matched by portfolio_id (stable) — the nick can be renamed
        for t in prev_roster.get('traders', []):
            tid = t.get('portfolio_id')
            if tid not in updated:
                continue
            bad = set(updated[tid]) & (det.DISQUALIFYING | {'decopy_2neg'})
            if bad:
                newly_disq.append({'portfolio_id': tid, 'nick': t['nick'],
                                   'flags': sorted(bad)})
    return {'snapshot': snapshot_date, 'prev': prev,
            'added_a': [], 'removed_a': [], 'weight_moves': [],
            'new_disqualified_incumbents': newly_disq,
            'material': prev is None or bool(newly_disq)}
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(trend): diff between snapshots, de-copy rule and trend_bonus"`

---

### Task 7: rank — score, tiers, weights and roster.json

**Files:**
- Create: `pipeline/rank.py`
- Test: `tests/test_rank.py`

**Interfaces:**
- Consumes: `trader_metrics` with flags and trend_bonus; `detect.DISQUALIFYING`; the diff from `trend.run`; `prev_roster` (a dict or None); the number of snapshots each trader has been seen in (`SELECT COUNT(DISTINCT snapshot_date) FROM trader_metrics WHERE trader_id=?`).
- Produces: `rank.run(con, snapshot_date, exchange='binance', diff=None, prev_roster=None) -> dict` (the roster, in the spec's format). Effects: `UPDATE trader_metrics SET score, tier, weight`; fills `diff["added_a"/"removed_a"/"weight_moves"]` and re-evaluates `diff["material"]`.
- Algorithm:
  1. Survivors = no flag in `DISQUALIFYING | {"decopy_2neg"}` **and score > 0**.
  2. `score = 0.40·t_stat + 0.25·alpha·100 + 0.20·(payoff or 0) + 0.15·trend_bonus`; then `score ·= (0.9 ** n_warnings)` (warnings = flags ∩ `detect.WARNINGS`).
  3. Roster = top-5 by score. Tier A: 0 warnings **and** (seen in ≥2 snapshots **or** (n>300 **and it is the pipeline's first run** — a single snapshot in the DB)). Tier B: the rest of the top-5. Tier W: survivors outside the top-5 **and** those whose ONLY disqualifying flag is `insufficient` (newcomers, not frauds). Tier X: the remaining disqualified.
  4. Weights: with both A and B → pool A 0.70 / pool B 0.30; A only → 1.0. **B only (typical of run #1): each B is capped at 0.10 and the remainder stays UNALLOCATED** (sum < 1.0, declared by the roster in `unallocated`) — the excess is never dumped onto a single trader. Within the group, proportional to score; B's cap excess is redistributed to A only if A exists. Round to multiples of 0.05; the rounding adjustment goes to A's largest weight (or is skipped if there is no A).
  5. `removed` in the roster: `prev_roster` incumbents (by `portfolio_id`) no longer in A∪B, with `reason` = disqualifying flags or "out of the top-5 by score".
  6. Additional materiality: an entry/exit in tier A vs prev_roster, **any incumbent (A or B) leaving the roster**, or |Δweight|>0.10 for an incumbent (an exit counts as prev→0).
  7. Every roster trader carries `trend`: `{"rank_prev", "rank_now", "alpha_delta"}` — rank by score within the previous snapshot (`trader_metrics` at `prev_date`, NULL if they did not exist) and the alpha delta.

- [ ] **Step 1: Failing test**

```python
# tests/test_rank.py
from pipeline import rank

EX, D = "binance", "2026-09-01"

def _tm(con, tid, t=4.0, alpha=0.015, payoff=1.2, tb=0.5, n=400, flags='[]'):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,n_alpha,"
        "alpha,t_stat,payoff,trend_bonus,flags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (D, EX, tid, tid, n, n, alpha, t, payoff, tb, flags))
    con.commit()

def test_score_formula_and_warning_penalty(con):
    _tm(con, "A")                                   # clean
    _tm(con, "B", flags='["alpha_decay"]')          # 1 warning
    r = rank.run(con, D, EX)
    sa = next(t for t in r["traders"] if t["nick"] == "A")["score"]
    sb = next(t for t in r["traders"] if t["nick"] == "B")["score"]
    expected = 0.40*4.0 + 0.25*1.5 + 0.20*1.2 + 0.15*0.5
    assert abs(sa - expected) < 1e-9
    assert abs(sb - expected*0.9) < 1e-9

def test_disqualified_excluded_and_cap5(con):
    for i in range(7):
        _tm(con, f"t{i}", t=5.0 - i*0.2)
    _tm(con, "bad", t=9.9, flags='["loss_hider"]')
    r = rank.run(con, D, EX)
    nicks = [t["nick"] for t in r["traders"]]
    assert "bad" not in nicks and len(nicks) == 5
    assert nicks[0] == "t0"                          # highest score first

def test_tiers_and_weights(con):
    _tm(con, "vet", n=400)                           # A (n>300, 0 warnings)
    _tm(con, "rookie", n=100, flags='["alpha_decay"]')  # B
    r = rank.run(con, D, EX)
    by = {t["nick"]: t for t in r["traders"]}
    assert by["vet"]["tier"] == "A" and by["rookie"]["tier"] == "B"
    assert abs(sum(t["weight"] for t in r["traders"]) - 1.0) < 1e-9
    assert by["rookie"]["weight"] <= 0.10 + 1e-9
    assert all(abs(t["weight"] * 20 - round(t["weight"] * 20)) < 1e-6
               for t in r["traders"])                # multiples of 0.05

def test_material_on_tier_a_change(con):
    _tm(con, "vet", n=400)
    diff = {"material": False, "added_a": [], "removed_a": [], "weight_moves": []}
    prev = {"traders": [{"portfolio_id": "otro", "nick": "otro",
                         "tier": "A", "weight": 0.5}]}
    rank.run(con, D, EX, diff=diff, prev_roster=prev)
    assert "vet" in diff["added_a"] and "otro" in diff["removed_a"]
    # the incumbent's exit also shows up as a weight_move prev->0
    assert any(m["nick"] == "otro" and m["now"] == 0.0
               for m in diff["weight_moves"])
    assert diff["material"] is True

def test_weights_all_B_respects_cap_and_leaves_unallocated(con):
    # typical run #1: nobody qualifies for tier A (everyone has a warning)
    for i in range(5):
        _tm(con, f"b{i}", t=4.0 - i * 0.1, n=100, flags='["alpha_decay"]')
    r = rank.run(con, D, EX)
    assert all(t["tier"] == "B" for t in r["traders"])
    assert all(t["weight"] <= 0.10 + 1e-9 for t in r["traders"])   # cap ALWAYS
    assert abs(sum(t["weight"] for t in r["traders"]) - 0.50) < 1e-9
    assert abs(r["unallocated"] - 0.50) < 1e-9   # remainder declared, not dumped

def test_insufficient_only_goes_to_W_not_X(con):
    _tm(con, "newbie_ins", n=30, flags='["insufficient"]')
    _tm(con, "fraud", n=100, flags='["loss_hider"]')
    rank.run(con, D, EX)
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    assert tiers["newbie_ins"] == "W" and tiers["fraud"] == "X"
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/rank.py
"""Score, tiers and weights -> roster. Capped at 5 traders (A+B).
Runs are ALWAYS matched by portfolio_id (the nick can be renamed)."""
import json, datetime as dt
from pipeline import detect as det

BAD = det.DISQUALIFYING | {'decopy_2neg'}

def _round05(x):
    return round(x * 20) / 20

def _weights(roster):
    """A and B: 70/30 pools. A only: pool 1.0. B only: cap of 0.10 each and the
    remainder stays UNALLOCATED (sums < 1.0) — never dumped onto a single one.
    Returns the unallocated weight."""
    A = [t for t in roster if t['tier'] == 'A']
    B = [t for t in roster if t['tier'] == 'B']
    poolA = 1.0 if (A and not B) else 0.70
    poolB = 0.30 if A else 1.0
    for grp, pool in ((A, poolA), (B, poolB)):
        tot = sum(t['score'] for t in grp)
        for t in grp:
            t['weight'] = pool * t['score'] / tot if tot else 0.0
    # iterative cap on B: the excess is spread within B among the uncapped ones
    for _ in range(len(B)):
        excess = sum(max(0.0, t['weight'] - 0.10) for t in B)
        if excess < 1e-9:
            break
        for t in B:
            t['weight'] = min(t['weight'], 0.10)
        free = [t for t in B if t['weight'] < 0.10 - 1e-9]
        if not free:
            break
        tot = sum(t['score'] for t in free)
        for t in free:
            t['weight'] += excess * t['score'] / tot if tot else 0.0
    for t in B:
        t['weight'] = min(t['weight'], 0.10)
    b_excess = poolB - sum(t['weight'] for t in B) if B else 0.0
    if A and b_excess > 1e-9:                 # B's excess goes to A if A exists
        totA = sum(t['weight'] for t in A)
        for t in A:
            t['weight'] += b_excess * t['weight'] / totA if totA else 0.0
    for t in roster:
        t['weight'] = _round05(t['weight'])
    assigned = sum(t['weight'] for t in roster)
    drift = 1.0 - assigned
    if A and abs(drift) > 1e-9:               # rounding adjustment ONLY on A
        mx = max(A, key=lambda t: t['weight'])
        mx['weight'] = _round05(mx['weight'] + drift)
        assigned = sum(t['weight'] for t in roster)
    return max(0.0, round(1.0 - assigned, 2))  # unallocated (B-only leaves it >0)

def run(con, snapshot_date, exchange='binance', diff=None, prev_roster=None):
    ms = con.execute("SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
                     (snapshot_date, exchange)).fetchall()
    seen = {r[0]: r[1] for r in con.execute(
        "SELECT trader_id, COUNT(DISTINCT snapshot_date) FROM trader_metrics "
        "WHERE exchange=? GROUP BY trader_id", (exchange,))}
    total_snaps = con.execute(
        "SELECT COUNT(DISTINCT snapshot_date) FROM snapshots WHERE exchange=?",
        (exchange,)).fetchone()[0]
    prev_date = con.execute(
        "SELECT MAX(snapshot_date) FROM snapshots WHERE exchange=? AND snapshot_date<?",
        (exchange, snapshot_date)).fetchone()[0]
    prev_m = {}
    if prev_date:
        prev_m = {r['trader_id']: r for r in con.execute(
            "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
            (prev_date, exchange))}
    cands = []
    for m in ms:
        flags = set(json.loads(m['flags'] or '[]'))
        warns = flags & det.WARNINGS
        score = (0.40 * (m['t_stat'] or 0) + 0.25 * (m['alpha'] or 0) * 100 +
                 0.20 * (m['payoff'] or 0) + 0.15 * (m['trend_bonus'] or 0))
        score *= 0.9 ** len(warns)
        cands.append({'tid': m['trader_id'], 'nick': m['nick'], 'score': score,
                      'flags': flags, 'warns': warns, 'm': m,
                      'disq': bool(flags & BAD)})
    surv = sorted((c for c in cands if not c['disq'] and c['score'] > 0),
                  key=lambda c: -c['score'])
    roster = surv[:5]
    for c in roster:
        # n>300 stands in for history ONLY on the pipeline's first run
        c['tier'] = 'A' if (not c['warns'] and
                            (seen.get(c['tid'], 1) >= 2 or
                             (total_snaps <= 1 and (c['m']['n'] or 0) > 300))) \
                    else 'B'
    unallocated = _weights(roster)
    # previous snapshot's rank by score (for the roster's trend block)
    prev_rank = {}
    if prev_m:
        ordered = sorted(prev_m.values(),
                         key=lambda r: -(r['score'] if r['score'] is not None else -1e9))
        prev_rank = {r['trader_id']: i + 1 for i, r in enumerate(ordered)}
    in_roster = {c['tid'] for c in roster}
    for c in cands:
        if c['tid'] in in_roster:
            tier = c['tier']
        elif c['flags'] & BAD == {'insufficient'}:
            tier = 'W'                        # newcomer, not fraud (spec)
        elif c['disq']:
            tier = 'X'
        else:
            tier = 'W'
        c['final_tier'] = tier
        con.execute("UPDATE trader_metrics SET score=?, tier=?, weight=? "
                    "WHERE snapshot_date=? AND exchange=? AND trader_id=?",
                    (c['score'], tier, c.get('weight', 0.0),
                     snapshot_date, exchange, c['tid']))
    con.commit()
    out_traders = []
    for i, c in enumerate(roster):
        m = c['m']
        p = prev_m.get(c['tid'])
        out_traders.append({
            'exchange': exchange, 'portfolio_id': c['tid'], 'nick': c['nick'],
            'tier': c['tier'], 'weight': c['weight'], 'score': round(c['score'], 3),
            'metrics': {'alpha': m['alpha'], 't': m['t_stat'], 'payoff': m['payoff'],
                        'lev_med': m['lev_med'], 'mdd': m['mdd'], 'n': m['n']},
            'warnings': sorted(c['warns']),
            'trend': {'rank_prev': prev_rank.get(c['tid']), 'rank_now': i + 1,
                      'alpha_delta': (round(m['alpha'] - p['alpha'], 6)
                                      if p and p['alpha'] is not None
                                      and m['alpha'] is not None else None)}})
    removed = []
    if prev_roster:
        now_ids = {t['portfolio_id'] for t in out_traders}
        by_id = {c['tid']: c for c in cands}
        for t in prev_roster.get('traders', []):
            pid = t.get('portfolio_id')
            if pid in now_ids:
                continue
            c = by_id.get(pid)
            reason = (', '.join(sorted(c['flags'] & BAD)) if c and (c['flags'] & BAD)
                      else 'out of the top-5 by score' if c else 'out of the universe')
            removed.append({'portfolio_id': pid, 'nick': t['nick'], 'reason': reason})
    if diff is not None:
        prev_traders = (prev_roster or {}).get('traders', [])
        prev_a = {t['portfolio_id'] for t in prev_traders if t.get('tier') == 'A'}
        now_a = {t['portfolio_id'] for t in out_traders if t['tier'] == 'A'}
        id2nick = {t['portfolio_id']: t['nick'] for t in out_traders + prev_traders}
        diff['added_a'] = sorted(id2nick.get(i, i) for i in now_a - prev_a)
        diff['removed_a'] = sorted(id2nick.get(i, i) for i in prev_a - now_a)
        now_w = {t['portfolio_id']: t['weight'] for t in out_traders}
        moves = []
        for t in prev_traders:               # titulares: cambio o SALIDA (prev→0)
            pid = t.get('portfolio_id')
            w_now = now_w.get(pid, 0.0)
            if abs(w_now - t.get('weight', 0)) > 0.10 or pid not in now_w:
                moves.append({'nick': t['nick'], 'prev': t.get('weight', 0),
                              'now': w_now})
        diff['weight_moves'] = moves
        left_roster = [t['nick'] for t in prev_traders
                       if t.get('portfolio_id') not in now_w]
        diff['material'] = bool(diff.get('material') or diff['added_a'] or
                                diff['removed_a'] or diff['weight_moves'] or
                                left_roster)
    return {'generated': dt.date.today().isoformat(), 'snapshot': snapshot_date,
            'engine': 'v1.0', 'unallocated': unallocated,
            'traders': out_traders, 'removed': removed}
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(rank): score, A/B/W/X tiers, weights and roster"`

---

### Task 8: report — TOP_YYYY-MM.md

**Files:**
- Create: `pipeline/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: roster (the dict from `rank.run`), diff (dict), `trader_metrics` (for the notable exclusions).
- Produces: `report.write(con, snapshot_date, exchange, roster, diff, out_dir) -> str` (the .md path). Writes `TOP_<YYYY-MM>.md` into `out_dir`. Sections: title+date; the roster table (nick, tier, weight, score, alpha%, t, payoff, lev, mdd, n, warnings); **Changes vs the previous run** (the diff's `prev`; A entries/exits, weight_moves, new_disqualified_incumbents; or "First run — no previous run"); **Notable exclusions** (top-10 by `trader_snapshot.roi` among tier X, with their flags); **Standing caveats** (literal text: single regime window; top-600 survivorship; winner's curse ≈ half the alpha; only closed positions visible).

- [ ] **Step 1: Failing test**

```python
# tests/test_report.py
from pipeline import report

def test_report_contains_sections(con, tmp_path):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,tier,flags)"
        " VALUES ('2026-09-01','binance','v','vicky',100,'X','[\"roi_artifact\"]')")
    con.execute("INSERT INTO trader_snapshot VALUES "
                "('2026-09-01','binance','v','vicky',5435.9,0,0,0,0)")
    con.commit()
    roster = {"generated": "2026-09-01", "snapshot": "2026-09-01", "engine": "v1.0",
              "traders": [{"exchange": "binance", "portfolio_id": "1", "nick": "suoha",
                           "tier": "A", "weight": 0.5, "score": 4.1,
                           "metrics": {"alpha": 0.016, "t": 6.11, "payoff": 1.04,
                                       "lev_med": 5, "mdd": 20.1, "n": 527},
                           "warnings": ["alpha_decay"]}],
              "removed": []}
    diff = {"snapshot": "2026-09-01", "prev": None, "added_a": [], "removed_a": [],
            "weight_moves": [], "new_disqualified_incumbents": [], "material": True}
    p = report.write(con, "2026-09-01", "binance", roster, diff, tmp_path)
    text = open(p).read()
    assert "suoha" in text and "Changes" in text
    assert "vicky" in text and "roi_artifact" in text
    assert "winner" in text.lower() or "half the" in text
    assert "First run" in text
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
# pipeline/report.py
"""Generates the human-readable TOP_YYYY-MM.md report."""
import json, os

CAVEATS = """## Standing caveats
- **Single regime window**: the data covers few months and one cycle only; \
consistency within the cycle, not universal stability.
- **Survivorship**: the Binance universe is the top-600 by 90D ROI; there is no \
control group of blown-up traders.
- **Winner's curse**: with hundreds of candidates filtered down, expect ~half the \
alpha shown.
- **Only closed positions** are visible (barring open-position data): a \
loss-hider's latent losses may never show up.
"""

def write(con, snapshot_date, exchange, roster, diff, out_dir):
    month = snapshot_date[:7]
    path = os.path.join(str(out_dir), f"TOP_{month}.md")
    L = [f"# Copy-trading roster — {snapshot_date} ({exchange})", ""]
    L += ["| nick | tier | peso | score | alpha% | t | payoff | lev | mdd | n | warnings |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in roster["traders"]:
        m = t["metrics"]
        fmt = lambda x, k=2: f"{x:.{k}f}" if isinstance(x, (int, float)) else "—"
        L.append(f"| {t['nick']} | {t['tier']} | {t['weight']:.0%} | {t['score']:.2f} "
                 f"| {fmt((m['alpha'] or 0)*100)} | {fmt(m['t'])} | {fmt(m['payoff'])} "
                 f"| {fmt(m['lev_med'],0)} | {fmt(m['mdd'])} | {m['n']} "
                 f"| {', '.join(t['warnings']) or '—'} |")
    if roster.get("unallocated"):
        L.append(f"\n**Unallocated weight: {roster['unallocated']:.0%}** "
                 f"(roster is all tier B — 10% cap per trader)")
    L += ["", "## Changes vs previous run"]
    if diff.get("prev") is None:
        L.append("First run — no previous run.")
    else:
        L.append(f"Compared with {diff['prev']}.")
        for n in diff["added_a"]:
            L.append(f"- ▲ **{n}** enters tier A")
        for n in diff["removed_a"]:
            L.append(f"- ▼ **{n}** leaves tier A")
        for w in diff["weight_moves"]:
            L.append(f"- ⚖ **{w['nick']}**: {w['prev']:.0%} → {w['now']:.0%}")
        for d in diff["new_disqualified_incumbents"]:
            L.append(f"- ✖ **{d['nick']}** disqualified: {', '.join(d['flags'])}")
        if len(L[-1]) and L[-1].startswith("Comparado") :
            L.append("No material changes.")
    for r in roster.get("removed", []):
        L.append(f"- ✖ **{r['nick']}** out of the roster: {r['reason']}")
    L += ["", "## Notable exclusions"]
    rows = con.execute(
        "SELECT tm.nick, ts.roi, tm.flags FROM trader_metrics tm "
        "LEFT JOIN trader_snapshot ts ON ts.snapshot_date=tm.snapshot_date "
        "AND ts.exchange=tm.exchange AND ts.trader_id=tm.trader_id "
        "WHERE tm.snapshot_date=? AND tm.exchange=? AND tm.tier='X' "
        "ORDER BY ts.roi DESC LIMIT 10", (snapshot_date, exchange)).fetchall()
    for r in rows:
        roi = f"{r['roi']:.0f}%" if r['roi'] is not None else "—"
        L.append(f"- **{r['nick']}** (headline ROI {roi}): "
                 f"{', '.join(json.loads(r['flags'] or '[]'))}")
    L += ["", CAVEATS]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(report): human report TOP_YYYY-MM.md"`

---

### Task 9: scrape — into a dated snapshot, resumable

**Files:**
- Create: `pipeline/scrape.py`
- Test: `tests/test_scrape.py`

**Interfaces:**
- Consumes: the network (Binance/Phemex, endpoints and headers identical to `scripts/scrape_binance.py` and `scripts/scrape_positions.py` — copy `UA`, URLs and bodies verbatim; do NOT import the old scripts).
- Produces: `scrape.run(snap_dir, exchanges=('binance','phemex'), pages_binance=20, pages_phemex=7, extra_ids_binance=(), http_post=None, http_get=None) -> dict {"binance": n_traders, "phemex": n_traders}`. Writes `binance_raw.jsonl` / `phemex_raw.jsonl` into `snap_dir` (line format identical to the current one). Resumable: if the file already exists in the snapshot dir, it skips the trader_ids present. `http_post`/`http_get` injectable for tests (default = the real urllib functions). The portfolio/trader listings are also saved as `binance_list.json` / `phemex_list.json` in the snapshot dir.
- **`extra_ids_binance`** (the spec's historical union): portfolio_ids known from previous runs that are NO longer in the live listing — their position-history is downloaded anyway (the endpoint accepts any pid) with a minimal record `{'portfolioId': pid, 'nick': None, ..., 'positions': rows}`. That way de-copy sees a trader decay exactly as they drop out of the top-600.
- **⚠️ The list API's real cap: 30/page even if you ask for 50** (SKILL.md: "pageSize is ignored"). Hence: `pages_binance=20` by default (≥600 portfolios) and `fetch_portfolios`'s loop breaks ONLY on an empty page (`not lst`), NEVER on `len(lst) < pageSize` — with the cap of 30 that break would stop at page 1 and deliver half the universe, passing the ±50% validation by 3 traders.
- **A network failure ≠ done**: if `fetch_history` receives `{'code':'ERR'}` mid-pagination, the trader's record is NOT written (it stays out of `done` and the resume retries it). The bug inherited from `scripts/scrape_binance.py` (ERR → `positions: []` → marked complete forever) is NOT copied. `fetch_history` returns `(rows, ok)` and only `ok=True` writes.
- Differences from the old scripts: (1) it writes to the snapshot dir, not to a global `data/*.jsonl`; (2) pure parameterised functions; (3) it prints a `{exchange: n}` summary at the end; (4) the two points above.

- [ ] **Step 1: Failing test** (with mocked HTTP)

```python
# tests/test_scrape.py
import json
from pipeline import scrape

def _fake_post(url, body):
    if "query-list" in url:
        if body["pageNumber"] == 1:
            return {"code": "000000", "data": {"list": [
                {"leadPortfolioId": "P1", "nickname": "alice", "roi": 1, "pnl": 2,
                 "aum": 3, "winRate": 4, "mdd": 5}]}}
        return {"code": "000000", "data": {"list": []}}
    if "position-history" in url:
        if body["pageNumber"] == 1:
            return {"code": "000000", "data": {"list": [{"symbol": "BTCUSDT"}]}}
        return {"code": "000000", "data": {"list": []}}
    raise AssertionError(url)

def test_binance_scrape_writes_snapshot(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1
    line = json.loads((tmp_path / "binance_raw.jsonl").read_text().strip())
    assert line["portfolioId"] == "P1" and line["positions"][0]["symbol"] == "BTCUSDT"

def test_binance_scrape_resumes(tmp_path):
    scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 0          # already there, no re-scrape
    lines = (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1                  # no duplicates

def test_network_error_does_not_mark_trader_done(tmp_path):
    def _err_post(url, body):
        if "query-list" in url:
            return _fake_post(url, body)
        return {"code": "ERR"}              # history always fails
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_err_post)
    assert counts["binance"] == 0           # nothing written
    raw = tmp_path / "binance_raw.jsonl"
    assert not raw.exists() or raw.read_text().strip() == ""
    # on retry with a healthy network the trader IS fetched (never marked done)
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1

def test_extra_ids_historical_union(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post,
                        extra_ids_binance=("P_OLD",))
    assert counts["binance"] == 2           # P1 (live listing) + P_OLD (historical)
    lines = [json.loads(l) for l in
             (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()]
    ids = {l["portfolioId"] for l in lines}
    assert ids == {"P1", "P_OLD"}
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement** — port both scrapers into `pipeline/scrape.py` with this structure:

```python
# pipeline/scrape.py  (esqueleto — cuerpos de red copiados de scripts/scrape_*.py)
"""Scrapes Binance+Phemex into a dated snapshot. Resumable within the snapshot."""
import json, os, time, urllib.request

BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
       'Content-Type': 'application/json', 'clienttype': 'web',
       'Origin': 'https://www.binance.com',
       'Referer': 'https://www.binance.com/en/copy-trading'}
PUA = {'User-Agent': BUA['User-Agent'], 'Accept': 'application/json',
       'Origin': 'https://phemex.com', 'Referer': 'https://phemex.com/'}
LIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/home-page/query-list'
HIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history'
PH_REC = ('https://api.phemex.com/phemex-lb/public/data/v3/user/recommend'
          '?hideFullyCopied=false&keyword=&pageNum={}&pageSize=50&showChart=false'
          '&sortBy=PnlRate30d')
PH_POS = 'https://api.phemex.com/phemex-lb/public/data/position/closed/v2'

def _post(url, body, tries=3):
    # identical to scripts/scrape_binance.py::post
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=BUA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return {'code': 'ERR'}
            time.sleep(2 * (i + 1))

def _get(url, tries=3):
    # identical to scripts/scrape_positions.py::get, PUA headers
    ...

def _done_ids(path, key):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try: done.add(json.loads(line)[key])
            except Exception: pass
    return done

def _fetch_history(pid, post):
    """Returns (rows, ok). ok=False if an ERR hit mid-pagination — in that case
    the caller does NOT write the record (the resume retries it).
    Do NOT copy the bug in scripts/scrape_binance.py (ERR -> [] -> 'done')."""
    all_rows, page = [], 1
    while page <= 40:
        d = post(HIST_URL, {'portfolioId': pid, 'pageNumber': page, 'pageSize': 50})
        if d.get('code') == 'ERR':
            return all_rows, False
        if d.get('code') != '000000' or not d.get('data'):
            break
        rows = d['data'].get('list') or []
        all_rows += rows
        if len(rows) < 50:
            break
        page += 1
        time.sleep(0.4)
    return all_rows, True

def _scrape_binance(snap_dir, pages, post, extra_ids=()):
    # fetch_portfolios de scripts/scrape_binance.py -> snap_dir/binance_list.json;
    # for each portfolio in the listing + each extra_ids pid not present in it:
    #   rows, ok = _fetch_history(pid, post)
    #   only if ok: write the record (format identical to the current one; for
    #   extra_ids without metadata: nick/roi/pnl/aum/winRate/mdd = None) and append
    #   a snap_dir/binance_raw.jsonl, saltando _done_ids(..., 'portfolioId').
    # Devuelve nº de portfolios NUEVOS escritos.
    ...

def _scrape_phemex(snap_dir, pages, get):
    # fetch_trader_list + the loop from scripts/scrape_positions.py, same pattern
    # (including the same rule: network failure -> do not write, do not mark done).
    # Devuelve nº de traders NUEVOS escritos.
    ...

def run(snap_dir, exchanges=('binance', 'phemex'), pages_binance=20,
        pages_phemex=7, extra_ids_binance=(), http_post=None, http_get=None):
    os.makedirs(str(snap_dir), exist_ok=True)
    post, get = http_post or _post, http_get or _get
    out = {}
    if 'binance' in exchanges:
        out['binance'] = _scrape_binance(str(snap_dir), pages_binance, post,
                                         extra_ids_binance)
    if 'phemex' in exchanges:
        out['phemex'] = _scrape_phemex(str(snap_dir), pages_phemex, get)
    return out
```

The bodies of `_scrape_binance`/`_scrape_phemex`/`_get` are copied line by line from the old scripts, changing only the output paths and the `post`/`get` injection. The per-trader record must be **identical** to the current format (`{'portfolioId', 'nick', 'roi', 'pnl', 'aum', 'winRate', 'mdd', 'n_pos', 'positions'}` / `{'userId', 'nick', 'n_pos', 'positions'}`) so that Task 2 can read them.

- [ ] **Step 4: PASS** (tests only for the mocked Binance path; add an analogous Phemex test with a mocked `http_get` returning 1 trader with `showPosition: true` and 1 page of positions).
- [ ] **Step 5: Commit** — `git commit -m "feat(scrape): scrapers into a dated snapshot, resumable and injectable"`

---

### Task 10: CLI — pipeline.py with subcommands and validation

**Files:**
- Create: `pipeline.py` (project root)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: every previous module.
- Produces: CLI:
  - `python3 pipeline.py scrape [--date YYYY-MM-DD] [--exchange binance|phemex|all]` → `data/snapshots/<date>/` (date defaults to today). Passes `scrape.run` the `extra_ids_binance` = the DB's distinct historical `trader_id`s not already downloaded (the spec's historical union).
  - `python3 pipeline.py analyze [--date YYYY-MM-DD] [--force]` → flatten→**validation (BEFORE ingest, from the CSVs)**→ingest→metrics→detect→trend→rank→report; writes `analysis/runs/<date>/{roster.json,diff.json,TOP_*.md}`. **Does NOT touch `analysis/roster.json`** (the latest).
  - `python3 pipeline.py publish --date YYYY-MM-DD` → copies `analysis/runs/<date>/roster.json` to `analysis/roster.json`. The ONLY command that writes the latest; the skill invokes it after the council gate.
  - Granular subcommands `metrics|detect|trend|rank|report --date ...` for debugging. **Mandatory order documented in `--help`**: metrics→detect→trend→rank→report (metrics resets flags/trend_bonus via INSERT OR REPLACE; a rank without a subsequent detect/trend would rank with no flags).
- **Pre-ingest validation** (the DB is untouched on failure): (a) `data/snapshots/<date>/` must exist and hold at least one non-empty `*_raw.jsonl` — a typo'd `--date` NEVER produces an empty roster; (b) counting rows of the just-flattened CSVs against the previous snapshot in `snapshots` (if any): `n_traders` and `n_positions` within ±50%; (c) **an exchange with a previous snapshot in the DB whose CSV today is missing or empty → fails** (Phemex being down ≠ complete data). Any failure → details to stderr and `return 2`, unless `--force`.
- `prev_roster`: loaded from `analysis/runs/<prev_date>/roster.json` if it exists (prev_date = the previous snapshot in the DB **for the analysed exchange**).
- A `main(argv=None, project_root=None)` function so it can be tested with `tmp_path`.

- [ ] **Step 1: Failing test**

```python
# tests/test_cli.py
import importlib.util, json, pathlib, shutil

# pipeline.py (file) collides with pipeline/ (package): load the CLI by path
_spec = importlib.util.spec_from_file_location(
    "cli", pathlib.Path(__file__).parent.parent / "pipeline.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

def _setup_project(tmp_path, snap_fixture, date="2026-09-01"):
    root = tmp_path / "proj"
    (root / "data" / "snapshots" / date).mkdir(parents=True)
    for f in snap_fixture.iterdir():
        shutil.copy(f, root / "data" / "snapshots" / date / f.name)
    return root

def test_analyze_end_to_end_and_publish_gate(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    rc = cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    run_dir = root / "analysis" / "runs" / "2026-09-01"
    roster = json.loads((run_dir / "roster.json").read_text())
    diff = json.loads((run_dir / "diff.json").read_text())
    assert roster["snapshot"] == "2026-09-01"
    assert diff["material"] is True            # first run
    assert (run_dir / "TOP_2026-09.md").exists()
    # analyze does NOT publish the latest — that is publish, after the gate
    assert not (root / "analysis" / "roster.json").exists()
    rc = cli.main(["publish", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    assert (root / "analysis" / "roster.json").exists()

def test_analyze_aborts_on_missing_snapshot_dir(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    # typo in --date: must not produce a roster (least of all an empty one)
    rc = cli.main(["analyze", "--date", "2026-12-31"], project_root=str(root))
    assert rc == 2
    assert not (root / "analysis" / "runs" / "2026-12-31").exists()

def test_analyze_validation_blocks_partial_data(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir, "2026-09-01")
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    # second snapshot with 5x the positions -> outside ±50%
    d2 = root / "data" / "snapshots" / "2026-10-01"
    d2.mkdir()
    lines = (snap_dir / "binance_raw.jsonl").read_text()
    rec = json.loads(lines)
    rec["positions"] = rec["positions"] * 5
    (d2 / "binance_raw.jsonl").write_text(json.dumps(rec) + "\n")
    rc = cli.main(["analyze", "--date", "2026-10-01"], project_root=str(root))
    assert rc == 2
    # the DB was NOT poisoned: the rejected snapshot is absent from `snapshots`
    from pipeline import db as dbmod
    con = dbmod.connect(root / "data" / "copytrade.sqlite")
    assert con.execute("SELECT COUNT(*) FROM snapshots "
                       "WHERE snapshot_date='2026-10-01'").fetchone()[0] == 0
    con.close()
    rc = cli.main(["analyze", "--date", "2026-10-01", "--force"],
                  project_root=str(root))
    assert rc == 0
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
# pipeline.py — entrypoint for the copy-trading-refresh pipeline
"""Usage:
  python3 pipeline.py scrape  [--date YYYY-MM-DD] [--exchange all|binance|phemex]
  python3 pipeline.py analyze [--date YYYY-MM-DD] [--force]
  python3 pipeline.py publish --date YYYY-MM-DD     (the only one that writes analysis/roster.json)
  python3 pipeline.py metrics|detect|trend|rank|report --date YYYY-MM-DD
     (mandatory order: metrics -> detect -> trend -> rank -> report;
      metrics resets flags/trend_bonus — a rank without detect+trend ranks with no flags)
"""
import argparse, csv, datetime as dt, glob, json, os, shutil, sys
from pipeline import db as dbmod, flatten, ingest, metrics, detect, trend, rank, report
from pipeline import scrape as scrape_mod

def _paths(root, date):
    return {'snap': os.path.join(root, 'data', 'snapshots', date),
            'db': os.path.join(root, 'data', 'copytrade.sqlite'),
            'run': os.path.join(root, 'analysis', 'runs', date),
            'latest': os.path.join(root, 'analysis', 'roster.json')}

def _csv_counts(snap_dir, ex):
    """(n_traders, n_positions) from the snapshot CSV, or None if missing/empty."""
    path = os.path.join(snap_dir, f'{ex}.csv')
    if not os.path.exists(path):
        return None
    key = 'portfolio_id' if ex == 'binance' else 'trader_id'
    traders, n = set(), 0
    for r in csv.DictReader(open(path)):
        traders.add(r[key]); n += 1
    return (len(traders), n) if n else None

def _validate_pre(con, snap_dir, date, force):
    """BEFORE ingest, straight from the CSVs — the DB is left untouched on failure."""
    raws = [p for p in glob.glob(os.path.join(snap_dir, '*_raw.jsonl'))
            if os.path.getsize(p) > 0]
    if not os.path.isdir(snap_dir) or not raws:
        print(f"VALIDATION: {snap_dir} does not exist or has no *_raw.jsonl — "
              f"typo in --date?", file=sys.stderr)
        return False                       # not even --force skips this one
    if _csv_counts(snap_dir, 'binance') is None:
        print("VALIDATION: no binance.csv (or empty) — v1 analyses Binance; "
              "carrying on would produce an EMPTY roster", file=sys.stderr)
        return False                       # --force does NOT skip this one either
    ok = True
    for ex in ('binance', 'phemex'):
        prev = con.execute(
            "SELECT snapshot_date, n_traders, n_positions FROM snapshots "
            "WHERE exchange=? AND snapshot_date<? ORDER BY snapshot_date DESC LIMIT 1",
            (ex, date)).fetchone()
        cur = _csv_counts(snap_dir, ex)
        if prev and cur is None:
            print(f"VALIDATION {ex}: had a previous snapshot ({prev['snapshot_date']}) "
                  f"but there is no CSV today — incomplete scrape", file=sys.stderr)
            ok = False
            continue
        if not prev or cur is None:
            continue
        for field, c, p in (('n_traders', cur[0], prev['n_traders']),
                            ('n_positions', cur[1], prev['n_positions'])):
            if p and not (0.5 * p <= c <= 1.5 * p):
                print(f"VALIDATION {ex}.{field}: {c} vs {p} on "
                      f"{prev['snapshot_date']} (outside ±50%)", file=sys.stderr)
                ok = False
    if not ok and not force:
        print("Aborting WITHOUT touching the DB; use --force to continue.",
              file=sys.stderr)
        return False
    return True

def _known_ids(con, snap_dir):
    """Historical union: DB ids not yet downloaded into this snapshot."""
    hist = {r[0] for r in con.execute(
        "SELECT DISTINCT trader_id FROM positions WHERE exchange='binance'")}
    done = set()
    raw = os.path.join(snap_dir, 'binance_raw.jsonl')
    if os.path.exists(raw):
        for line in open(raw):
            try: done.add(json.loads(line)['portfolioId'])
            except Exception: pass
    return tuple(sorted(hist - done))

def main(argv=None, project_root=None):
    root = project_root or os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        epilog='Order of the granular subcommands: metrics -> detect -> trend -> '
               'rank -> report (metrics resets flags/trend_bonus).')
    ap.add_argument('cmd', choices=['scrape', 'analyze', 'publish', 'metrics',
                                    'detect', 'trend', 'rank', 'report'])
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--exchange', default='all')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    P = _paths(root, a.date)

    if a.cmd == 'publish':
        src = os.path.join(P['run'], 'roster.json')
        if not os.path.exists(src):
            print(f"publish: {src} does not exist — run analyze first",
                  file=sys.stderr)
            return 1
        shutil.copy(src, P['latest'])
        print('published:', P['latest'])
        return 0

    con = dbmod.connect(P['db'])
    try:
        if a.cmd == 'scrape':
            ex = ('binance', 'phemex') if a.exchange == 'all' else (a.exchange,)
            extra = _known_ids(con, P['snap']) if 'binance' in ex else ()
            print(scrape_mod.run(P['snap'], exchanges=ex, extra_ids_binance=extra))
            return 0
        if a.cmd == 'analyze':
            print('flatten:', flatten.flatten_snapshot(P['snap'])
                  if os.path.isdir(P['snap']) else 'snapshot dir does not exist')
            if not _validate_pre(con, P['snap'], a.date, a.force):
                return 2
            print('ingest:', ingest.ingest_snapshot(con, P['snap'], a.date))
            print('metrics:', metrics.compute(con, a.date))
            detect.run(con, a.date)
            prev_roster = None
            prev = con.execute(
                "SELECT MAX(snapshot_date) FROM snapshots "
                "WHERE exchange='binance' AND snapshot_date<?",
                (a.date,)).fetchone()[0]
            if prev:
                pr = os.path.join(root, 'analysis', 'runs', prev, 'roster.json')
                if os.path.exists(pr):
                    prev_roster = json.load(open(pr))
            diff = trend.run(con, a.date, prev_roster=prev_roster)
            roster = rank.run(con, a.date, diff=diff, prev_roster=prev_roster)
            os.makedirs(P['run'], exist_ok=True)
            json.dump(roster, open(os.path.join(P['run'], 'roster.json'), 'w'),
                      indent=1, ensure_ascii=False)
            json.dump(diff, open(os.path.join(P['run'], 'diff.json'), 'w'),
                      indent=1, ensure_ascii=False)
            p = report.write(con, a.date, 'binance', roster, diff, P['run'])
            # NOT copied to analysis/roster.json here: that is `publish`, after the gate
            print('report:', p)
            print('material:', diff['material'])
            return 0
        if a.cmd == 'metrics':
            print(metrics.compute(con, a.date)); return 0
        if a.cmd == 'detect':
            print(detect.run(con, a.date)); return 0
        if a.cmd == 'trend':
            print(trend.run(con, a.date)); return 0
        if a.cmd == 'rank':
            print(json.dumps(rank.run(con, a.date), ensure_ascii=False)); return 0
        if a.cmd == 'report':
            # reads the run artifacts — does NOT recompute trend/rank
            # (recomputing without prev_roster would yield a diff unlike analyze's)
            rp = os.path.join(P['run'], 'roster.json')
            dp = os.path.join(P['run'], 'diff.json')
            if not (os.path.exists(rp) and os.path.exists(dp)):
                print("report: roster.json/diff.json missing — run analyze first",
                      file=sys.stderr)
                return 1
            print(report.write(con, a.date, 'binance', json.load(open(rp)),
                               json.load(open(dp)), P['run']))
            return 0
    finally:
        con.close()

if __name__ == '__main__':
    sys.exit(main())
```

**Note:** `pipeline.py` (the file) and `pipeline/` (the package) coexist — which is why `tests/test_cli.py` loads the CLI via `importlib` by path (already included in Step 1's block).

- [ ] **Step 4: PASS** — `python3 -m pytest tests/ -v` (the whole suite green).
- [ ] **Step 5: Commit** — `git commit -m "feat(cli): pipeline.py with scrape/analyze and snapshot validation"`

---

### Task 11: Regression against the real 2026-08-25 snapshot

**Files:**
- Create: `tests/test_regression.py`, `data/snapshots/2026-08-25/` (symlinks/copies of the existing data)

**Interfaces:**
- Consumes: the real `data/binance_positions.jsonl` and `data/positions_all.jsonl` (43MB/4.4MB — they already exist, gitignored).

- [ ] **Step 1: Prepare the historical snapshot** (once, not a test):

```bash
cd ~/Projects/trading/copy-trading-intel
mkdir -p data/snapshots/2026-08-25
ln -sf ../../binance_positions.jsonl data/snapshots/2026-08-25/binance_raw.jsonl
ln -sf ../../positions_all.jsonl data/snapshots/2026-08-25/phemex_raw.jsonl
```

- [ ] **Step 2: Write the regression test** (marked `slow`, skipped if the data is missing):

```python
# tests/test_regression.py
"""Reproduces the audited 2026-08-25 analysis with the new pipeline.
Reference: analysis/TOP5.md and FINDINGS_v2.md."""
import json, os, pathlib, pytest
from pipeline import db as dbmod, flatten, ingest, metrics, detect, rank

ROOT = pathlib.Path(__file__).parent.parent
SNAP = ROOT / "data" / "snapshots" / "2026-08-25"

pytestmark = pytest.mark.skipif(
    not (SNAP / "binance_raw.jsonl").exists(), reason="data real no disponible")

@pytest.fixture(scope="module")
def real(tmp_path_factory):
    con = dbmod.connect(tmp_path_factory.mktemp("db") / "r.sqlite")
    flatten.flatten_snapshot(SNAP)
    ingest.ingest_snapshot(con, SNAP, "2026-08-25")
    metrics.compute(con, "2026-08-25")
    flags = detect.run(con, "2026-08-25")
    roster = rank.run(con, "2026-08-25")
    return con, flags, roster

def _by_nick(con):
    return {r["nick"]: r for r in con.execute(
        "SELECT * FROM trader_metrics WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance'")}

def test_mdd_scale_is_percentage(real):
    """Guards against the scale regression: mdd is a PERCENTAGE (Trap 5)."""
    con, flags, roster = real
    med = con.execute(
        "SELECT mdd FROM trader_snapshot WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance' AND mdd IS NOT NULL ORDER BY mdd "
        "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM trader_snapshot "
        "WHERE snapshot_date='2026-08-25' AND exchange='binance' "
        "AND mdd IS NOT NULL)").fetchone()[0]
    assert 10 <= med <= 60          # real median ~30.15; if <1, the scale broke

def test_known_top_traders_survive(real):
    con, flags, roster = real
    m = _by_nick(con)
    # 梭哈到世界尽头: n=527, t~6, lev 5x, top-1 conc = 26.1% — survives
    s = m["梭哈到世界尽头"]
    assert s["n"] > 400 and s["t_stat"] > 4
    assert s["conc_top1"] < 30
    assert not (set(json.loads(s["flags"])) & detect.DISQUALIFYING)

def test_known_frauds_are_flagged(real):
    con, flags, roster = real
    m = _by_nick(con)
    assert "roi_artifact" in json.loads(m["VickyKaushal"]["flags"]) or \
           "no_alpha" in json.loads(m["VickyKaushal"]["flags"])
    assert "loss_hider" in json.loads(m["GGbond哦"]["flags"])
    # CAREFUL: the real nick in the data carries a suffix — 龟兔赛跑985-重新起航
    assert "lottery" in json.loads(m["龟兔赛跑985-重新起航"]["flags"])
    assert "ruin_risk" in json.loads(m["牛熊摆渡人"]["flags"])   # lev p90 / -1173%

def test_roster_is_five_and_sane(real):
    con, flags, roster = real
    assert len(roster["traders"]) <= 5
    total = sum(t["weight"] for t in roster["traders"]) + roster["unallocated"]
    assert abs(total - 1.0) < 1e-9   # allocated + unallocated = 1.0 (run #1 can
                                     # can be all-B → unallocated > 0)
```

- [ ] **Step 3: Run** — `python3 -m pytest tests/test_regression.py -v` (takes ~1-2 min for the 108k rows). If an assert fails, investigate BEFORE relaxing the threshold: the real data rules; exact names may differ (e.g. nick suffixes — search with `LIKE` if the exact one is absent and adjust the test with the literal nick found).
- [ ] **Step 4: Commit** — `git commit -m "test(regression): pipeline reproduces the audited 2026-08-25 analysis"`

---

### Task 12: Spike — open positions (direct open_loss_divergence)

**Files:**
- Create: `scripts/probe_open_positions.py` (throwaway until confirmed)
- Modify (only if the spike works): `pipeline/scrape.py`, `pipeline/ingest.py`, `SKILL.md`

**Interfaces:**
- Produces: a documented answer to "is there a public per-lead-trader OPEN positions endpoint?". If yes: scrape/ingest fill `open_positions` and the `open_loss_divergence` flag (already implemented in Task 5) fires on real data.

- [ ] **Step 1: Write the probe**

```python
#!/usr/bin/env python3
# scripts/probe_open_positions.py — spike: are open positions public?
import json, urllib.request

BUA = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json',
       'clienttype': 'web', 'Origin': 'https://www.binance.com',
       'Referer': 'https://www.binance.com/en/copy-trading'}
PUA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
       'Origin': 'https://phemex.com', 'Referer': 'https://phemex.com/'}

CANDIDATES_BINANCE = [
    'lead-portfolio/positions', 'lead-portfolio/position-list',
    'lead-portfolio/current-position', 'lead-portfolio/open-positions']
BASE = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/'

def try_binance(pid):
    for c in CANDIDATES_BINANCE:
        for body in ({'portfolioId': pid},
                     {'portfolioId': pid, 'pageNumber': 1, 'pageSize': 20}):
            try:
                req = urllib.request.Request(BASE + c, data=json.dumps(body).encode(),
                                             headers=BUA)
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.load(r)
                print(f"BINANCE {c}: code={d.get('code')} "
                      f"data={'YES' if d.get('data') else 'empty'}")
                if d.get('data'):
                    print(json.dumps(d['data'], ensure_ascii=False)[:800])
            except Exception as e:
                print(f"BINANCE {c}: {e}")

def try_phemex(uid):
    url = (f'https://api.phemex.com/phemex-lb/public/data/position/current/v2'
           f'?userId={uid}')
    try:
        req = urllib.request.Request(url, headers=PUA)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        print(f"PHEMEX current/v2: code={d.get('code')}")
        print(json.dumps(d.get('data'), ensure_ascii=False)[:800])
    except Exception as e:
        print(f"PHEMEX current/v2: {e}")

if __name__ == '__main__':
    import sys
    # real ids: take them from data/snapshots/<latest>/binance_list.json and
    # phemex_list.json (or data/binance_portfolios.json / all_traders.json)
    try_binance(sys.argv[1] if len(sys.argv) > 1 else '')
    try_phemex(sys.argv[2] if len(sys.argv) > 2 else '')
```

- [ ] **Step 2: Run the probe** with a real `portfolioId` (from `data/binance_portfolios.json`) and a real `userId` (from `data/all_traders.json`). Note the output.
- [ ] **Step 3: Document the result** — add one line per exchange to `SKILL.md` (Endpoints section): confirmed endpoint + fields, or "verified NOT available on 2026-XX-XX".
- [ ] **Step 4 (only if it works):** in `pipeline/scrape.py` add the per-trader call and dump into the snapshot's `open_raw.jsonl`; in `pipeline/ingest.py` populate `open_positions` (columns: symbol, side, notional, unrealized_pnl, following the real names the endpoint returns). A test analogous to Task 9's with mocked HTTP.
- [ ] **Step 5: Commit** — `git commit -m "spike: open-positions probe (+ integration if available)"`

---

### Task 13: Skill `/copy-trading-refresh`

**Files:**
- Create: an agent skill (outside the repo)

**Interfaces:**
- Consumes: Task 10's CLI, `diff.json`'s materiality gate, the existing `adversarial-review` skill.

- [ ] **Step 1: Write the skill**

```markdown
---
name: copy-trading-refresh
description: Refreshes the roster of lead traders to copy (Binance+Phemex). Scrapes fresh data, runs the deterministic engine (alpha, anti-inflation, trend), and if the roster changes materially convenes the adversarial council (Fable/Kimi/GLM) before publishing. Use when the user asks to "refresh the roster", "update the traders", "run the copy-trading pipeline", "check whether the traders to follow changed", or mentions copy-trading-refresh. Runs 1-2 times a month.
---

# copy-trading-refresh

Project: the copy-trading-intel repo. Spec:
`docs/specs/2026-08-28-copy-trading-refresh-design.md`.

## Runbook

1. `cd` into the project root.
2. **Scrape** (takes several minutes; resumable):
   `python3 pipeline.py scrape`
   - If it fails midway (network, rate limit): re-run the same command — it skips what
     was already downloaded; a trader whose history failed on the network was NOT
     marked as done.
   - If an endpoint returns a persistent error (repeated HTTP 4xx/5xx): STOP and report
     the exact status to the operator. Binance rotates APIs without notice; do not
     improvise new endpoints without confirming them.
3. **Analyze** (seconds, no network):
   `python3 pipeline.py analyze`
   - It validates BEFORE ingesting; if it fails (exit 2) the DB is untouched. Check
     stderr, report to the operator, and only use `--force` if the operator approves it
     (a snapshot with no binance.csv does not pass even with --force — it would produce
     an empty roster).
   - `analyze` NEVER writes `analysis/roster.json` — that is step 7.
4. Read `analysis/runs/<today>/diff.json`.
5. **Council gate**:
   - `material: false` → go to step 7.
   - `material: true` → invoke the `adversarial-review` skill with: the `diff.json`,
     the `roster.json`, the snapshot CSVs (`data/snapshots/<today>/binance.csv`), and
     the concrete question: "The engine promoted/expelled <X>. Re-derive their numbers
     from the CSV and refute or confirm every change in the diff. Do not approve out of
     politeness."
6. **Merge the verdicts**: add a `## Adversarial council` section to `TOP_*.md` with
   confirms/objects per change. If the council OBJECTS to a promotion to tier A:
   do NOT publish that change — present the objection to the operator and wait for
   their decision.
7. **Publish**: `python3 pipeline.py publish --date <today>` — the ONLY command that
   writes `analysis/roster.json` (what the mirror bot consumes). Only after passing the
   gate (or after the operator's decision if there were objections).
8. **Present to the operator**: the roster table, the diff's ▲▼ (each trader carries
   `trend.rank_prev/rank_now/alpha_delta`), entries/exits with reasons, `unallocated`
   if the roster is all-B, and the council's objections if any. Remember the standing
   caveat: expect ~half the alpha shown (winner's curse).

## What it does NOT do
- It does not configure the mirror bot (the operator wires `analysis/roster.json` up by hand).
- It does not run on cron (manual invocation, 1-2x/month).
- It does not delete old snapshots: `data/snapshots/` is the historical source of truth.
```

- [ ] **Step 2: Verify** — in a new Claude Code session: `/copy-trading-refresh` appears and loads.
- [ ] **Step 3: Commit in the project** (the skill lives outside the repo; commit the reference): add a line to `SKILL.md`'s Scripts section: `- pipeline.py — the permanent pipeline (see docs/specs/2026-08-28-...)`. `git commit -m "docs: reference the pipeline and the copy-trading-refresh skill"`

---

### Task 14: First real end-to-end run

- [ ] **Step 1:** `python3 pipeline.py scrape` (for real, ~10-20 min). Verify `data/snapshots/<today>/` has both `_raw.jsonl`.
- [ ] **Step 2:** `python3 pipeline.py analyze`. First run → `material: true` expected.
- [ ] **Step 3:** Review `TOP_<month>.md` by hand: does the roster resemble the audited Top 5 (it may vary with new data)? Do the notable exclusions make sense?
- [ ] **Step 4:** Present the result to the operator with the diff against the 2026-08-25 Top 5. The operator decides whether to convene the adversarial council on this first run (it is material by definition).
- [ ] **Step 5: Commit** — `git add analysis/runs/ && git commit -m "chore: first pipeline run"` (runs ARE versioned; only the raw data is gitignored — check that `.gitignore` does not exclude `analysis/runs/`).

---

## Self-review + adversarial review (2026-08-28)

The plan went through adversarial review by 3 independent reviewers (Fable, Kimi, GLM, in
design mode) and ALL corrections are incorporated above. The major changes against the
initial version:

1. **mdd is a PERCENTAGE** (all 3 reviewers + direct verification) — thresholds 35/60, fixtures in %, a scale regression test (T11).
2. **conc = top-1 >30%** (the audited criterion) — top-3>30 disqualified 5/6 of the audited survivors. NULL if total PnL ≤0.
3. **Phemex: explicitly de-scoped in v1** — archived (scrape/flatten/ingest, `side` from `pos_side`) but not ranked.
4. **All-B weights**: 10% cap always, remainder `unallocated` (never dumped onto one trader); score>0 to enter the roster.
5. **PRE-ingest validation from the CSVs** — the DB is not poisoned by rejected snapshots; with no binance.csv not even `--force` passes; an exchange with history and no CSV fails.
6. **`publish` split from `analyze`** — the latest is only written after the council gate.
7. **Gate**: matching by `portfolio_id`, incumbent exits (A or B) are material, `decopy_2neg` visible (fresh flags in trend), cross-snapshot alpha_decay.
8. **Scrape**: a network failure ≠ a done trader; real cap of 30/page (pages=20, break only on an empty page); historical union via `extra_ids_binance`.
9. **`insufficient`-only → W** (newcomer), not X (fraud). Tier A via n>300 only on run #1.
10. **Roster with a `trend` block** (`rank_prev/rank_now/alpha_delta`); the granular `report` reads artifacts, it does not recompute.
11. Tests: vacuous assert removed, fixtures with correct epochs (2025), the real nick `龟兔赛跑985-重新起航`, inline importlib, new tests (all-B, zero-losers with a break-even, network error, extra_ids, W-vs-X, DB not poisoned).

- **Placeholders:** the only `...` are in Task 9, with an explicit instruction to copy the bodies line by line from `scripts/scrape_*.py` — acceptable because the exact content exists and is referenced (with the 2 mandatory deviations documented: ERR≠done and breaking on an empty page).
- **Type consistency:** `flags` always a JSON array in TEXT; `conc_top1` renamed consistently (schema, metrics, detect, tests, regression); `decopy_2neg` disqualifying in `rank.BAD` and in `trend`; roster/removed/diff all carry `portfolio_id`.
```
