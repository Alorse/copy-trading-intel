"""Style or skill?
 A) winrate vs payoff across traders -> a negative correlation means a STYLE axis.
 B) does EXPECTANCY persist (the only thing that pays) or only the winrate?
 C) is there any trace of partial closes (closedVolume vs maxOpenInterest)?"""
import csv, collections, statistics as st

SYM = 'BTCUSDT'
D = collections.defaultdict(list)
partial = tot = 0
for r in csv.DictReader(open('binance_positions.csv')):
    if r['symbol'] != SYM: continue
    c, x = float(r['avg_cost']), float(r['avg_close'])
    if c <= 0 or x <= 0: continue
    m = x/c - 1.0
    p = m if r['side'] == 'Long' else -m
    if abs(p) > 3: continue
    oi, cv = float(r['max_oi']), float(r['closed_volume'])
    tot += 1
    if oi > 0 and cv > 0 and abs(cv-oi)/oi > 0.02: partial += 1
    try: t = int(r['closed_ms'])
    except: continue
    D[r['portfolio_id']].append((t, p))

def pearson(a,b):
    n=len(a); ma,mb=st.mean(a),st.mean(b)
    num=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    den=(sum((x-ma)**2 for x in a)*sum((x-mb)**2 for x in b))**0.5
    return num/den if den else 0.0
def spear(a,b):
    def rk(v):
        s=sorted(range(len(v)),key=lambda i:v[i]); r=[0]*len(v)
        for p_,i in enumerate(s): r[i]=p_
        return r
    return pearson(rk(a),rk(b))

def prof(P):
    w=[x for x in P if x>0]; l=[x for x in P if x<0]
    if not w or not l: return None
    wr=len(w)/len(P)
    return wr, st.mean(w)/abs(st.mean(l)), st.mean(P)   # winrate, payoff, expectancy

print(f"C) rows with a partial close (|closedVol-maxOI|>2%): {partial}/{tot} = {partial/tot*100:.1f}%\n")

WR,PO,EX = [],[],[]
for tid,v in D.items():
    if len(v) < 20: continue
    r = prof([x[1] for x in v])
    if r: WR.append(r[0]); PO.append(r[1]); EX.append(r[2])
print(f"A) traders (>=20 pos): {len(WR)}")
print(f"   corr(winrate, payoff)     Pearson {pearson(WR,PO):+.3f}  Spearman {spear(WR,PO):+.3f}")
print(f"   corr(winrate, expectancy) Pearson {pearson(WR,EX):+.3f}  Spearman {spear(WR,EX):+.3f}")
print(f"   corr(payoff , expectancy) Pearson {pearson(PO,EX):+.3f}  Spearman {spear(PO,EX):+.3f}\n")

e1,e2,w1,w2,p1,p2=[],[],[],[],[],[]
for tid,v in D.items():
    v.sort()
    if len(v) < 30: continue
    k=len(v)//2
    a,b = prof([x[1] for x in v[:k]]), prof([x[1] for x in v[k:]])
    if not a or not b: continue
    w1.append(a[0]); w2.append(b[0]); p1.append(a[1]); p2.append(b[1]); e1.append(a[2]); e2.append(b[2])
print(f"B) H1->H2 persistence (traders with >=30 pos: {len(e1)})")
print(f"   winrate    rho {spear(w1,w2):+.3f}")
print(f"   payoff     rho {spear(p1,p2):+.3f}")
print(f"   EXPECTANCY rho {spear(e1,e2):+.3f}   <-- the only thing that pays")
