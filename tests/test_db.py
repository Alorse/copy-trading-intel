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
