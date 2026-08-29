"""Now that trader selection IS valid (pooled rho +0.36):
1) rank traders by NET multi-pair expectancy in period 1
2) look at how they trade BTC in period 2 (pure out-of-sample)
3) contrast against the rest -> that is where the soft rules come from"""
import csv, statistics as st, collections, datetime as dt

rows=[]
for r in csv.DictReader(open('binance_positions.csv')):
    try:
        o=int(r['opened_ms']); notio=float(r['notional']); pnl=float(r['closing_pnl']); d=float(r['dur_h'])
    except: continue
    if notio<=0: continue
    net=pnl/notio
    if abs(net)>3: continue
    rows.append(dict(tid=r['portfolio_id'], nick=r['nick'], sym=r['symbol'], side=r['side'],
                     o=o, net=net, dur=d, lev=float(r['leverage']), iso=r['isolated'],
                     notio=notio))
ts=sorted(x['o'] for x in rows); CUT=ts[len(ts)//2]
print(f"cut: {dt.datetime.fromtimestamp(CUT/1000, dt.UTC):%Y-%m-%d}")

# 1) multi-pair score in P1
p1=collections.defaultdict(list)
for x in rows:
    if x['o']<CUT: p1[x['tid']].append(x['net'])
score={t:st.mean(v) for t,v in p1.items() if len(v)>=30}
o=sorted(score,key=lambda t:-score[t]); k=len(o)//3
ELITE=set(o[:k]); REST=set(o[-k:])
print(f"rankable traders: {len(o)} | elite={len(ELITE)} rest={len(REST)}\n")

# 2) their BTC in P2
def btc_p2(g):
    return [x for x in rows if x['o']>=CUT and x['sym']=='BTCUSDT' and x['tid'] in g]
E,R = btc_p2(ELITE), btc_p2(REST)
def durb(d): return ('<1h' if d<1 else '1-4h' if d<4 else '4-12h' if d<12 else '12-24h' if d<24
                     else '1-3d' if d<72 else '>3d')

for lab,G in (('ELITE',E),('REST',R)):
    if not G: print(lab,'no BTC positions in P2'); continue
    w=[x['net'] for x in G if x['net']>0]; l=[x['net'] for x in G if x['net']<0]
    print(f"=== {lab} on BTCUSDT, period 2 (out-of-sample) ===  n={len(G)}  traders={len(set(x['tid'] for x in G))}")
    print(f"  mean net return/pos      {st.mean(x['net'] for x in G)*100:+7.3f}%")
    print(f"  median net return/pos    {st.median(x['net'] for x in G)*100:+7.3f}%")
    print(f"  win rate                 {len(w)/len(G)*100:7.1f}%")
    print(f"  payoff                   {st.mean(w)/abs(st.mean(l)):7.2f}")
    print(f"  median duration          {st.median(x['dur'] for x in G):7.1f}h")
    print(f"  median leverage          {st.median(x['lev'] for x in G):7.0f}x")
    print(f"  %long                    {sum(1 for x in G if x['side']=='Long')/len(G)*100:7.1f}%")
    print(f"  %cross                   {sum(1 for x in G if x['iso']=='Cross')/len(G)*100:7.1f}%")
    d=collections.Counter(durb(x['dur']) for x in G)
    tot=sum(d.values())
    print("  duration mix:", {kk: f"{v/tot*100:.0f}%" for kk,v in sorted(d.items(), key=lambda z:-z[1])})
    print()
