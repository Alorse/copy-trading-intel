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
    # 21 traders "masa" en la celda (BTCUSDT, 2025-04, Long): pr = 0 -> benchmark 0
    base = 1743500000000            # 2025-04-01 UTC (OJO: 2025, no 2026)
    for i in range(21):
        _pos(con, f"m{i}", "BTCUSDT", "Long", base + i, 100, 100, 0.0)
    # trader objetivo: 5 trades, pr = +2%,+2%,+2%,+2%,-1% -> alpha igual (bench 0)
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
    _pos(con, "T", "BTCUSDT", "Long", 1743500000000, 0, 110, 5)   # avg_cost 0 -> invalida
    con.commit()
    metrics.compute(con, D, EX, min_cell=20)
    r = con.execute("SELECT price_return FROM positions WHERE trader_id='T' "
                    "AND avg_cost=0").fetchone()
    assert r["price_return"] is None
    m = con.execute("SELECT n FROM trader_metrics WHERE trader_id='T'").fetchone()
    assert m["n"] == 5                               # la invalida NO cuenta en n
