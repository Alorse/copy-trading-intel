"""THE decisive test: does skill persist out-of-sample?
Each trader is ranked on the FIRST half of their history and measured on the SECOND.
With no correlation there is no pattern to copy: it is noise among survivors.
Ranking uses the PRICE return (de-leveraged) so leverage is not rewarded."""
import csv, collections, statistics as st

def load(sym):
    out = collections.defaultdict(list)
    for r in csv.DictReader(open('binance_positions.csv')):
        if r['symbol'] != sym: continue
        c, x = float(r['avg_cost']), float(r['avg_close'])
        if c <= 0 or x <= 0: continue
        m = x / c - 1.0
        p = m if r['side'] == 'Long' else -m
        if abs(p) > 3: continue
        try: t = int(r['closed_ms'])
        except: continue
        out[r['portfolio_id']].append((t, p, float(r['roi']), float(r['leverage'])))
    return out

def spearman(a, b):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i]); rk = [0]*len(v)
        for pos, i in enumerate(s): rk[i] = pos
        return rk
    ra, rb = rank(a), rank(b); n = len(a)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((ra[i]-ma)*(rb[i]-mb) for i in range(n))
    den = (sum((x-ma)**2 for x in ra) * sum((x-mb)**2 for x in rb)) ** 0.5
    return num/den if den else 0.0

for sym in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']:
    D = load(sym)
    h1s, h2s, wr1, wr2 = [], [], [], []
    for tid, v in D.items():
        v.sort()
        if len(v) < 20: continue          # >=10 per half
        k = len(v)//2; a, b = v[:k], v[k:]
        h1s.append(st.mean(x[1] for x in a)); h2s.append(st.mean(x[1] for x in b))
        wr1.append(sum(1 for x in a if x[1] > 0)/len(a))
        wr2.append(sum(1 for x in b if x[1] > 0)/len(b))
    if len(h1s) < 15:
        print(f"{sym}: insufficient sample ({len(h1s)} traders)\n"); continue
    rho_r, rho_w = spearman(h1s, h2s), spearman(wr1, wr2)
    # top vs bottom third, selected on H1, evaluated on H2
    order = sorted(range(len(h1s)), key=lambda i: -h1s[i]); n = max(1, len(order)//3)
    t, b = order[:n], order[-n:]
    print(f"=== {sym} ===  traders with >=20 pos: {len(h1s)}")
    print(f"  Spearman rho  return  H1 -> H2 : {rho_r:+.3f}")
    print(f"  Spearman rho  winrate H1 -> H2 : {rho_w:+.3f}")
    print(f"  Selected TOP on H1  -> median H2 return: {st.median([h2s[i] for i in t])*100:+.3f}%")
    print(f"  Selected BOT on H1  -> median H2 return: {st.median([h2s[i] for i in b])*100:+.3f}%")
    print(f"  (their H1 returns were: top {st.median([h1s[i] for i in t])*100:+.3f}% / bot {st.median([h1s[i] for i in b])*100:+.3f}%)")
    print(f"  winrate H2: top {st.median([wr2[i] for i in t])*100:.1f}%  bot {st.median([wr2[i] for i in b])*100:.1f}%\n")
