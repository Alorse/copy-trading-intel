#!/usr/bin/env python3
"""Scrapes KuCoin public copy-trading data: leaderboard (with its inline PnL
series), closed positions, open positions (with fees, for the upl guard) and a
headline cross-check snapshot (`leadShow/summary`) folded into the manifest.

⚠️ **Access** (verified live 2026-08-30): all endpoints below answer plain
`curl_cffi` requests with `impersonate='chrome'` from this VPS, with NO auth, NO
cookies, NO session tokens — just Origin + a plausible Referer. This module
drives the HTTP calls itself (no injectable browser fetch_fn needed).

Endpoints (all under `https://www.kucoin.com/_api/ct-copy-trade`):
  - Leaderboard: `POST v1/copyTrading/leaderboard/query?lang=en_US` body
    `{currentPage, pageSize}`. Universe **165** traders live (re-verified
    2026-08-30; SKILL.md's "170" was an earlier, slightly stale estimate).
    ⚠️ **`pageNum` is a silent no-op** — sending `{pageNum: N, pageSize}` always
    re-returns page 1 (`data.currentPage` stays `1` regardless of N; verified by
    requesting pages 1-4 with `pageNum` and getting byte-identical `items`). The
    real parameter is **`currentPage`**. `data.totalNum`/`data.totalPage` ARE
    honest here (unlike Bitget's leaderboard `totals`) — cross-checked: page 4
    of 4 (pageSize 50) returned exactly the remaining 15/165 rows.
  - Closed positions: `GET v2/copyTrading/leadHomePage/positions/history
    ?currentPage=N&pageSize=N&leadConfigId=<id>&lang=en_US` (referer: a
    trader-profile URL — kept per SKILL.md's verified access path, though no
    referer-based 403 was actually observed). Honest pagination: `totalNum`/
    `totalPage` matched exact row counts up to `pageSize=500` in a live probe
    (260/213-row traders each returned in one page at pageSize>=totalNum, no
    silent cap observed at 100, 200 or 500). ⚠️ **No natural per-row id** (unlike
    Bitget's `orderNo` or Bybit's `orderId`) — the dedup key here is
    `(leadConfigId, symbol, startTime, endTime)`, verified unique across a live
    260-row single-trader sample (0 collisions).
  - Open positions: `GET v2/copyTrading/rn/leadHomePage/positions/current
    ?leadConfigId=<id>&lang=en_US` — top-level `pnl`/`pnlRatio` on THIS endpoint
    ARE unrealized (verified against the nested `extendPositionResponse.
    unrealisedPnl`, which matches exactly); `extendPositionResponse` also
    carries `cumulativeTradeFee`/`cumulativeFundingFee`/`liquidationPrice`. This
    is the first exchange in this project where the open-position upl guard has
    real, verified unrealized-PnL data to act on (Bitget/Bybit had none).
  - Summary (headline cross-check, folded into manifest):
    `GET v1/copyTrading/leadShow/summary?leadConfigId=<id>&lang=en_US` — uid,
    introduce, followersSum, leadDays, allowCopyTraders, positionVisibility.
  - `leadShow/pnl/history` (daily PnL+ratio series) was probed live and
    DELIBERATELY NOT scraped: its `ratio` field is a per-day figure that blows
    up to a meaningless multi-quadrillion-fold "equity curve" under naive
    compounding (tested on trader 1004009: cumulative multiplier 6.7e14) — it is
    not a return series that compounds sanely, and the leaderboard's inline
    series below already covers the same ground. See `analysis/kucoin_top5.py`
    for the decided drawdown-screen basis instead.

## The leaderboard's inline PnL series (the KuCoin analogue of OKX's pnlRatios /
## Bitget's cycleData roiRows)

Every leaderboard row inlines FOUR series, live-verified against their own
headline totals (n=200 sampled rows, duplicates included):

  - `totalPnlDate` (30 points) — ⚠️ **KuCoin's own field name is misleading**:
    its LAST point matches `thirtyDayPnl` exactly in 200/200 sampled rows, i.e.
    it is the **30-DAY cumulative $ PnL series**, not a lifetime one. Renamed
    here to `pnl_series_30d` to avoid propagating the exchange's naming bug.
  - `ninetyDayPnlDate` (~89-91 points) — matches `ninetyDayPnl` at its last
    point in 188/200 sampled rows (the ~6% gap is traders whose `daysAsLeader`
    is younger than the series length, a coverage edge, not a semantic
    mismatch). Renamed `pnl_series_90d` — the **longest disclosed cumulative
    series available**, used as the drawdown-screen basis in
    `analysis/kucoin_top5.py`.
  - `sevenDayPnlDate` (7 points) → `pnl_series_7d`.
  - `thirtyDayPnlRatioDate` (30 points, matches `thirtyDayPnlRatio` at its last
    point) → `pnl_ratio_series_30d` — a cumulative FRACTION series (not
    percent), but only covers 30 days; the 90d screen therefore has to use the
    **dollar** series (`pnl_series_90d`), normalized by `leadPrincipal` in
    `analysis/kucoin_top5.py` (documented there as an approximation: dollar
    drawdown over a CURRENT principal snapshot, not a point-in-time equity
    curve — the same class of caveat as Bitget's AUM-based normalization).
  - `totalPnl`/`totalPnlRatio` are genuinely LIFETIME once `daysAsLeader > 90`
    (verified: they diverge from `ninetyDayPnl`/`ninetyDayPnlRatio` for older
    traders, and are identical for traders younger than the 90d window) — used
    as the uniform headline cross-check basis against `sum(pnl)` over every
    closed row scraped.

## The pnl-reconciliation finding (net vs gross)

Measured live over 395 closed rows / 5 traders (2026-08-30): price-derived gross
PnL (`(close-entry)*closeQty*multiplier`, direction-adjusted) vs the API's own
`pnl` field: **median residual -12.0 bps of notional, 91.6% negative** — the
same signature as every other exchange's fee-deducted NET field (Binance -7.85
bps, OKX -6.5 bps). Declared: **`pnl` is NET of fees.**

`pnlRatio` was verified self-consistent: `pnlRatio == pnl / posMargin` to a
median absolute difference of 5.8e-6 (n=395) — i.e. it is the LEVERAGED return
on margin, not a de-leveraged price return. `analysis/kucoin_top5.py` derives
its de-leveraged return basis as `pnlRatio / leverage`.

## The "success:false, code:200" trap

An invalid `leadConfigId` (or a genuinely gone trader) returns HTTP 200 with
`{"success": false, "code": "200", "data": null}` on EVERY endpoint tried
(history, summary, current) — the numeric `code` field alone is USELESS as a
signal (it's always "200" whether the request actually succeeded or not); only
the boolean `success` field distinguishes a real answer from a not-found
trader. `paginate_history`/`fetch_open_positions`/`fetch_summary` all check
`success`, never `code`, for exactly this reason.

Output files (data/):
  kucoin_traders.jsonl        — one row per leaderboard entry (full universe,
                                 series included, no extra network call needed).
  kucoin_positions.jsonl      — one row per CLOSED position, dedup key
                                 `(leadConfigId, symbol, startTime, endTime)`.
  kucoin_open_positions.jsonl — one row per OPEN position (positions/current).
  kucoin_manifest.jsonl       — resumability ledger, one row per leadConfigId
                                 already attempted, with a status per endpoint
                                 (history_status, open_status) plus the
                                 leadShow/summary snapshot folded in as
                                 `summary_*` fields. Overall `status` in
                                 {ok, not_found, error}; only 'error' is
                                 retried on resume.

Usage:
  python3 scripts/scrape_kucoin_positions.py            # all 165 traders, small universe
  python3 scripts/scrape_kucoin_positions.py --traders 50
"""
import argparse, json, os, time

