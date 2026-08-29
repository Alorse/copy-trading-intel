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


def test_ingest_stores_start_time_from_listing(con, snap_dir):
    # startTime is only in <exchange>_list.json, never in the positions jsonl
    _load(con, snap_dir)
    st = con.execute("SELECT start_time FROM trader_snapshot "
                     "WHERE exchange='binance'").fetchone()[0]
    assert st == 1735689600000
    # phemex has no listing in the fixture -> NULL, not a crash
    assert con.execute("SELECT start_time FROM trader_snapshot "
                       "WHERE exchange='phemex'").fetchone()[0] is None


def test_ingest_survives_missing_listing(con, snap_dir, tmp_path):
    (snap_dir / "binance_list.json").unlink()
    counts = _load(con, snap_dir)
    assert counts["binance"] == 1
    assert con.execute("SELECT start_time FROM trader_snapshot "
                       "WHERE exchange='binance'").fetchone()[0] is None
