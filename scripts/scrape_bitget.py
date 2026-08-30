#!/usr/bin/env python3
"""Scrapes Bitget copy-trading order history — best effort, session-token gated.

Bitget dismantled its public v1 leaderboard (`trace/traderList`) and the v2
official API's copy-trading listing is under maintenance. The only endpoint
verified working (2026-08-29) requires **web session headers that expire**:

  POST https://www.bitget.com/v1/trigger/trace/order/historyList
  body {"languageType":0,"pageNo":1,"pageSize":20,"traderUid":"<uid>"}
  headers: terminalcode, dy-token, custom-token, uhti, deviceid, tm,
           website: copy, terminaltype: 1
  -> code "00000", data.rows/totals/nextFlag (rows: [] with a stale token,
     not an error — Bitget does not signal expiry, it just returns nothing).

There is no public leaderboard endpoint to discover trader UIDs from, so this
script does NOT rank or discover Bitget traders — it fetches order history for
a human-supplied list of UIDs (from a browser profile URL:
/copy-trading/futures-trader-v1/<traderUid>/order). Because it cannot rank
traders, its output is NOT one of the `*_traders.jsonl` files unify.py reads;
Bitget does not contribute rows to the unified pool in Phase 1.

Session config lives in data/bitget_session.json (gitignored — refresh it by
opening bitget.com in a browser, copying the request headers of a live
`historyList` call, and pasting them in):
  {"headers": {"terminalcode": "...", "dy-token": "...", "custom-token": "...",
               "uhti": "...", "deviceid": "...", "tm": "..."},
   "trader_uids": ["..."]}

If the file is missing, or every trader comes back with 0 rows (stale
tokens), this script says so clearly and exits without writing partial data.
Usage: python3 scripts/scrape_bitget.py
"""
import json, time, urllib.request, os, sys

SESSION_PATH = 'data/bitget_session.json'
HIST_URL = 'https://www.bitget.com/v1/trigger/trace/order/historyList'
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Content-Type': 'application/json', 'website': 'copy', 'terminaltype': '1',
    'Origin': 'https://www.bitget.com', 'Referer': 'https://www.bitget.com/copy-trading',
}


def load_session(path=SESSION_PATH):
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def post(url, body, headers, tries=2):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                          headers={**BASE_HEADERS, **headers})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    return {'code': 'ERR'}


def fetch_history(trader_uid, headers, post_fn):
    """Returns (rows, ok). ok=False on a network/API failure; an empty `rows`
    with ok=True (code 00000, totals 0) means the tokens are likely stale —
    Bitget does not distinguish that from a trader with no orders."""
    all_rows, page = [], 1
    while page <= 20:
        d = post_fn(HIST_URL, {'languageType': 0, 'pageNo': page, 'pageSize': 20,
                                'traderUid': trader_uid}, headers)
        if d.get('code') != '00000':
            return all_rows, False
        data = d.get('data') or {}
        rows = data.get('rows') or []
        all_rows += rows
        if not data.get('nextFlag') or len(rows) < 20:
            break
        page += 1
        time.sleep(0.5)
    return all_rows, True


def run(out_dir='data', session=None, http_post=None):
    """Returns a status dict. status['ok'] is False if nothing could be
    fetched (missing session, stale tokens, or every request failing)."""
    post_fn = http_post or post
    session_path = os.path.join(out_dir, 'bitget_session.json')
    session = session if session is not None else load_session(session_path)
    if session is None:
        return {'ok': False, 'reason': f'no session file - see the module docstring '
                                        f'to create {session_path}', 'n_traders': 0}

    headers = session.get('headers') or {}
    uids = session.get('trader_uids') or []
    if not uids:
        return {'ok': False, 'reason': 'session file has no trader_uids', 'n_traders': 0}

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'bitget_orders.jsonl')
    out = open(path, 'w')
    n_total_rows, n_ok = 0, 0
    for uid in uids:
        rows, ok = fetch_history(uid, headers, post_fn)
        if not ok:
            print(f'  ERR order history for {uid} - request failed', flush=True)
            continue
        out.write(json.dumps({'traderUid': uid, 'n_orders': len(rows), 'orders': rows},
                              ensure_ascii=False) + '\n')
        n_ok += 1
        n_total_rows += len(rows)
        time.sleep(0.5)
    out.close()

    if n_total_rows == 0:
        return {'ok': False, 'reason': 'every trader returned 0 orders - session '
                                        'tokens are almost certainly stale, refresh '
                                        f'{SESSION_PATH} from a browser', 'n_traders': n_ok}
    return {'ok': True, 'reason': None, 'n_traders': n_ok, 'n_orders': n_total_rows}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    status = run()
    if not status['ok']:
        print(f"BITGET STUB: {status['reason']}", flush=True)
        sys.exit(1)
    print(f"DONE: {status['n_traders']} traders, {status['n_orders']} orders written "
          f"to data/bitget_orders.jsonl", flush=True)


if __name__ == '__main__':
    main()
