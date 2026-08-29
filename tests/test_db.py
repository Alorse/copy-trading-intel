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


def test_migration_adds_column_to_an_existing_db(tmp_path):
    """CREATE TABLE IF NOT EXISTS will not add a column to a DB that already
    exists, and rebuilding needs the raw snapshots — so connect() must migrate."""
    import sqlite3
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE trader_snapshot (snapshot_date TEXT NOT NULL, "
                "exchange TEXT NOT NULL, trader_id TEXT NOT NULL, nick TEXT, "
                "roi REAL, pnl REAL, aum REAL, win_rate REAL, mdd REAL, "
                "PRIMARY KEY (snapshot_date, exchange, trader_id))")
    old.execute("INSERT INTO trader_snapshot VALUES "
                "('2026-01-01','binance','X','x',1,2,3,4,5)")
    old.commit()
    old.close()
    con = dbmod.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(trader_snapshot)")}
    assert "start_time" in cols
    row = con.execute("SELECT nick, start_time FROM trader_snapshot").fetchone()
    assert row["nick"] == "x" and row["start_time"] is None   # data preserved
    con.close()
