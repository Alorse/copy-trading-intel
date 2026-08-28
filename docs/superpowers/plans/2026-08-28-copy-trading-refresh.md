# copy-trading-refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pipeline repetible (scrape → SQLite → métricas → detección anti-inflado → tendencia → roster) que mantiene actualizado el listado de lead-traders a copiar, invocable por la skill `/copy-trading-refresh`.

**Architecture:** Capa cruda inmutable en `data/snapshots/YYYY-MM-DD/` + capa analítica SQLite (`data/copytrade.sqlite`) reconstruible desde la cruda. Un entrypoint `pipeline.py` con subcomandos; cada stage un módulo en `pipeline/`. El consejo adversarial NO es código: lo orquesta el agente vía la skill.

**Tech Stack:** Python 3 stdlib únicamente (`sqlite3`, `json`, `csv`, `urllib`, `statistics`, `argparse`). Tests con `pytest` (dev-only). **Cero dependencias de runtime** (portabilidad a VPS).

**Spec:** `docs/superpowers/specs/2026-08-28-copy-trading-refresh-design.md`

## Global Constraints

- Runtime = stdlib puro. `pytest` solo para tests. DuckDB explícitamente descartado.
- La DB es derivada: todo debe poder reconstruirse re-ingiriendo `data/snapshots/`.
- Ingest idempotente por `(snapshot_date, exchange)` — re-correr reemplaza, nunca duplica.
- `analyze` (flatten→report) nunca toca la red.
- Métrica central intacta del motor auditado: `alpha = price_return − mediana de celda (symbol, mes, side, n≥20)`.
- Score: `0.40·t + 0.25·alpha·100 + 0.20·payoff + 0.15·trend_bonus`, −10% por warning. Solo scores >0 entran al roster.
- Roster (A+B) capeado en 5 traders.
- **Escala de mdd (Binance): PORCENTUAL** — mediana ~30.15, máx ~102.7 (GGbond哦=50.5). Umbrales de mdd SIEMPRE en esa escala (35/60). Verificado contra data real en revisión adversarial.
- **Concentración = top-1** (mejor trade / PnL total), umbral >30% — el criterio auditado de `top5_final.py`. Top-3>30 fue refutado: descalificaba a 5/6 supervivientes auditados (梭哈 top-3=59.4%, top-1=26.1%).
- **v1 analiza SOLO Binance.** Phemex se scrapea/aplana/ingiere (archivo histórico) pero no entra a metrics/detect/trend/rank/report. En Phemex el lado real es `pos_side` (Long/Short/Merged), no `side` (Buy/Sell) — ingest lo mapea para el futuro.
- Matching de titulares entre corridas por `portfolio_id`, nunca por nick.
- `analyze` no publica el latest (`analysis/roster.json`); eso lo hace `publish`, tras el gate.
- Todos los paths relativos a la raíz del proyecto: `~/Projects/trading/copy-trading-intel`.
- Endpoints/headers exactos: los de `SKILL.v3.md` (Binance `/friendly/`, Phemex `api.phemex.com`).
- Commits en español, formato convencional, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
pipeline.py                  ← CLI (argparse subcommands)
pipeline/
  __init__.py                ← vacío
  db.py                      ← schema, conexión, helpers
  scrape.py                  ← Binance+Phemex → data/snapshots/<date>/*_raw.jsonl (resumable)
  flatten.py                 ← *_raw.jsonl → binance.csv / phemex.csv (en el snapshot dir)
  ingest.py                  ← CSV → SQLite (idempotente)
  metrics.py                 ← price_return, alpha, t, payoff, … → trader_metrics
  detect.py                  ← flags descalificantes + warnings
  trend.py                   ← diff vs snapshot previo, trend_bonus, diff.json
  rank.py                    ← score, tiers, weights → roster.json
  report.py                  ← TOP_YYYY-MM.md
scripts/probe_open_positions.py   ← spike posiciones abiertas (throwaway hasta confirmar)
tests/
  conftest.py                ← fixtures sintéticas
  test_db.py test_flatten.py test_ingest.py test_metrics.py
  test_detect.py test_trend.py test_rank.py test_report.py test_cli.py
  test_regression.py         ← contra el snapshot real 2026-08-25 (marcado slow)
~/.claude/skills/copy-trading-refresh/SKILL.md   ← runbook del agente
```

Los scripts históricos (`scripts/scrape_*.py`, `analysis/*.py`) NO se tocan ni borran: son la evidencia reproducible de FINDINGS_v2. El pipeline nuevo copia su lógica, no los importa.

---

### Task 1: Schema SQLite + módulo db

**Files:**
- Create: `pipeline/__init__.py`, `pipeline/db.py`
- Test: `tests/test_db.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `db.connect(path) -> sqlite3.Connection` (crea schema si falta, `row_factory=sqlite3.Row`, FKs ON); `db.clear_snapshot(con, snapshot_date, exchange)` (borra ese snapshot de todas las tablas); constante `db.SCHEMA` (str SQL).

- [ ] **Step 1: Escribir el test que falla**

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

- [ ] **Step 2: Verificar que falla** — `cd ~/Projects/trading/copy-trading-intel && python3 -m pytest tests/test_db.py -v` → FAIL (`ModuleNotFoundError: pipeline`).

- [ ] **Step 3: Implementación mínima**

```python
# pipeline/db.py
"""Capa analitica SQLite. La DB es derivada: se reconstruye desde data/snapshots/."""
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

`pipeline/__init__.py`: archivo vacío.

- [ ] **Step 4: Verificar que pasa** — `python3 -m pytest tests/test_db.py -v` → 2 PASS.

- [ ] **Step 5: Commit** — `git add pipeline/ tests/ && git commit -m "feat(db): schema sqlite y modulo de conexion"`

---

### Task 2: flatten — jsonl crudo → CSV en el snapshot dir

**Files:**
- Create: `pipeline/flatten.py`
- Test: `tests/test_flatten.py`

**Interfaces:**
- Consumes: `data/snapshots/<date>/binance_raw.jsonl` y `phemex_raw.jsonl` (mismo formato de línea que los actuales `data/binance_positions.jsonl` / `data/positions_all.jsonl`: `{"portfolioId"/"userId", "nick", ..., "positions": [...]}`).
- Produces: `flatten.flatten_snapshot(snap_dir) -> dict` con `{"binance": n_rows, "phemex": n_rows}`; escribe `binance.csv` y `phemex.csv` en `snap_dir`. Columnas Binance: `portfolio_id,nick,p_roi,p_pnl,aum,win_rate,mdd,symbol,side,leverage,isolated,avg_cost,avg_close,closing_pnl,roi,max_oi,closed_volume,opened_ms,closed_ms,dur_h,notional,margin_est` (idénticas a `analysis/flatten.py`). Columnas Phemex: `trader_id,nick,symbol,side,pos_side,size,open_price,close_price,open_val,margin,roi,closed_pnl,realized_pnl,exchange_fee,funding_fee,opened_ms,closed_ms,dur_h`.

- [ ] **Step 1: Test que falla** (con fixture de jsonl mínimo)

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

- [ ] **Step 2: Verificar FAIL** — `python3 -m pytest tests/test_flatten.py -v`.

- [ ] **Step 3: Implementar** — portar `analysis/flatten.py` a función parametrizada:

```python
# pipeline/flatten.py
"""Aplana los *_raw.jsonl de un snapshot a CSV planos. Sin red."""
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

- [ ] **Step 4: Verificar PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(flatten): jsonl crudo a csv por snapshot"`

---

### Task 3: ingest — CSV → SQLite, idempotente

**Files:**
- Create: `pipeline/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `db.connect`, `db.clear_snapshot`, CSVs de Task 2.
- Produces: `ingest.ingest_snapshot(con, snap_dir, snapshot_date) -> dict {"binance": n, "phemex": n}`. Llena `snapshots`, `trader_snapshot`, `positions`. `price_return`/`alpha` quedan NULL (los pone `metrics`). Binance: `margin = margin_est`, `partial = 1 si closed_volume < max_oi`, `avg_cost/avg_close` del CSV. Phemex: `notional = open_val`, `leverage = open_val/margin` (0 si margin=0), `closing_pnl = realized_pnl` (neto), `avg_cost/avg_close` = `open_price/close_price`, y **`side` = `pos_side`** (`Long`/`Short`/`Merged` — el `side` Buy/Sell del CSV NO es el lado de la posición; guardar el correcto evita el signo invertido si Phemex se analiza a futuro). En `trader_snapshot` Phemex: roi/pnl/aum/win_rate/mdd = NULL. **`clear_snapshot` se ejecuta para cada exchange ANTES del check de existencia del CSV** — si el CSV desapareció en un re-ingest, la data vieja de ese exchange no debe sobrevivir.

- [ ] **Step 1: Test que falla**

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
    assert p["closing_pnl"] == 99.0         # realized (neto)
    assert p["side"] == "Short"             # pos_side, NO el Buy/Sell del CSV
    ts = con.execute("SELECT * FROM trader_snapshot WHERE exchange='binance'").fetchone()
    assert ts["mdd"] == 0.2 and ts["nick"] == "alice"
    snaps = con.execute("SELECT * FROM snapshots ORDER BY exchange").fetchall()
    assert [(s["exchange"], s["n_traders"], s["n_positions"]) for s in snaps] == \
        [("binance", 1, 1), ("phemex", 1, 1)]

def test_ingest_is_idempotent(con, snap_dir):
    _load(con, snap_dir)
    _load(con, snap_dir)   # re-ingest mismo snapshot
    n = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    assert n == 2          # 1 binance + 1 phemex, sin duplicar
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementar**

```python
# pipeline/ingest.py
"""CSV de un snapshot -> SQLite. Idempotente por (snapshot_date, exchange)."""
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
        # limpiar SIEMPRE: si el CSV desaparecio en un re-ingest, la data vieja
        # de ese exchange no debe sobrevivir en la DB
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
                # side REAL de la posicion = pos_side (Long/Short/Merged);
                # el side del CSV es Buy/Sell y NO es el lado de la posicion
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
- [ ] **Step 5: Commit** — `git commit -m "feat(ingest): carga idempotente de snapshots a sqlite"`

**Nota:** las columnas `avg_cost`/`avg_close` ya están en el schema de Task 1 — no hay migración que hacer aquí.

---

### Task 4: metrics — alpha, t-stat y métricas por trader

**Files:**
- Create: `pipeline/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: tablas `positions`, `trader_snapshot`.
- Produces: `metrics.compute(con, snapshot_date, exchange='binance', min_cell=20) -> int` (nº de traders con métricas). Efectos: (1) `UPDATE positions SET price_return, alpha` (sobre TODAS las filas); (2) inserta filas en `trader_metrics` con: `n, n_alpha, alpha` (media de alphas), `t_stat, payoff, wr, conc_top1, ruin, mdd, lev_med, lev_p90, marg_med, dur_med, months_active, alpha_h1, alpha_h2, monthly_alpha` (JSON `{"2025-04": 0.012, ...}`, meses con ≥5 alphas). **Las métricas por trader se computan SOLO sobre filas válidas (`pr` no NULL)** — igual que `top5_final.py`, que descarta inválidas antes de contar; `n` = filas válidas. `tier/weight/score/flags/trend_bonus` los llenan stages posteriores.
- Fórmulas (idénticas a `analysis/top5_final.py`, con conc sobre top-3 según spec):
  - `price_return = (avg_close/avg_cost − 1) · (+1 Long / −1 Short)`; fila inválida si `avg_cost≤0 or avg_close≤0 or notional≤0 or leverage≤0 or |pr|>3` → pr/alpha NULL.
  - celda = `(symbol, mes_de_opened_ms_UTC, side)`; benchmark = mediana de pr de la celda si `n≥min_cell`; `alpha = pr − benchmark` (NULL sin benchmark).
  - `t_stat = mean(alphas) / (pstdev(alphas)/√n_alpha)` (0 si pstdev=0).
  - `payoff = mean(pr>0) / |mean(pr<0)|`; sin ganadoras o sin perdedoras → NULL (lo lee `detect`).
  - `conc_top1 = mejor closing_pnl / total_pnl · 100` (**NULL si total ≤ 0** — un trader perdedor no es "lotería"; cae por `no_alpha`/score, no por un conc=999 que mal-rotula el motivo) — **top-1, el criterio auditado** (`top5_final.py` línea `best/tot`); top-3 fue refutado en revisión adversarial.
  - `ruin = min(pr) · mediana(leverage) · 100` (solo si hay perdedoras, si no NULL).
  - `alpha_h1/alpha_h2`: media de la primera/segunda mitad de los alphas ordenados por `opened_ms`.

- [ ] **Step 1: Test que falla** — fixture sintética directa a la DB (sin CSV):

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
    # 21 traders "masa" en la celda (BTCUSDT, 2025-04, Long): pr = 0 → benchmark 0
    base = 1743500000000            # 2025-04-01 UTC (OJO: 2025, no 2026)
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
    assert m["mdd"] == 25.0                         # escala PORCENTUAL
    mo = json.loads(m["monthly_alpha"])
    assert abs(mo["2025-04"] - 0.014) < 1e-9        # mes con >=5 alphas presente
    pr = con.execute(
        "SELECT price_return, alpha FROM positions WHERE trader_id='T' "
        "ORDER BY opened_ms").fetchall()
    assert abs(pr[0]["price_return"] - 0.02) < 1e-9
    assert abs(pr[0]["alpha"] - 0.02) < 1e-9        # benchmark de la celda = 0

def test_invalid_rows_get_null_pr_and_dont_count(con):
    _seed(con)
    _pos(con, "T", "BTCUSDT", "Long", 1743500000000, 0, 110, 5)   # avg_cost 0 → invalida
    con.commit()
    metrics.compute(con, D, EX, min_cell=20)
    r = con.execute("SELECT price_return FROM positions WHERE trader_id='T' "
                    "AND avg_cost=0").fetchone()
    assert r["price_return"] is None
    m = con.execute("SELECT n FROM trader_metrics WHERE trader_id='T'").fetchone()
    assert m["n"] == 5                               # la invalida NO cuenta en n
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementar**

```python
# pipeline/metrics.py
"""Motor de metricas por trader. Replica top5_final.py sobre SQLite.
alpha = price_return des-apalancado - mediana de celda (symbol, mes, side)."""
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
                  'mes': _month(r['opened_ms']) if r['opened_ms'] else None})
    cell = collections.defaultdict(list)
    for x in R:
        if x['pr'] is not None:
            cell[(x['sym'], x['mes'], x['side'])].append(x['pr'])
    bench = {k: st.median(v) for k, v in cell.items() if len(v) >= min_cell}
    upd = []
    for x in R:
        b = bench.get((x['sym'], x['mes'], x['side']))
        x['alpha'] = (x['pr'] - b) if (x['pr'] is not None and b is not None) else None
        upd.append((x['pr'], x['alpha'], x['rowid']))
    con.executemany("UPDATE positions SET price_return=?, alpha=? WHERE rowid=?", upd)

    # metricas por trader SOLO sobre filas validas (pr no NULL) — como top5_final.py,
    # que descarta las invalidas antes de contar (n<60, celdas, pnl, meses)
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
        # top-1 (criterio auditado); NULL si el trader pierde en neto — un
        # perdedor no es "loteria", cae por no_alpha/score
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
                mo[z['mes']].append(z['alpha'])
        monthly = {m: st.mean(a) for m, a in sorted(mo.items()) if len(a) >= 5}
        s = snap.get(tid)
        out.append((snapshot_date, exchange, tid, v[0]['nick'], len(v), len(al),
                    st.mean(al) if al else None, t_stat, payoff, wr, conc, ruin,
                    s['mdd'] if s else None, lev_med, lev_p90,
                    st.median(z['marg'] for z in v) if v else None,
                    st.median(z['dur'] for z in v) if v else None,
                    len(set(z['mes'] for z in v if z['mes'])), h1, h2,
                    json.dumps(monthly)))
    con.executemany(
        "INSERT OR REPLACE INTO trader_metrics (snapshot_date,exchange,trader_id,nick,"
        "n,n_alpha,alpha,t_stat,payoff,wr,conc_top1,ruin,mdd,lev_med,lev_p90,marg_med,"
        "dur_med,months_active,alpha_h1,alpha_h2,monthly_alpha) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.commit()
    return len(out)
```

- [ ] **Step 4: PASS.** Si un assert falla, el bug está en la implementación o en la aritmética de la fixture — corregir la CAUSA, nunca debilitar el assert.
- [ ] **Step 5: Commit** — `git commit -m "feat(metrics): alpha por celda, t-stat, payoff y metricas por trader"`

---

### Task 5: detect — flags descalificantes y warnings

**Files:**
- Create: `pipeline/detect.py`
- Test: `tests/test_detect.py`

**Interfaces:**
- Consumes: `trader_metrics` (Task 4), `open_positions` (puede estar vacía).
- Produces: `detect.run(con, snapshot_date, exchange='binance') -> dict {trader_id: [flags]}`; escribe `trader_metrics.flags` (JSON array). Constantes exportadas: `detect.DISQUALIFYING = {"loss_hider","open_loss_divergence","lottery","roi_artifact","ruin_risk","not_copyable","insufficient","no_alpha"}` y `detect.WARNINGS = {"alpha_decay","inactive","style_drift","regime_onesided","mdd_high"}`.
- Reglas (umbral → flag), evaluadas en este orden; un trader puede acumular varios:
  - `insufficient`: `n<60 or n_alpha<40 or months_active<3`
  - `loss_hider`: `(wr>92 and n≥20) or (payoff is NULL and n≥20) or (payoff<0.5 and mdd>35)` — la rama de cero perdedoras NO exige `wr==100` (un trade break-even da wr<100 con cero perdedoras reales; el caso Una躺平记_ debe caer igual)
  - `open_loss_divergence`: existe fila en `open_positions` del trader con `sum(unrealized_pnl) < −2 × max(1, pnl_realizado_total)` (solo si hay data de abiertas)
  - `lottery`: `conc_top1 > 30` (top-1, criterio auditado)
  - `roi_artifact`: `roi_portada > 300` (%) y (`alpha ≤ 0 or t_stat < 2`) — roi de `trader_snapshot.roi`
  - `ruin_risk`: `lev_p90 > 25 or ruin < −500`
  - `not_copyable`: `marg_med < 50 or dur_med < 0.5`
  - `no_alpha`: `t_stat < 2.5`
  - `mdd_high` (warning): `35 ≤ mdd ≤ 60` — **escala PORCENTUAL** (mediana real ~30.15, GGbond哦=50.5; "Trampa 5" de SKILL.v3.md). Sin guard de loss_hider (el spec no lo pide).
  - `alpha_decay` (warning): `alpha_h2 < alpha_h1` (ambos no NULL). La mitad entre-snapshots la aplica `trend` (Task 6).
  - `inactive` (warning): sin posiciones con `closed_ms` en los últimos 30 días del máximo `closed_ms` del snapshot
  - `style_drift` NO va aquí — vive en `trend` (Task 6); `regime_onesided`: alpha mensual (de `monthly_alpha`) positivo en <50% de sus meses con dato, con ≥2 meses.

- [ ] **Step 1: Test que falla**

```python
# tests/test_detect.py
import json
from pipeline import detect

D, EX = "2026-09-01", "binance"

def _tm(con, tid, **kw):
    # mdd en escala PORCENTUAL (como la data real de Binance)
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
    # una posicion reciente para no disparar inactive
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
    _tm(con, "gg", wr=98.5, mdd=50.5)               # caso GGbond哦, escala %
    assert "loss_hider" in detect.run(con, D, EX)["gg"]

def test_loss_hider_zero_losers_with_breakeven(con):
    # caso Una躺平记_: cero perdedoras (payoff NULL) pero wr<100 por un break-even
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
- [ ] **Step 3: Implementar**

```python
# pipeline/detect.py
"""Bateria anti-inflado. Cada regla emite un flag por trader.
Casos de referencia: FINDINGS_v2.md / TOP5.md (GGbond, VickyKaushal, etc.)."""
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
        # mdd en escala PORCENTUAL (mediana ~30, GGbond=50.5) — Trampa 5 de SKILL.v3
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
- [ ] **Step 5: Commit** — `git commit -m "feat(detect): flags anti-inflado (loss_hider, lottery, roi_artifact, ...)"`

---

### Task 6: trend — diff entre snapshots, de-copy y trend_bonus

**Files:**
- Create: `pipeline/trend.py`
- Test: `tests/test_trend.py`

**Interfaces:**
- Consumes: `trader_metrics` de ≥1 snapshots; `detect.DISQUALIFYING`.
- Produces: `trend.run(con, snapshot_date, exchange='binance', prev_roster=None) -> dict` (el contenido de `diff.json`). Efectos: actualiza `trader_metrics.trend_bonus` y añade flags `style_drift` / decopy a `flags`. `prev_roster` = dict cargado del `roster.json` de la corrida previa o None.
- Lógica:
  - `prev_date` = mayor `snapshot_date < snapshot_date` en `snapshots` para ese exchange (None si no hay).
  - **trend_bonus**: pendiente por mínimos cuadrados de `monthly_alpha` (ordenado por mes, índice 0..k-1), `slope·100` clampeado a [−2, +2]; 0 si <3 meses con dato. Si hay `prev_date`, promedio simple entre ese valor y `sign(alpha_now − alpha_prev)` (+1/−1/0 clampeado igual): `bonus = clamp((slope·100 + sign)/2, −2, 2)`.
  - **de-copy** (flag descalificante `decopy_2neg` — añadirlo a `detect.DISQUALIFYING` NO: se trata como descalificante propio de trend; `rank` excluye `DISQUALIFYING | {"decopy_2neg"}`): `alpha<0` en este snapshot **y** en `prev_date`.
  - **alpha_decay entre snapshots** (la mitad del spec que detect no cubre): `alpha_now < alpha_prev` → añade el warning `alpha_decay` si no está.
  - **style_drift** (warning): `lev_med` o `marg_med` cambia >2× o <0.5× vs `prev_date` (ambos no NULL/no 0).
  - **Flags frescos**: `newly_disq` se calcula de los flags YA actualizados en esta corrida (dict en memoria), nunca del fetch inicial — si no, el propio `decopy_2neg` que trend añade sería invisible para el gate.
  - **Matching por `portfolio_id`** contra `prev_roster` (el nick es renombrable).
  - **diff.json**: `{"snapshot": date, "prev": prev_date, "added_a": [], "removed_a": [], "new_disqualified_incumbents": [{"nick","flags"}], "weight_moves": [{"nick","prev","now"}], "material": bool}` — los campos de roster (`added_a`, `removed_a`, `weight_moves`) los completa `rank` después de asignar tiers (trend deja listas vacías y `material` provisional); `material = true` si `prev_date is None` (primera corrida) o si algún titular de `prev_roster` recibió flag descalificante nuevo. `rank` re-evalúa `material` con los cambios de tier/peso.

- [ ] **Step 1: Test que falla**

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
    _tm(con, "2026-09-01", "A", 0.01)   # pendiente positiva en monthly
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
    # el gate ve el flag AÑADIDO EN ESTA CORRIDA (no flags stale del fetch inicial)
    assert d["new_disqualified_incumbents"][0]["portfolio_id"] == "B"
    assert d["material"] is True

def test_alpha_decay_between_snapshots(con):
    _tm(con, "2026-08-01", "E", 0.020)
    _tm(con, "2026-09-01", "E", 0.012)     # positivo pero decreciente
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
- [ ] **Step 3: Implementar**

```python
# pipeline/trend.py
"""Compara snapshots: quien mejora, quien decae, de-copy y style_drift."""
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
    updated = {}                      # flags FRESCOS post-update (evita leer stale)
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
                # mitad entre-snapshots de alpha_decay (spec): alpha bajo vs prev
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
        # matching por portfolio_id (estable) — el nick es renombrable
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
- [ ] **Step 5: Commit** — `git commit -m "feat(trend): diff entre snapshots, regla de-copy y trend_bonus"`

---

### Task 7: rank — score, tiers, pesos y roster.json

**Files:**
- Create: `pipeline/rank.py`
- Test: `tests/test_rank.py`

**Interfaces:**
- Consumes: `trader_metrics` con flags y trend_bonus; `detect.DISQUALIFYING`; el diff de `trend.run`; `prev_roster` (dict o None); nº de snapshots en que se ha visto cada trader (`SELECT COUNT(DISTINCT snapshot_date) FROM trader_metrics WHERE trader_id=?`).
- Produces: `rank.run(con, snapshot_date, exchange='binance', diff=None, prev_roster=None) -> dict` (el roster, formato del spec). Efectos: `UPDATE trader_metrics SET score, tier, weight`; completa `diff["added_a"/"removed_a"/"weight_moves"]` y re-evalúa `diff["material"]`.
- Algoritmo:
  1. Sobrevivientes = sin ningún flag en `DISQUALIFYING | {"decopy_2neg"}` **y score > 0**.
  2. `score = 0.40·t_stat + 0.25·alpha·100 + 0.20·(payoff or 0) + 0.15·trend_bonus`; luego `score ·= (0.9 ** n_warnings)` (warnings = flags ∩ `detect.WARNINGS`).
  3. Roster = top-5 por score. Tier A: 0 warnings **y** (visto en ≥2 snapshots **o** (n>300 **y es la primera corrida del pipeline** — un solo snapshot en la DB)). Tier B: el resto del top-5. Tier W: sobrevivientes fuera del top-5 **y** los que tienen `insufficient` como ÚNICO flag descalificante (novatos, no fraudes). Tier X: el resto de descalificados.
  4. Pesos: si hay A y B → pool A 0.70 / pool B 0.30; solo A → 1.0. **Solo B (típico de la corrida #1): cada B se capea a 0.10 y el remanente queda SIN ASIGNAR** (suma < 1.0, el roster lo declara en `unallocated`) — jamás se vuelca el exceso en un solo trader. Dentro del grupo proporcional al score; el exceso de caps de B se redistribuye a A solo si A existe. Redondear a múltiplos de 0.05; el ajuste de redondeo va al mayor peso de A (o se omite si no hay A).
  5. `removed` en el roster: titulares de `prev_roster` (por `portfolio_id`) que ya no están en A∪B, con `reason` = flags descalificantes o "fuera del top-5 por score".
  6. Material adicional: alta/baja en tier A vs prev_roster, **cualquier titular (A o B) que sale del roster**, o |Δweight|>0.10 de un titular (una salida cuenta como prev→0).
  7. Cada trader del roster lleva `trend`: `{"rank_prev", "rank_now", "alpha_delta"}` — rank por score dentro del snapshot previo (`trader_metrics` de `prev_date`, NULL si no existía) y delta de alpha.

- [ ] **Step 1: Test que falla**

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
    _tm(con, "A")                                   # limpio
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
    assert nicks[0] == "t0"                          # mayor score primero

def test_tiers_and_weights(con):
    _tm(con, "vet", n=400)                           # A (n>300, 0 warnings)
    _tm(con, "rookie", n=100, flags='["alpha_decay"]')  # B
    r = rank.run(con, D, EX)
    by = {t["nick"]: t for t in r["traders"]}
    assert by["vet"]["tier"] == "A" and by["rookie"]["tier"] == "B"
    assert abs(sum(t["weight"] for t in r["traders"]) - 1.0) < 1e-9
    assert by["rookie"]["weight"] <= 0.10 + 1e-9
    assert all(abs(t["weight"] * 20 - round(t["weight"] * 20)) < 1e-6
               for t in r["traders"])                # multiplos de 0.05

def test_material_on_tier_a_change(con):
    _tm(con, "vet", n=400)
    diff = {"material": False, "added_a": [], "removed_a": [], "weight_moves": []}
    prev = {"traders": [{"portfolio_id": "otro", "nick": "otro",
                         "tier": "A", "weight": 0.5}]}
    rank.run(con, D, EX, diff=diff, prev_roster=prev)
    assert "vet" in diff["added_a"] and "otro" in diff["removed_a"]
    # la salida del titular tambien aparece como weight_move prev->0
    assert any(m["nick"] == "otro" and m["now"] == 0.0
               for m in diff["weight_moves"])
    assert diff["material"] is True

def test_weights_all_B_respects_cap_and_leaves_unallocated(con):
    # corrida #1 tipica: nadie califica a tier A (todos con warning)
    for i in range(5):
        _tm(con, f"b{i}", t=4.0 - i * 0.1, n=100, flags='["alpha_decay"]')
    r = rank.run(con, D, EX)
    assert all(t["tier"] == "B" for t in r["traders"])
    assert all(t["weight"] <= 0.10 + 1e-9 for t in r["traders"])   # cap SIEMPRE
    assert abs(sum(t["weight"] for t in r["traders"]) - 0.50) < 1e-9
    assert abs(r["unallocated"] - 0.50) < 1e-9   # remanente declarado, no volcado

def test_insufficient_only_goes_to_W_not_X(con):
    _tm(con, "novato", n=30, flags='["insufficient"]')
    _tm(con, "fraude", n=100, flags='["loss_hider"]')
    rank.run(con, D, EX)
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    assert tiers["novato"] == "W" and tiers["fraude"] == "X"
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementar**

```python
# pipeline/rank.py
"""Score, tiers y pesos -> roster. Cap de 5 traders (A+B).
Matching entre corridas SIEMPRE por portfolio_id (el nick es renombrable)."""
import json, datetime as dt
from pipeline import detect as det

BAD = det.DISQUALIFYING | {'decopy_2neg'}

def _round05(x):
    return round(x * 20) / 20

def _weights(roster):
    """A y B: pool 70/30. Solo A: pool 1.0. Solo B: cap 0.10 c/u y el
    remanente queda SIN ASIGNAR (suma < 1.0) — nunca se vuelca en uno solo.
    Devuelve el peso no asignado."""
    A = [t for t in roster if t['tier'] == 'A']
    B = [t for t in roster if t['tier'] == 'B']
    poolA = 1.0 if (A and not B) else 0.70
    poolB = 0.30 if A else 1.0
    for grp, pool in ((A, poolA), (B, poolB)):
        tot = sum(t['score'] for t in grp)
        for t in grp:
            t['weight'] = pool * t['score'] / tot if tot else 0.0
    # cap iterativo de B: el exceso se reparte dentro de B entre los no capeados
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
    if A and b_excess > 1e-9:                 # exceso de B pasa a A si A existe
        totA = sum(t['weight'] for t in A)
        for t in A:
            t['weight'] += b_excess * t['weight'] / totA if totA else 0.0
    for t in roster:
        t['weight'] = _round05(t['weight'])
    assigned = sum(t['weight'] for t in roster)
    drift = 1.0 - assigned
    if A and abs(drift) > 1e-9:               # ajuste de redondeo SOLO sobre A
        mx = max(A, key=lambda t: t['weight'])
        mx['weight'] = _round05(mx['weight'] + drift)
        assigned = sum(t['weight'] for t in roster)
    return max(0.0, round(1.0 - assigned, 2))  # unallocated (solo-B lo deja >0)

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
        # n>300 sustituye historial SOLO en la primera corrida del pipeline
        c['tier'] = 'A' if (not c['warns'] and
                            (seen.get(c['tid'], 1) >= 2 or
                             (total_snaps <= 1 and (c['m']['n'] or 0) > 300))) \
                    else 'B'
    unallocated = _weights(roster)
    # rank del snapshot previo por score (para el bloque trend del roster)
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
            tier = 'W'                        # novato, no fraude (spec)
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
                      else 'fuera del top-5 por score' if c else 'fuera del universo')
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
- [ ] **Step 5: Commit** — `git commit -m "feat(rank): score, tiers A/B/W/X, pesos y roster"`

---

### Task 8: report — TOP_YYYY-MM.md

**Files:**
- Create: `pipeline/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: roster (dict de `rank.run`), diff (dict), `trader_metrics` (para excluidos notables).
- Produces: `report.write(con, snapshot_date, exchange, roster, diff, out_dir) -> str` (path del .md). Escribe `TOP_<YYYY-MM>.md` en `out_dir`. Secciones: título+fecha; tabla del roster (nick, tier, weight, score, alpha%, t, payoff, lev, mdd, n, warnings); **Cambios vs corrida anterior** (`prev` del diff; altas/bajas A, weight_moves, new_disqualified_incumbents; o "Primera corrida — sin corrida previa"); **Excluidos notables** (top-10 por `trader_snapshot.roi` entre tier X, con sus flags); **Caveats fijos** (texto literal: ventana de régimen única; survivorship top-600; winner's curse ≈ mitad del alpha; solo posiciones cerradas visibles).

- [ ] **Step 1: Test que falla**

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
    assert "suoha" in text and "Cambios" in text
    assert "vicky" in text and "roi_artifact" in text
    assert "winner" in text.lower() or "mitad del alpha" in text
    assert "Primera corrida" in text
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementar**

```python
# pipeline/report.py
"""Genera el reporte humano TOP_YYYY-MM.md."""
import json, os

CAVEATS = """## Caveats fijos
- **Ventana de régimen única**: la data cubre pocos meses y un solo ciclo; \
consistencia dentro del ciclo, no estabilidad universal.
- **Survivorship**: el universo Binance es el top-600 por ROI-90D; no hay grupo \
de control de traders quebrados.
- **Winner's curse**: con cientos de candidatos filtrados, espera ~la mitad del \
alpha mostrado.
- **Solo posiciones cerradas** son visibles (salvo data de abiertas): las \
perdidas latentes de un loss-hider pueden no aparecer.
"""

def write(con, snapshot_date, exchange, roster, diff, out_dir):
    month = snapshot_date[:7]
    path = os.path.join(str(out_dir), f"TOP_{month}.md")
    L = [f"# Roster copy-trading — {snapshot_date} ({exchange})", ""]
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
        L.append(f"\n**Peso sin asignar: {roster['unallocated']:.0%}** "
                 f"(roster todo tier B — cap del 10% por trader)")
    L += ["", "## Cambios vs corrida anterior"]
    if diff.get("prev") is None:
        L.append("Primera corrida — sin corrida previa.")
    else:
        L.append(f"Comparado con {diff['prev']}.")
        for n in diff["added_a"]:
            L.append(f"- ▲ **{n}** entra a tier A")
        for n in diff["removed_a"]:
            L.append(f"- ▼ **{n}** sale de tier A")
        for w in diff["weight_moves"]:
            L.append(f"- ⚖ **{w['nick']}**: {w['prev']:.0%} → {w['now']:.0%}")
        for d in diff["new_disqualified_incumbents"]:
            L.append(f"- ✖ **{d['nick']}** descalificado: {', '.join(d['flags'])}")
        if len(L[-1]) and L[-1].startswith("Comparado") :
            L.append("Sin cambios materiales.")
    for r in roster.get("removed", []):
        L.append(f"- ✖ **{r['nick']}** fuera del roster: {r['reason']}")
    L += ["", "## Excluidos notables"]
    rows = con.execute(
        "SELECT tm.nick, ts.roi, tm.flags FROM trader_metrics tm "
        "LEFT JOIN trader_snapshot ts ON ts.snapshot_date=tm.snapshot_date "
        "AND ts.exchange=tm.exchange AND ts.trader_id=tm.trader_id "
        "WHERE tm.snapshot_date=? AND tm.exchange=? AND tm.tier='X' "
        "ORDER BY ts.roi DESC LIMIT 10", (snapshot_date, exchange)).fetchall()
    for r in rows:
        roi = f"{r['roi']:.0f}%" if r['roi'] is not None else "—"
        L.append(f"- **{r['nick']}** (ROI portada {roi}): "
                 f"{', '.join(json.loads(r['flags'] or '[]'))}")
    L += ["", CAVEATS]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
```

- [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat(report): reporte humano TOP_YYYY-MM.md"`

---

### Task 9: scrape — a snapshot fechado, resumable

**Files:**
- Create: `pipeline/scrape.py`
- Test: `tests/test_scrape.py`

**Interfaces:**
- Consumes: red (Binance/Phemex, endpoints y headers idénticos a `scripts/scrape_binance.py` y `scripts/scrape_positions.py` — copiar `UA`, URLs y cuerpos tal cual; NO importar los scripts viejos).
- Produces: `scrape.run(snap_dir, exchanges=('binance','phemex'), pages_binance=20, pages_phemex=7, extra_ids_binance=(), http_post=None, http_get=None) -> dict {"binance": n_traders, "phemex": n_traders}`. Escribe `binance_raw.jsonl` / `phemex_raw.jsonl` en `snap_dir` (formato de línea idéntico al actual). Resumable: si el archivo ya existe en el snapshot dir, salta los trader_id presentes. `http_post`/`http_get` inyectables para tests (default = las funciones reales con urllib). Las listas de portfolios/traders se guardan también como `binance_list.json` / `phemex_list.json` en el snapshot dir.
- **`extra_ids_binance`** (unión histórica del spec): portfolio_ids conocidos de corridas previas que ya NO están en la lista viva — se les baja igual el position-history (el endpoint acepta cualquier pid) con un registro mínimo `{'portfolioId': pid, 'nick': None, ..., 'positions': rows}`. Así el de-copy ve decaer a un trader justo cuando sale del top-600.
- **⚠️ Cap real de la list API: 30/página aunque pidas 50** (SKILL.v3: "pageSize se ignora"). Por eso: `pages_binance=20` por default (≥600 portfolios) y el loop de `fetch_portfolios` corta SOLO con página vacía (`not lst`), NUNCA con `len(lst) < pageSize` — con el cap de 30 ese break cortaría en la página 1 y entregaría la mitad del universo pasando la validación ±50% por 3 traders.
- **Fallo de red ≠ hecho**: si `fetch_history` recibe `{'code':'ERR'}` a mitad de paginación, NO se escribe el registro del trader (queda fuera de `done` y el resume lo reintenta). El bug heredado de `scripts/scrape_binance.py` (ERR → `positions: []` → marcado como completo para siempre) NO se copia. `fetch_history` devuelve `(rows, ok)` y solo `ok=True` escribe.
- Diferencias vs scripts viejos: (1) escribe al snapshot dir, no a `data/*.jsonl` global; (2) funciones puras parametrizadas; (3) al final imprime resumen `{exchange: n}`; (4) los dos puntos de arriba.

- [ ] **Step 1: Test que falla** (con HTTP mockeado)

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
    assert counts["binance"] == 0          # ya estaba, no re-scrapea
    lines = (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1                  # sin duplicados

def test_network_error_does_not_mark_trader_done(tmp_path):
    def _err_post(url, body):
        if "query-list" in url:
            return _fake_post(url, body)
        return {"code": "ERR"}              # historial siempre falla
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_err_post)
    assert counts["binance"] == 0           # nada escrito
    raw = tmp_path / "binance_raw.jsonl"
    assert not raw.exists() or raw.read_text().strip() == ""
    # al reintentar con red sana, el trader SI se baja (no quedo marcado hecho)
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1

def test_extra_ids_union_historica(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post,
                        extra_ids_binance=("P_OLD",))
    assert counts["binance"] == 2           # P1 (lista viva) + P_OLD (historico)
    lines = [json.loads(l) for l in
             (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()]
    ids = {l["portfolioId"] for l in lines}
    assert ids == {"P1", "P_OLD"}
```

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implementar** — portar los dos scrapers a `pipeline/scrape.py` con la estructura:

```python
# pipeline/scrape.py  (esqueleto — cuerpos de red copiados de scripts/scrape_*.py)
"""Scrape Binance+Phemex a un snapshot fechado. Resumable dentro del snapshot."""
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
    # identico a scripts/scrape_binance.py::post
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
    # identico a scripts/scrape_positions.py::get, headers PUA
    ...

def _done_ids(path, key):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try: done.add(json.loads(line)[key])
            except Exception: pass
    return done

def _fetch_history(pid, post):
    """Devuelve (rows, ok). ok=False si hubo ERR a mitad de paginacion —
    en ese caso el caller NO escribe el registro (el resume lo reintenta).
    NO copiar el bug de scripts/scrape_binance.py (ERR -> [] -> 'hecho')."""
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
    # por cada portfolio de la lista + cada pid de extra_ids no presente en ella:
    #   rows, ok = _fetch_history(pid, post)
    #   solo si ok: escribir el registro (formato identico al actual; para
    #   extra_ids sin metadata: nick/roi/pnl/aum/winRate/mdd = None) y append
    #   a snap_dir/binance_raw.jsonl, saltando _done_ids(..., 'portfolioId').
    # Devuelve nº de portfolios NUEVOS escritos.
    ...

def _scrape_phemex(snap_dir, pages, get):
    # fetch_trader_list + loop de scripts/scrape_positions.py, mismo patron
    # (incluida la misma regla: fallo de red -> no escribir, no marcar hecho).
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

Los cuerpos de `_scrape_binance`/`_scrape_phemex`/`_get` se copian línea a línea de los scripts viejos cambiando solo rutas de salida y la inyección de `post`/`get`. El registro por trader debe ser **idéntico** al formato actual (`{'portfolioId', 'nick', 'roi', 'pnl', 'aum', 'winRate', 'mdd', 'n_pos', 'positions'}` / `{'userId', 'nick', 'n_pos', 'positions'}`) para que Task 2 los lea.

- [ ] **Step 4: PASS** (tests solo del camino Binance mockeado; añadir un test análogo para Phemex con `http_get` mockeado que devuelva 1 trader con `showPosition: true` y 1 página de posiciones).
- [ ] **Step 5: Commit** — `git commit -m "feat(scrape): scrapers a snapshot fechado, resumable e inyectable"`

---

### Task 10: CLI — pipeline.py con subcomandos y validación

**Files:**
- Create: `pipeline.py` (raíz del proyecto)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: todos los módulos anteriores.
- Produces: CLI:
  - `python3 pipeline.py scrape [--date YYYY-MM-DD] [--exchange binance|phemex|all]` → `data/snapshots/<date>/` (date default hoy). Pasa a `scrape.run` los `extra_ids_binance` = distinct `trader_id` históricos de la DB que no estén ya bajados (unión histórica del spec).
  - `python3 pipeline.py analyze [--date YYYY-MM-DD] [--force]` → flatten→**validación (ANTES de ingest, desde los CSV)**→ingest→metrics→detect→trend→rank→report; escribe `analysis/runs/<date>/{roster.json,diff.json,TOP_*.md}`. **NO toca `analysis/roster.json`** (el latest).
  - `python3 pipeline.py publish --date YYYY-MM-DD` → copia `analysis/runs/<date>/roster.json` a `analysis/roster.json`. Es el ÚNICO comando que escribe el latest; la skill lo invoca tras el gate del consejo.
  - Subcomandos granulares `metrics|detect|trend|rank|report --date ...` para debug. **Orden obligatorio documentado en el `--help`**: metrics→detect→trend→rank→report (metrics resetea flags/trend_bonus vía INSERT OR REPLACE; un rank sin detect/trend posterior rankearía sin flags).
- **Validación pre-ingest** (la DB no se toca si falla): (a) `data/snapshots/<date>/` debe existir y tener al menos un `*_raw.jsonl` no vacío — un `--date` con typo NUNCA produce un roster vacío; (b) contando filas de los CSV recién flatteneados vs el snapshot previo en `snapshots` (si existe): `n_traders` y `n_positions` dentro de ±50%; (c) **un exchange con snapshot previo en la DB cuyo CSV hoy no existe o está vacío → falla** (Phemex caído ≠ data completa). Cualquier fallo → detalle a stderr y `return 2`, salvo `--force`.
- `prev_roster`: se carga de `analysis/runs/<prev_date>/roster.json` si existe (prev_date = snapshot previo en DB **del exchange analizado**).
- Función `main(argv=None, project_root=None)` para testear con `tmp_path`.

- [ ] **Step 1: Test que falla**

```python
# tests/test_cli.py
import importlib.util, json, pathlib, shutil

# pipeline.py (archivo) colisiona con pipeline/ (paquete): cargar el CLI por path
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
    assert diff["material"] is True            # primera corrida
    assert (run_dir / "TOP_2026-09.md").exists()
    # analyze NO publica el latest — eso es publish, tras el gate
    assert not (root / "analysis" / "roster.json").exists()
    rc = cli.main(["publish", "--date", "2026-09-01"], project_root=str(root))
    assert rc == 0
    assert (root / "analysis" / "roster.json").exists()

def test_analyze_aborts_on_missing_snapshot_dir(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir)
    # typo en --date: no debe producir un roster (menos aun uno vacio)
    rc = cli.main(["analyze", "--date", "2026-12-31"], project_root=str(root))
    assert rc == 2
    assert not (root / "analysis" / "runs" / "2026-12-31").exists()

def test_analyze_validation_blocks_partial_data(tmp_path, snap_dir):
    root = _setup_project(tmp_path, snap_dir, "2026-09-01")
    cli.main(["analyze", "--date", "2026-09-01"], project_root=str(root))
    # segundo snapshot con 5x las posiciones -> fuera de ±50%
    d2 = root / "data" / "snapshots" / "2026-10-01"
    d2.mkdir()
    lines = (snap_dir / "binance_raw.jsonl").read_text()
    rec = json.loads(lines)
    rec["positions"] = rec["positions"] * 5
    (d2 / "binance_raw.jsonl").write_text(json.dumps(rec) + "\n")
    rc = cli.main(["analyze", "--date", "2026-10-01"], project_root=str(root))
    assert rc == 2
    # la DB NO quedo envenenada: el snapshot rechazado no existe en `snapshots`
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
- [ ] **Step 3: Implementar**

```python
#!/usr/bin/env python3
# pipeline.py — entrypoint del pipeline copy-trading-refresh
"""Uso:
  python3 pipeline.py scrape  [--date YYYY-MM-DD] [--exchange all|binance|phemex]
  python3 pipeline.py analyze [--date YYYY-MM-DD] [--force]
  python3 pipeline.py publish --date YYYY-MM-DD     (unico que escribe analysis/roster.json)
  python3 pipeline.py metrics|detect|trend|rank|report --date YYYY-MM-DD
     (orden obligatorio: metrics -> detect -> trend -> rank -> report;
      metrics resetea flags/trend_bonus — un rank sin detect+trend rankea sin flags)
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
    """(n_traders, n_positions) del CSV del snapshot, o None si no existe/vacio."""
    path = os.path.join(snap_dir, f'{ex}.csv')
    if not os.path.exists(path):
        return None
    key = 'portfolio_id' if ex == 'binance' else 'trader_id'
    traders, n = set(), 0
    for r in csv.DictReader(open(path)):
        traders.add(r[key]); n += 1
    return (len(traders), n) if n else None

def _validate_pre(con, snap_dir, date, force):
    """ANTES de ingest, desde los CSV — la DB no se toca si falla."""
    raws = [p for p in glob.glob(os.path.join(snap_dir, '*_raw.jsonl'))
            if os.path.getsize(p) > 0]
    if not os.path.isdir(snap_dir) or not raws:
        print(f"VALIDACION: {snap_dir} no existe o no tiene *_raw.jsonl — "
              f"¿typo en --date?", file=sys.stderr)
        return False                       # esto ni --force lo salta
    if _csv_counts(snap_dir, 'binance') is None:
        print("VALIDACION: sin binance.csv (o vacio) — v1 analiza Binance; "
              "seguir produciria un roster VACIO", file=sys.stderr)
        return False                       # esto TAMPOCO lo salta --force
    ok = True
    for ex in ('binance', 'phemex'):
        prev = con.execute(
            "SELECT snapshot_date, n_traders, n_positions FROM snapshots "
            "WHERE exchange=? AND snapshot_date<? ORDER BY snapshot_date DESC LIMIT 1",
            (ex, date)).fetchone()
        cur = _csv_counts(snap_dir, ex)
        if prev and cur is None:
            print(f"VALIDACION {ex}: tenia snapshot previo ({prev['snapshot_date']}) "
                  f"pero hoy no hay CSV — scrape incompleto", file=sys.stderr)
            ok = False
            continue
        if not prev or cur is None:
            continue
        for field, c, p in (('n_traders', cur[0], prev['n_traders']),
                            ('n_positions', cur[1], prev['n_positions'])):
            if p and not (0.5 * p <= c <= 1.5 * p):
                print(f"VALIDACION {ex}.{field}: {c} vs {p} en "
                      f"{prev['snapshot_date']} (fuera de ±50%)", file=sys.stderr)
                ok = False
    if not ok and not force:
        print("Abortando SIN tocar la DB; usa --force para continuar.",
              file=sys.stderr)
        return False
    return True

def _known_ids(con, snap_dir):
    """Union historica: ids de la DB que aun no estan bajados en este snapshot."""
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
        epilog='Orden de subcomandos granulares: metrics -> detect -> trend -> '
               'rank -> report (metrics resetea flags/trend_bonus).')
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
            print(f"publish: no existe {src} — corre analyze primero",
                  file=sys.stderr)
            return 1
        shutil.copy(src, P['latest'])
        print('publicado:', P['latest'])
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
                  if os.path.isdir(P['snap']) else 'snapshot dir inexistente')
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
            # NO se copia a analysis/roster.json aqui: eso es `publish`, tras el gate
            print('reporte:', p)
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
            # lee los artefactos de la corrida — NO recomputa trend/rank
            # (recomputar sin prev_roster produciria un diff distinto al de analyze)
            rp = os.path.join(P['run'], 'roster.json')
            dp = os.path.join(P['run'], 'diff.json')
            if not (os.path.exists(rp) and os.path.exists(dp)):
                print("report: faltan roster.json/diff.json — corre analyze primero",
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

**Nota:** `pipeline.py` (archivo) y `pipeline/` (paquete) coexisten — por eso `tests/test_cli.py` carga el CLI vía `importlib` por path (ya incluido en el bloque del Step 1).

- [ ] **Step 4: PASS** — `python3 -m pytest tests/ -v` (suite completa en verde).
- [ ] **Step 5: Commit** — `git commit -m "feat(cli): pipeline.py con scrape/analyze y validacion de snapshot"`

---

### Task 11: Regresión contra el snapshot real 2026-08-25

**Files:**
- Create: `tests/test_regression.py`, `data/snapshots/2026-08-25/` (symlinks/copias de la data existente)

**Interfaces:**
- Consumes: `data/binance_positions.jsonl` y `data/positions_all.jsonl` reales (43MB/4.4MB — ya existen, gitignored).

- [ ] **Step 1: Preparar el snapshot histórico** (una vez, no test):

```bash
cd ~/Projects/trading/copy-trading-intel
mkdir -p data/snapshots/2026-08-25
ln -sf ../../binance_positions.jsonl data/snapshots/2026-08-25/binance_raw.jsonl
ln -sf ../../positions_all.jsonl data/snapshots/2026-08-25/phemex_raw.jsonl
```

- [ ] **Step 2: Escribir el test de regresión** (marcado `slow`, se salta si falta la data):

```python
# tests/test_regression.py
"""Reproduce el analisis auditado del 2026-08-25 con el pipeline nuevo.
Referencia: analysis/TOP5.md y FINDINGS_v2.md."""
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
    """Guarda contra la regresion de escala: mdd es PORCENTUAL (Trampa 5)."""
    con, flags, roster = real
    med = con.execute(
        "SELECT mdd FROM trader_snapshot WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance' AND mdd IS NOT NULL ORDER BY mdd "
        "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM trader_snapshot "
        "WHERE snapshot_date='2026-08-25' AND exchange='binance' "
        "AND mdd IS NOT NULL)").fetchone()[0]
    assert 10 <= med <= 60          # mediana real ~30.15; si sale <1, la escala se rompio

def test_known_top_traders_survive(real):
    con, flags, roster = real
    m = _by_nick(con)
    # 梭哈到世界尽头: n=527, t~6, lev 5x, conc top-1 = 26.1% — sobrevive
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
    # OJO: el nick real en la data lleva sufijo — es 龟兔赛跑985-重新起航
    assert "lottery" in json.loads(m["龟兔赛跑985-重新起航"]["flags"])
    assert "ruin_risk" in json.loads(m["牛熊摆渡人"]["flags"])   # lev p90 / -1173%

def test_roster_is_five_and_sane(real):
    con, flags, roster = real
    assert len(roster["traders"]) <= 5
    total = sum(t["weight"] for t in roster["traders"]) + roster["unallocated"]
    assert abs(total - 1.0) < 1e-9   # asignado + sin asignar = 1.0 (corrida #1
                                     # puede ser todo-B → unallocated > 0)
```

- [ ] **Step 3: Correr** — `python3 -m pytest tests/test_regression.py -v` (tarda ~1-2 min por los 108k rows). Si un assert falla, investigar ANTES de relajar el umbral: la data real manda; los nombres exactos pueden diferir (p.ej. sufijos en el nick — buscar con `LIKE` si el exacto no aparece y ajustar el test con el nick literal encontrado).
- [ ] **Step 4: Commit** — `git commit -m "test(regression): pipeline reproduce el analisis auditado 2026-08-25"`

---

### Task 12: Spike — posiciones abiertas (open_loss_divergence directo)

**Files:**
- Create: `scripts/probe_open_positions.py` (throwaway hasta confirmar)
- Modify (solo si el spike funciona): `pipeline/scrape.py`, `pipeline/ingest.py`, `SKILL.v3.md`

**Interfaces:**
- Produces: respuesta a "¿hay endpoint público de posiciones ABIERTAS por lead-trader?" documentada. Si sí: scrape/ingest llenan `open_positions` y el flag `open_loss_divergence` (ya implementado en Task 5) se activa con data real.

- [ ] **Step 1: Escribir la sonda**

```python
#!/usr/bin/env python3
# scripts/probe_open_positions.py — spike: ¿posiciones abiertas publicas?
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
                      f"data={'SI' if d.get('data') else 'vacio'}")
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
    # ids reales: sacarlos de data/snapshots/<ultimo>/binance_list.json y
    # phemex_list.json (o data/binance_portfolios.json / all_traders.json)
    try_binance(sys.argv[1] if len(sys.argv) > 1 else '')
    try_phemex(sys.argv[2] if len(sys.argv) > 2 else '')
```

- [ ] **Step 2: Correr la sonda** con un `portfolioId` real (de `data/binance_portfolios.json`) y un `userId` real (de `data/all_traders.json`). Anotar salida.
- [ ] **Step 3: Documentar el resultado** — añadir a `SKILL.v3.md` (sección Endpoints) una línea por exchange: endpoint confirmado + campos, o "verificado NO disponible el 2026-XX-XX".
- [ ] **Step 4 (solo si funciona):** en `pipeline/scrape.py` añadir la llamada por trader y volcar a `open_raw.jsonl` del snapshot; en `pipeline/ingest.py` poblar `open_positions` (columnas: symbol, side, notional, unrealized_pnl según los nombres reales que devuelva el endpoint). Test análogo a los de Task 9 con HTTP mockeado.
- [ ] **Step 5: Commit** — `git commit -m "spike: sonda de posiciones abiertas (+ integracion si disponible)"`

---

### Task 13: Skill `/copy-trading-refresh`

**Files:**
- Create: `~/.claude/skills/copy-trading-refresh/SKILL.md`

**Interfaces:**
- Consumes: el CLI de Task 10, el gate de materialidad de `diff.json`, la skill `adversarial-review` existente.

- [ ] **Step 1: Escribir la skill**

```markdown
---
name: copy-trading-refresh
description: Refresca el roster de lead-traders a copiar (Binance+Phemex). Scrapea data fresca, corre el motor determinista (alpha, anti-inflado, tendencia), y si el roster cambia materialmente lanza el consejo adversarial (Fable/Kimi/GLM) antes de publicar. Use when the user asks to "refrescar el roster", "actualizar los traders", "correr el pipeline de copy-trading", "revisar si cambiaron los traders a seguir", o menciona copy-trading-refresh. Se corre 1-2 veces al mes.
---

# copy-trading-refresh

Proyecto: `~/Projects/trading/copy-trading-intel`. Spec:
`docs/superpowers/specs/2026-08-28-copy-trading-refresh-design.md`.

## Runbook

1. `cd ~/Projects/trading/copy-trading-intel`
2. **Scrape** (tarda varios minutos; resumable):
   `python3 pipeline.py scrape`
   - Si falla a mitad (red, rate-limit): re-correr el mismo comando — salta lo ya
     bajado; un trader cuyo historial falló por red NO quedó marcado como hecho.
   - Si un endpoint devuelve error persistente (HTTP 4xx/5xx repetido): PARAR y
     reportar a the operator el status exacto. Binance rota APIs sin aviso; no improvisar
     endpoints nuevos sin confirmar.
3. **Analyze** (segundos, sin red):
   `python3 pipeline.py analyze`
   - Valida ANTES de ingerir; si falla (exit 2) la DB queda intacta. Revisar el
     stderr, reportar a the operator, y solo usar `--force` si the operator lo aprueba (un
     snapshot sin binance.csv ni con --force pasa — produciría roster vacío).
   - `analyze` NUNCA escribe `analysis/roster.json` — eso es el paso 7.
4. Leer `analysis/runs/<hoy>/diff.json`.
5. **Gate del consejo**:
   - `material: false` → ir al paso 7.
   - `material: true` → invocar la skill `adversarial-review` con: el `diff.json`,
     el `roster.json`, los CSV del snapshot (`data/snapshots/<hoy>/binance.csv`), y
     la pregunta concreta: "El motor promovió/expulsó a <X>. Re-deriva sus números
     desde el CSV y refuta o confirma cada cambio del diff. No apruebes por cortesía."
6. **Merge de veredictos**: añadir al `TOP_*.md` una sección `## Consejo adversarial`
   con confirma/objeta por cambio. Si el consejo OBJETA una promoción a tier A:
   NO publicar ese cambio — presentar la objeción a the operator y esperar su decisión.
7. **Publicar**: `python3 pipeline.py publish --date <hoy>` — el ÚNICO comando que
   escribe `analysis/roster.json` (lo que consume el mirror-bot). Solo tras pasar
   el gate (o tras la decisión de the operator si hubo objeciones).
8. **Presentar a the operator**: tabla del roster, ▲▼ del diff (cada trader trae
   `trend.rank_prev/rank_now/alpha_delta`), altas/bajas con motivo, `unallocated`
   si el roster es todo-B, objeciones del consejo si las hubo. Recordar el caveat
   fijo: espera ~la mitad del alpha mostrado (winner's curse).

## Qué NO hace
- No configura el mirror-bot (the operator conecta `analysis/roster.json` a mano).
- No corre por cron (invocación manual, 1-2x/mes).
- No borra snapshots viejos: `data/snapshots/` es la fuente de verdad histórica.
```

- [ ] **Step 2: Verificar** — nueva sesión de Claude Code: `/copy-trading-refresh` aparece y carga.
- [ ] **Step 3: Commit del proyecto** (la skill vive fuera del repo; commitear la referencia): añadir al final de `SKILL.v3.md` una línea en Scripts: `- pipeline.py — pipeline permanente (ver docs/superpowers/specs/2026-08-28-...). Skill de invocación: ~/.claude/skills/copy-trading-refresh/`. `git commit -m "docs: referencia al pipeline y skill copy-trading-refresh"`

---

### Task 14: Primera corrida real de punta a punta

- [ ] **Step 1:** `python3 pipeline.py scrape` (real, ~10-20 min). Verificar `data/snapshots/<hoy>/` con los dos `_raw.jsonl`.
- [ ] **Step 2:** `python3 pipeline.py analyze`. Primera corrida → `material: true` esperado.
- [ ] **Step 3:** Revisar `TOP_<mes>.md` manualmente: ¿el roster se parece al Top 5 auditado (con la data nueva puede variar)? ¿Los excluidos notables tienen sentido?
- [ ] **Step 4:** Presentar el resultado a the operator con el diff vs el Top 5 del 2026-08-25. the operator decide si lanzar el consejo adversarial en esta primera corrida (es material por definición).
- [ ] **Step 5: Commit** — `git add analysis/runs/ && git commit -m "chore: primera corrida del pipeline"` (los runs SÍ se versionan; solo la data cruda está gitignored — verificar que `.gitignore` no excluya `analysis/runs/`).

---

## Self-Review + Revisión adversarial (2026-08-28)

El plan pasó por revisión adversarial de 3 revisores independientes (Fable, Kimi, GLM,
modo diseño) y TODAS las correcciones están incorporadas arriba. Los cambios mayores vs
la versión inicial:

1. **mdd es PORCENTUAL** (los 3 revisores + verificación directa) — umbrales 35/60, fixtures en %, test de regresión de escala (T11).
2. **conc = top-1 >30%** (criterio auditado) — top-3>30 descalificaba a 5/6 supervivientes auditados. NULL si PnL total ≤0.
3. **Phemex: de-scope explícito en v1** — se archiva (scrape/flatten/ingest, `side` desde `pos_side`) pero no se rankea.
4. **Pesos all-B**: cap 10% siempre, remanente `unallocated` (nunca volcado en uno solo); score>0 para entrar al roster.
5. **Validación PRE-ingest desde CSVs** — la DB no se envenena con snapshots rechazados; sin binance.csv ni `--force` pasa; exchange con historia y sin CSV falla.
6. **`publish` separado de `analyze`** — el latest solo se escribe tras el gate del consejo.
7. **Gate**: matching por `portfolio_id`, salidas de titulares (A o B) son materiales, `decopy_2neg` visible (flags frescos en trend), alpha_decay entre snapshots.
8. **Scrape**: fallo de red ≠ trader hecho; cap real 30/página (pages=20, break solo con página vacía); unión histórica vía `extra_ids_binance`.
9. **`insufficient`-only → W** (novato), no X (fraude). Tier A por n>300 solo en la corrida #1.
10. **Roster con bloque `trend`** (`rank_prev/rank_now/alpha_delta`); `report` granular lee artefactos, no recomputa.
11. Tests: assert vacuo eliminado, fixtures con epochs correctos (2025), nick real `龟兔赛跑985-重新起航`, importlib inline, tests nuevos (all-B, zero-losers con break-even, error de red, extra_ids, W-vs-X, DB no envenenada).

- **Placeholders:** los únicos `...` están en Task 9 con instrucción explícita de copiar línea-a-línea los cuerpos desde `scripts/scrape_*.py` — aceptable porque el contenido exacto existe y está referenciado (con las 2 desviaciones obligatorias documentadas: ERR≠hecho y break por página vacía).
- **Consistencia de tipos:** `flags` siempre JSON array en TEXT; `conc_top1` renombrado consistentemente (schema, metrics, detect, tests, regresión); `decopy_2neg` descalificante en `rank.BAD` y en `trend`; roster/removed/diff llevan `portfolio_id`.
```
