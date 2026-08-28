"""Se adapta el LADO al regimen? Y persiste esa adaptacion por trader?
Regimen = precio vs media movil de 200h en el momento de apertura (info disponible
en tiempo real, sin mirar al futuro)."""
import csv, bisect, statistics as st, collections

K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h.csv')):
    K.append((int(r['open_ms']), float(r['close'])))
K.sort(); ks=[x[0] for x in K]; cl=[x[1] for x in K]
ma=[None]*len(K)
run=0.0
for i,c in enumerate(cl):
    run+=c
    if i>=200: run-=cl[i-200]
    if i>=199: ma[i]=run/200

def regime(ms):
    """+1 alcista (precio>MA200h), -1 bajista. None si no hay historia."""
    i=bisect.bisect_right(ks,ms)-1
    if i<199 or i>=len(K): return None
    return 1 if cl[i]>ma[i] else -1

P=collections.defaultdict(list)
tot=al=0
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol']!='BTCUSDT': continue
    try: o=int(r['opened_ms'])
    except: continue
    g=regime(o)
    ac,acl=float(r['avg_cost']),float(r['avg_close'])
    if g is None or ac<=0 or acl<=0: continue
    side = 1 if r['side']=='Long' else -1
    ret=(acl/ac-1)*side
    if abs(ret)>3: continue
    tot+=1; al += (side==g)
    P[r['portfolio_id']].append((o,g,side,ret))

print(f"posiciones BTC con regimen definido: {tot}")
print(f"lado ALINEADO con el regimen: {al/tot*100:.1f}%  (50% = sin adaptacion)\n")

# rentabilidad por celda regimen x lado
cell=collections.defaultdict(list)
for v in P.values():
    for o,g,s,ret in v: cell[(g,s)].append(ret)
print(f"{'regimen':<10}{'lado':<7}{'n':>7}{'retMed%':>10}{'winrate%':>10}")
print('-'*44)
for g in (1,-1):
    for s in (1,-1):
        v=cell[(g,s)]
        if not v: continue
        print(f"{'alcista' if g==1 else 'bajista':<10}{'Long' if s==1 else 'Short':<7}"
              f"{len(v):>7}{st.median(v)*100:>10.3f}{sum(1 for x in v if x>0)/len(v)*100:>10.1f}")

# persistencia de la ADAPTACION por trader
def spear(a,b):
    def rk(v):
        s=sorted(range(len(v)),key=lambda i:v[i]); r=[0]*len(v)
        for p,i in enumerate(s): r[i]=p
        return r
    ra,rb=rk(a),rk(b); n=len(a); ma_,mb=st.mean(ra),st.mean(rb)
    num=sum((ra[i]-ma_)*(rb[i]-mb) for i in range(n))
    den=(sum((x-ma_)**2 for x in ra)*sum((x-mb)**2 for x in rb))**0.5
    return num/den if den else 0.0

a1,a2,r2=[],[],[]
for tid,v in P.items():
    v.sort()
    if len(v)<30: continue
    k=len(v)//2; h1,h2=v[:k],v[k:]
    a1.append(sum(1 for x in h1 if x[2]==x[1])/len(h1))
    a2.append(sum(1 for x in h2 if x[2]==x[1])/len(h2))
    r2.append(st.mean(x[3] for x in h2))
print(f"\npersistencia de la ADAPTACION al regimen (n={len(a1)} traders >=30 pos):")
print(f"  rho alineacion H1 -> H2 : {spear(a1,a2):+.3f}")
print(f"  rho alineacion H1 -> retorno H2 : {spear(a1,r2):+.3f}   <-- paga adaptarse?")
hi=[i for i in range(len(a1)) if a1[i]>=st.median(a1)]
lo=[i for i in range(len(a1)) if a1[i]< st.median(a1)]
print(f"  retorno mediano H2, alta alineacion en H1: {st.median([r2[i] for i in hi])*100:+.3f}%")
print(f"  retorno mediano H2, baja alineacion en H1: {st.median([r2[i] for i in lo])*100:+.3f}%")
