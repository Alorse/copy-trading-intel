#!/usr/bin/env python3
# scripts/probe_open_positions.py — spike: are open positions public?
import json, urllib.request

BUA = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json',
       'clienttype': 'web', 'Origin': 'https://www.binance.com',
       'Referer': 'https://www.binance.com/en/copy-trading'}
PUA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
       'Origin': 'https://phemex.com', 'Referer': 'https://phemex.com/'}

CANDIDATES_BINANCE = [
    'lead-portfolio/positions', 'lead-portfolio/position-list',
    'lead-portfolio/current-position', 'lead-portfolio/open-positions']
BASE = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/'


def try_binance(pid):
    for c in CANDIDATES_BINANCE:
        for body in ({'portfolioId': pid},
                     {'portfolioId': pid, 'pageNumber': 1, 'pageSize': 20}):
            try:
                req = urllib.request.Request(BASE + c, data=json.dumps(body).encode(),
                                             headers=BUA)
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.load(r)
                print(f"BINANCE {c}: code={d.get('code')} "
                      f"data={'YES' if d.get('data') else 'empty'}")
                if d.get('data'):
                    print(json.dumps(d['data'], ensure_ascii=False)[:800])
            except Exception as e:
                print(f"BINANCE {c}: {e}")


def try_phemex(uid):
    url = (f'https://api.phemex.com/phemex-lb/public/data/position/current/v2'
           f'?userId={uid}')
    try:
        req = urllib.request.Request(url, headers=PUA)
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
        print(f"PHEMEX current/v2: code={d.get('code')}")
        print(json.dumps(d.get('data'), ensure_ascii=False)[:800])
    except Exception as e:
        print(f"PHEMEX current/v2: {e}")


if __name__ == '__main__':
    import sys
    # real ids: take them from data/snapshots/<latest>/binance_list.json and
    # phemex_list.json (or data/binance_portfolios.json / all_traders.json)
    try_binance(sys.argv[1] if len(sys.argv) > 1 else '')
    try_phemex(sys.argv[2] if len(sys.argv) > 2 else '')
