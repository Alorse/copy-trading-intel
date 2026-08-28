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
    _tm(con, "gg", wr=98.5, mdd=50.5)               # caso GGbond, escala %
    assert "loss_hider" in detect.run(con, D, EX)["gg"]


def test_loss_hider_zero_losers_with_breakeven(con):
    # caso Una: cero perdedoras (payoff NULL) pero wr<100 por un break-even
    _tm(con, "una", payoff=None, wr=99.4)
    assert "loss_hider" in detect.run(con, D, EX)["una"]


def test_lottery(con):
    _tm(con, "rabbit", conc_top1=96.9)              # top-1 96.9%
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
