"""Score, tiers y pesos -> roster. Cap de 5 traders (A+B).
Matching entre corridas SIEMPRE por portfolio_id (el nick es renombrable)."""
import json, datetime as dt
from pipeline import detect as det

BAD = det.DISQUALIFYING | {'decopy_2neg'}


def _round05(x):
    return round(x * 20) / 20


def _weights(roster):
    """A y B: pool 70/30. Solo A: pool 1.0. Solo B: cap 0.10 c/u y el
    remanente queda SIN ASIGNAR (suma < 1.0) - nunca se vuelca en uno solo.
    Devuelve el peso no asignado."""
    A = [t for t in roster if t['tier'] == 'A']
    B = [t for t in roster if t['tier'] == 'B']
    poolA = 1.0 if (A and not B) else 0.70
    poolB = 0.30 if A else 1.0
    for grp, pool in ((A, poolA), (B, poolB)):
        tot = sum(t['score'] for t in grp)
        for t in grp:
            t['weight'] = pool * t['score'] / tot if tot else 0.0
    # cap iterativo de B: el exceso se reparte dentro de B entre los no capeados
    for _ in range(len(B)):
        excess = sum(max(0.0, t['weight'] - 0.10) for t in B)
        if excess < 1e-9:
            break
        for t in B:
            t['weight'] = min(t['weight'], 0.10)
        free = [t for t in B if t['weight'] < 0.10 - 1e-9]
        if not free:
            break
        tot = sum(t['score'] for t in free)
        for t in free:
            t['weight'] += excess * t['score'] / tot if tot else 0.0
    for t in B:
        t['weight'] = min(t['weight'], 0.10)
    b_excess = poolB - sum(t['weight'] for t in B) if B else 0.0
    if A and b_excess > 1e-9:                 # exceso de B pasa a A si A existe
        totA = sum(t['weight'] for t in A)
        for t in A:
            t['weight'] += b_excess * t['weight'] / totA if totA else 0.0
    for t in roster:
        t['weight'] = _round05(t['weight'])
    assigned = sum(t['weight'] for t in roster)
    drift = 1.0 - assigned
    if A and abs(drift) > 1e-9:               # ajuste de redondeo SOLO sobre A
        mx = max(A, key=lambda t: t['weight'])
        mx['weight'] = _round05(mx['weight'] + drift)
        assigned = sum(t['weight'] for t in roster)
    return max(0.0, round(1.0 - assigned, 2))  # unallocated (solo-B lo deja >0)


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
        # n>300 sustituye historial SOLO en la primera corrida del pipeline
        c['tier'] = 'A' if (not c['warns'] and
                            (seen.get(c['tid'], 1) >= 2 or
                             (total_snaps <= 1 and (c['m']['n'] or 0) > 300))) \
                    else 'B'
    unallocated = _weights(roster)
    # rank del snapshot previo por score (para el bloque trend del roster)
    prev_rank = {}
    if prev_m:
        ordered = sorted(prev_m.values(),
                         key=lambda r: -(r['score'] if r['score'] is not None else -1e9))
        prev_rank = {r['trader_id']: i + 1 for i, r in enumerate(ordered)}
    in_roster = {c['tid'] for c in roster}
    for c in cands:
        if c['tid'] in in_roster:
            tier = c['tier']
        elif c['flags'] & BAD == {'insufficient'}:
            tier = 'W'                        # novato, no fraude (spec)
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
                        'lev_med': m['lev_med'], 'mdd': m['mdd'], 'n': m['n']},
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
                      else 'fuera del top-5 por score' if c else 'fuera del universo')
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
        for t in prev_traders:               # titulares: cambio o SALIDA (prev->0)
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
