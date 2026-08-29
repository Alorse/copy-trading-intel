"""Downloads BTCUSDT perpetual klines (Binance futures, public) for the period
the positions cover. The only authorised download; nothing from scripts/."""
import json, time, csv, sys, os
import urllib.request

SYM   = 'BTCUSDT'
START = 1738162800000   # 2025-01-29, one day before the first opening
END   = 1787774400000   # 2026-08-26, one day after the last close
URL   = 'https://fapi.binance.com/fapi/v1/klines'

def fetch(interval, out):
    rows, cur = [], START
    while cur < END:
        q = f'{URL}?symbol={SYM}&interval={interval}&startTime={cur}&limit=1500'
        req = urllib.request.Request(q, headers={'User-Agent': 'Mozilla/5.0'})
        for attempt in range(4):
            try:
                data = json.load(urllib.request.urlopen(req, timeout=30)); break
            except Exception as e:
                if attempt == 3: raise
                print('  retry', e, file=sys.stderr); time.sleep(2 * (attempt + 1))
        if not data: break
        rows.extend(data)
        nxt = data[-1][0] + 1
        if nxt <= cur: break
        cur = nxt
        if len(data) < 1500: break
        time.sleep(0.25)
    seen, ded = set(), []
    for r in rows:
        if r[0] in seen or r[0] >= END: continue
        seen.add(r[0]); ded.append(r)
    ded.sort()
    with open(out, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['open_ms','open','high','low','close','volume','close_ms',
                    'quote_vol','trades','taker_buy_base','taker_buy_quote'])
        for r in ded: w.writerow(r[:11])
    print(f'{interval}: {len(ded)} candles -> {out}')
    return len(ded)

for iv, fn in [('1h','ohlc/btcusdt_1h.csv'), ('15m','ohlc/btcusdt_15m.csv'), ('1d','ohlc/btcusdt_1d.csv')]:
    fetch(iv, fn)
