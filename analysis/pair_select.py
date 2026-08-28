"""Seleccion de par con metricas normalizadas (peso igual por trader).
Sin descargas: solo lee los CSV aplanados."""
import csv, collections, statistics as st

B = list(csv.DictReader(open('binance_positions.csv')))

# --- agrupar por (symbol, trader) ---
bysym = collections.defaultdict(lambda: collections.defaultdict(list))
for r in B:
    try: roi = float(r['roi'])
    except: continue
    bysym[r['symbol']][r['portfolio_id']].append((roi, float(r['closing_pnl'])))

rows = []
for sym, traders in bysym.items():
    npos = sum(len(v) for v in traders.values())
    ntr  = len(traders)
    if ntr < 20 or npos < 100:      # muestra minima
        continue
    usd = sum(p for v in traders.values() for _, p in v)
    # metrica normalizada: ROI medio por trader, luego mediana entre traders
    trader_roi = [st.mean(x[0] for x in v) for v in traders.values()]
    trader_usd = {t: sum(p for _, p in v) for t, v in traders.items()}
    med_roi   = st.median(trader_roi)
    pct_win   = sum(1 for x in trader_roi if x > 0) / ntr * 100
    top1      = max(trader_usd.values()) / usd * 100 if usd > 0 else float('nan')
    all_roi   = [x[0] for v in traders.values() for x in v]
    wins      = [x for x in all_roi if x > 0]; losses = [x for x in all_roi if x < 0]
    wr        = len(wins) / len(all_roi) * 100
    payoff    = (st.mean(wins) / abs(st.mean(losses))) if wins and losses else float('nan')
    exp_roi   = st.mean(all_roi)
    rows.append(dict(sym=sym, npos=npos, ntr=ntr, usd=usd, med_roi=med_roi,
                     pct_win=pct_win, top1=top1, wr=wr, payoff=payoff,
                     exp_roi=exp_roi, med_usd=st.median(trader_usd.values())))

rows.sort(key=lambda d: -d['med_roi'])
h = f"{'symbol':<12}{'pos':>7}{'trad':>6}{'USD':>12}{'medROI%':>9}{'%trGana':>9}{'top1%':>8}{'wr%':>7}{'payoff':>8}{'expROI%':>9}"
print(h); print('-'*len(h))
for d in rows[:25]:
    print(f"{d['sym']:<12}{d['npos']:>7}{d['ntr']:>6}{d['usd']:>12,.0f}"
          f"{d['med_roi']*100:>9.2f}{d['pct_win']:>9.1f}{d['top1']:>8.1f}"
          f"{d['wr']:>7.1f}{d['payoff']:>8.2f}{d['exp_roi']*100:>9.2f}")
print('\n--- pares de referencia ---')
for d in rows:
    if d['sym'] in ('BTCUSDT','ETHUSDT','XRPUSDT','SOLUSDT'):
        print(f"{d['sym']:<12}{d['npos']:>7}{d['ntr']:>6}{d['usd']:>12,.0f}"
              f"{d['med_roi']*100:>9.2f}{d['pct_win']:>9.1f}{d['top1']:>8.1f}"
              f"{d['wr']:>7.1f}{d['payoff']:>8.2f}{d['exp_roi']*100:>9.2f}")
print(f"\npares que pasan muestra minima (>=20 traders, >=100 pos): {len(rows)}")