from curl_cffi import requests as cf_requests

BASE = 'https://www.kucoin.com/_api/ct-copy-trade'
LEADERBOARD_URL = BASE + '/v1/copyTrading/leaderboard/query?lang=en_US'
HISTORY_URL = BASE + '/v2/copyTrading/leadHomePage/positions/history'
OPEN_URL = BASE + '/v2/copyTrading/rn/leadHomePage/positions/current'
SUMMARY_URL = BASE + '/v1/copyTrading/leadShow/summary'

LEADERBOARD_REFERER = 'https://www.kucoin.com/copy-trading/leaderboard'


def profile_referer(lead_id):
    return f'https://www.kucoin.com/copy-trading/lead-trader/{lead_id}'


HTTP_HEADERS = {
    'Content-Type': 'application/json',
    'Origin': 'https://www.kucoin.com',
}

PAGE_SIZE_LEADERBOARD = 50
PAGE_SIZE_HISTORY = 100         # verified honest up to 500 (no server-side cap found)
FETCH_SLEEP_S = 0.6              # SKILL.md brief: "polite pacing 0.5-0.8s"
TRADER_SLEEP_S = 0.3
RETRY_BACKOFF_S = 5
MAX_RETRIES = 4
TOP_N_DEFAULT = 0                # 0 = no cap (universe is 165, small by design)
MAX_CONSECUTIVE_ERRORS = 30


