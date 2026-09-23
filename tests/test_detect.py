import json
from pipeline import detect

D, EX = "2026-09-01", "binance"


def _tm(con, tid, **kw):
    # mdd on a PERCENTAGE scale (like Binance's real data)
    base = dict(n=100, n_alpha=80, alpha=0.01, t_stat=3.0, payoff=1.2, wr=70.0,
                conc_top1=20.0, ruin=-100.0, mdd=20.0, lev_med=5, lev_p90=10,
                marg_med=500.0, dur_med=4.0, months_active=4, alpha_h1=0.01,
                alpha_h2=0.012, monthly_alpha='{"2025-04":0.01,"2025-05":0.012}')
    snap_only = ("start_time", "listed")   # trader_snapshot columns, not metrics
    base.update({k: v for k, v in kw.items() if k not in snap_only})
    cols = ",".join(base)
    con.execute(
        f"INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,{cols}) "
        f"VALUES (?,?,?,?,{','.join('?'*len(base))})",
        (D, EX, tid, tid, *base.values()))
    con.execute("INSERT INTO trader_snapshot (snapshot_date,exchange,trader_id,nick,"
                "roi,pnl,aum,win_rate,mdd,start_time,listed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (D, EX, tid, tid, 50.0, 0, 0, 0, base["mdd"],
                 kw.get("start_time"), kw.get("listed", 1)))
    # a recent position so `inactive` is not triggered
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
    _tm(con, "gg", wr=98.5, mdd=50.5)               # GGbond case, % scale
    assert "loss_hider" in detect.run(con, D, EX)["gg"]


def test_loss_hider_zero_losers_with_breakeven(con):
    # Una case: zero losers (payoff NULL) but wr<100 because of a break-even
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


def test_mdd_high_is_open_ended(con):
    # 重生之我在币圈捡垃圾- case (2026-08-28): mdd=63.8 got NO warning under
    # the closed band 35<=mdd<=60 — the worst drawdown came out clean
    _tm(con, "basura", mdd=63.8)
    assert "mdd_high" in detect.run(con, D, EX)["basura"]


def test_mdd_below_band_no_warning(con):
    _tm(con, "sano", mdd=34.9)
    assert "mdd_high" not in detect.run(con, D, EX)["sano"]


def test_flags_persisted(con):
    _tm(con, "gg", wr=98.5, mdd=50.5)
    detect.run(con, D, EX)
    row = con.execute(
        "SELECT flags FROM trader_metrics WHERE trader_id='gg'").fetchone()
    assert "loss_hider" in json.loads(row["flags"])


def test_fresh_start_warns_on_young_portfolio(con):
    # 2026-06-07: the real startTime of 梭哈到世界尽头, 86 days before the snapshot.
    # Nothing he traded before it is served by the API any more.
    _tm(con, "fresh", start_time=1780876800000)
    f = detect.run(con, D, EX)["fresh"]
    assert "fresh_start" in f
    assert "fresh_start" in detect.WARNINGS       # a warning, never disqualifying
    assert not (set(f) & detect.DISQUALIFYING)


def test_fresh_start_silent_on_old_portfolio(con):
    _tm(con, "veteran", start_time=1735689600000)          # 2025-01-01
    assert "fresh_start" not in detect.run(con, D, EX)["veteran"]


def test_fresh_start_silent_without_start_time(con):
    # Phemex has no startTime in its listing: absence must not fabricate a flag
    _tm(con, "nostart", start_time=None)
    assert "fresh_start" not in detect.run(con, D, EX)["nostart"]


# --- the "went dark / died" guard (2026-09-23) -------------------------------
# Post-mortem of 牛熊摆渡人 (portfolio 5096968193101811713): last opening
# 2026-08-28, then on 2026-09-02 14 positions closed in the same second for
# -15,295 USDT, and nothing since. Both halves of that shape get a flag.

DAY = 86400000
T0 = 1789000000000          # an arbitrary "now" for the universe clock


def _pos(con, tid, opened_ms, closed_ms, pnl, snapshot=D):
    con.execute(
        "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
        "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
        "avg_cost,avg_close) VALUES (?,?,?,?, 'BTCUSDT','Long',?,?,1,1,1,1,?,0,1,1)",
        (snapshot, EX, tid, tid, opened_ms, closed_ms, pnl))
    con.commit()


def test_went_dark_flags_a_trader_who_stopped_opening(con):
    _tm(con, "active")
    _pos(con, "active", T0 - DAY, T0, 10.0)             # sets the universe clock
    _tm(con, "dark")
    _pos(con, "dark", T0 - 40 * DAY, T0 - 21 * DAY, -10.0)
    flags = detect.run(con, D, EX)
    assert "went_dark" in flags["dark"]
    assert "went_dark" not in flags["active"]


