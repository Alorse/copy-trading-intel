#!/usr/bin/env python3
"""Scrape copy-trading publico de Binance Futures (lead portfolios + position history).

Endpoints (POST JSON, sin auth):
  - Lista:    /bapi/futures/v1/friendly/future/copy-trade/home-page/query-list
  - Historial /bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history
    (la variante /public/ devuelve 0 rows — usar /friendly/)

Resumable: salta los portfolioId ya presentes en data/binance_positions.jsonl.
Uso: python3 scripts/scrape_binance.py [--refresh] [--pages N]
"""
import json, time, urllib.request, os, sys

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
      'Content-Type': 'application/json', 'clienttype': 'web',
      'Origin': 'https://www.binance.com', 'Referer': 'https://www.binance.com/en/copy-trading'}
LIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/home-page/query-list'
HIST_URL = 'https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history'


def post(url, body, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return {'code': 'ERR', 'success': False}
            time.sleep(2 * (i + 1))


def fetch_portfolios(pages=10, time_range='90D', data_type='ROI'):
    rows = {}
    for p in range(1, pages + 1):
        body = {'pageNumber': p, 'pageSize': 50, 'timeRange': time_range,
                'dataType': data_type, 'favoriteOnly': False, 'hideFull': True,
                'nickname': '', 'order': 'DESC', 'userAsset': 0, 'portfolioType': 'PUBLIC'}
        d = post(LIST_URL, body)
        if d.get('code') != '000000' or not d.get('data'):
            break
        lst = d['data'].get('list') or []
        for r in lst:
            rows[r['leadPortfolioId']] = r
        if len(lst) < 50:
            break
        time.sleep(0.5)
    return list(rows.values())


def fetch_history(pid):
    all_rows, page = [], 1
    while page <= 40:
        d = post(HIST_URL, {'portfolioId': pid, 'pageNumber': page, 'pageSize': 50})
        if d.get('code') != '000000' or not d.get('data'):
            break
        rows = d['data'].get('list') or []
        all_rows += rows
        if len(rows) < 50:
            break
        page += 1
        time.sleep(0.4)
    return all_rows


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    os.makedirs('data', exist_ok=True)

    if not os.path.exists('data/binance_portfolios.json') or '--refresh' in sys.argv:
        pf = fetch_portfolios()
        json.dump(pf, open('data/binance_portfolios.json', 'w'), indent=1)
        print(f'lista: {len(pf)} portfolios', flush=True)
    portfolios = json.load(open('data/binance_portfolios.json'))

    done = set()
    if os.path.exists('data/binance_positions.jsonl'):
        for line in open('data/binance_positions.jsonl'):
            try:
                done.add(json.loads(line)['portfolioId'])
            except Exception:
                pass
    todo = [p for p in portfolios if p['leadPortfolioId'] not in done]
    print(f'a scrapear: {len(todo)} | ya hechos: {len(done)}', flush=True)

    out = open('data/binance_positions.jsonl', 'a')
    fetched = 0
    for p in todo:
        pid = p['leadPortfolioId']
        rows = fetch_history(pid)
        rec = {'portfolioId': pid, 'nick': p.get('nickname'), 'roi': p.get('roi'),
               'pnl': p.get('pnl'), 'aum': p.get('aum'), 'winRate': p.get('winRate'),
               'mdd': p.get('mdd'), 'n_pos': len(rows), 'positions': rows}
        out.write(json.dumps(rec) + '\n')
        out.flush()
        fetched += 1
        if fetched % 25 == 0:
            print(f'  {fetched} portfolios', flush=True)
        time.sleep(0.5)
    print(f'LISTO: {fetched} nuevos | {sum(1 for _ in open("data/binance_positions.jsonl"))} lineas', flush=True)


if __name__ == '__main__':
    main()
