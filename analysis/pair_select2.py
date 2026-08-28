"""Ranking desapalancado: retorno de PRECIO por posicion (quita el efecto leverage),
peso igual por trader, + estabilidad temporal en dos mitades."""
import csv, collections, statistics as st

B = list(csv.DictReader(open('binance_positions.csv')))

def price_ret(r):
    """Retorno del movimiento de precio, con signo por lado. Sin leverage."""
    c, x = float(r['avg_cost']), float(r['avg_close'])
    if c <= 0 or x <= 0: return None
    m = (x / c) - 1.0
    return m if r['side'] == 'Long' else -m

recs = []
for r in B:
    pr = price_ret(r)
    if pr is None or abs(pr) > 3: continue      # descarta basura/outliers absurdos
    try: t = int(r['closed_ms'])
    except: continue
    recs.append((r['symbol'], r['portfolio_id'], pr, float(r['closing_pnl']), t, float(r['leverage'])))

ts = sorted(x[4] for x in recs); mid = ts[len(ts)//2]
print('corte temporal:', __import__('datetime').datetime.utcfromtimestamp(mid/1000).date(),
      '| pos validas:', len(recs))

bysym = collections.defaultdict(list)
for x in recs: bysym[x[0]].append(x)

out = []
for sym, rr in bysym.items():
    traders = collections.defaultdict(list)
    for _, tid, pr, pnl, t, lev in rr: traders[tid].append((pr, pnl, t, lev))
    if len(traders) < 20 or len(rr) < 100: continue
    tr_pr = [st.mean(y[0] for y in v) for v in traders.values()]
    med_pr = st.median(tr_pr)
    pct_w  = sum(1 for x in tr_pr if x > 0) / len(tr_pr) * 100
    # estabilidad: mediana de retorno de precio por posicion, cada mitad
    h1 = [y[0] for v in traders.values() for y in v if y[2] <  mid]
    h2 = [y[0] for v in traders.values() for y in v if y[2] >= mid]
    m1 = st.median(h1) if len(h1) > 30 else None
    m2 = st.median(h2) if len(h2) > 30 else None
    lev = st.median([y[3] for v in traders.values() for y in v])
    usd = sum(y[1] for v in traders.values() for y in v)
    out.append(dict(sym=sym, npos=len(rr), ntr=len(traders), usd=usd, med_pr=med_pr,
                    pct_w=pct_w, m1=m1, m2=m2, lev=lev,
                    both=(m1 is not None and m2 is not None and m1 > 0 and m2 > 0)))

out.sort(key=lambda d: -d['med_pr'])
h = f"{'symbol':<13}{'pos':>6}{'trad':>5}{'USD':>11}{'medPr%':>8}{'%trGana':>8}{'H1%':>7}{'H2%':>7}{'levMed':>7}  estable"
print(h); print('-'*len(h))
def line(d):
    f = lambda v: f"{v*100:>7.2f}" if v is not None else "      -"
    return (f"{d['sym']:<13}{d['npos']:>6}{d['ntr']:>5}{d['usd']:>11,.0f}{d['med_pr']*100:>8.2f}"
            f"{d['pct_w']:>8.1f}{f(d['m1'])}{f(d['m2'])}{d['lev']:>7.0f}  {'SI' if d['both'] else 'no'}")
for d in out[:20]: print(line(d))
print('\n--- referencia ---')
for d in out:
    if d['sym'] in ('BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT'): print(line(d))
print('\n--- cola inferior ---')
for d in out[-5:]: print(line(d))
neg = sum(1 for d in out if d['med_pr'] < 0)
print(f"\ntotal pares: {len(out)} | con medPr negativa: {neg} ({neg/len(out)*100:.0f}%)"
      f" | estables ambas mitades: {sum(1 for d in out if d['both'])}")
