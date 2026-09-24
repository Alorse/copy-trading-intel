"""Score, tiers and weights -> roster. Capped at 5 traders (A+B).
Runs are ALWAYS matched by portfolio_id (the nick can be renamed)."""
import json, datetime as dt
from pipeline import detect as det

BAD = det.DISQUALIFYING | {'decopy_2neg'}


def _round05(x):
    return round(x * 20) / 20


# No single lead may hold more than this share of the book, whatever it scores.
# The A pool is 70% of the book (100% when there is no B) split by score, so ONE
# tier-A trader used to take all of it: on 2026-09-23 汤普猫 was handed 70% on 84
# trades, t=2.58 and a $2,001 lead account. The failure mode this caps is not
# a bad average, it is a single event -- 牛熊摆渡人 closed 14 positions for
# -15,295 USDT in one second and stopped existing. 20% is the most the
# 2026-08-28 hand ranking ever gave one trader (Mine13), it is the most a
# roster of the engine's 5 slots can give everyone at once, and it is the level
# at which one lead's total loss costs a fifth of the book rather than most of
# it. The excess is NOT moved to anyone else: it stays unallocated, as B's
# remainder already did.
MAX_WEIGHT = 0.20
# Tier B is "qualified but carrying a warning", and keeps its own stricter cap.
MAX_WEIGHT_B = 0.10


def _allocate(grp, pool, cap):
    """Split `pool` among `grp` by score, with a per-trader `cap`.

    The excess of a capped trader is redistributed WITHIN the group, by score,
    to those still below the cap; once everyone is at the cap, whatever is left
    of the pool stays unallocated rather than being piled onto one name.
    """
    tot = sum(t['score'] for t in grp)
    for t in grp:
        t['weight'] = pool * t['score'] / tot if tot else 0.0
    for _ in range(len(grp)):
        excess = sum(max(0.0, t['weight'] - cap) for t in grp)
        if excess < 1e-9:
            break
        for t in grp:
            t['weight'] = min(t['weight'], cap)
        free = [t for t in grp if t['weight'] < cap - 1e-9]
        if not free:
            break
        tot = sum(t['score'] for t in free)
        for t in free:
            t['weight'] += excess * t['score'] / tot if tot else 0.0
    for t in grp:
        t['weight'] = min(t['weight'], cap)


def _weights(roster):
    """A and B: 70/30 pools, each split by score and capped per trader (A:
    MAX_WEIGHT, B: MAX_WEIGHT_B). A only: pool 1.0. B only: pool 1.0.
    Everything the caps leave over stays UNALLOCATED - never dumped onto
    another trader, and never used to top the book up to 1.0.
    Returns the unallocated weight."""
    A = [t for t in roster if t['tier'] == 'A']
    B = [t for t in roster if t['tier'] == 'B']
    _allocate(A, 1.0 if (A and not B) else 0.70, MAX_WEIGHT)
    _allocate(B, 0.30 if A else 1.0, MAX_WEIGHT_B)
    for t in roster:                          # publishable multiples of 5%,
        t['weight'] = min(_round05(t['weight']),   # and rounding may not lift
                          MAX_WEIGHT if t['tier'] == 'A' else MAX_WEIGHT_B)
    return max(0.0, round(1.0 - sum(t['weight'] for t in roster), 2))


