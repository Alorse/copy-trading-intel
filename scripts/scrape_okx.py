#!/usr/bin/env python3
"""Scrapes OKX public copy-trading lead-trader ranking (+ per-trader stats).

Endpoints (public, GET, no auth — verified 2026-08-29):
  - Ranking: /api/v5/copytrading/public-lead-traders?instType=SWAP&page=N
    Do NOT pass sortType (any value -> error 51000). ~10 rows/page; `totalPage`
    comes back in data[0].totalPage.
  - Per-trader stats: /api/v5/copytrading/public-stats?uniqueCode=<code>&lastDays=3&instType=SWAP
    `uniqueCode` lives directly on each ranks[] entry (earlier notes said it was
    missing — it isn't). `lastDays` only accepts {1, 2, 3}; any other value ->
    error 51000 "Parameter lastDays error". 3 gives the most history of the three.

data/okx_traders.jsonl is a full refresh each run (one line per ranks[] entry,
like data/all_traders.json for Phemex) — the ranking is cheap to re-fetch in full.
data/okx_trader_stats.jsonl is resumable: skips uniqueCodes already present.
Usage: python3 scripts/scrape_okx.py [--pages N] [--no-stats]
"""
import json, time, urllib.request, urllib.error, os, sys

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept': 'application/json'}
RANK_URL = 'https://www.okx.com/api/v5/copytrading/public-lead-traders?instType=SWAP&page={}'
STATS_URL = 'https://www.okx.com/api/v5/copytrading/public-stats?uniqueCode={}&lastDays=3&instType=SWAP'


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return json.load(e)   # OKX puts {"code":..,"msg":..} in 4xx bodies too
            except Exception:
                pass
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return {'code': 'ERR'}


def fetch_ranking(pages, get_fn):
    """Refreshes the full ranking, capped at `pages`. Stops early on totalPage
    or on an empty/failed page (a mid-pagination failure just truncates, it
    does not corrupt what was already collected)."""
    rows = {}
    total_page = None
    for p in range(1, pages + 1):
        if total_page is not None and p > total_page:
            break
        d = get_fn(RANK_URL.format(p))
        if d.get('code') != '0' or not d.get('data'):
            if p > 1:
                print(f'  WARN okx ranking: page {p} returned {d.get("code")!r} '
                      f'- universe may be truncated', flush=True)
            break
        page = d['data'][0]
        total_page = int(page.get('totalPage') or 0) or total_page
        ranks = page.get('ranks') or []
        if not ranks:
            break
        for r in ranks:
            rows[r['uniqueCode']] = {**r, 'page': p}
        time.sleep(0.5)
    return list(rows.values())


def fetch_stats(unique_code, get_fn):
    """Returns (stats_dict_or_None, ok). ok=False on network/API failure —
    the caller must NOT mark the trader as done in that case."""
    d = get_fn(STATS_URL.format(unique_code))
    if d.get('code') != '0':
        return None, False
    data = d.get('data') or []
    return (data[0] if data else {}), True


def _done_ids(path, key):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                done.add(json.loads(line)[key])
            except Exception:
                pass
    return done


def run(out_dir='data', pages=30, http_get=None, fetch_stats_flag=True):
    get_fn = http_get or get
    os.makedirs(out_dir, exist_ok=True)

    ranking = fetch_ranking(pages, get_fn)
    traders_path = os.path.join(out_dir, 'okx_traders.jsonl')
    with open(traders_path, 'w') as out:
        for r in ranking:
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'okx ranking: {len(ranking)} traders written to {traders_path}', flush=True)

    n_stats = 0
    if fetch_stats_flag:
        stats_path = os.path.join(out_dir, 'okx_trader_stats.jsonl')
        done = _done_ids(stats_path, 'uniqueCode')
        todo = [r for r in ranking if r['uniqueCode'] not in done]
        print(f'okx stats to fetch: {len(todo)} | already done: {len(done)}', flush=True)
        sout = open(stats_path, 'a')
        for r in todo:
            stats, ok = fetch_stats(r['uniqueCode'], get_fn)
            if not ok:
                print(f"  ERR stats {r['uniqueCode']} - will be retried on resume", flush=True)
                time.sleep(0.5)
                continue
            rec = {'uniqueCode': r['uniqueCode'], 'nickName': r.get('nickName'), **(stats or {})}
            sout.write(json.dumps(rec, ensure_ascii=False) + '\n')
            sout.flush()
            n_stats += 1
            if n_stats % 25 == 0:
                print(f'  {n_stats} stats fetched', flush=True)
            time.sleep(0.5)
        sout.close()
    return {'ranking': len(ranking), 'stats': n_stats}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    argv = sys.argv[1:]
    pages = 30
    if '--pages' in argv:
        pages = int(argv[argv.index('--pages') + 1])
    fetch_stats_flag = '--no-stats' not in argv
    counts = run(pages=pages, fetch_stats_flag=fetch_stats_flag)
    print(f"DONE: {counts['ranking']} ranking rows, {counts['stats']} new stats rows", flush=True)


if __name__ == '__main__':
    main()
