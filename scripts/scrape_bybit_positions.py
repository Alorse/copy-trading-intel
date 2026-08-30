#!/usr/bin/env python3
"""Scrapes Bybit public copy-trading position history, open positions, trader info,
and yield-trend for the leader universe already captured by `scrape_bybit.py` into
`data/bybit_traders.jsonl`.

⚠️ **Access** (verified live 2026-08-30, see SKILL.md "Endpoints Bybit"): ALL beehive
endpoints 403 via curl/curl_cffi from this VPS (Akamai TLS fingerprinting). They only
work via `fetch()` same-origin from a real browser tab on bybit.com (cloud browser, US
proxy). This module does NOT drive a browser itself — it takes an injectable
`fetch_fn(url) -> dict` (parsed JSON) so it can be:
  - unit tested with a fixture-backed fake (see tests/test_scrape_bybit_positions.py),
  - driven from a `browser-use` heredoc that wraps `js()` calls (see the module-level
    `browser_fetch_snippet` docstring below for the exact pattern used live).

Live `js()` gotcha (discovered 2026-08-30, not previously documented): the harness's
IPC socket read has a hard **5s** timeout, but a `fetch()` through the residential
proxy to Bybit's Akamai-fronted endpoints can take much longer than that to resolve
(the very first fetch in a fresh tab took ~40s; warmed-up fetches ran ~2s). Awaiting
the fetch promise directly inside one `js()` call therefore times out at the harness
level even though the browser-side request would have succeeded. Workaround: fire the
fetch as a detached promise that stashes its result on `window`, then poll a cheap
synchronous `js()` expression (`window.__bf_X.done`) every ~1.2s until it flips —
each poll is fast (no network), so it never hits the 5s ceiling. See `run_via_browser`
docstring for the exact JS.

Endpoints (all under `https://www.bybit.com/x-api/fapi/beehive/`):
  - Closed positions: `public/v1/common/leader-history?leaderMark=<enc>&pageAction=
    next_page&page=N&pageSize=50`. `totalCount`/`hasNext` lie (observed 100/false on
    a page with 0 rows); `cursor` is broken. Paginate `page=N` until a page returns
    0 rows, regardless of what `totalCount`/`hasNext` claim. `pageSize` caps at 50.
    `result.openTradeInfoProtection == 1` (with `data: []`) means the trader hides
    their history — a terminal 'protected' state, not a scrape error. `orderId` is
    the dedup key.
  - Open positions: `public/v1/common/position/list?leaderMark=<enc>`.
  - Trader info: `private/v1/pub-leader/info?leaderMark=<enc>` (works without login
    despite the path).
  - Yield trend: `public/v2/leader/yield-trend?dayCycleType=DAY_CYCLE_TYPE_NINETY_DAY
    |DATA_CYCLE_TYPE_SEVEN_DAY&period=PERIOD_DAY&leaderMark=<enc>`.

Field encoding (verified against real captures 2026-08-30, `tests/fixtures/bybit_*.json`):
  - `leverageE2` / 100 = leverage (e.g. "1000" -> 10x).
  - `orderNetProfitE8` / 1e8 = pnl in USD, **NET** of fees (declared, not yet
    independently reconstructed against gross price return the way OKX/Binance were —
    document this as an open item, don't claim verified).
  - `orderNetProfitRateE4` / 1e4 = ROI as a fraction (e.g. "-15800" -> -1.58 = -158%).
  - `orderCostE8` / 1e8 ~= margin in USD.
  - `startedTimeE3`/`closedTimeE3`/`statisticDate`: despite the "E3" suffix these are
    **already** standard Unix milliseconds (13-digit values, e.g. 1787994194656 ==
    2026-08-29ish) — NOT raw/1000 and NOT raw*1000. Verified by sanity-checking the
    decoded date against the scrape date. No conversion applied beyond `int()`.
  - `side`: "Buy"/"Sell" -> "long"/"short".
  - Fee fields (`openCumExecFeeE8`, `closeCumExecFeeE8`, `cumFundingFeeE8`) and
    `walletBalanceE8`, `last7DaysYieldE8`, etc.: all /1e8.
  - `last7DaysWinRateE4`/`last3WeeksWinRateE4`: /1e4 = fraction (e.g. "10000" -> 1.0).

Output files (data/):
  bybit_positions.jsonl       — one row per CLOSED position, leaderMark/leaderUserId/
                                 nick embedded, dedup key `orderId`.
  bybit_open_positions.jsonl  — one row per OPEN position (position/list), same
                                 embedding.
  bybit_trader_info.jsonl     — one row per trader, raw pub-leader/info + leaderMark.
  bybit_yield_trend.jsonl     — one row per trader per duration (7D/90D), the raw
                                 `yieldTrend[]` series embedded.
  bybit_positions_manifest.jsonl — resumability ledger, one row per leaderMark already
                                 attempted: {leaderMark, leaderUserId, nickName,
                                 n_closed, n_open, status, history_status, ...}.
                                 status in {ok, protected, error}. Terminal states
                                 (ok, protected) are skipped on resume; 'error' is
                                 retried.

Usage (not runnable standalone — see `run_via_browser`'s docstring for the actual
`browser-use` invocation; this module is imported from inside that session):
  from scripts.scrape_bybit_positions import run
  run(leaders, out_dir='data', fetch_fn=my_fetch_fn, sleep_fn=time.sleep,
      traders_cap=300)
"""
import json, os, time, urllib.parse

