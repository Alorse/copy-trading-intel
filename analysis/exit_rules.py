"""EXIT RULES: reconstructs each position's path from 1h OHLC.
MAE = maximum adverse excursion; MFE = maximum favourable (both in % of price).
Stop-loss and take-profit come out of this empirically, not invented."""
import csv, bisect, statistics as st, collections

K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h.csv')):
    K.append((int(r['open_ms']), float(r['high']), float(r['low'])))
K.sort(); ks=[x[0] for x in K]

def path(o,c,entry,side):
    i=bisect.bisect_left(ks,o); j=bisect.bisect_right(ks,c)
    if i>=j or i>=len(K): return None
    seg=K[i:j]
    if not seg: return None
    hh=max(x[1] for x in seg); ll=min(x[2] for x in seg)
    if side==1: mfe=(hh/entry-1); mae=(ll/entry-1)
    else:       mfe=(1-ll/entry); mae=(1-hh/entry)
    return mae, mfe        # typically mae<=0, mfe>=0

rows=[]
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol']!='BTCUSDT': continue
    try:
        o=int(r['opened_ms']); c=int(r['closed_ms']); notio=float(r['notional'])
        pnl=float(r['closing_pnl']); ac=float(r['avg_cost']); d=float(r['dur_h'] or 0)
    except: continue
    if notio<=0 or ac<=0: continue
    net=pnl/notio
    if abs(net)>3: continue
    side=1 if r['side']=='Long' else -1
    p=path(o,c,ac,side)
    if not p: continue
    rows.append(dict(mae=p[0], mfe=p[1], net=net, dur=d, side=side,
                     lev=float(r['leverage'])))
print(f"BTC positions with a reconstructed path: {len(rows)}\n")

W=[z for z in rows if z['net']>0]; L=[z for z in rows if z['net']<0]
print("=== How far does a winner go against you before winning? (sets the stop) ===")
for lab,G in (('WINNERS',W),('LOSERS',L)):
    m=sorted(abs(z['mae']) for z in G)
    q=lambda p: m[int(p*len(m))]*100
    print(f"  {lab:<12} n={len(G):>5}  median MAE {st.median(m)*100:6.2f}%"
          f"  p75 {q(.75):6.2f}%  p90 {q(.90):6.2f}%  p95 {q(.95):6.2f}%")
print("\n  -> a stop below the WINNERS p90 kills trades that were going to win")

print("\n=== Exit efficiency: how much of the favourable move is captured ===")
cap=[]
for z in rows:
    if z['mfe']>0.001:
        pr=z['net']
        cap.append(min(max(pr/z['mfe'],-1),2))
print(f"  median MFE capture: {st.median(cap)*100:.1f}%  (p25 {st.quantiles(cap,n=4)[0]*100:.0f}%, p75 {st.quantiles(cap,n=4)[2]*100:.0f}%)")

print("\n=== MFE by duration: how far does the move get? ===")
def db(d): return ('<1h' if d<1 else '1-4h' if d<4 else '4-12h' if d<12 else '12-24h' if d<24
                   else '1-3d' if d<72 else '>3d')
g=collections.defaultdict(list)
for z in rows: g[db(z['dur'])].append(z)
print(f"{'bucket':<9}{'n':>6}{'MFE med%':>10}{'MAE med%':>10}{'ratio':>8}{'net med%':>10}")
for b in ('<1h','1-4h','4-12h','12-24h','1-3d','>3d'):
    v=g.get(b,[])
    if len(v)<30: continue
    mf=st.median(z['mfe'] for z in v); ma=st.median(abs(z['mae']) for z in v)
    print(f"{b:<9}{len(v):>6}{mf*100:>10.3f}{ma*100:>10.3f}{mf/ma if ma else 0:>8.2f}"
          f"{st.median(z['net'] for z in v)*100:>10.3f}")

print("\n=== Liquidation risk by leverage (MAE vs margin) ===")
for lo,hisep,lab in ((0,10,'<=10x'),(10,25,'11-25x'),(25,60,'26-60x'),(60,999,'>60x')):
    v=[z for z in rows if lo<z['lev']<=hisep]
    if len(v)<30: continue
    liq=[z for z in v if abs(z['mae'])*z['lev']>0.8]   # 80% of the margin consumed
    print(f"  {lab:<8} n={len(v):>5}  MAE med {st.median(abs(z['mae']) for z in v)*100:5.2f}%"
          f"  |  {len(liq)/len(v)*100:5.1f}% got to consume >80% of the margin")
