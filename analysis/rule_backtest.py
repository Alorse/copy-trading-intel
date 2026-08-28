"""Prueba del conjunto de reglas como FILTRO sobre posiciones REALES.
Reglas fijadas mirando SOLO el periodo 1; se evaluan en el periodo 2.
El stop se re-simula con el MAE reconstruido del OHLC: si el recorrido lo toco,
la operacion se cierra ahi; si no, se usa el resultado real."""
import csv, bisect, statistics as st, math, datetime as dt, random
random.seed(11)

K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h.csv')):
    K.append((int(r['open_ms']), float(r['high']), float(r['low']), float(r['close'])))
K.sort(); ks=[x[0] for x in K]; cl=[x[3] for x in K]

def mom(ms, h):
    i=bisect.bisect_right(ks,ms)-1
    if i<max(h,200): return None
    return cl[i]/cl[i-h]-1
def ma200(ms):
    i=bisect.bisect_right(ks,ms)-1
    if i<200: return None
    return cl[i]/(sum(cl[i-200:i])/200)-1
def path(o,c,entry,side):
    i=bisect.bisect_left(ks,o); j=bisect.bisect_right(ks,c)
    seg=K[i:j]
    if not seg: return None
    hh=max(x[1] for x in seg); ll=min(x[2] for x in seg)
    return ((ll/entry-1) if side==1 else (1-hh/entry))

R=[]
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
    m24,m72,ma=mom(o,24),mom(o,72),ma200(o)
    if m24 is None or m72 is None or ma is None: continue
    mae=path(o,c,ac,side)
    if mae is None: continue
    R.append(dict(o=o,net=net,dur=d,lev=float(r['leverage']),side=side,
                  m24=m24,m72=m72,ma=ma,mae=mae))
R.sort(key=lambda z:z['o']); CUT=R[len(R)//2]['o']
A=[z for z in R if z['o']<CUT]; B=[z for z in R if z['o']>=CUT]
print(f"n={len(R)}  P1={len(A)}  P2={len(B)}  corte {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}\n")

# umbrales fijados SOLO con P1
m24q=sorted(z['m24'] for z in A)[2*len(A)//3]
m72q=sorted(z['m72'] for z in A)[2*len(A)//3]
maq =sorted(z['ma']  for z in A)[2*len(A)//3]
print(f"umbrales de P1: mom24h>{m24q*100:.2f}%  mom72h>{m72q*100:.2f}%  distMA200>{maq*100:.2f}%\n")

STOP=0.024   # p90 del MAE de las ganadoras, medido en P1

def apply(z, use_stop=True, sl=STOP):
    if use_stop and z['mae'] <= -sl:
        return -sl            # el recorrido toco el stop
    return z['net']

def ev(rows, label, filt=None, use_stop=True):
    g=[z for z in rows if (filt(z) if filt else True)]
    if len(g)<30: print(f"{label}: muestra chica ({len(g)})"); return
    v=[apply(z,use_stop) for z in g]
    w=[x for x in v if x>0]
    print(f"{label:<34}n={len(g):>5}  media {st.mean(v)*100:+7.3f}%  mediana {st.median(v)*100:+7.3f}%"
          f"  wr {len(w)/len(v)*100:5.1f}%  suma {sum(v)*100:+8.1f}%")

for per,rows in (('P1 (en muestra)',A), ('P2 (FUERA de muestra)',B)):
    print(f"--- {per} ---")
    ev(rows, 'todas, sin stop', None, False)
    ev(rows, 'todas, con stop 2.4%', None, True)
    ev(rows, 'R1 momentum alto (3 filtros)', lambda z: z['m24']>m24q and z['m72']>m72q and z['ma']>maq)
    ev(rows, 'R2 = R1 + leverage <=25x',     lambda z: z['m24']>m24q and z['m72']>m72q and z['ma']>maq and z['lev']<=25)
    ev(rows, 'R3 = R2 + duracion >=1h',      lambda z: z['m24']>m24q and z['m72']>m72q and z['ma']>maq and z['lev']<=25 and z['dur']>=1)
    print()

# significancia del filtro final en P2
sel=[apply(z) for z in B if z['m24']>m24q and z['m72']>m72q and z['ma']>maq and z['lev']<=25 and z['dur']>=1]
rest=[apply(z) for z in B if not (z['m24']>m24q and z['m72']>m72q and z['ma']>maq and z['lev']<=25 and z['dur']>=1)]
def perm(a,b,n=20000):
    obs=abs(st.mean(a)-st.mean(b)); pool=a+b; na=len(a); c=0
    for _ in range(n):
        random.shuffle(pool)
        if abs(st.mean(pool[:na])-st.mean(pool[na:]))>=obs: c+=1
    return (c+1)/(n+1)
print(f"P2: filtradas n={len(sel)} media {st.mean(sel)*100:+.3f}%  vs  resto n={len(rest)} media {st.mean(rest)*100:+.3f}%")
print(f"    permutacion sobre la media: p = {perm(sel,rest):.4f}")
