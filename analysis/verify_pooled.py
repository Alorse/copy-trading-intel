"""VERIFICACION INDEPENDIENTE del claim central de Fable:
la expectancy persiste al agrupar TODOS los simbolos (no solo BTC).
Implementado desde cero. Split por CALENDARIO. Retorno NETO (closing_pnl/notional).
Control: demean por simbolo x lado x mitad -> compara a cada trader contra otros
que hicieron LO MISMO (mismo par, mismo lado, mismo periodo)."""
import csv, statistics as st, collections, random, math
random.seed(7)

def avg_rank(v):
    idx=sorted(range(len(v)), key=lambda i: v[i]); r=[0.0]*len(v); i=0
    while i<len(idx):
        j=i
        while j+1<len(idx) and v[idx[j+1]]==v[idx[i]]: j+=1
        mr=(i+j)/2.0
        for k in range(i,j+1): r[idx[k]]=mr
        i=j+1
    return r
def pear(a,b):
    n=len(a); ma,mb=st.mean(a),st.mean(b)
    num=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    den=(sum((x-ma)**2 for x in a)*sum((x-mb)**2 for x in b))**0.5
    return num/den if den else 0.0
def spear(a,b): return pear(avg_rank(a),avg_rank(b))
def perm_p(a,b,n=10000):
    obs=abs(spear(a,b)); bb=list(b); c=0
    for _ in range(n):
        random.shuffle(bb)
        if abs(spear(a,bb))>=obs: c+=1
    return (c+1)/(n+1)
def boot(a,b,n=2000):
    N=len(a); o=[]
    for _ in range(n):
        s=[random.randrange(N) for _ in range(N)]
        o.append(spear([a[i] for i in s],[b[i] for i in s]))
    o.sort(); return o[int(.025*n)], o[int(.975*n)]

rows=[]
for r in csv.DictReader(open('binance_positions.csv')):
    try:
        o=int(r['opened_ms']); notio=float(r['notional']); pnl=float(r['closing_pnl'])
    except: continue
    if notio<=0: continue
    net = pnl/notio                     # retorno NETO sobre notional (fees dentro)
    if abs(net)>3: continue
    rows.append((r['portfolio_id'], r['symbol'], r['side'], o, net))

ts=sorted(x[3] for x in rows); CUT=ts[len(ts)//2]
import datetime as dt
print(f"posiciones: {len(rows)} | corte calendario: {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}")

def half(o): return 0 if o<CUT else 1

# demean por (simbolo, lado, mitad)
grp=collections.defaultdict(list)
for tid,sym,side,o,net in rows: grp[(sym,side,half(o))].append(net)
gmean={k: st.mean(v) for k,v in grp.items() if len(v)>=10}

def build(demean):
    A=collections.defaultdict(list); B=collections.defaultdict(list)
    for tid,sym,side,o,net in rows:
        h=half(o); k=(sym,side,h)
        if demean:
            if k not in gmean: continue
            v=net-gmean[k]
        else: v=net
        (A if h==0 else B)[tid].append(v)
    return A,B

for label,demean in [('SIN control (crudo)',False), ('CON demean simbolo x lado x mitad',True)]:
    A,B=build(demean)
    ids=[t for t in A if t in B and len(A[t])>=30 and len(B[t])>=30]
    e1=[st.mean(A[t]) for t in ids]; e2=[st.mean(B[t]) for t in ids]
    rho=spear(e1,e2); lo,hi=boot(e1,e2); p=perm_p(e1,e2)
    print(f"\n=== {label} ===  n={len(ids)} traders (>=30 pos por mitad)")
    print(f"  EXPECTANCY neta  rho={rho:+.3f}  IC95%[{lo:+.3f},{hi:+.3f}]  p={p:.4f}")
    o=sorted(range(len(ids)), key=lambda i:-e1[i]); k=len(o)//3
    top,bot=o[:k],o[-k:]
    print(f"  tercil TOP en H1 -> mediana H2: {st.median([e2[i] for i in top])*100:+.4f}% / posicion")
    print(f"  tercil BOT en H1 -> mediana H2: {st.median([e2[i] for i in bot])*100:+.4f}% / posicion")
