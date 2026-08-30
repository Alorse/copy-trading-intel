"""Anti-inflation battery. Each rule emits one flag per trader.
Reference cases: FINDINGS_v2.md / TOP5.md (GGbond, VickyKaushal, etc.)."""
import datetime as dt, json

DISQUALIFYING = {"loss_hider", "open_loss_divergence", "lottery", "roi_artifact",
                 "ruin_risk", "not_copyable", "insufficient", "no_alpha"}
WARNINGS = {"alpha_decay", "inactive", "style_drift", "regime_onesided", "mdd_high",
            "fresh_start", "thin_benchmark"}

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


def run(con, snapshot_date, exchange='binance'):
    ms = con.execute("SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
                     (snapshot_date, exchange)).fetchall()
    snap = {r['trader_id']: r for r in con.execute(
        "SELECT trader_id, roi, start_time FROM trader_snapshot "
        "WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange))}
    roi = {k: v['roi'] for k, v in snap.items()}
    snap_ms = dt.datetime.fromisoformat(snapshot_date).replace(
        tzinfo=dt.UTC).timestamp() * 1000
    maxclose = con.execute(
        "SELECT MAX(closed_ms) FROM positions WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange)).fetchone()[0] or 0
    last_close = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, MAX(closed_ms) FROM positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    unreal = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, SUM(unrealized_pnl) FROM open_positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
    realized = {r['trader_id']: r[1] for r in con.execute(
        "SELECT trader_id, SUM(closing_pnl) FROM positions "
        "WHERE snapshot_date=? AND exchange=? GROUP BY trader_id",
        (snapshot_date, exchange))}
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