def run(con, snapshot_date, exchange='binance', diff=None, prev_roster=None):
    ms = con.execute("SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
                     (snapshot_date, exchange)).fetchall()
    seen = {r[0]: r[1] for r in con.execute(
        "SELECT trader_id, COUNT(DISTINCT snapshot_date) FROM trader_metrics "
        "WHERE exchange=? GROUP BY trader_id", (exchange,))}
    total_snaps = con.execute(
        "SELECT COUNT(DISTINCT snapshot_date) FROM snapshots WHERE exchange=?",
        (exchange,)).fetchone()[0]
    prev_date = con.execute(
        "SELECT MAX(snapshot_date) FROM snapshots WHERE exchange=? AND snapshot_date<?",
        (exchange, snapshot_date)).fetchone()[0]
    roi = {r['trader_id']: r['roi'] for r in con.execute(
        "SELECT trader_id, roi FROM trader_snapshot WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    prev_m = {}
    if prev_date:
        prev_m = {r['trader_id']: r for r in con.execute(
            "SELECT * FROM trader_metrics WHERE snapshot_date=? AND exchange=?",
            (prev_date, exchange))}
    cands = []
    for m in ms:
        flags = set(json.loads(m['flags'] or '[]'))
        warns = flags & det.WARNINGS
        score = (0.40 * (m['t_stat'] or 0) + 0.25 * (m['alpha'] or 0) * 100 +
                 0.20 * (m['payoff'] or 0) + 0.15 * (m['trend_bonus'] or 0))
        score *= 0.9 ** len(warns)
        cands.append({'tid': m['trader_id'], 'nick': m['nick'], 'score': score,
                      'flags': flags, 'warns': warns, 'm': m,
                      'disq': bool(flags & BAD)})
    surv = sorted((c for c in cands if not c['disq'] and c['score'] > 0),
                  key=lambda c: -c['score'])
    roster = surv[:5]
    for c in roster:
        # n>300 stands in for history ONLY on the pipeline's first run
        c['tier'] = 'A' if (not c['warns'] and
                            (seen.get(c['tid'], 1) >= 2 or
                             (total_snaps <= 1 and (c['m']['n'] or 0) > 300))) \
                    else 'B'
    unallocated = _weights(roster)
    # previous snapshot's rank by score (for the roster's trend block)
    prev_rank = {}
    if prev_m:
        ordered = sorted(prev_m.values(),
                         key=lambda r: -(r['score'] if r['score'] is not None else -1e9))
        prev_rank = {r['trader_id']: i + 1 for i, r in enumerate(ordered)}
    in_roster = {c['tid'] for c in roster}
    for c in cands:
        if c['tid'] in in_roster:
            tier = c['tier']
        elif c['flags'] & BAD <= det.NOT_A_DEFECT:
            tier = 'W'                        # newcomer or unscreenable, not fraud
        elif c['disq']:
            tier = 'X'
        else:
            tier = 'W'
        c['final_tier'] = tier
        con.execute("UPDATE trader_metrics SET score=?, tier=?, weight=? "
                    "WHERE snapshot_date=? AND exchange=? AND trader_id=?",
                    (c['score'], tier, c.get('weight', 0.0),
                     snapshot_date, exchange, c['tid']))
    con.commit()
    out_traders = []
    for i, c in enumerate(roster):
        m = c['m']
        p = prev_m.get(c['tid'])
        out_traders.append({
            'exchange': exchange, 'portfolio_id': c['tid'], 'nick': c['nick'],
            'tier': c['tier'], 'weight': c['weight'], 'score': round(c['score'], 3),
            'metrics': {'alpha': m['alpha'], 't': m['t_stat'], 'payoff': m['payoff'],
                        'lev_med': m['lev_med'], 'mdd': m['mdd'], 'n': m['n'],
                        # the t rests on n_alpha (<= n): disclose it
                        'n_alpha': m['n_alpha'],
                        # headline ROI of the picked trader, not just the excluded one
                        'roi': roi.get(c['tid'])},
            'warnings': sorted(c['warns']),
            'trend': {'rank_prev': prev_rank.get(c['tid']), 'rank_now': i + 1,
                      'alpha_delta': (round(m['alpha'] - p['alpha'], 6)
                                      if p and p['alpha'] is not None
                                      and m['alpha'] is not None else None)}})
    removed = []
    if prev_roster:
        now_ids = {t['portfolio_id'] for t in out_traders}
        by_id = {c['tid']: c for c in cands}
        for t in prev_roster.get('traders', []):
            pid = t.get('portfolio_id')
            if pid in now_ids:
                continue
            c = by_id.get(pid)
            reason = (', '.join(sorted(c['flags'] & BAD)) if c and (c['flags'] & BAD)
                      else 'out of the top-5 by score' if c else 'out of the universe')
            removed.append({'portfolio_id': pid, 'nick': t['nick'], 'reason': reason})
    if diff is not None:
        prev_traders = (prev_roster or {}).get('traders', [])
        prev_a = {t['portfolio_id'] for t in prev_traders if t.get('tier') == 'A'}
        now_a = {t['portfolio_id'] for t in out_traders if t['tier'] == 'A'}
        id2nick = {t['portfolio_id']: t['nick'] for t in out_traders + prev_traders}
        diff['added_a'] = sorted(id2nick.get(i, i) for i in now_a - prev_a)
        diff['removed_a'] = sorted(id2nick.get(i, i) for i in prev_a - now_a)
        now_w = {t['portfolio_id']: t['weight'] for t in out_traders}
        moves = []
        for t in prev_traders:               # incumbents: change or EXIT (prev->0)
            pid = t.get('portfolio_id')
            w_now = now_w.get(pid, 0.0)
            if abs(w_now - t.get('weight', 0)) > 0.10 or pid not in now_w:
                moves.append({'nick': t['nick'], 'prev': t.get('weight', 0),
                              'now': w_now})
        diff['weight_moves'] = moves
        left_roster = [t['nick'] for t in prev_traders
                       if t.get('portfolio_id') not in now_w]
        diff['material'] = bool(diff.get('material') or diff['added_a'] or
                                diff['removed_a'] or diff['weight_moves'] or
                                left_roster)
    return {'generated': dt.date.today().isoformat(), 'snapshot': snapshot_date,
            'engine': 'v1.0', 'unallocated': unallocated,
            'traders': out_traders, 'removed': removed}
