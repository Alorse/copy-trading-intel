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
  start_time INTEGER,
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
  n_alpha_dropped_self_dominated INTEGER DEFAULT 0, max_cell_share REAL DEFAULT 0,
  PRIMARY KEY (snapshot_date, exchange, trader_id));
"""

TABLES = ["snapshots", "trader_snapshot", "positions",
          "open_positions", "trader_metrics"]


# Columns added after the first schema shipped. CREATE TABLE IF NOT EXISTS will
# not add them to a DB that already exists, and the DB is expensive to rebuild
# (it needs the raw snapshots), so add them in place.
_ADDED = [("trader_snapshot", "start_time", "INTEGER"),
          ("trader_metrics", "n_alpha_dropped_self_dominated", "INTEGER"),
          ("trader_metrics", "max_cell_share", "REAL")]


def _migrate(con):
    for table, col, typ in _ADDED:
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.commit()


def connect(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def clear_snapshot(con, snapshot_date, exchange):
    for t in TABLES:
        con.execute(f"DELETE FROM {t} WHERE snapshot_date=? AND exchange=?",
                    (snapshot_date, exchange))
    con.commit()
