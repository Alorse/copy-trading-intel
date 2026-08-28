"""Que separa a los buenos de los malos DENTRO del set de supervivientes, en BTCUSDT.
Controla el sesgo de supervivencia: todos aqui son top-600, asi que la comparacion
top-decil vs bottom-decil aisla comportamiento, no suerte de muestra."""
import csv, collections, statistics as st, datetime as dt

B = [r for r in csv.DictReader(open('binance_positions.csv')) if r['symbol'] == 'BTCUSDT']

def pr(r):
    c, x = float(r['avg_cost']), float(r['avg_close'])
    if c <= 0 or x <= 0: return None
    m = x / c - 1.0
    return m if r['side'] == 'Long' else -m

pos = []
for r in B:
    p = pr(r)
    if p is None or abs(p) > 3: continue
    try: d = float(r['dur_h']); o = int(r['opened_ms']); c = int(r['closed_ms'])
    except: continue
    pos.append(dict(tid=r['portfolio_id'], nick=r['nick'], pr=p, roi=float(r['roi']),
                    pnl=float(r['closing_pnl']), dur=d, lev=float(r['leverage']),
                    side=r['side'], iso=r['isolated'], opened=o, closed=c,
                    notional=float(r['notional'])))

# --- ranking de traders por ROI medio por posicion (>=10 pos para que sea senal) ---
tr = collections.defaultdict(list)
for p in pos: tr[p['tid']].append(p)
tr = {k: v for k, v in tr.items() if len(v) >= 10}
score = {k: st.mean(x['roi'] for x in v) for k, v in tr.items()}
order = sorted(score, key=lambda k: -score[k])
n = max(1, len(order) // 4)
top, bot = order[:n], order[-n:]
print(f"traders BTC con >=10 pos: {len(order)}  | cuartil = {n} c/u")
print(f"score top  (ROI medio/pos): {st.median([score[k] for k in top])*100:.1f}%")
print(f"score bot  (ROI medio/pos): {st.median([score[k] for k in bot])*100:.1f}%\n")

def stats(group, label):
    P = [x for k in group for x in tr[k]]
    wins = [x['pr'] for x in P if x['pr'] > 0]; los = [x['pr'] for x in P if x['pr'] < 0]
    durs = [x['dur'] for x in P]
    longs = [x for x in P if x['side'] == 'Long']
    # consistencia de tamano: CV del notional por trader, luego mediana
    cvs = []
    for k in group:
        ns = [x['notional'] for x in tr[k] if x['notional'] > 0]
        if len(ns) > 3 and st.mean(ns) > 0: cvs.append(st.stdev(ns)/st.mean(ns))
    print(f"{label}")
    print(f"  posiciones                {len(P):>8}")
    print(f"  win rate                  {len(wins)/len(P)*100:>7.1f}%")
    print(f"  payoff (gan/perd, precio) {st.mean(wins)/abs(st.mean(los)):>8.2f}")
    print(f"  |perdida| mediana precio  {st.median([abs(x) for x in los])*100:>7.2f}%")
    print(f"  ganancia mediana precio   {st.median(wins)*100:>7.2f}%")
    print(f"  duracion mediana (h)      {st.median(durs):>8.1f}")
    print(f"  duracion p90 (h)          {st.quantiles(durs, n=10)[8]:>8.1f}")
    print(f"  leverage mediana          {st.median([x['lev'] for x in P]):>8.0f}")
    print(f"  leverage p90              {st.quantiles([x['lev'] for x in P], n=10)[8]:>8.0f}")
    print(f"  %long                     {len(longs)/len(P)*100:>7.1f}%")
    print(f"  %cross                    {sum(1 for x in P if x['iso']=='Cross')/len(P)*100:>7.1f}%")
    print(f"  pos/trader mediana        {st.median([len(tr[k]) for k in group]):>8.0f}")
    print(f"  CV tamano mediano         {st.median(cvs) if cvs else float('nan'):>8.2f}")
    print()
    return P

Pt = stats(top, 'TOP cuartil')
Pb = stats(bot, 'BOTTOM cuartil')

# --- duracion: donde gana cada grupo ---
def bucket(d):
    return ('<1h' if d<1 else '1-4h' if d<4 else '4-12h' if d<12 else '12-24h' if d<24
            else '1-3d' if d<72 else '3-7d' if d<168 else '7-30d' if d<720 else '>30d')
ORD = ['<1h','1-4h','4-12h','12-24h','1-3d','3-7d','7-30d','>30d']
print(f"{'bucket':<9}{'TOP n':>7}{'TOP medPr%':>12}{'TOP wr%':>9}   {'BOT n':>7}{'BOT medPr%':>12}{'BOT wr%':>9}")
print('-'*72)
for b in ORD:
    t = [x for x in Pt if bucket(x['dur']) == b]; o = [x for x in Pb if bucket(x['dur']) == b]
    if not t and not o: continue
    f = lambda g: (f"{len(g):>7}", f"{st.median([x['pr'] for x in g])*100:>12.3f}",
                   f"{sum(1 for x in g if x['pr']>0)/len(g)*100:>9.1f}") if g else ("      -","           -","        -")
    print(f"{b:<9}{''.join(f(t))}   {''.join(f(o))}")
