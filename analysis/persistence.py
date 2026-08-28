"""LA prueba decisiva: la habilidad persiste out-of-sample?
Se ranquea a cada trader con su PRIMERA mitad de historial y se mide su SEGUNDA.
Si no hay correlacion, no hay patron que copiar: es ruido dentro de supervivientes.
Se ranquea por retorno de PRECIO (desapalancado) para no premiar leverage."""
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
        if len(v) < 20: continue          # >=10 por mitad
        k = len(v)//2; a, b = v[:k], v[k:]
        h1s.append(st.mean(x[1] for x in a)); h2s.append(st.mean(x[1] for x in b))
        wr1.append(sum(1 for x in a if x[1] > 0)/len(a))
        wr2.append(sum(1 for x in b if x[1] > 0)/len(b))
    if len(h1s) < 15:
        print(f"{sym}: muestra insuficiente ({len(h1s)} traders)\n"); continue
    rho_r, rho_w = spearman(h1s, h2s), spearman(wr1, wr2)
    # top vs bottom mitad, seleccionados en H1, evaluados en H2
    order = sorted(range(len(h1s)), key=lambda i: -h1s[i]); n = max(1, len(order)//3)
    t, b = order[:n], order[-n:]
    print(f"=== {sym} ===  traders con >=20 pos: {len(h1s)}")
    print(f"  Spearman rho  retorno H1 -> H2 : {rho_r:+.3f}")
    print(f"  Spearman rho  winrate H1 -> H2 : {rho_w:+.3f}")
    print(f"  Seleccionados TOP en H1  -> retorno mediano H2: {st.median([h2s[i] for i in t])*100:+.3f}%")
    print(f"  Seleccionados BOT en H1  -> retorno mediano H2: {st.median([h2s[i] for i in b])*100:+.3f}%")
    print(f"  (sus retornos en H1 fueron: top {st.median([h1s[i] for i in t])*100:+.3f}% / bot {st.median([h1s[i] for i in b])*100:+.3f}%)")
    print(f"  winrate H2: top {st.median([wr2[i] for i in t])*100:.1f}%  bot {st.median([wr2[i] for i in b])*100:.1f}%\n")
