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
    # el gate ve el flag ANADIDO EN ESTA CORRIDA (no flags stale del fetch inicial)
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