def _f(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _i(raw, default=None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _series(raw_list):
    out = []
    for x in raw_list or []:
        v = _f(x, default=None)
        if v is not None:
            out.append(v)
    return out


def make_session():
    return cf_requests.Session(impersonate='chrome')


def make_request_fn(session, sleep_fn=time.sleep, tries=MAX_RETRIES, backoff_s=RETRY_BACKOFF_S,
                     default_timeout_s=20):
    """Returns `request_fn(method, url, params=None, json_body=None, referer=None,
    timeout=None) -> dict|None`. Retries with linear backoff on any
    non-200/unparseable response AND on a transport-level exception (timeout,
    connection reset) raised by `session.get`/`session.post` itself — the
    transport try/except sits INSIDE this loop (the Bitget lesson: catching it
    outside means one slow request discards a trader's worth of already-fetched
    pages and the manifest's 'error' status restarts from page 1 on resume)."""
    def _request(method, url, params=None, json_body=None, referer=None, timeout=None):
        headers = dict(HTTP_HEADERS)
        headers['Referer'] = referer or LEADERBOARD_REFERER
        for attempt in range(tries):
            try:
                if method == 'GET':
                    r = session.get(url, params=params, headers=headers,
                                     timeout=timeout or default_timeout_s)
                else:
                    r = session.post(url, json=json_body, headers=headers,
                                      timeout=timeout or default_timeout_s)
            except Exception:
                if attempt < tries - 1:
                    sleep_fn(backoff_s * (attempt + 1))
                continue
            if r.status_code == 200 and r.content:
                try:
                    return r.json()
                except ValueError:
                    pass
            if attempt < tries - 1:
                sleep_fn(backoff_s * (attempt + 1))
        return None
    return _request


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def row_from_leaderboard(entry):
    return {
        'leadConfigId': entry.get('leadConfigId'),
        'nickName': entry.get('nickName'),
        'exchange': entry.get('exchange'),
        'currency': entry.get('currency'),
        'currentCopyUserCount': _i(entry.get('currentCopyUserCount'), 0),
        'maxCopyUserCount': _i(entry.get('maxCopyUserCount'), 0),
        'leadPrincipal': _f(entry.get('leadPrincipal')),
        'leadAmount': _f(entry.get('leadAmount')),
        'daysAsLeader': _i(entry.get('daysAsLeader'), 0),
        'followerPnl': _f(entry.get('followerPnl')),
        # Lifetime once daysAsLeader>90 (verified); equals the 90d figures for
        # younger traders (see module docstring).
        'totalPnl': _f(entry.get('totalPnl')),
        'totalPnlRatio': _f(entry.get('totalPnlRatio')),
        'ninetyDayPnl': _f(entry.get('ninetyDayPnl')),
        'ninetyDayPnlRatio': _f(entry.get('ninetyDayPnlRatio')),
        'thirtyDayPnl': _f(entry.get('thirtyDayPnl')),
        'thirtyDayPnlRatio': _f(entry.get('thirtyDayPnlRatio')),
        'sevenDayPnl': _f(entry.get('sevenDayPnl')),
        'sevenDayPnlRatio': _f(entry.get('sevenDayPnlRatio')),
        'sevenDayTradeCount': _i(entry.get('sevenDayTradeCount'), 0),
        'thirtyDayTradeCount': _i(entry.get('thirtyDayTradeCount'), 0),
        # Renamed from KuCoin's own (misleading) field names -- see module
        # docstring's "inline PnL series" section.
        'pnl_series_30d': _series(entry.get('totalPnlDate')),
        'pnl_series_90d': _series(entry.get('ninetyDayPnlDate')),
        'pnl_series_7d': _series(entry.get('sevenDayPnlDate')),
        'pnl_ratio_series_30d': _series(entry.get('thirtyDayPnlRatioDate')),
    }


def fetch_leaderboard(request_fn, sleep_fn=time.sleep, page_size=PAGE_SIZE_LEADERBOARD,
                       sleep_s=FETCH_SLEEP_S, max_pages=40):
    """Paginates leaderboard/query. ⚠️ Uses `currentPage`, NOT `pageNum` -- the
    latter is a silent no-op that always re-returns page 1 (see module
    docstring). Stop condition: a page with fewer than `page_size` rows
    (`data.totalNum`/`totalPage` were verified honest here, unlike Bitget's
    leaderboard, but the short-page check is kept as the primary signal anyway,
    matching every sibling scraper's defensive pattern)."""
    rows, seen = [], set()
    for page in range(1, max_pages + 1):
        d = request_fn('POST', LEADERBOARD_URL,
                        json_body={'currentPage': page, 'pageSize': page_size},
                        referer=LEADERBOARD_REFERER)
        if d is None or not d.get('success'):
            raise RuntimeError(f'leaderboard request failed at page {page}: {d}')
        data = d.get('data') or {}
        page_rows = data.get('items') or []
        for entry in page_rows:
            lid = entry.get('leadConfigId')
            if lid is not None and lid not in seen:
                seen.add(lid)
                rows.append(row_from_leaderboard(entry))
        if len(page_rows) < page_size:
            break
        sleep_fn(sleep_s)
    return rows


# ---------------------------------------------------------------------------
# Closed positions (positions/history)
# ---------------------------------------------------------------------------

def row_from_history(entry, lead_id, nick):
    return {
        'leadConfigId': lead_id, 'nickName': nick,
        'symbol': entry.get('symbol'),
        'side': {'Long': 'long', 'Short': 'short'}.get(entry.get('positionDirection')),
        'positionSide': entry.get('positionSide'),
        'leverage': _f(entry.get('leverage')),
        'marginMode': entry.get('marginMode'),
        'pnl': _f(entry.get('pnl')),
        'pnlRatio': _f(entry.get('pnlRatio')),
        'posMargin': _f(entry.get('posMargin')),
        'closeQty': _f(entry.get('closeQty')),
        'avgEntryPrice': _f(entry.get('avgEntryPrice')),
        'avgClosePrice': _f(entry.get('avgClosePrice')),
        'multiplier': _f(entry.get('multiplier'), default=1.0),
        'currency': entry.get('currency'),
        'startTime': _i(entry.get('startTime')),
        'endTime': _i(entry.get('endTime')),
    }


def paginate_history(lead_id, request_fn, sleep_fn=time.sleep, page_size=PAGE_SIZE_HISTORY,
                      sleep_s=FETCH_SLEEP_S, max_pages=200):
    """Paginates positions/history. Stop condition: a page with fewer than
    `page_size` rows OR `currentPage >= totalPage` (both checked; `totalPage`
    was verified honest live, unlike Bitget's leaderboard totals). An invalid
    `leadConfigId` returns `success:false, data:null` (see module docstring's
    "success:false, code:200" trap) -- treated as 'not_found', a terminal state,
    never as an 'error' worth retrying."""
    rows = []
    referer = profile_referer(lead_id)
    for page in range(1, max_pages + 1):
        d = request_fn('GET', HISTORY_URL,
                        params={'currentPage': page, 'pageSize': page_size,
                                'leadConfigId': lead_id, 'lang': 'en_US'},
                        referer=referer)
        if d is None:
            raise RuntimeError(f'positions/history request failed for {lead_id} page {page}')
        if not d.get('success'):
            return [], 'not_found'
        data = d.get('data') or {}
        page_rows = data.get('items') or []
        rows.extend(page_rows)
        total_page = data.get('totalPage') or 0
        if len(page_rows) < page_size or page >= total_page:
            break
        sleep_fn(sleep_s)
    return rows, 'ok'


# ---------------------------------------------------------------------------
# Open positions (positions/current)
# ---------------------------------------------------------------------------

def row_from_open_position(entry, lead_id, nick):
    """`pnl`/`pnlRatio` at the top level of THIS endpoint are UNREALIZED
    (verified live: identical to the nested `extendPositionResponse.
    unrealisedPnl`) -- unlike `positions/history`, where the same field names
    mean net realized PnL. Fee fields only exist nested under
    `extendPositionResponse` (absent from the top-level dict)."""
    ext = entry.get('extendPositionResponse') or {}
    return {
        'leadConfigId': lead_id, 'nickName': nick,
        'symbol': entry.get('symbol'),
        'side': {'Long': 'long', 'Short': 'short'}.get(entry.get('positionDirection')),
        'leverage': _f(entry.get('leverage')),
        'marginMode': entry.get('marginMode'),
        'startTime': _i(entry.get('startTime')),
        'unrealisedPnl': _f(entry.get('pnl')),
        'unrealisedPnlRatio': _f(entry.get('pnlRatio')),
        'realisedPnl': _f(entry.get('realisedPnl')),
        'avgEntryPrice': _f(entry.get('avgEntryPrice')),
        'markPrice': _f(entry.get('markPrice')),
        'posMargin': _f(entry.get('posMargin')),
        'positionQty': _f(entry.get('position')),
        'multiplier': _f(entry.get('multiplier'), default=1.0),
        'liquidationPrice': _f(ext.get('liquidationPrice')),
        'cumulativeTradeFee': _f(ext.get('cumulativeTradeFee')),
        'cumulativeFundingFee': _f(ext.get('cumulativeFundingFee')),
    }


def fetch_open_positions(lead_id, request_fn):
    referer = profile_referer(lead_id)
    d = request_fn('GET', OPEN_URL, params={'leadConfigId': lead_id, 'lang': 'en_US'},
                    referer=referer)
    if d is None:
        raise RuntimeError(f'positions/current request failed for {lead_id}')
    if not d.get('success'):
        return [], 'not_found'
    items = d.get('data') or []
    return items, 'ok'


# ---------------------------------------------------------------------------
# leadShow/summary (headline cross-check, folded into the manifest)
# ---------------------------------------------------------------------------

def fetch_summary(lead_id, request_fn):
    referer = profile_referer(lead_id)
    d = request_fn('GET', SUMMARY_URL, params={'leadConfigId': lead_id, 'lang': 'en_US'},
                    referer=referer)
    if d is None:
        raise RuntimeError(f'leadShow/summary request failed for {lead_id}')
    if not d.get('success'):
        return {}
    return d.get('data') or {}


def summary_fields(data):
    return {
        'uid': data.get('uid'),
        'introduce': data.get('introduce'),
        'followersSum': _i(data.get('followersSum'), 0),
        'followingSum': _i(data.get('followingSum'), 0),
        'alreadyCopyTraders': _i(data.get('alreadyCopyTraders'), 0),
        'allowCopyTraders': _i(data.get('allowCopyTraders'), 0),
        'leadDays': _i(data.get('leadDays'), 0),
        'positionVisibility': data.get('positionVisibility'),
        'copyTraderVisibility': data.get('copyTraderVisibility'),
        'onLeaderboard': data.get('onLeaderboard'),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scrape_trader(trader, request_fn, sleep_fn=time.sleep, sleep_s=FETCH_SLEEP_S):
    """Scrapes one trader's closed history / open positions / summary. Returns a
    dict with closed/open rows and a manifest entry, or raises on a
    network/parse failure (caller marks 'error' and moves on)."""
    lead_id = trader['leadConfigId']
    nick = trader.get('nickName')

    hist_rows, hist_status = paginate_history(lead_id, request_fn, sleep_fn, sleep_s=sleep_s)
    closed = [row_from_history(r, lead_id, nick) for r in hist_rows]
    sleep_fn(sleep_s)

    open_items, open_status = fetch_open_positions(lead_id, request_fn)
    open_rows = [row_from_open_position(r, lead_id, nick) for r in open_items]
    sleep_fn(sleep_s)

    summary_data = fetch_summary(lead_id, request_fn)
    summary = summary_fields(summary_data)

    manifest = {
        'leadConfigId': lead_id, 'nickName': nick,
        'status': 'not_found' if hist_status == 'not_found' else 'ok',
        'history_status': hist_status, 'n_closed': len(closed),
        'open_status': open_status, 'n_open': len(open_rows),
        **{f'summary_{k}': v for k, v in summary.items()},
    }
    return {'closed': closed, 'open': open_rows, 'manifest': manifest}


def _manifest_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                rec = json.loads(line)
                if rec.get('status') in ('ok', 'not_found'):
                    done.add(rec['leadConfigId'])
            except Exception:
                pass
    return done


def load_universe(path='data/kucoin_traders.jsonl'):
    traders, seen = [], set()
    if not os.path.exists(path):
        return traders
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        lid = r.get('leadConfigId')
        if lid is None or lid in seen:
            continue
        seen.add(lid)
        traders.append(r)
    return traders


def run(traders, out_dir='data', request_fn=None, sleep_fn=time.sleep, sleep_s=FETCH_SLEEP_S,
        trader_sleep_s=TRADER_SLEEP_S, max_consecutive_errors=MAX_CONSECUTIVE_ERRORS,
        print_fn=print):
    """Main driver, resumable via the manifest ('ok'/'not_found' are terminal and
    skipped on resume; 'error' is retried). Flushes each trader's rows before
    writing its manifest 'done' line (a kill between flush and manifest must not
    duplicate rows on resume -- dedup on read by `(leadConfigId, symbol,
    startTime, endTime)` happens in `analysis/kucoin_flatten.py`)."""
    if request_fn is None:
        raise ValueError('request_fn is required')
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, 'kucoin_manifest.jsonl')
    done = _manifest_done(manifest_path)
    todo = [t for t in traders if t['leadConfigId'] not in done]
    print_fn(f'kucoin positions: {len(todo)} traders to fetch | {len(done)} already done', flush=True)

    closed_out = open(os.path.join(out_dir, 'kucoin_positions.jsonl'), 'a')
    open_out = open(os.path.join(out_dir, 'kucoin_open_positions.jsonl'), 'a')
    manifest_out = open(manifest_path, 'a')

    n_done = n_closed = n_open = n_error = n_not_found = 0
    consecutive_errors = 0
    t0 = time.time()
    try:
        for trader in todo:
            lid = trader['leadConfigId']
            try:
                result = scrape_trader(trader, request_fn, sleep_fn, sleep_s=sleep_s)
            except Exception as exc:
                print_fn(f'  ERR {lid} ({trader.get("nickName")}): {exc} - will retry on resume', flush=True)
                manifest_out.write(json.dumps({'leadConfigId': lid, 'nickName': trader.get('nickName'),
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
            closed_out.flush(); open_out.flush()

            manifest_out.write(json.dumps(result['manifest'], ensure_ascii=False) + '\n')
            manifest_out.flush()

            n_done += 1
            n_closed += len(result['closed'])
            n_open += len(result['open'])
            if result['manifest']['status'] == 'not_found':
                n_not_found += 1
            if n_done % 25 == 0:
                elapsed = time.time() - t0
                eta_min = (elapsed / n_done) * (len(todo) - n_done) / 60
                print_fn(f'  {n_done}/{len(todo)} traders | {n_closed} closed, {n_open} open '
                         f'positions | {n_not_found} not_found | {n_error} errors | '
                         f'ETA {eta_min:.1f} min', flush=True)
            sleep_fn(trader_sleep_s)
    finally:
        closed_out.close(); open_out.close(); manifest_out.close()

    return {'processed': n_done, 'closed': n_closed, 'open': n_open,
            'not_found': n_not_found, 'errors': n_error}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--traders', type=int, default=TOP_N_DEFAULT,
                     help=f'cap on traders to scrape positions for, by follower count '
                          f'descending (default {TOP_N_DEFAULT or "no cap"})')
    ap.add_argument('--out-dir', default='data')
    ap.add_argument('--refresh-leaderboard', action='store_true',
                     help='re-fetch the leaderboard even if data/kucoin_traders.jsonl exists')
    args = ap.parse_args()

    session = make_session()
    request_fn = make_request_fn(session)

    traders_path = os.path.join(args.out_dir, 'kucoin_traders.jsonl')
    if args.refresh_leaderboard or not os.path.exists(traders_path):
        print('Fetching leaderboard...', flush=True)
        rows = fetch_leaderboard(request_fn)
        os.makedirs(args.out_dir, exist_ok=True)
        with open(traders_path, 'w') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'universe: {len(rows)} traders scraped', flush=True)

    traders = load_universe(traders_path)
    traders_sorted = sorted(traders, key=lambda t: t.get('currentCopyUserCount') or 0, reverse=True)
    todo_universe = traders_sorted[:args.traders] if args.traders else traders_sorted
    print(f'scraping positions for {len(todo_universe)} of {len(traders_sorted)} traders', flush=True)

    counts = run(todo_universe, out_dir=args.out_dir, request_fn=request_fn)
    print('DONE', counts, flush=True)


if __name__ == '__main__':
    main()
