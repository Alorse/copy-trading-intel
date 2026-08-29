"""SOFT RULE candidates: each structural feature is evaluated on calendar period 1
and VALIDATED on period 2. Only what works in both survives.
Metric: de-leveraged price return, equal weight per position."""
import csv, bisect, statistics as st, collections, datetime as dt, math

# regime from the OHLC
K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h.csv')):
    K.append((int(r['open_ms']), float(r['close'])))
K.sort(); ks=[x[0] for x in K]; cl=[x[1] for x in K]
ma=[None]*len(K); run=0.0
for i,c in enumerate(cl):
    run+=c
    if i>=200: run-=cl[i-200]
    if i>=199: ma[i]=run/200
def reg(ms):
    i=bisect.bisect_right(ks,ms)-1
    if i<199 or i>=len(K): return None
    return 1 if cl[i]>ma[i] else -1

P=[]
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol']!='BTCUSDT': continue
    c,x=float(r['avg_cost']),float(r['avg_close'])
    if c<=0 or x<=0: continue
    m=x/c-1.0; side=1 if r['side']=='Long' else -1
    ret=m*side
    if abs(ret)>3: continue
    try: o=int(r['opened_ms']); d=float(r['dur_h'])
    except: continue
    g=reg(o)
    if g is None: continue
    t=dt.datetime.fromtimestamp(o/1000, dt.UTC)
    oi,cv=float(r['max_oi']),float(r['closed_volume'])
    P.append(dict(o=o, ret=ret, dur=d, lev=float(r['leverage']), side=side, reg=g,
                  iso=r['isolated'], hour=t.hour, dow=t.weekday(),
                  partial=1 if (oi>0 and cv>0 and abs(cv-oi)/oi>0.02) else 0))

P.sort(key=lambda z: z['o'])
CUT=P[len(P)//2]['o']
A=[z for z in P if z['o']<CUT]; B=[z for z in P if z['o']>=CUT]
print(f"period 1: {len(A)} pos up to {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}")
print(f"period 2: {len(B)} pos\n")

def durb(d): return ('<1h' if d<1 else '1-4h' if d<4 else '4-12h' if d<12 else '12-24h' if d<24
                     else '1-3d' if d<72 else '3-7d' if d<168 else '>7d')
def levb(l): return ('<=5x' if l<=5 else '6-20x' if l<=20 else '21-50x' if l<=50 else '>50x')

FEATURES = [
  ('duration',      lambda z: durb(z['dur'])),
  ('leverage',      lambda z: levb(z['lev'])),
  ('side',          lambda z: 'Long' if z['side']==1 else 'Short'),
  ('regime x side', lambda z: ('bull' if z['reg']==1 else 'bear')+'+'+('Long' if z['side']==1 else 'Short')),
  ('margin',        lambda z: z['iso']),
  ('partial close', lambda z: 'partial' if z['partial'] else 'full'),
  ('day of week',   lambda z: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][z['dow']]),
  ('hour UTC',      lambda z: f"{z['hour']//6*6:02d}-{z['hour']//6*6+5:02d}h"),
]

def cells(rows, fn):
    d=collections.defaultdict(list)
    for z in rows: d[fn(z)].append(z['ret'])
    return d

def mwu_z(a, b):
    """Approximate Mann-Whitney: the cell vs the rest. z>2 ~ p<0.05."""
    na,nb=len(a),len(b)
    if na<20 or nb<20: return 0.0
    allv=sorted([(v,0) for v in a]+[(v,1) for v in b])
    r=0.0; i=0
    while i<len(allv):
        j=i
        while j+1<len(allv) and allv[j+1][0]==allv[i][0]: j+=1
        rank=(i+j)/2.0+1
        for k in range(i,j+1):
            if allv[k][1]==0: r+=rank
        i=j+1
    u=r-na*(na+1)/2.0
    mu=na*nb/2.0; sd=math.sqrt(na*nb*(na+nb+1)/12.0)
    return (u-mu)/sd if sd else 0.0

for name, fn in FEATURES:
    ca, cb = cells(A, fn), cells(B, fn)
    keys = sorted(set(ca) | set(cb))
    print(f"### {name}")
    print(f"{'cell':<16}{'P1 n':>7}{'P1 medRet%':>12}{'P2 n':>7}{'P2 medRet%':>12}{'sign':>8}{'z(P2)':>8}")
    for k in keys:
        a, b = ca.get(k, []), cb.get(k, [])
        if len(a) < 30 or len(b) < 30: continue
        m1, m2 = st.median(a), st.median(b)
        rest = [z['ret'] for z in B if fn(z) != k]
        z = mwu_z(b, rest)
        same = 'consist' if (m1 > 0) == (m2 > 0) else 'FLIP'
        print(f"{k:<16}{len(a):>7}{m1*100:>12.3f}{len(b):>7}{m2*100:>12.3f}{same:>8}{z:>8.2f}")
    print()
