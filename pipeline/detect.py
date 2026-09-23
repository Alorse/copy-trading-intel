"""Anti-inflation battery. Each rule emits one flag per trader.
Reference cases: FINDINGS_v2.md / TOP5.md (GGbond, VickyKaushal, etc.)."""
import collections, datetime as dt, json

DISQUALIFYING = {"loss_hider", "open_loss_divergence", "lottery", "roi_artifact",
                 "ruin_risk", "not_copyable", "insufficient", "no_alpha",
                 "went_dark", "mass_close_loss", "no_listing_data"}
WARNINGS = {"alpha_decay", "inactive", "style_drift", "regime_onesided", "mdd_high",
            "fresh_start", "thin_benchmark"}
# Disqualifying, but absence of evidence rather than evidence of a defect: these
# keep a trader out of the roster without calling them a fraud. `rank` sends a
# trader marked only by these to tier W, not X, so the report does not list them
# beside `loss_hider` and `roi_artifact`.
NOT_A_DEFECT = {"insufficient", "no_listing_data"}

# A leave-self-out alpha computed against a benchmark cell where the trader IS
# most of the "other traders" evidence rests on a thin sample of genuinely
# independent trades. Report-only (ported from analysis/okx_top5.py 2026-08-29),
# not disqualifying: it's a caveat on how much to trust the number, not a defect
# in the trader.
MAX_CELL_SHARE_FLAG = 0.40

# A portfolio younger than this has no verifiable pre-history at all: Binance
# serves nothing opened before startTime, and what it used to serve is gone.
# 120d is the observed ceiling of the closed-position window, so below it not
# even the old retention could have exposed the pre-public record.
FRESH_START_DAYS = 120

# --- the "went dark / died" guard (added 2026-09-23) -------------------------
# Post-mortem of 牛熊摆渡人 (5096968193101811713): its LAST OPENING was
# 2026-08-28, on 2026-09-02 it closed 14 positions in the same second for
# -15,295 USDT, and it never traded again. Every pre-existing rule reads the
# shape of the closed trades; none of them reads whether the trader is still
# there. These three do: it stopped opening (`went_dark`), it was liquidated
# (`mass_close_loss`), or it fell off the leaderboard (`no_listing_data`).
#
# The rule this module follows for clocks: an ABSOLUTE clock (`snap_ms`, from
# snapshot_date) for age-of-evidence questions like `fresh_start`, and a
# UNIVERSE-RELATIVE clock (the newest opening/close in the snapshot) for
# liveness-versus-peers questions like `inactive` and `went_dark`. The reason is
# not determinism -- `snap_ms` comes from snapshot_date, so both are already
# reproducible on an old snapshot -- it is that `positions` carries scrape lag,
# so the newest timestamp in the snapshot is the true "as of" instant for
# position data, and that an exchange-wide halt is not a trader-specific signal.

# No position OPENED in this many days. `inactive` already watches closes, but a
# dying portfolio keeps closing for weeks after it stops opening: on 2026-09-23
# 牛熊摆渡人 was 26.2 days past its last opening and only 21.0 days past its last
# close, i.e. 9 days short of tripping `inactive`, which stayed silent on it.
# 21 is the largest value that still catches it. Cost, measured on the 2026-09-23
# snapshot (950 traders, 553 still on the leaderboard): fires on 21.3% of all /
# 18.8% of leaderboard traders, but on 0 of the 7 that survive the other
# disqualifiers -- every trader it flags was already out on another rule, so its
# price today is nil and its value is forward-looking.
WENT_DARK_DAYS = 21

# A same-second close cluster this large whose net loss erases this share of
# everything the trader ever earned. The count keeps one catastrophic trade in
# ruin_risk/mdd territory where it belongs; the share keeps the rule scale-free.
# Fires on 10 of 950 (1.1%), 2 of 553 leaderboard traders (0.4%), and on 0 of the
# 7 that survive the other disqualifiers.
MASS_CLOSE_MIN_POSITIONS = 5
MASS_CLOSE_LOSS_SHARE = 0.50

# The third way a trader leaves: off the leaderboard we scrape. `no_listing_data`
# says only that -- NOT that the portfolio is closed (verified 2026-09-23: of the
# 398 such portfolios, 再也不做空了 is still ACTIVE and copyable, while the genuinely
# retired 牛熊摆渡人 returns code 11012028 from lead-portfolio/detail; distinguishing
# the two needs that endpoint, which the scrape stage does not yet call).
# It is disqualifying anyway, because for these traders the listing-only fields
# (roi, mdd, startTime) are absent, so `mdd_high`, `roi_artifact` and
# `fresh_start` silently cannot fire -- 再也不做空了 reached tier A and 30% weight on
# 2026-09-23 with an empty flag list and an unknown drawdown. The historical union
# exists so de-copy can watch an incumbent decay after it drops out of the
# ranking (see the design doc), not to recruit new picks out of it.
# NOTE: `listed == 0` is a PROXY for "the listing-only fields are missing". The
# day `scrape` starts calling lead-portfolio/detail, the two diverge and this
# trigger needs revisiting; the honest fix underneath is for flatten.py to stop
# defaulting the absent trader-level fields (roi, pnl, aum, winRate, mdd) to
# 0.0, so "never measured" reaches SQL as NULL instead of a fabricated zero.