def test_went_dark_is_about_openings_not_closes(con):
    # the gap `inactive` misses: nothing OPENED for weeks, but a close is recent
    _tm(con, "active")
    _pos(con, "active", T0 - DAY, T0, 10.0)
    _tm(con, "stale")
    _pos(con, "stale", T0 - 60 * DAY, T0 - DAY, -10.0)   # closed yesterday
    flags = detect.run(con, D, EX)
    assert "went_dark" in flags["stale"]
    assert "inactive" not in flags["stale"]             # 30d-on-closes says nothing


def test_went_dark_silent_without_opening_timestamps(con):
    # absence of data must not fabricate a flag
    _tm(con, "active")
    _pos(con, "active", T0 - DAY, T0, 10.0)
    _tm(con, "noopen")
    _pos(con, "noopen", None, T0 - 40 * DAY, -10.0)
    con.execute("UPDATE positions SET opened_ms=NULL WHERE trader_id='noopen'")
    con.commit()
    assert "went_dark" not in detect.run(con, D, EX)["noopen"]


def test_mass_close_loss_flags_a_single_second_liquidation(con):
    _tm(con, "bull")
    for i in range(10):                                  # +10,000 gross earned
        _pos(con, "bull", T0 - 50 * DAY, T0 - 40 * DAY + i, 1000.0)
    for i in range(14):                                  # -15,295 in one second
        _pos(con, "bull", T0 - 30 * DAY, T0 - 20 * DAY + i, -15295.0 / 14)
    assert "mass_close_loss" in detect.run(con, D, EX)["bull"]


def test_mass_close_loss_silent_on_a_routine_close_cluster(con):
    _tm(con, "tidy")
    for i in range(10):
        _pos(con, "tidy", T0 - 50 * DAY, T0 - 40 * DAY + i, 1000.0)
    for i in range(6):                                   # -100 total, 1% of gross
        _pos(con, "tidy", T0 - 30 * DAY, T0 - 20 * DAY + i, -100.0 / 6)
    assert "mass_close_loss" not in detect.run(con, D, EX)["tidy"]


def test_mass_close_loss_needs_a_cluster_not_one_bad_trade(con):
    # one big loser is `ruin_risk`/mdd territory, not a liquidation event
    _tm(con, "unlucky")
    for i in range(10):
        _pos(con, "unlucky", T0 - 50 * DAY, T0 - 40 * DAY + i, 1000.0)
    _pos(con, "unlucky", T0 - 30 * DAY, T0 - 20 * DAY, -15295.0)
    assert "mass_close_loss" not in detect.run(con, D, EX)["unlucky"]


def test_mass_close_loss_groups_by_second_not_millisecond(con):
    # the 14 closes land on different milliseconds of the same second
    _tm(con, "bull")
    for i in range(10):
        _pos(con, "bull", T0 - 50 * DAY, T0 - 40 * DAY + i, 1000.0)
    base = (T0 - 20 * DAY) // 1000 * 1000
    for i in range(14):
        _pos(con, "bull", T0 - 30 * DAY, base + 70 * i, -15295.0 / 14)   # 0..910ms
    assert "mass_close_loss" in detect.run(con, D, EX)["bull"]


def test_no_listing_data_flags_a_trader_who_left_the_leaderboard(con):
    # 再也不做空了 (4563197729960674304) on 2026-09-23: reached only through the
    # historical union, so mdd/roi/startTime are all absent -- mdd_high,
    # roi_artifact and fresh_start cannot fire -- and it scored tier A, 30% weight,
    # on a risk screen that never ran.
    _tm(con, "dropped", listed=0)
    assert "no_listing_data" in detect.run(con, D, EX)["dropped"]


def test_no_listing_data_silent_on_a_listed_trader(con):
    _tm(con, "ranked", listed=1)
    assert "no_listing_data" not in detect.run(con, D, EX)["ranked"]


def test_no_listing_data_silent_when_membership_is_unknown(con):
    # listed IS NULL = no listing file was scraped (Phemex): absence of evidence
    # is not evidence of absence
    _tm(con, "unknown", listed=None)
    assert "no_listing_data" not in detect.run(con, D, EX)["unknown"]


def test_new_guards_are_disqualifying(con):
    assert {"went_dark", "mass_close_loss",
            "no_listing_data"} <= detect.DISQUALIFYING
