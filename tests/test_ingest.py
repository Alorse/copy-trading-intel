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


def test_ingest_marks_listing_membership(con, snap_dir):
    """A portfolio present in <exchange>_list.json is `listed`; one reached only
    through the historical-union `extra_ids` path is not. Without this the two are
    indistinguishable in the DB, because the scraper writes the same record shape
    for both and every listing-only field (roi, mdd, startTime) lands as 0/NULL."""
    import json
    raw = snap_dir / "binance_raw.jsonl"
    rec = json.loads(raw.read_text().splitlines()[0])
    rec["portfolioId"] = "P_UNLISTED"          # not in binance_list.json
    with open(raw, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    _load(con, snap_dir)
    got = {r["trader_id"]: r["listed"] for r in con.execute(
        "SELECT trader_id, listed FROM trader_snapshot WHERE exchange='binance'")}
    assert got == {"P1": 1, "P_UNLISTED": 0}


def test_ingest_leaves_listing_membership_unknown_without_a_listing(con, snap_dir):
    # no listing file at all (Phemex, or a snapshot scraped before the field
    # existed) -> NULL, never a fabricated 0
    (snap_dir / "binance_list.json").unlink()
    _load(con, snap_dir)
    assert con.execute("SELECT listed FROM trader_snapshot "
                       "WHERE exchange='binance'").fetchone()[0] is None
    assert con.execute("SELECT listed FROM trader_snapshot "
                       "WHERE exchange='phemex'").fetchone()[0] is None


# --- lead-portfolio/detail -> trader_snapshot (2026-09-23) ------------------

def _detail(snap_dir, **kw):
    import json
    rec = {"portfolioId": "P1", "code": "000000", "retired": False,
           "status": "ACTIVE", "copierPnl": -6117.10893387,
           "currentCopyCount": 2, "totalCopyCount": 47,
           "aumAmount": 2340.2675162, "marginBalance": 2001.39704602,
           "fixedAmountMinCopyUsd": 10.0, "lastTradeTime": 1790179695096,
           "positionShow": False}
    rec.update(kw)
    (snap_dir / "binance_detail.jsonl").write_text(json.dumps(rec) + "\n")


def test_ingest_stores_the_copier_record(con, snap_dir):
    _detail(snap_dir)
    _load(con, snap_dir)
    r = con.execute("SELECT * FROM trader_snapshot WHERE exchange='binance'").fetchone()
    assert r["copier_pnl"] == -6117.10893387
    assert r["copier_count_current"] == 2 and r["copier_count_total"] == 47
    assert r["margin_balance"] == 2001.39704602
    assert r["aum_amount"] == 2340.2675162
    assert r["min_copy_usd"] == 10.0
    assert r["retired"] == 0


def test_ingest_marks_a_retired_portfolio(con, snap_dir):
    _detail(snap_dir, code="11012028", retired=True, status=None, copierPnl=None,
            currentCopyCount=None, totalCopyCount=None, aumAmount=None,
            marginBalance=None, fixedAmountMinCopyUsd=None)
    _load(con, snap_dir)
    r = con.execute("SELECT * FROM trader_snapshot WHERE exchange='binance'").fetchone()
    assert r["retired"] == 1
    assert r["copier_pnl"] is None and r["copier_count_total"] is None


def test_ingest_leaves_the_copier_record_null_without_a_detail_file(con, snap_dir):
    """No detail pass yet -> NULL, never 0. A fabricated 0.0 copierPnl is not
    < 0, so the gate would silently pass every unmeasured lead."""
    _load(con, snap_dir)
    r = con.execute("SELECT * FROM trader_snapshot WHERE exchange='binance'").fetchone()
    for col in ("copier_pnl", "copier_count_current", "copier_count_total",
                "aum_amount", "margin_balance", "min_copy_usd", "retired"):
        assert r[col] is None, col


def test_ingest_leaves_unfetched_traders_null(con, snap_dir):
    """`detail` is fetched for the ranked candidates only: everyone else keeps
    NULLs rather than inheriting another trader's row."""
    import json
    raw = snap_dir / "binance_raw.jsonl"
    rec = json.loads(raw.read_text().splitlines()[0])
    rec["portfolioId"] = "P_NODETAIL"
    with open(raw, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    _detail(snap_dir)                       # only P1 was fetched
    _load(con, snap_dir)
    got = {r["trader_id"]: r["copier_pnl"] for r in con.execute(
        "SELECT trader_id, copier_pnl FROM trader_snapshot WHERE exchange='binance'")}
    assert got == {"P1": -6117.10893387, "P_NODETAIL": None}


def test_ingest_detail_is_idempotent(con, snap_dir):
    _detail(snap_dir)
    _load(con, snap_dir)
    _load(con, snap_dir)
    rows = con.execute("SELECT copier_pnl FROM trader_snapshot "
                       "WHERE exchange='binance'").fetchall()
    assert len(rows) == 1 and rows[0][0] == -6117.10893387