def _mass_closes(con, snapshot_date, exchange, gross_win):
    """The traders with a disqualifying same-second close cluster.

    Grouping is by SECOND, not millisecond: an exchange-side mass close spreads
    its fills over a few hundred milliseconds. The grouping and both count/sign
    predicates run in SQL, so only the handful of candidate clusters crosses
    into Python instead of every closed position in the snapshot.
    """
    rows = con.execute(
        "SELECT trader_id, COUNT(*), SUM(closing_pnl) FROM positions "
        "WHERE snapshot_date=? AND exchange=? AND closed_ms IS NOT NULL "
        "GROUP BY trader_id, closed_ms/1000 "
        "HAVING COUNT(*) >= ? AND SUM(closing_pnl) < 0",
        (snapshot_date, exchange, MASS_CLOSE_MIN_POSITIONS))
    return {tid for tid, _n, net in rows
            if -net >= MASS_CLOSE_LOSS_SHARE * (gross_win.get(tid) or 0.0)}


def run(con, snapshot_date, exchange='binance'):
    ms = con.execute("SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
                     (snapshot_date, exchange)).fetchall()
    snap = {r['trader_id']: r for r in con.execute(
        "SELECT trader_id, roi, start_time, listed FROM trader_snapshot "
        "WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange))}
    roi = {k: v['roi'] for k, v in snap.items()}
    listed = {k: v['listed'] for k, v in snap.items()}
    snap_ms = dt.datetime.fromisoformat(snapshot_date).replace(
        tzinfo=dt.UTC).timestamp() * 1000
    # one pass over `positions` for every per-trader aggregate the rules need
    agg = {r[0]: r for r in con.execute(
        "SELECT trader_id, MAX(closed_ms), MAX(opened_ms), SUM(closing_pnl), "
        "SUM(CASE WHEN closing_pnl>0 THEN closing_pnl ELSE 0 END) FROM positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    last_close = {k: v[1] for k, v in agg.items()}
    last_open = {k: v[2] for k, v in agg.items()}
    realized = {k: v[3] for k, v in agg.items()}
    maxclose = max((v for v in last_close.values() if v is not None), default=0)
    maxopen = max((v for v in last_open.values() if v is not None), default=0)
    unreal = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, SUM(unrealized_pnl) FROM open_positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    mass_close = _mass_closes(con, snapshot_date, exchange,
                              {k: v[4] for k, v in agg.items()})
    out = {}
    for m in ms:
        f = []
        tid = m['trader_id']
        n, na = m['n'] or 0, m['n_alpha'] or 0
        if n < 60 or na < 40 or (m['months_active'] or 0) < 3:
            f.append('insufficient')
        wr, payoff, mdd = m['wr'], m['payoff'], m['mdd']
        # mdd on a PERCENTAGE scale (median ~30, GGbond=50.5) - Trap 5 in SKILL.md
        if n >= 20 and ((wr is not None and wr > 92) or
                        payoff is None or
                        (payoff is not None and payoff < 0.5
                         and mdd is not None and mdd > 35)):
            f.append('loss_hider')
        u = unreal.get(tid)
        if u is not None and u < -2 * max(1.0, realized.get(tid) or 0):
            f.append('open_loss_divergence')
        if (m['conc_top1'] or 0) > 30:
            f.append('lottery')
        r = roi.get(tid)
        if r is not None and r > 300 and ((m['alpha'] or 0) <= 0 or (m['t_stat'] or 0) < 2):
            f.append('roi_artifact')
        if (m['lev_p90'] or 0) > 25 or (m['ruin'] is not None and m['ruin'] < -500):
            f.append('ruin_risk')
        if (m['marg_med'] is not None and m['marg_med'] < 50) or \
           (m['dur_med'] is not None and m['dur_med'] < 0.5):
            f.append('not_copyable')
        if (m['t_stat'] or 0) < 2.5:
            f.append('no_alpha')
        # warnings
        if mdd is not None and mdd >= 35:   # OPEN band: an mdd of 64 is worse
            f.append('mdd_high')            # than one of 40, not better
        if m['alpha_h1'] is not None and m['alpha_h2'] is not None \
           and m['alpha_h2'] < m['alpha_h1']:
            f.append('alpha_decay')
        lc = last_close.get(tid)
        if lc is not None and maxclose and lc < maxclose - 30 * 86400000:
            f.append('inactive')
        lo = last_open.get(tid)
        if lo is not None and maxopen and lo < maxopen - WENT_DARK_DAYS * 86400000:
            f.append('went_dark')
        if tid in mass_close:
            f.append('mass_close_loss')
        if listed.get(tid) == 0:
            f.append('no_listing_data')
        # the public record starts where the trader chose to start it, and what
        # came before is unverifiable: of 177 portfolios whose pre-startTime
        # history was still visible on 2026-08-25, 86% were net NEGATIVE before
        # going public (p=4e-20). Trap 7 in SKILL.md.
        st = (snap.get(tid) or {})['start_time'] if snap.get(tid) else None
        if st is not None and (snap_ms - st) < FRESH_START_DAYS * 86400000:
            f.append('fresh_start')
        monthly = json.loads(m['monthly_alpha'] or '{}')
        if len(monthly) >= 2:
            pos = sum(1 for v in monthly.values() if v > 0)
            if pos / len(monthly) < 0.5:
                f.append('regime_onesided')
        if (m['max_cell_share'] or 0) > MAX_CELL_SHARE_FLAG:
            f.append('thin_benchmark')
        con.execute("UPDATE trader_metrics SET flags=? WHERE snapshot_date=? "
                    "AND exchange=? AND trader_id=?",
                    (json.dumps(f), snapshot_date, exchange, tid))
        out[tid] = f
    con.commit()
    return out
