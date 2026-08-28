"""R6 hecho bien: Spearman con rangos promediados en empates, test de permutacion
para significancia, e IC bootstrap. Ataca L2 (potencia) de frente.
Ademas: split por CALENDARIO ademas de por mediana del trader (ataca L1)."""
import csv, collections, statistics as st, random, datetime as dt
random.seed(42)

def avg_rank(v):
    """Rangos con promedio en empates (Spearman correcto)."""
    idx = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0]*len(v); i = 0
    while i < len(idx):
        j = i
        while j+1 < len(idx) and v[idx[j+1]] == v[idx[i]]: j += 1
        mean_rank = (i + j) / 2.0
        for k in range(i, j+1): r[idx[k]] = mean_rank
        i = j+1
    return r

def pearson(a, b):
    n=len(a); ma,mb=st.mean(a),st.mean(b)
    num=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    den=(sum((x-ma)**2 for x in a)*sum((x-mb)**2 for x in b))**0.5
    return num/den if den else 0.0

def spearman(a, b): return pearson(avg_rank(a), avg_rank(b))

def perm_p(a, b, n=10000):
    """p-value de dos colas por permutacion. No asume normalidad."""
    obs = abs(spearman(a, b)); bb = list(b); cnt = 0
    for _ in range(n):
        random.shuffle(bb)
        if abs(spearman(a, bb)) >= obs: cnt += 1
    return (cnt+1)/(n+1)

def boot_ci(a, b, n=2000):
    N=len(a); out=[]
    for _ in range(n):
        s=[random.randrange(N) for _ in range(N)]
        out.append(spearman([a[i] for i in s], [b[i] for i in s]))
    out.sort()
    return out[int(.025*n)], out[int(.975*n)]

# ---- carga ----
D = collections.defaultdict(list)
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol'] != 'BTCUSDT': continue
    c,x = float(r['avg_cost']), float(r['avg_close'])
    if c<=0 or x<=0: continue
    m = x/c-1.0
    p = m if r['side']=='Long' else -m
    if abs(p)>3: continue
    try: o=int(r['opened_ms'])
    except: continue
    D[r['portfolio_id']].append((o, p))

def prof(P):
    w=[x for x in P if x>0]; l=[x for x in P if x<0]
    if not w or not l: return None
    return len(w)/len(P), st.mean(w)/abs(st.mean(l)), st.mean(P)

def run(label, splitter, minpos):
    W1,W2,P1,P2,E1,E2 = [],[],[],[],[],[]
    for tid,v in D.items():
        v.sort()                                   # por APERTURA (corrige el bug de ordenar por cierre)
        a,b = splitter(v)
        if len(a) < minpos or len(b) < minpos: continue
        ra,rb = prof([x[1] for x in a]), prof([x[1] for x in b])
        if not ra or not rb: continue
        W1.append(ra[0]); W2.append(rb[0]); P1.append(ra[1]); P2.append(rb[1]); E1.append(ra[2]); E2.append(rb[2])
    if len(E1) < 12:
        print(f"{label}: muestra insuficiente (n={len(E1)})\n"); return
    print(f"=== {label} ===  n={len(E1)} traders (>={minpos} pos por mitad)")
    print(f"{'metrica':<12}{'rho':>8}{'IC95%':>20}{'p (perm)':>11}")
    print('-'*51)
    for nm,(a,b) in [('win rate',(W1,W2)),('payoff',(P1,P2)),('EXPECTANCY',(E1,E2))]:
        rho=spearman(a,b); lo,hi=boot_ci(a,b); p=perm_p(a,b)
        print(f"{nm:<12}{rho:>+8.3f}   [{lo:>+6.3f}, {hi:>+6.3f}]{p:>11.4f}")
    print()

# A) split por la mediana del propio historial (como el original, pero ordenado por apertura)
run('split por historial del trader', lambda v: (v[:len(v)//2], v[len(v)//2:]), 10)

# B) split por CALENDARIO — mismo periodo para todos (ataca L1: confound de regimen)
allt = sorted(x[0] for v in D.values() for x in v); CUT = allt[len(allt)//2]
print(f"[corte calendario: {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}]")
run('split por CALENDARIO', lambda v: ([x for x in v if x[0]<CUT], [x for x in v if x[0]>=CUT]), 10)

# C) potencia: con n traders, que rho se detectaria al 80%?
import math
for n in (30, 59, 100, 200):
    se = 1/math.sqrt(n-3)
    print(f"n={n:>4}  SE(z)≈{se:.3f}  rho minimo detectable al 80% de potencia ≈ {math.tanh(2.8*se):.3f}")
