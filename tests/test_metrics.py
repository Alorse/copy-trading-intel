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
    # 21 "crowd" traders in the cell (BTCUSDT, 2025-04, Long): pr = 0 -> benchmark 0
    base = 1743500000000            # 2025-04-01 UTC (CAREFUL: 2025, not 2026)
    for i in range(21):
        _pos(con, f"m{i}", "BTCUSDT", "Long", base + i, 100, 100, 0.0)
    # target trader: 5 trades, pr = +2%,+2%,+2%,+2%,-1% -> same alpha (bench 0)
    for j, (c, pnl) in enumerate([(102, 20)] * 4 + [(99, -10)]):
        _pos(con, "T", "BTCUSDT", "Long", base + 1000 + j, 100, c, pnl)
    con.execute("INSERT INTO trader_snapshot VALUES (?,?,?,?,?,?,?,?,?,NULL)",
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
    _pos(con, "T", "BTCUSDT", "Long", 1743500000000, 0, 110, 5)   # avg_cost 0 -> invalid
    con.commit()
    metrics.compute(con, D, EX, min_cell=20)
    r = con.execute("SELECT price_return FROM positions WHERE trader_id='T' "
                    "AND avg_cost=0").fetchone()
    assert r["price_return"] is None
    m = con.execute("SELECT n FROM trader_metrics WHERE trader_id='T'").fetchone()
    assert m["n"] == 5                               # the invalid one does NOT count in n


# ---------------------------------------------------------------------------
# Leave-self-out alpha (ported from analysis/okx_top5.py's compute_alpha,
# 2026-08-29): the cell median must exclude the trader's own rows.
# ---------------------------------------------------------------------------

def _seed_self_dominated_cell(con):
    # 9-row cell (BTCUSDT, 2025-04, Long): 6 rows from A at pr=+5%, 3 from B at
    # pr=+1%. Self-inclusive median is dragged toward A's own return (mostly
    # A's own volume); leave-self-out benchmarks A only against B.
    base = 1743500000000
    for i in range(6):
        _pos(con, "A", "BTCUSDT", "Long", base + i, 100, 105, 50.0)
    for i in range(3):
        _pos(con, "B", "BTCUSDT", "Long", base + 100 + i, 100, 101, 10.0)
    con.commit()


def test_alpha_leave_self_out_shifts_in_self_dominated_cell(con):
    _seed_self_dominated_cell(con)
    metrics.compute(con, D, EX, min_cell=8)
    a = con.execute("SELECT * FROM trader_metrics WHERE trader_id='A'").fetchone()
    b = con.execute("SELECT * FROM trader_metrics WHERE trader_id='B'").fetchone()
    assert abs(a["alpha"] - 0.04) < 1e-9    # 0.05 - median(B's 0.01) = +0.04, not ~0
    assert abs(a["max_cell_share"] - 6 / 9) < 1e-9
    assert abs(b["max_cell_share"] - 3 / 9) < 1e-9
    assert a["n_alpha_dropped_self_dominated"] == 0
    rows = con.execute("SELECT alpha FROM positions WHERE trader_id='A'").fetchall()
    assert all(abs(r["alpha"] - 0.04) < 1e-9 for r in rows)


def _seed_solo_cell(con):
    # 8-row cell (ETHUSDT, 2025-04, Short), all from trader A: pr=+5% each
    # (cost 100 -> close 95, short). No "other" trader exists in this cell.
    base = 1743500000000
    for i in range(8):
        _pos(con, "A", "ETHUSDT", "Short", base + i, 100, 95, 10.0)
    con.commit()


def test_alpha_drops_self_dominated_solo_cell(con):
    _seed_solo_cell(con)
    metrics.compute(con, D, EX, min_cell=8)
    rows = con.execute("SELECT price_return, alpha FROM positions "
                       "WHERE trader_id='A'").fetchall()
    assert all(r["price_return"] is not None for r in rows)   # price_return still defined
    assert all(r["alpha"] is None for r in rows)               # leave-self-out: unusable
    m = con.execute("SELECT * FROM trader_metrics WHERE trader_id='A'").fetchone()
    assert m["n"] == 8 and m["n_alpha"] == 0
    assert m["alpha"] is None
    assert m["n_alpha_dropped_self_dominated"] == 8
    assert m["max_cell_share"] == 1.0


def test_thin_benchmark_flag_fires_above_40pct_cell_share(con):
    from pipeline import detect
    _seed_self_dominated_cell(con)   # A owns 6/9 = 67% of its only cell
    metrics.compute(con, D, EX, min_cell=8)
    flags = detect.run(con, D, EX)
    assert "thin_benchmark" in flags["A"]
    assert "thin_benchmark" not in flags["B"]   # B owns only 3/9 = 33%, under the 40% flag
