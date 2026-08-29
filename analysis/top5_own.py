"""Multi-factor ranking of traders to COPY TRADES.
Principle: PnL in USD is unfair (account size and leverage inflate it). We use:
 - alpha = return minus the median of their peers in the SAME symbol-month-side
   (separates skill from beta: winning long in a pump is no merit)
 - DE-LEVERAGED return (the price move actually captured)
 - temporal trend (improving or decaying?)
 - ruin risk, concentration, consistency, copyability"""
import csv, statistics as st, collections, datetime as dt, math

ROWS=[]
for r in csv.DictReader(open('binance_positions.csv')):
    try:
        o=int(r['opened_ms']); c=int(r['closed_ms']); notio=float(r['notional'])
        pnl=float(r['closing_pnl']); ac=float(r['avg_cost']); acl=float(r['avg_close'])
        lev=float(r['leverage'])
    except: continue
    if notio<=0 or ac<=0 or acl<=0: continue
    net=pnl/notio                                    # net on notional (fees included)
    pr=(acl/ac-1)*(1 if r['side']=='Long' else -1)   # de-leveraged
    if abs(net)>3 or abs(pr)>3: continue
    ROWS.append(dict(tid=r['portfolio_id'], nick=r['nick'], sym=r['symbol'], side=r['side'],
                     o=o, c=c, net=net, pr=pr, lev=lev, notio=notio, pnl=pnl,
                     mdd=float(r['mdd'] or 0), aum=float(r['aum'] or 0),
                     month=dt.datetime.fromtimestamp(o/1000, dt.UTC).strftime('%Y-%m')))

# benchmark: median net return per (symbol, month, side) -> alpha
cell=collections.defaultdict(list)
for x in ROWS: cell[(x['sym'],x['month'],x['side'])].append(x['net'])
bench={k:st.median(v) for k,v in cell.items() if len(v)>=20}
for x in ROWS:
    b=bench.get((x['sym'],x['month'],x['side']))
    x['alpha']= x['net']-b if b is not None else None

T=collections.defaultdict(list)
for x in ROWS: T[x['tid']].append(x)

def slope(pairs):
    """temporal trend: OLS slope of return vs normalised time."""
    if len(pairs)<10: return None
    xs=[p[0] for p in pairs]; ys=[p[1] for p in pairs]
    lo,hi=min(xs),max(xs)
    if hi==lo: return None
    xs=[(x-lo)/(hi-lo) for x in xs]
    mx,my=st.mean(xs),st.mean(ys)
    den=sum((x-mx)**2 for x in xs)
    return sum((xs[i]-mx)*(ys[i]-my) for i in range(len(xs)))/den if den else None

CAND=[]
for tid,v in T.items():
    v.sort(key=lambda z:z['o'])
    al=[z['alpha'] for z in v if z['alpha'] is not None]
    if len(v)<40 or len(al)<30: continue          # minimum sample
    net=[z['net'] for z in v]; pr=[z['pr'] for z in v]
    k=len(v)//2; h1,h2=v[:k],v[k:]
    a1=[z['alpha'] for z in h1 if z['alpha'] is not None]
    a2=[z['alpha'] for z in h2 if z['alpha'] is not None]
    w=[x for x in pr if x>0]; l=[x for x in pr if x<0]
    tot=sum(z['pnl'] for z in v)
    best=max(z['pnl'] for z in v)
    CAND.append(dict(
        tid=tid, nick=v[0]['nick'], n=len(v),
        alpha=st.mean(al), alpha_med=st.median(al),
        net=st.mean(net), pr=st.mean(pr), pr_med=st.median(pr),
        wr=len(w)/len(pr)*100,
        payoff=(st.mean(w)/abs(st.mean(l))) if w and l else float('nan'),
        lev_med=st.median(z['lev'] for z in v),
        lev_p90=sorted(z['lev'] for z in v)[int(.9*len(v))],
        trend=slope([(z['o'],z['alpha']) for z in v if z['alpha'] is not None]),
        a1=st.mean(a1) if len(a1)>=10 else None,
        a2=st.mean(a2) if len(a2)>=10 else None,
        conc=(best/tot*100) if tot>0 else float('nan'),
        mdd=v[0]['mdd']*100, aum=v[0]['aum'],
        syms=len(set(z['sym'] for z in v)),
        pnl=tot,
    ))
print(f"candidates with >=40 positions and >=30 with a benchmark: {len(CAND)}\n")

# composite score, explicit weights
als=[c['alpha'] for c in CAND]; ma,sa=st.mean(als),st.pstdev(als)
for c in CAND:
    z_alpha=(c['alpha']-ma)/sa if sa else 0
    z_cons =1.0 if (c['a1'] is not None and c['a2'] is not None and c['a1']>0 and c['a2']>0) else 0.0
    z_trend=1.0 if (c['trend'] is not None and c['trend']>0) else 0.0
    pen_lev=-1.0 if c['lev_med']>25 else 0.0
    pen_conc=-1.0 if c['conc']>40 else 0.0
    pen_n  =-0.5 if c['n']<60 else 0.0
    c['score']= 3.0*z_alpha + 1.5*z_cons + 1.0*z_trend + 1.0*pen_lev + 1.5*pen_conc + pen_n

CAND.sort(key=lambda c:-c['score'])
print("score = 3·z(alpha) + 1.5·(alpha>0 in both halves) + 1·(trend>0) − 1·(lev>25) − 1.5·(concentration>40%) − 0.5·(n<60)\n")
h=f"{'#':<3}{'nick':<20}{'n':>5}{'alpha%':>8}{'a-H1%':>7}{'a-H2%':>7}{'pr%':>7}{'wr%':>6}{'lev':>5}{'conc%':>7}{'mdd%':>6}{'sym':>5}{'score':>7}"
print(h); print('-'*len(h))
for i,c in enumerate(CAND[:12],1):
    a1=f"{c['a1']*100:.2f}" if c['a1'] is not None else '-'
    a2=f"{c['a2']*100:.2f}" if c['a2'] is not None else '-'
    print(f"{i:<3}{c['nick'][:19]:<20}{c['n']:>5}{c['alpha']*100:>8.2f}{a1:>7}{a2:>7}"
          f"{c['pr']*100:>7.2f}{c['wr']:>6.1f}{c['lev_med']:>5.0f}{c['conc']:>7.1f}{c['mdd']:>6.1f}{c['syms']:>5}{c['score']:>7.2f}")
