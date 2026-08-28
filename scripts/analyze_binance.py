#!/usr/bin/env python3
"""Pipeline de analisis del dataset Binance copy-trading (binance_positions.jsonl).

Salidas (stdout):
  1. Derrotero del dataset (cobertura, rango, calidad)
  2. Mejor par por portfolio (con filtro anti-loteria)
  3. PnL neto agregado por par
  4. Deep-dive XRP: lado, duracion, horario, leverage, gestion
"""
import json, os, statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

BOG = timezone(timedelta(hours=-5))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load():
    recs = [json.loads(l) for l in open(os.path.join(DATA, 'binance_positions.jsonl'))]
    return [r for r in recs if r['n_pos'] > 0]


def derrotero(recs):
    times = [p['opened'] for r in recs for p in r['positions'] if p.get('opened')]
    times.sort()
    tot = sum(r['n_pos'] for r in recs)
    print('=== 1. DERROTERO ===')
    print(f'portfolios con historial: {len(recs)}')
    print(f'posiciones cerradas: {tot}')
    if times:
        print(f'rango: {datetime.fromtimestamp(times[0]/1000, tz=timezone.utc).date()} -> '
              f'{datetime.fromtimestamp(times[-1]/1000, tz=timezone.utc).date()}')
    ns = [r['n_pos'] for r in recs]
    print(f'n_pos por portfolio: mediana={statistics.median(ns):.0f} max={max(ns)} (cap API 2000)')
    lev = [int(p.get('leverage', 0)) for r in recs for p in r['positions'] if str(p.get('leverage', '0')).isdigit()]
    if lev:
        print(f'leverage usado: mediana={statistics.median(lev):.0f}x p90={sorted(lev)[int(len(lev)*0.9)]}x max={max(lev)}x')
    iso = sum(1 for r in recs for p in r['positions'] if p.get('isolated') == 'Isolated')
    tot2 = sum(r['n_pos'] for r in recs)
    print(f'margen: {iso/tot2*100:.0f}% isolated / {100-iso/tot2*100:.0f}% cross')


def best_pair(recs, min_positions=8):
    print('\n=== 2. MEJOR PAR POR PORTFOLIO (top 25 por PnL del par) ===')
    results = []
    for r in recs:
        by_sym = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'wins': 0})
        for p in r['positions']:
            s = by_sym[p['symbol']]
            pnl = f(p.get('closingPnl'))
            s['n'] += 1
            s['pnl'] += pnl
            if pnl > 0:
                s['wins'] += 1
        best = None
        for sym, st in by_sym.items():
            if st['n'] >= min_positions and (best is None or st['pnl'] > best[1]['pnl']):
                best = (sym, st)
        if best:
            sym, st = best
            results.append({'nick': r['nick'], 'pid': r['portfolioId'], 'best': sym,
                            'n': st['n'], 'pnl': st['pnl'], 'wr': st['wins'] / st['n'],
                            'total_pnl': sum(v['pnl'] for v in by_sym.values())})
    results.sort(key=lambda x: -x['pnl'])
    print(f"{'nick':<24}{'par':<14}{'n':>5}{'pnl':>11}{'wr':>6}{'pnl_total':>11}")
    for r in results[:25]:
        print(f"{r['nick'][:23]:<24}{r['best']:<14}{r['n']:>5}{r['pnl']:>11.1f}{r['wr']:>6.2f}{r['total_pnl']:>11.1f}")
    freq = defaultdict(int)
    for r in results:
        freq[r['best']] += 1
    print('\npares mas frecuentes como mejor par:', dict(sorted(freq.items(), key=lambda x: -x[1])[:10]))
    return results


def aggregate(recs):
    print('\n=== 3. PnL NETO POR PAR (todas las posiciones) ===')
    agg = defaultdict(lambda: {'n': 0, 'pnl': 0.0, 'wins': 0})
    for r in recs:
        for p in r['positions']:
            a = agg[p['symbol']]
            pnl = f(p.get('closingPnl'))
            a['n'] += 1
            a['pnl'] += pnl
            if pnl > 0:
                a['wins'] += 1
    rk = sorted(agg.items(), key=lambda x: -x[1]['pnl'])
    print(f"{'par':<16}{'n':>7}{'pnl_net':>12}{'wr':>7}")
    for sym, a in rk[:12]:
        print(f"{sym:<16}{a['n']:>7}{a['pnl']:>12.1f}{a['wins']/a['n']:>7.2f}")
    print('   ...')
    for sym, a in rk[-6:]:
        print(f"{sym:<16}{a['n']:>7}{a['pnl']:>12.1f}{a['wins']/a['n']:>7.2f}")
    return agg


