"""WALK-FORWARD of R-1 as a standalone price rule, 2019-2026.
Rule: go LONG when mom24h>0.55%, mom72h>0.63% and price>MA200h.
Exit after H hours. No overlap. Fees 8 bps round-trip (measured on the real data).
Baseline: random entries at the same frequency and the same holding period.
The question: does it survive outside the one cycle it was derived from (May-Aug 2026)?"""
import csv, statistics as st, datetime as dt, random, collections
random.seed(42)

K=[]
for r in csv.DictReader(open('ohlc/btcusdt_1h_long.csv')):
    K.append((int(r['open_ms']), float(r['close'])))
K.sort()
ts=[x[0] for x in K]; cl=[x[1] for x in K]
n=len(cl)
ma=[None]*n; run=0.0
for i,c in enumerate(cl):
    run+=c
    if i>=200: run-=cl[i-200]
    if i>=199: ma[i]=run/200

FEE=0.0008   # 8 bps round-trip, measured over 96,994 real closes
TH24, TH72 = 0.0055, 0.0063

def fires(i):
    if i<200: return False
    return (cl[i]/cl[i-24]-1)>TH24 and (cl[i]/cl[i-72]-1)>TH72 and cl[i]>ma[i]

def run_strategy(H, signal):
    trades=[]; i=200
    while i < n-H:
        if signal(i):
            r = cl[i+H]/cl[i]-1 - FEE
            trades.append((ts[i], r)); i += H
        else: i += 1
    return trades

def stats(tr, label):
    if not tr: print(f"{label}: no trades"); return None
    r=[x[1] for x in tr]
    eq=1.0; peak=1.0; mdd=0.0
    for x in r:
        eq*=(1+x); peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
    w=[x for x in r if x>0]
    print(f"{label:<26}n={len(r):>5}  mean {st.mean(r)*100:+6.3f}%  median {st.median(r)*100:+6.3f}%"
          f"  wr {len(w)/len(r)*100:5.1f}%  equity x{eq:6.2f}  MDD {mdd*100:5.1f}%")
    return dict(n=len(r), mean=st.mean(r), eq=eq, mdd=mdd)

print("=== Sensitivity to the holding period ===")
for H in (24,48,72,120):
    tr=run_strategy(H, fires)
    stats(tr, f"R-1, hold {H}h")

print("\n=== Baseline: RANDOM entries, same n and same holding (hold 72h) ===")
H=72
real=run_strategy(H, fires)
target=len(real)
sims=[]
for s in range(200):
    random.seed(1000+s)
    idxs=sorted(random.sample(range(200, n-H), min(target, n-H-200)))
    picked=[]; last=-10**9
    for i in idxs:
        if i-last>=H: picked.append(i); last=i
    r=[cl[i+H]/cl[i]-1-FEE for i in picked]
    if r: sims.append(st.mean(r))
print(f"  real rule: mean {st.mean(x[1] for x in real)*100:+.3f}%  (n={len(real)})")
print(f"  random   : mean {st.mean(sims)*100:+.3f}%  p5 {sorted(sims)[10]*100:+.3f}%  p95 {sorted(sims)[189]*100:+.3f}%")
better=sum(1 for s in sims if s>=st.mean(x[1] for x in real))
print(f"  -> the rule beats {200-better}/200 random simulations  (p ≈ {(better+1)/201:.3f})")

print("\n=== BY YEAR (the test that matters: does it survive the 2022 bear?) ===")
byyear=collections.defaultdict(list)
for t,r in real: byyear[dt.datetime.fromtimestamp(t/1000, dt.UTC).year].append(r)
# BTC return per year for comparison
bh=collections.defaultdict(list)
for i in range(1,n): bh[dt.datetime.fromtimestamp(ts[i]/1000, dt.UTC).year].append(cl[i]/cl[i-1]-1)
print(f"{'year':<6}{'n':>5}{'mean%':>9}{'median%':>10}{'wr%':>7}{'equity':>9}{'BTC year%':>10}")
for y in sorted(byyear):
    r=byyear[y]; eq=1.0
    for x in r: eq*=(1+x)
    btc=1.0
    for x in bh[y]: btc*=(1+x)
    w=[x for x in r if x>0]
    print(f"{y:<6}{len(r):>5}{st.mean(r)*100:>9.3f}{st.median(r)*100:>10.3f}"
          f"{len(w)/len(r)*100:>7.1f}{eq:>9.3f}{(btc-1)*100:>10.1f}")
