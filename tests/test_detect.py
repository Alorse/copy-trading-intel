import json
from conftest import insert_trader_snapshot
from pipeline import detect

D, EX = "2026-09-01", "binance"
DAY = 86400000
T0 = 1789000000000          # an arbitrary "now" for the universe clock


def _pos(con, tid, opened_ms, closed_ms, pnl, snapshot=D):
    con.execute(
        "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
        "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
        "avg_cost,avg_close) VALUES (?,?,?,?, 'BTCUSDT','Long',?,?,1,1,1,1,?,0,1,1)",
        (snapshot, EX, tid, tid, opened_ms, closed_ms, pnl))
    con.commit()


def _tm(con, tid, start_time=None, listed=1, **kw):
    # mdd on a PERCENTAGE scale (like Binance's real data)
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
    insert_trader_snapshot(con, D, EX, tid, mdd=base["mdd"],
                           start_time=start_time, listed=listed)
    _pos(con, tid, 1, 1000, 0)   # a recent position so `inactive` is not triggered


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


# --- the copier gate (2026-09-23) -------------------------------------------
# 汤普猫 (4113397127009634560) reached tier A and 70% of the 2026-09-23 roster
# with a clean flag list while its 47 lifetime copiers were down $6,117, and
# 重生之我在币圈捡垃圾- held 5% with +617% ROI while its 1,862 copiers were down
# $322,314. Realized copier PnL is the only direct measurement of whether an
# edge survives being copied, and the engine could not see it.

def _copiers(con, tid, copier_pnl, total, lead_pnl=10000.0):
    """A trader whose lead record earns `lead_pnl` and whose copiers made
    `copier_pnl` between them."""
    _tm(con, tid)
    con.execute("UPDATE trader_snapshot SET copier_pnl=?, copier_count_total=? "
                "WHERE trader_id=?", (copier_pnl, total, tid))
    con.execute("UPDATE positions SET closing_pnl=? WHERE trader_id=?",
                (lead_pnl, tid))
    con.commit()


def test_copiers_losing_flags_the_tangpumao_shape(con):
    # 47 lifetime copiers, -$6,117 between them (-$130 each) against a lead
    # record of +$4,793: the copiers lost more than the lead ever made
    _copiers(con, "tangpu", -6117.11, 47, lead_pnl=4792.96)
    assert "copiers_losing" in detect.run(con, D, EX)["tangpu"]


def test_copiers_losing_flags_the_zhshengsheng_shape(con):
    # +617% ROI, 1,862 copiers, -$322,314 between them
    _copiers(con, "zhsheng", -320510.43, 1862, lead_pnl=31264.85)
    assert "copiers_losing" in detect.run(con, D, EX)["zhsheng"]


def test_copiers_losing_silent_when_the_copiers_made_money(con):
    # 梭哈到世界尽头 (+$19,426 over 112) and Cooma (+$1,876 over 218)
    _copiers(con, "suoha", 19426.23, 112, lead_pnl=17473.59)
    _copiers(con, "cooma", 1875.66, 218, lead_pnl=11068.69)
    flags = detect.run(con, D, EX)
    assert "copiers_losing" not in flags["suoha"]
    assert "copiers_losing" not in flags["cooma"]


def test_copiers_losing_does_not_condemn_on_a_thin_sample(con):
    # 再也不做空了: 2 copiers, -$11.79 between them. A handful of minimum-size
    # copiers quitting is not a measurement.
    _copiers(con, "thin", -11.79, 2, lead_pnl=1076.91)
    assert "copiers_losing" not in detect.run(con, D, EX)["thin"]


def test_copiers_losing_does_not_condemn_a_small_average_loss(con):
    # 黑袍小分队: 19 copiers, -$188.54 -> -$9.92 each, 3.8% of the lead's own
    # +$4,961. Below one platform-minimum copy ($10) per head: fees and timing,
    # not an edge that inverts. The universe median negative lead is -$11.43
    # per copier, so condemning this shape would condemn half the leaderboard.
    _copiers(con, "small", -188.54, 19, lead_pnl=4961.10)
    assert "copiers_losing" not in detect.run(con, D, EX)["small"]


def test_copiers_losing_fires_on_the_lead_share_clause_alone(con):
    # a shallow per-head loss (-$20) that still erases twice everything the
    # lead earned, because the copier base is far bigger than the lead
    _copiers(con, "wide", -20000.0, 1000, lead_pnl=10000.0)
    assert "copiers_losing" in detect.run(con, D, EX)["wide"]


def test_copiers_losing_silent_without_a_copier_record(con):
    # no `detail` pass for this trader: absence of evidence, and a fabricated
    # 0.0 would read as "the copiers broke even"
    _tm(con, "unmeasured")
    f = detect.run(con, D, EX)["unmeasured"]
    assert "copiers_losing" not in f
    row = con.execute("SELECT copier_pnl FROM trader_snapshot "
                      "WHERE trader_id='unmeasured'").fetchone()
    assert row[0] is None


def test_copiers_losing_silent_when_nobody_ever_copied(con):
    # 179 of the 951 portfolios in the 2026-09-23 snapshot have 0 lifetime
    # copiers and copierPnl 0.0: never measured, not measured at zero
    _copiers(con, "uncopied", 0.0, 0)
    assert "copiers_losing" not in detect.run(con, D, EX)["uncopied"]


def test_copiers_losing_is_disqualifying_and_is_a_defect(con):
    assert "copiers_losing" in detect.DISQUALIFYING
    # not in NOT_A_DEFECT: this is a measured outcome, not a gap in the data
    assert "copiers_losing" not in detect.NOT_A_DEFECT
