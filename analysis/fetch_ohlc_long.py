"""Long history of the BTCUSDT perpetual for the walk-forward.
Covers 2019-09 (the perp's start) to today: several cycles, including the 2022 bear."""
import json, time, csv, sys, urllib.request

URL='https://fapi.binance.com/fapi/v1/klines'
START=1567900800000   # 2019-09-08
END  =1787788800000   # 2026-08-26

rows=[]; cur=START
while cur < END:
    q=f'{URL}?symbol=BTCUSDT&interval=1h&startTime={cur}&limit=1500'
    req=urllib.request.Request(q, headers={'User-Agent':'Mozilla/5.0'})
    for a in range(4):
        try:
            d=json.load(urllib.request.urlopen(req, timeout=30)); break
        except Exception as e:
            if a==3: raise
            print('retry', e, file=sys.stderr); time.sleep(2*(a+1))
    if not d: break
    rows.extend(d)
    nxt=d[-1][0]+1
    if nxt<=cur: break
    cur=nxt
    if len(d)<1500: break
    time.sleep(0.2)

seen=set(); out=[]
for r in rows:
    if r[0] in seen or r[0]>=END: continue
    seen.add(r[0]); out.append(r)
out.sort()
with open('ohlc/btcusdt_1h_long.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['open_ms','open','high','low','close','volume'])
    for r in out: w.writerow(r[:6])
import datetime as dt
f_=lambda ms: dt.datetime.fromtimestamp(ms/1000, dt.UTC).strftime('%Y-%m-%d')
print(f"{len(out)} candles | {f_(out[0][0])} -> {f_(out[-1][0])}")
