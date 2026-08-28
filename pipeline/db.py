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
