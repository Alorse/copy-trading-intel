#!/usr/bin/env python3
"""Scrapes closed positions of Phemex copy-trading traders (public history).

Endpoints:
  - Listing: GET /phemex-lb/public/data/v3/user/recommend  (saved to data/all_traders.json)
  - History: GET /phemex-lb/public/data/position/closed/v2?pageNum&pageSize&userId

Resumable: skips userIds already present in data/positions_all.jsonl.
Usage: python3 scripts/scrape_positions.py  (~6 min, 0.4s sleep between requests)
"""
import json, time, urllib.request, urllib.error, os

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      'Accept': 'application/json', 'Origin': 'https://phemex.com', 'Referer': 'https://phemex.com/'}
BASE = 'https://api.phemex.com/phemex-lb/public/data/position/closed/v2'
# api10.phemex.com returns 403 (CloudFront) — use api.phemex.com


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                return {'error': 'fail'}
            time.sleep(2 * (i + 1))


def fetch_trader_list(pages=7):
    """Refreshes data/all_traders.json from the recommend endpoint."""
    rec_url = 'https://api.phemex.com/phemex-lb/public/data/v3/user/recommend?hideFullyCopied=false&keyword=&pageNum={}&pageSize=50&showChart=false&sortBy=PnlRate30d'
    rows = {}
    for p in range(1, pages + 1):
        d = get(rec_url.format(p))
        if d.get('code') != 0 or not d.get('data'):
            break
        for r in d['data'].get('rows') or []:
            rows[r['userId']] = r
        if len(d['data'].get('rows') or []) < 50:
            break
        time.sleep(0.4)
    out = [{'userId': r['userId'], 'nick': r['nickName'], 'roi30': r['pnlRate30d'],
            'pnl30': r['pnl30d'], 'wr30': r['tradeWinRate30d'], 'aum': r['aum'],
            'followers': r['followerCount'], 'mdd30': r['mdd30d'],
            'showPosition': r['showPosition']} for r in rows.values()]
    return out


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    # refresh the trader listing if it is missing or --refresh is requested
    if not os.path.exists('data/all_traders.json') or '--refresh' in os.sys.argv:
        traders_list = fetch_trader_list()
        os.makedirs('data', exist_ok=True)
        json.dump(traders_list, open('data/all_traders.json', 'w'), indent=1)
        print(f'listing refreshed: {len(traders_list)} traders', flush=True)

    traders = [t for t in json.load(open('data/all_traders.json')) if t['showPosition']]
    done_ids = set()
    if os.path.exists('data/positions_all.jsonl'):
        for line in open('data/positions_all.jsonl'):
            try:
                done_ids.add(json.loads(line)['userId'])
            except Exception:
                pass
    print(f'to scrape: {len(traders)}, already done: {len(done_ids)}', flush=True)

    out = open('data/positions_all.jsonl', 'a')
    fetched = 0
    for t in traders:
        if t['userId'] in done_ids:
            continue
        all_rows, page, empty = [], 1, 0
        while page <= 30 and empty < 2:
            d = get(f"{BASE}?pageNum={page}&pageSize=100&userId={t['userId']}")
            if d.get('code') != 0 or not d.get('data'):
                empty += 1
                page += 1
                continue
            rows = d['data'].get('rows') or []
            all_rows += rows
            if len(rows) < 100:
                break
            page += 1
            time.sleep(0.4)
        rec = {'userId': t['userId'], 'nick': t['nick'], 'n_pos': len(all_rows), 'positions': all_rows}
        out.write(json.dumps(rec) + '\n')
        out.flush()
        fetched += 1
        if fetched % 25 == 0:
            print(f'  {fetched} new traders', flush=True)
        time.sleep(0.4)
    n = sum(1 for _ in open('data/positions_all.jsonl'))
    print(f'DONE: {fetched} new traders | {n} lines total', flush=True)


if __name__ == '__main__':
    main()