BASE = 'https://www.bybit.com/x-api/fapi/beehive'
HISTORY_URL = BASE + '/public/v1/common/leader-history'
OPEN_URL = BASE + '/public/v1/common/position/list'
INFO_URL = BASE + '/private/v1/pub-leader/info'
YIELD_URL = BASE + '/public/v2/leader/yield-trend'

PAGE_SIZE = 50
FETCH_SLEEP_S = 3.5        # pacing between fetches within one trader
TRADER_SLEEP_S = 0.5       # pacing between traders
MAX_CONSECUTIVE_ERRORS = 30


def enc_mark(leader_mark):
    return urllib.parse.quote(leader_mark, safe='')


def e(raw, scale, default=0.0):
    """Decodes a Bybit E{n}-suffixed string field: float(raw) / 10**scale."""
    try:
        return float(raw) / (10 ** scale)
    except (TypeError, ValueError):
        return default


def i(raw, default=None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def row_from_history(entry, leader_mark, leader_user_id, nick):
    return {
        'leaderMark': leader_mark, 'leaderUserId': leader_user_id, 'nickName': nick,
        'orderId': entry.get('orderId'), 'symbol': entry.get('symbol'),
        'side': {'Buy': 'long', 'Sell': 'short'}.get(entry.get('side')),
        'side_raw': entry.get('side'),
        'leverage': e(entry.get('leverageE2'), 2),
        'entry_price': _f(entry.get('entryPrice')),
        'close_price': _f(entry.get('closedPrice')),
        'size': _f(entry.get('size')),
        'pnl_usd': e(entry.get('orderNetProfitE8'), 8),
        'roi': e(entry.get('orderNetProfitRateE4'), 4),
        'margin': e(entry.get('orderCostE8'), 8),
        'open_fee': e(entry.get('openCumExecFeeE8'), 8),
        'close_fee': e(entry.get('closeCumExecFeeE8'), 8),
        'funding_fee': e(entry.get('cumFundingFeeE8'), 8),
        'started_ms': i(entry.get('startedTimeE3')),
        'closed_ms': i(entry.get('closedTimeE3')),
        'follower_num': entry.get('followerNum'),
        'full_closed': entry.get('fullClosed'),
        'closed_type': entry.get('closedType'),
        'liq_price': entry.get('liqPrice') or None,
    }


def _f(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def row_from_open_position(entry, leader_mark, leader_user_id, nick):
    return {
        'leaderMark': leader_mark, 'leaderUserId': leader_user_id, 'nickName': nick,
        'symbol': entry.get('symbol'),
        'side': {'Buy': 'long', 'Sell': 'short'}.get(entry.get('side')),
        'side_raw': entry.get('side'),
        'leverage': e(entry.get('leverageE2'), 2),
        'entry_price': _f(entry.get('entryPrice')),
        'size': _f(entry.get('size') or entry.get('sizeX')),
        'margin': e(entry.get('orderCostE8'), 8),
        'stop_loss': _f(entry.get('stopLossPrice'), None),
        'take_profit': _f(entry.get('takeProfitPrice'), None),
    }


def row_from_trader_info(result, leader_mark, nick):
    return {
        'leaderMark': leader_mark, 'nickName': nick,
        'leaderUserId': result.get('leaderUserId'),
        'win_rate_7d': e(result.get('last7DaysWinRateE4'), 4),
        'win_rate_3w': e(result.get('last3WeeksWinRateE4'), 4),
        'yield_7d': e(result.get('last7DaysYieldE8'), 8),
        'follower_yield_7d': e(result.get('last7DaysFollowerYieldE8'), 8),
        'cum_history_transactions_count': i(result.get('cumHistoryTransactionsCount')),
        'cum_follower_count': i(result.get('cumFollowerCount')),
        'locate_days': i(result.get('locateDays')),
        'current_follower_count': i(result.get('currentFollowerCount')),
        'max_follower_count': i(result.get('maxFollowerCount')),
        'profit_count': i(result.get('profitCount')),
        'loss_count': i(result.get('lossCount')),
        'wallet_balance': e(result.get('walletBalanceE8'), 8),
    }


def yield_trend_series(result):
    """Returns [(ts_ms, total_yield_rate), ...] sorted by ts_ms from a yield-trend
    response's raw `yieldTrend[]` — `totalYieldRateE4`/1e4 is the cumulative total
    yield rate, the Bybit analogue of OKX's weekly `pnlRatios[]` used for the
    drawdown screen."""
    out = []
    for pt in result.get('yieldTrend') or []:
        ts = i(pt.get('statisticDate'))
        rate = e(pt.get('totalYieldRateE4'), 4, default=None)
        if ts is not None and rate is not None:
            out.append((ts, rate))
    return sorted(out)


def paginate_history(leader_mark, fetch_fn, sleep_fn=time.sleep, page_size=PAGE_SIZE,
                      sleep_s=FETCH_SLEEP_S, max_pages=1000):
    """Pages leader-history until a page returns 0 rows (per SKILL.md: totalCount/
    hasNext lie, cursor is broken — page=N until empty is the only reliable stop
    condition). Returns (rows, status) where status is 'ok' or 'protected'
    (openTradeInfoProtection==1 on page 1, before any pagination happens)."""
    rows = []
    for page in range(1, max_pages + 1):
        enc = enc_mark(leader_mark)
        url = f'{HISTORY_URL}?leaderMark={enc}&pageAction=next_page&page={page}&pageSize={page_size}'
        d = fetch_fn(url)
        result = (d or {}).get('result') or {}
        if page == 1 and result.get('openTradeInfoProtection') == 1:
            return [], 'protected'
        data = result.get('data') or []
        if not data:
            break
        rows.extend(data)
        if page < max_pages:
            sleep_fn(sleep_s)
    return rows, 'ok'


def scrape_leader(leader, fetch_fn, sleep_fn=time.sleep, sleep_s=FETCH_SLEEP_S):
    """Scrapes one leader's history/open-positions/info/yield-trend(7D+90D).
    Returns a dict with closed/open/info/yield_7d/yield_90d rows and a manifest
    entry, or raises on a network/parse failure (caller marks 'error' and moves on)."""
    leader_mark = leader['leaderMark']
    leader_user_id = leader.get('leaderUserId')
    nick = leader.get('nickName')
    enc = enc_mark(leader_mark)

    hist_rows, hist_status = paginate_history(leader_mark, fetch_fn, sleep_fn, sleep_s=sleep_s)
    closed = [row_from_history(r, leader_mark, leader_user_id, nick) for r in hist_rows]

    sleep_fn(sleep_s)
    open_d = fetch_fn(f'{OPEN_URL}?leaderMark={enc}')
    open_rows = [row_from_open_position(r, leader_mark, leader_user_id, nick)
                 for r in ((open_d or {}).get('result') or {}).get('data') or []]

    sleep_fn(sleep_s)
    info_d = fetch_fn(f'{INFO_URL}?leaderMark={enc}')
    info_row = row_from_trader_info((info_d or {}).get('result') or {}, leader_mark, nick)

    sleep_fn(sleep_s)
    y90_d = fetch_fn(f'{YIELD_URL}?dayCycleType=DAY_CYCLE_TYPE_NINETY_DAY&period=PERIOD_DAY&leaderMark={enc}')
    y90 = yield_trend_series((y90_d or {}).get('result') or {})

    sleep_fn(sleep_s)
    y7_d = fetch_fn(f'{YIELD_URL}?dayCycleType=DAY_CYCLE_TYPE_SEVEN_DAY&period=PERIOD_DAY&leaderMark={enc}')
    y7 = yield_trend_series((y7_d or {}).get('result') or {})

    status = 'protected' if hist_status == 'protected' else 'ok'
    manifest = {
        'leaderMark': leader_mark, 'leaderUserId': leader_user_id, 'nickName': nick,
        'n_closed': len(closed), 'n_open': len(open_rows),
        'status': status, 'history_status': hist_status,
    }
    return {'closed': closed, 'open': open_rows, 'info': info_row,
            'yield_90d': {'leaderMark': leader_mark, 'nickName': nick, 'duration': '90D', 'series': y90},
            'yield_7d': {'leaderMark': leader_mark, 'nickName': nick, 'duration': '7D', 'series': y7},
            'manifest': manifest}


def _manifest_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                rec = json.loads(line)
                if rec.get('status') in ('ok', 'protected'):
                    done.add(rec['leaderMark'])
            except Exception:
                pass
    return done


def load_universe(path='data/bybit_traders.jsonl'):
    leaders, seen = [], set()
    if not os.path.exists(path):
        return leaders
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        mark = r.get('leaderMark')
        if not mark or mark in seen:
            continue
        seen.add(mark)
        leaders.append(r)
    return leaders


def run(leaders, out_dir='data', fetch_fn=None, sleep_fn=time.sleep, traders_cap=None,
        sleep_s=FETCH_SLEEP_S, trader_sleep_s=TRADER_SLEEP_S,
        max_consecutive_errors=MAX_CONSECUTIVE_ERRORS, print_fn=print):
    """Main driver. `fetch_fn(url) -> dict` must be supplied by the caller (the
    browser-use session in production, a fixture-backed fake in tests). Resumable
    via the manifest; 'error' leaders are retried on the next call, 'ok'/'protected'
    are skipped. Flushes each leader's rows before writing its manifest 'done' line
    (Phase 3 rule: a kill between flush and manifest must not duplicate on resume)."""
    if fetch_fn is None:
        raise ValueError('fetch_fn is required (no default HTTP path — see module docstring)')
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, 'bybit_positions_manifest.jsonl')
    done = _manifest_done(manifest_path)
    todo = [ld for ld in leaders if ld['leaderMark'] not in done]
    if traders_cap is not None:
        todo = todo[:traders_cap]
    print_fn(f'bybit positions: {len(todo)} traders to fetch | {len(done)} already done', flush=True)

    closed_out = open(os.path.join(out_dir, 'bybit_positions.jsonl'), 'a')
    open_out = open(os.path.join(out_dir, 'bybit_open_positions.jsonl'), 'a')
    info_out = open(os.path.join(out_dir, 'bybit_trader_info.jsonl'), 'a')
    yield_out = open(os.path.join(out_dir, 'bybit_yield_trend.jsonl'), 'a')
    manifest_out = open(manifest_path, 'a')

    n_done = n_closed = n_open = n_error = 0
    consecutive_errors = 0
    t0 = time.time()
    try:
        for leader in todo:
            mark = leader['leaderMark']
            try:
                result = scrape_leader(leader, fetch_fn, sleep_fn, sleep_s=sleep_s)
            except Exception as exc:
                print_fn(f'  ERR {mark} ({leader.get("nickName")}): {exc} - will retry on resume', flush=True)
                manifest_out.write(json.dumps({'leaderMark': mark,
                                                'leaderUserId': leader.get('leaderUserId'),
                                                'nickName': leader.get('nickName'),
                                                'status': 'error', 'error': str(exc)},
                                               ensure_ascii=False) + '\n')
                manifest_out.flush()
                n_error += 1
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print_fn(f'STOP: {consecutive_errors} consecutive fetch failures', flush=True)
                    break
                sleep_fn(trader_sleep_s)
                continue

            consecutive_errors = 0
            for row in result['closed']:
                closed_out.write(json.dumps(row, ensure_ascii=False) + '\n')
            for row in result['open']:
                open_out.write(json.dumps(row, ensure_ascii=False) + '\n')
            info_out.write(json.dumps(result['info'], ensure_ascii=False) + '\n')
            yield_out.write(json.dumps(result['yield_90d'], ensure_ascii=False) + '\n')
            yield_out.write(json.dumps(result['yield_7d'], ensure_ascii=False) + '\n')
            closed_out.flush(); open_out.flush(); info_out.flush(); yield_out.flush()

            manifest_out.write(json.dumps(result['manifest'], ensure_ascii=False) + '\n')
            manifest_out.flush()

            n_done += 1
            n_closed += len(result['closed'])
            n_open += len(result['open'])
            if n_done % 25 == 0:
                elapsed = time.time() - t0
                eta_min = (elapsed / n_done) * (len(todo) - n_done) / 60
                print_fn(f'  {n_done}/{len(todo)} traders | {n_closed} closed, {n_open} open '
                         f'positions | {n_error} errors | ETA {eta_min:.1f} min', flush=True)
            sleep_fn(trader_sleep_s)
    finally:
        closed_out.close(); open_out.close(); info_out.close(); yield_out.close(); manifest_out.close()

    return {'processed': n_done, 'closed': n_closed, 'open': n_open, 'errors': n_error}


def run_via_browser():
    """Not a callable function — documents the exact `browser-use` invocation used
    live 2026-08-30 to drive this module from a real bybit.com tab. Paste (adapted)
    into a `browser-use <<'PY' ... PY` heredoc with `BU_NAME` set to the daemon
    started by `start_remote_daemon(...)`:

        import sys, json, time
        sys.path.insert(0, '/root/Projects/local/copy-trading-intel')
        from scripts.scrape_bybit_positions import run, load_universe

        def bfetch(url, timeout=60, poll=1.2):
            # Fires the fetch as a detached promise and polls for completion —
            # awaiting the promise directly inside one js() call hits the
            # harness's 5s IPC read timeout on cold/slow requests (see module
            # docstring). window.__bf_<key> avoids collisions across calls.
            key = f"__bf_{abs(hash(url))}"
            js(f'''
                window.{key} = {{done:false, result:null, err:null}};
                fetch({json.dumps(url)}, {{credentials:'include'}}).then(r=>r.json())
                  .then(d=>{{window.{key}.result=d; window.{key}.done=true;}})
                  .catch(e=>{{window.{key}.err=String(e); window.{key}.done=true;}});
                'started'
            ''')
            waited = 0
            while waited < timeout:
                time.sleep(poll); waited += poll
                if js(f'window.{key}.done'):
                    break
            err = js(f'window.{key}.err')
            result = js(f'window.{key}.result') if not err else None
            js(f'delete window.{key}')
            if err:
                raise RuntimeError(err)
            return result

        new_tab('https://www.bybit.com/copyTrade')
        wait_for_load()
        time.sleep(3)
        leaders = load_universe('data/bybit_traders.jsonl')
        counts = run(leaders, out_dir='data', fetch_fn=bfetch, traders_cap=300)
        print('DONE', counts)
    """
    raise NotImplementedError('documentation-only function; see docstring')
