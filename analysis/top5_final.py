"""Final ranking with the filters the adversarial verification proved necessary."""
import csv, statistics as st, collections, datetime as dt
R=[]
for r in csv.DictReader(open('binance_positions.csv')):
    try:
        o=int(r['opened_ms']); ac=float(r['avg_cost']); acl=float(r['avg_close'])
        notio=float(r['notional']); pnl=float(r['closing_pnl']); lev=float(r['leverage'])
    except: continue
    if ac<=0 or acl<=0 or notio<=0 or lev<=0: continue
    pr=(acl/ac-1)*(1 if r['side']=='Long' else -1)
    if abs(pr)>3: continue
    R.append(dict(tid=r['portfolio_id'], nick=r['nick'], sym=r['symbol'], side=r['side'], o=o,
                  pr=pr, pnl=pnl, lev=lev, dur=float(r['dur_h'] or 0), marg=notio/lev,
                  mdd=float(r['mdd'] or 0), aum=float(r['aum'] or 0), roi=float(r['p_roi'] or 0),
                  month=dt.datetime.fromtimestamp(o/1000, dt.UTC).strftime('%Y-%m')))
cell=collections.defaultdict(list)
for x in R: cell[(x['sym'],x['month'],x['side'])].append(x['pr'])
bench={k:st.median(v) for k,v in cell.items() if len(v)>=20}
for x in R:
    b=bench.get((x['sym'],x['month'],x['side'])); x['alpha']= x['pr']-b if b is not None else None
T=collections.defaultdict(list)
for x in R: T[x['tid']].append(x)

C=[]; rej=collections.Counter()
for tid,v in T.items():
    v.sort(key=lambda z:z['o'])
    al=[z['alpha'] for z in v if z['alpha'] is not None]
    if len(v)<60 or len(al)<40: rej['sample <60']+=1; continue
    w=[z['pr'] for z in v if z['pr']>0]; l=[z['pr'] for z in v if z['pr']<0]
    if not w or not l: rej['no losers (hidden)']+=1; continue
    wr=len(w)/len(v)*100
    payoff=st.mean(w)/abs(st.mean(l))
    tot=sum(z['pnl'] for z in v); best=max(z['pnl'] for z in v)
    t=(st.mean(al)/(st.pstdev(al)/len(al)**.5)) if st.pstdev(al)>0 else 0
    k=len(al)//2
    aH2=st.mean(al[k:])
    levp90=sorted(z['lev'] for z in v)[int(.9*len(v))]
    ruin=min(l)*st.median(z['lev'] for z in v)*100     # worst loss x leverage, % of margin
    months=sorted(set(z['month'] for z in v))
    margmed=st.median(z['marg'] for z in v)
    durmed=st.median(z['dur'] for z in v)
    conc=(best/tot*100) if tot>0 else 999
    d=dict(tid=tid,nick=v[0]['nick'],n=len(v),alpha=st.mean(al),t=t,aH2=aH2,wr=wr,payoff=payoff,
           lev=st.median(z['lev'] for z in v),levp90=levp90,ruin=ruin,conc=conc,mdd=v[0]['mdd'],
           aum=v[0]['aum'],roi=v[0]['roi'],marg=margmed,dur=durmed,months=len(months),
           aug='2026-08' in months)
    # hard filters
    if t<2.5: rej['t<2.5']+=1; continue
    if aH2<=0: rej['alpha H2<=0']+=1; continue
    if wr>92: rej['wr>92% (hides losers)']+=1; continue
    if payoff<0.5: rej['payoff<0.5 (left tail)']+=1; continue
    if conc>30: rej['concentration>30%']+=1; continue
    if levp90>25: rej['leverage p90>25x']+=1; continue
    if not d['aug']: rej['inactive in August']+=1; continue
    if margmed<50: rej['median margin<$50 (not copyable)']+=1; continue
    if durmed<0.5: rej['duration<30min (latency)']+=1; continue
    C.append(d)

print("Rejections by filter:")
for k,n in rej.most_common(): print(f"   {k:<36} {n}")
print(f"\nSURVIVE THE HARD FILTERS: {len(C)}\n")
C.sort(key=lambda d:-(d['t']*0.5 + d['alpha']*100*0.3 + d['payoff']*0.2))
h=f"{'nick':<20}{'n':>5}{'alpha%':>8}{'t':>6}{'wr%':>6}{'payoff':>7}{'lev':>4}{'ruin%':>8}{'conc%':>7}{'mdd':>6}{'marg$':>8}{'dur h':>7}{'ROI%':>7}"
print(h); print('-'*len(h))
for d in C:
    print(f"{d['nick'][:19]:<20}{d['n']:>5}{d['alpha']*100:>8.2f}{d['t']:>6.2f}{d['wr']:>6.1f}{d['payoff']:>7.2f}"
          f"{d['lev']:>4.0f}{d['ruin']:>8.0f}{d['conc']:>7.1f}{d['mdd']:>6.1f}{d['marg']:>8,.0f}{d['dur']:>7.1f}{d['roi']:>7.0f}")