def xrp_deep(recs):
    print('\n=== 4. XRPUSDT DEEP DIVE ===')
    xrp = [(r['nick'], p) for r in recs for p in r['positions'] if p['symbol'] == 'XRPUSDT']
    if not xrp:
        print('sin posiciones XRP')
        return
    pnl_tot = sum(f(p.get('closingPnl')) for _, p in xrp)
    xrp = [(n, p) for n, p in xrp if p.get('closed') and p.get('opened')]  # excluir abiertas
    longs = [(n, p) for n, p in xrp if p.get('side') == 'Long']
    shorts = [(n, p) for n, p in xrp if p.get('side') == 'Short']
    print(f'n={len(xrp)} pnl={pnl_tot:.1f} | Long: n={len(longs)} pnl={sum(f(p.get("closingPnl")) for _,p in longs):.1f} | Short: n={len(shorts)} pnl={sum(f(p.get("closingPnl")) for _,p in shorts):.1f}')
    wins = [p for _, p in xrp if f(p.get('closingPnl')) > 0]
    loss = [p for _, p in xrp if f(p.get('closingPnl')) <= 0]
    if wins and loss:
        wd = sorted((p['closed'] - p['opened']) / 3600000 for p in wins)
        ld = sorted((p['closed'] - p['opened']) / 3600000 for p in loss)
        print(f'wr={len(wins)/len(xrp):.2f} | dur ganadores med={wd[len(wd)//2]:.1f}h vs perdedores med={ld[len(ld)//2]:.1f}h')
        print(f'avg_win={sum(f(p.get("closingPnl")) for p in wins)/len(wins):.1f} avg_loss={sum(f(p.get("closingPnl")) for p in loss)/len(loss):.1f} ratio={abs(sum(f(p.get("closingPnl")) for p in loss)/len(loss)/(sum(f(p.get("closingPnl")) for p in wins)/len(wins))):.2f}')
    print('\nbuckets duracion:')
    for lo, hi, tag in [(0, 1, '<1h'), (1, 4, '1-4h'), (4, 12, '4-12h'), (12, 24, '12-24h'), (24, 72, '1-3d'), (72, 168, '3-7d'), (168, 1e9, '>7d')]:
        grp = [p for _, p in xrp if lo <= (p['closed'] - p['opened']) / 3600000 < hi]
        if grp:
            pnl = sum(f(p.get('closingPnl')) for p in grp)
            wr = sum(1 for p in grp if f(p.get('closingPnl')) > 0) / len(grp)
            print(f'  {tag:<7} n={len(grp):>4} pnl={pnl:>10.1f} wr={wr:.2f}')
    print('\npor leverage:')
    lev_b = defaultdict(lambda: [0, 0.0])
    for _, p in xrp:
        lv = int(p['leverage']) if str(p.get('leverage', '0')).isdigit() else 0
        b = '<=5x' if lv <= 5 else '6-20x' if lv <= 20 else '21-50x' if lv <= 50 else '>50x'
        lev_b[b][0] += 1
        lev_b[b][1] += f(p.get('closingPnl'))
    for b in ['<=5x', '6-20x', '21-50x', '>50x']:
        if b in lev_b:
            print(f'  {b:<7} n={lev_b[b][0]:>4} pnl={lev_b[b][1]:>10.1f}')
    print('\nhora apertura (Bogota) pnl neto:')
    hh = defaultdict(float)
    for _, p in xrp:
        hh[datetime.fromtimestamp(p['opened'] / 1000, tz=BOG).hour] += f(p.get('closingPnl'))
    for h in range(24):
        if h in hh and abs(hh[h]) > 1:
            print(f'  {h:02d}:00 {hh[h]:>10.1f}')
    # top traders XRP
    per = defaultdict(lambda: [0, 0.0])
    for n, p in xrp:
        per[n][0] += 1
        per[n][1] += f(p.get('closingPnl'))
    print('\ntop traders XRP:')
    for n, (cnt, pnl) in sorted(per.items(), key=lambda x: -x[1][1])[:8]:
        print(f'  {n[:24]:<25} n={cnt:>4} pnl={pnl:>10.1f}')


if __name__ == '__main__':
    recs = load()
    derrotero(recs)
    best_pair(recs)
    aggregate(recs)
    xrp_deep(recs)
