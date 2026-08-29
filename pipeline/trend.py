"""Compares snapshots: who improves, who decays, de-copy and style_drift."""
import json
from pipeline import detect as det


def _clamp(x, lo=-2.0, hi=2.0):
    return max(lo, min(hi, x))


def _slope(monthly):
    ys = [v for _, v in sorted(monthly.items())]
    k = len(ys)
    if k < 3:
        return None
    xs = list(range(k))
    mx, my = sum(xs) / k, sum(ys) / k
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def run(con, snapshot_date, exchange='binance', prev_roster=None):
    prev = con.execute(
        "SELECT MAX(snapshot_date) FROM snapshots WHERE exchange=? AND snapshot_date<?",
        (exchange, snapshot_date)).fetchone()[0]
    cur = {r['trader_id']: r for r in con.execute(
        "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    old = {}
    if prev:
        old = {r['trader_id']: r for r in con.execute(
            "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
            (prev, exchange))}
    updated = {}                      # FRESH post-update flags (avoids reading stale)
    for tid, m in cur.items():
        flags = json.loads(m['flags'] or '[]')
        s = _slope(json.loads(m['monthly_alpha'] or '{}'))
        bonus = _clamp(s * 100) if s is not None else 0.0
        o = old.get(tid)
        if o is not None:
            if m['alpha'] is not None and o['alpha'] is not None:
                sign = (m['alpha'] > o['alpha']) - (m['alpha'] < o['alpha'])
                bonus = _clamp((bonus + sign) / 2)
                if m['alpha'] < 0 and o['alpha'] < 0 and 'decopy_2neg' not in flags:
                    flags.append('decopy_2neg')
                # cross-snapshot half of alpha_decay (spec): alpha fell vs prev
                if m['alpha'] < o['alpha'] and 'alpha_decay' not in flags:
                    flags.append('alpha_decay')
            for col in ('lev_med', 'marg_med'):
                a, b = m[col], o[col]
                if a and b and (a / b > 2 or a / b < 0.5) and 'style_drift' not in flags:
                    flags.append('style_drift')
        updated[tid] = flags
        con.execute("UPDATE trader_metrics SET trend_bonus=?, flags=? "
                    "WHERE snapshot_date=? AND exchange=? AND trader_id=?",
                    (bonus, json.dumps(flags), snapshot_date, exchange, tid))
    con.commit()
    newly_disq = []
    if prev_roster:
        # matched by portfolio_id (stable) - the nick can be renamed
        for t in prev_roster.get('traders', []):
            tid = t.get('portfolio_id')
            if tid not in updated:
                continue
            bad = set(updated[tid]) & (det.DISQUALIFYING | {'decopy_2neg'})
            if bad:
                newly_disq.append({'portfolio_id': tid, 'nick': t['nick'],
                                   'flags': sorted(bad)})
    return {'snapshot': snapshot_date, 'prev': prev,
            'added_a': [], 'removed_a': [], 'weight_moves': [],
            'new_disqualified_incumbents': newly_disq,
            'material': prev is None or bool(newly_disq)}
