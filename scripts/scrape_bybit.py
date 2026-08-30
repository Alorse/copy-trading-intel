#!/usr/bin/env python3
"""Scrapes Bybit's public copy-trading leader list.

Endpoint (public, GET, no auth — verified 2026-08-29):
  GET {bybit}/x-api/fapi/beehive/public/v1/common/dynamic-leader-list
      ?pageNo=N&pageSize=20&dataDuration=DATA_DURATION_SEVEN_DAY
  result.leaderDetails[]: leaderUserId, leaderMark, nickName, leaderLevel,
    currentFollowerCount, maxFollowerCount, followerYieldE8 (divide by 1e8),
    metricValues[] — pre-formatted strings ("+5.54%") parallel to
    result.metricColumns (ROI, Drawdown, totalAllFollowProfit, WinRate,
    PLRatio, Sharpe). result.totalCount ~7,462 traders, 20/page.

⚠️ Akamai TLS-fingerprints this endpoint: plain urllib/requests get a 403.
`curl_cffi` with impersonate='chrome' is the verified workaround for other
Bybit endpoints, but `dynamic-leader-list` specifically has 403'd even under
curl_cffi from this VPS — it may be intermittent. This script tries curl_cffi
first; if every page 403s, it prints a clear warning and writes 0 rows rather
than failing loudly. For an unattended run that needs data anyway, use
`--input <path>`: a JSONL file with one already-parsed page response per
line, in page order — e.g. captured by running
`fetch(url, {credentials:'include'}).then(r=>r.json())` from a browser tab on
bybit.com and pasting each page's JSON as one line. This script does NOT
drive a browser itself.

Resumable: skips leaderUserIds already present in data/bybit_traders.jsonl.
Usage: python3 scripts/scrape_bybit.py [--pages N] [--input FILE]
"""
import json, time, os, sys

BASE = ('https://www.bybit.eu/x-api/fapi/beehive/public/v1/common/'
        'dynamic-leader-list')
METRIC_KEY_MAP = {
    'ROI': 'roi', 'Drawdown': 'drawdown', 'totalAllFollowProfit': 'total_all_follow_profit',
    'WinRate': 'win_rate', 'PLRatio': 'pl_ratio', 'Sharpe': 'sharpe',
}


def get(url, tries=2):
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print('  ERR curl_cffi not installed - run inside .venv/ (pip install curl_cffi)',
              flush=True)
        return {'retCode': -1}
    for i in range(tries):
        try:
            r = cffi_requests.get(url, impersonate='chrome', timeout=20,
                                   headers={'Accept': 'application/json'})
            if r.status_code == 200:
                return r.json()
            return {'retCode': r.status_code}
        except Exception:
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
    return {'retCode': -1}


def parse_metric(raw):
    """'+5.54%' -> 5.54, '1,234.5' -> 1234.5, '-'/''/None -> None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(',', '').replace('%', '')
    if s.startswith('+'):
        s = s[1:]
    if s in ('', '-', '--', 'N/A'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def row_from_leader(entry, metric_columns, page):
    row = {
        'leaderUserId': entry.get('leaderUserId'), 'nickName': entry.get('nickName'),
        'leaderMark': entry.get('leaderMark'), 'leaderLevel': entry.get('leaderLevel'),
        'currentFollowerCount': entry.get('currentFollowerCount'),
        'maxFollowerCount': entry.get('maxFollowerCount'), 'page': page,
    }
    yield_e8 = entry.get('followerYieldE8')
    row['follower_yield'] = (float(yield_e8) / 1e8) if yield_e8 not in (None, '') else None
    for col, val in zip(metric_columns or [], entry.get('metricValues') or []):
        key = METRIC_KEY_MAP.get(col)
        if key:
            row[key] = parse_metric(val)
    return row


def fetch_leaders(pages, get_fn, page_size=20, data_duration='DATA_DURATION_SEVEN_DAY'):
    rows = {}
    for p in range(1, pages + 1):
        url = f'{BASE}?pageNo={p}&pageSize={page_size}&dataDuration={data_duration}'
        d = get_fn(url)
        result = d.get('result') if isinstance(d, dict) else None
        if not result:
            if p == 1:
                print(f'  WARN bybit listing: page 1 blocked (retCode='
                      f'{d.get("retCode") if isinstance(d, dict) else "?"}) - see the '
                      f'module docstring for the --input fallback', flush=True)
            else:
                print(f'  WARN bybit listing: page {p} failed - universe truncated', flush=True)
            break
        leaders = result.get('leaderDetails') or []
        cols = result.get('metricColumns') or []
        if not leaders:
            break
        for entry in leaders:
            row = row_from_leader(entry, cols, p)
            rows[row['leaderUserId']] = row
        time.sleep(0.6)
    return list(rows.values())


def _done_ids(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                done.add(json.loads(line)['leaderUserId'])
            except Exception:
                pass
    return done


def _replay_get(path):
    lines = [json.loads(l) for l in open(path) if l.strip()]
    it = iter(lines)

    def _get(url):
        try:
            return next(it)
        except StopIteration:
            return {}
    return _get


def run(out_dir='data', pages=20, http_get=None):
    get_fn = http_get or get
    os.makedirs(out_dir, exist_ok=True)
    rows = fetch_leaders(pages, get_fn)

    path = os.path.join(out_dir, 'bybit_traders.jsonl')
    done = _done_ids(path)
    new_rows = [r for r in rows if r['leaderUserId'] not in done]
    out = open(path, 'a')
    for r in new_rows:
        out.write(json.dumps(r, ensure_ascii=False) + '\n')
    out.close()
    return {'fetched': len(rows), 'written': len(new_rows)}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    argv = sys.argv[1:]
    pages = 20
    if '--pages' in argv:
        pages = int(argv[argv.index('--pages') + 1])
    http_get = None
    if '--input' in argv:
        http_get = _replay_get(argv[argv.index('--input') + 1])
    counts = run(pages=pages, http_get=http_get)
    if counts['fetched'] == 0:
        print('DONE: 0 traders — Bybit blocked this run, nothing written. '
              'See the module docstring for the --input fallback.', flush=True)
    else:
        print(f"DONE: {counts['fetched']} fetched, {counts['written']} new rows written", flush=True)


if __name__ == '__main__':
    main()
