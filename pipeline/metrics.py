"""Motor de metricas por trader. Replica top5_final.py sobre SQLite.
alpha = price_return des-apalancado - mediana de celda (symbol, mes, side)."""
import json, statistics as st, collections, datetime as dt


def _month(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime('%Y-%m')


def compute(con, snapshot_date, exchange='binance', min_cell=20):
    rows = con.execute(
        "SELECT rowid, trader_id, nick, symbol, side, opened_ms, avg_cost, avg_close,"
        " notional, leverage, margin, closing_pnl, dur_h FROM positions"
        " WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange)).fetchall()
    R = []
    for r in rows:
        ok = (r['avg_cost'] and r['avg_cost'] > 0 and r['avg_close'] and
              r['avg_close'] > 0 and r['notional'] and r['notional'] > 0 and
              r['leverage'] and r['leverage'] > 0 and r['opened_ms'])
        pr = None
        if ok:
            pr = (r['avg_close'] / r['avg_cost'] - 1) * \
                 (1 if r['side'] == 'Long' else -1)
            if abs(pr) > 3:
                pr = None
        R.append({'rowid': r['rowid'], 'tid': r['trader_id'], 'nick': r['nick'],
                  'sym': r['symbol'], 'side': r['side'], 'o': r['opened_ms'],
                  'pr': pr, 'pnl': r['closing_pnl'] or 0, 'lev': r['leverage'] or 0,
                  'marg': r['margin'] or 0, 'dur': r['dur_h'] or 0,
                  'mes': _month(r['opened_ms']) if r['opened_ms'] else None})
    cell = collections.defaultdict(list)
    for x in R:
        if x['pr'] is not None:
            cell[(x['sym'], x['mes'], x['side'])].append(x['pr'])
    bench = {k: st.median(v) for k, v in cell.items() if len(v) >= min_cell}
    upd = []
    for x in R:
        b = bench.get((x['sym'], x['mes'], x['side']))
        x['alpha'] = (x['pr'] - b) if (x['pr'] is not None and b is not None) else None
        upd.append((x['pr'], x['alpha'], x['rowid']))
    con.executemany("UPDATE positions SET price_return=?, alpha=? WHERE rowid=?", upd)

    # metricas por trader SOLO sobre filas validas (pr no NULL) - como top5_final.py,
    # que descarta las invalidas antes de contar (n<60, celdas, pnl, meses)
    T = collections.defaultdict(list)
    for x in R:
        if x['pr'] is not None:
            T[x['tid']].append(x)
    snap = {r['trader_id']: r for r in con.execute(
        "SELECT * FROM trader_snapshot WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange))}
    out = []
    for tid, v in T.items():
        v.sort(key=lambda z: z['o'] or 0)
        al = [z['alpha'] for z in v if z['alpha'] is not None]
        prs = [z['pr'] for z in v if z['pr'] is not None]
        w = [p for p in prs if p > 0]; l = [p for p in prs if p < 0]
        wr = len(w) / len(prs) * 100 if prs else None
        payoff = (st.mean(w) / abs(st.mean(l))) if (w and l) else None
        tot = sum(z['pnl'] for z in v)
        best = max(z['pnl'] for z in v)
        # top-1 (criterio auditado); NULL si el trader pierde en neto - un
        # perdedor no es "loteria", cae por no_alpha/score
        conc = (best / tot * 100) if tot > 0 else None
        t_stat = 0.0
        if len(al) >= 2 and st.pstdev(al) > 0:
            t_stat = st.mean(al) / (st.pstdev(al) / len(al) ** .5)
        levs = sorted(z['lev'] for z in v if z['lev'])
        lev_med = st.median(levs) if levs else None
        lev_p90 = levs[int(.9 * len(levs))] if levs else None
        ruin = (min(l) * lev_med * 100) if (l and lev_med) else None
        k = len(al) // 2
        h1 = st.mean(al[:k]) if k else None
        h2 = st.mean(al[k:]) if al[k:] else None
        mo = collections.defaultdict(list)
        for z in v:
            if z['alpha'] is not None:
                mo[z['mes']].append(z['alpha'])
        monthly = {m: st.mean(a) for m, a in sorted(mo.items()) if len(a) >= 5}
        s = snap.get(tid)
        out.append((snapshot_date, exchange, tid, v[0]['nick'], len(v), len(al),
                    st.mean(al) if al else None, t_stat, payoff, wr, conc, ruin,
                    s['mdd'] if s else None, lev_med, lev_p90,
                    st.median(z['marg'] for z in v) if v else None,
                    st.median(z['dur'] for z in v) if v else None,
                    len(set(z['mes'] for z in v if z['mes'])), h1, h2,
                    json.dumps(monthly)))
    con.executemany(
        "INSERT OR REPLACE INTO trader_metrics (snapshot_date,exchange,trader_id,nick,"
        "n,n_alpha,alpha,t_stat,payoff,wr,conc_top1,ruin,mdd,lev_med,lev_p90,marg_med,"
        "dur_med,months_active,alpha_h1,alpha_h2,monthly_alpha) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
    con.commit()
    return len(out)
