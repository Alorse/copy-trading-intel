#!/usr/bin/env python3
"""Scrapes Bitget public copy-trading data: leaderboard, closed positions, open
positions and the 90-day drawdown/MDD series (`cycleData`), plus a headline
cross-check snapshot (`traderDetailPageV2`) folded into the manifest.

⚠️ **Access** (verified live 2026-08-30 by Ramona + GLM, re-verified here): unlike
Bybit (Akamai TLS-fingerprint blocked, browser-only) or Bitget's own OLD v1
session-token endpoints (`scripts/scrape_bitget.py`, 2026-08-29, now superseded),
ALL of the endpoints below answer plain `curl_cffi` requests with
`impersonate='chrome'` from this VPS, with NO auth, NO cookies, NO session tokens
— only a handful of static headers. This module drives the HTTP calls itself
(no injectable browser fetch_fn needed, unlike `scrape_bybit_positions.py`).

Endpoints (all under `https://www.bitget.com/v1/trigger`):
  - Leaderboard: `POST public/uta/traderView` body `{pageSize,pageNo,languageType:0}`.
    Universe **1,488** traders (live `maxShowSizes`, re-verified 2026-08-30 — SKILL.md's
    ~1,489 was a prior snapshot). ⚠️ `data.totals` LIES: it echoes the page size (50),
    not the universe count — use `maxShowSizes`. `pageSize` is capped at 50 server-side.
    Stop condition: a page returning fewer than `pageSize` rows (safe even if
    `maxShowSizes` itself were ever wrong, since it's cross-checked against actual
    row count, not trusted alone).
  - Closed positions: `POST trace/order/historyList` body
    `{languageType:0,pageNo,pageSize,traderUid}`. `pageSize` is capped at **20**
    server-side regardless of the requested value (verified: requesting 100 still
    returns 20 rows/page). ⚠️ **No cap on total depth found**: the busiest trader
    probed live (TrendTerm, `totals=734`) paginated cleanly to exactly 734/734 rows
    across 37 pages — unlike OKX's 100-row cap or Bybit's ~100-row cap, `totals`
    here appears honest at the per-trader level (only the *leaderboard's* `totals`
    lies). Still probe the busiest trader in every fresh run before trusting this.
  - Open positions: `POST trace/order/currentList` body
    `{languageType:0,pageNo,pageSize,traderUid}`. Response `code` is `"30066"`
    ("open position protection") for traders hiding their open book — a terminal
    state, not an error. Verified live: **14/40 (35%)** of a leaderboard sample were
    protected on THIS endpoint while their `historyList` (closed positions) stayed
    fully visible — the two protections are independent, unlike Bybit where one flag
    covers both open and closed. No unrealized-PnL field was found on any live
    `currentList` item (fields present: openAvgPrice/openDealCount/openMarginCount/
    openLevel/openTime — all *entry*-side; `achievedProfits` on open rows was 0.00 in
    every live sample and does not track money PnL) — same blind spot as Bybit's
    `position/list`, documented the same way: `has_upl_data` stays False for the
    entire universe until a real field is found.
  - 90-day drawdown series + native MDD: `POST trace/public/cycleData` body
    `{triggerUserId:<traderUid>,cycleTime:90}`. `roiRows.rows`/`pnlRows.rows`/
    `netProfitKlineDTO.rows` are 1-point-per-day series (`dataTime` ms, `amount`
    string). `statisticsDTO.maxRetracement` is Bitget's own MDD (NOT peak-to-trough
    of the published `roiRows` — an internal formula, used here as the primary MDD,
    cross-checked against a computed peak-to-trough in `analysis/bitget_top5.py`).
    Verified live: `roiRows.rows[-1]['amount'] == statisticsDTO['profitRate']` exactly
    (both "-3.43" for TrendTerm, 90d window) — the SKILL.md claim reconfirmed.
  - Headline cross-check: `POST trace/public/traderDetailPageV2` body
    `{languageType:0,traderUid}` — `aum`, `followerCount`, `distributeRatio` (profit
    share %), `followProfits` (day7/30/90/180, self-reported net follower profit —
    the uniform cross-check basis this pipeline's TOP5 doc uses), and `itemVoList`
    (pre-formatted ROI/MDD/win-rate, same shape as the leaderboard row's).

## The pnl-reconciliation finding (the "Bybit lesson", replicated here)

Bitget's closed-position rows carry BOTH price fields (`openAvgPrice`/
`closeAvgPrice`, per-lot — NOT a shared/aggregate value across a scaled position's
order rows, unlike Bybit) and a self-reported `returnRate` (%) + `netProfit` (net
USD). Measured live over 455 rows / 50 traders (2026-08-30):

  - **Price-derived de-leveraged return disagrees in SIGN with `netProfit` on
    10.1% of rows** (46/455) — close enough to Bybit's ~16% to be the same failure
    mode, not noise. Traced to one concrete case: a single large close (a stop or a
    manual flatten) fills across multiple resting entry orders of one scaled
    position; Bitget records each fill as its own row with its own real
    `openAvgPrice`, a SHARED `closeAvgPrice` (same batch, same ms), but the
    `netProfit` split across those rows does not reduce to
    `(close-open)*size*direction + fees` per row — the exact allocation logic isn't
    disclosed, and fees alone don't explain the residual (verified: for two rows
    inspected line-by-line, price-implied PnL minus `netProfit` was $2.7 on a $9.68
    margin row (28% of margin) even after subtracting both fees).
  - **`returnRate / openLevel` (self-consistent, verified against `netProfit /
    openMarginCount`)**: median absolute deviation **0.8 percentage points**, p90
    **6.0pp**, 79% of rows agree within 2pp (n=455). Weaker than Bybit's 0.02%
    median / 0.16% p90 — Bitget's `returnRate` is visibly noisier — but an order of
    magnitude tighter than the price-derived basis's 10% sign-flip rate, and it
    already bakes in direction via `netProfit`'s sign the same way Bybit's did.
  - **Decision, following the Bybit precedent**: `analysis/bitget_flatten.py` /
    `analysis/bitget_top5.py` use `pr = return_rate / open_level` as the de-leveraged
    return basis, NOT `(close_price/open_price - 1)`. `open_avg_price`/
    `close_avg_price` are kept in the CSV for reference only.
  - `openLevel` semantics verified: `openMarginCount * openLevel ≈
    openAvgPrice * openDealCount` (notional) held exactly on every inspected row
    (e.g. margin=9.68, lev=35, entry=80696.8, size=0.0042 -> notional=338.9,
    338.9/9.68=35.0) — `openLevel` is genuine leverage, not some other multiplier.

## Position-vs-order granularity (the other Bybit lesson)

Bitget's `historyList` is **one row per order/fill**, not one row per logical
position — confirmed live: a single scaled BTCUSDT short showed 9 rows sharing an
identical `positionAverage` (the position's running weighted-average entry, constant
across the batch) and `closeTime` within ~1ms of each other, each with its own real
`openAvgPrice`/`netProfit`. `analysis/bitget_top5.py`'s concentration guard
therefore aggregates to position level using the group key
`(trader_uid, symbol_id, close_time // 1000)` (closeTime rounded to the nearest
second — observed intra-batch jitter was ≤1ms, a 1-second bucket is generous
headroom without merging genuinely distinct closes of the same symbol a second
apart, which the eyeballed data never showed).

Output files (data/):
  bitget_traders.jsonl        — one row per leaderboard entry (full universe).
  bitget_positions.jsonl      — one row per CLOSED order/fill, dedup key `order_no`.
  bitget_open_positions.jsonl — one row per OPEN order/fill (currentList).
  bitget_cycle.jsonl          — one row per trader, the 90-day cycleData summary.
  bitget_manifest.jsonl       — resumability ledger, one row per trader_uid already
                                 attempted, with a status per endpoint (history_status,
                                 open_status) plus the traderDetailPageV2 headline
                                 snapshot folded in as `detail_*` fields. Overall
                                 `status` in {ok, protected, error}; only 'error' is
                                 retried on resume ('protected' covers history-hidden
                                 traders, which is terminal, same as Bybit/Phemex).

Usage:
  python3 scripts/scrape_bitget_positions.py --traders 400
  python3 scripts/scrape_bitget_positions.py --refresh-leaderboard --traders 0  # 0 = no cap
"""
import argparse, json, os, time

from curl_cffi import requests as cf_requests

BASE = 'https://www.bitget.com/v1/trigger'
LEADERBOARD_URL = BASE + '/public/uta/traderView'
HISTORY_URL = BASE + '/trace/order/historyList'
CURRENT_URL = BASE + '/trace/order/currentList'
DETAIL_URL = BASE + '/trace/public/traderDetailPageV2'
CYCLE_URL = BASE + '/trace/public/cycleData'

HTTP_HEADERS = {
    'terminaltype': '1', 'website': 'copy', 'locale': 'en-US',
    'Content-Type': 'application/json',
    'Origin': 'https://www.bitget.com', 'Referer': 'https://www.bitget.com/',
}

PAGE_SIZE_LEADERBOARD = 50
PAGE_SIZE_HISTORY = 20          # server-side cap; requesting more is silently ignored
HISTORY_TIMEOUT_S = 30          # historyList is the slowest endpoint under load (the
                                 # observed timeout-storm cases were all here); raised
                                 # from the 20s default given to every other endpoint
FETCH_SLEEP_S = 0.8             # SKILL.md: "0.8s+ entre calls OK"
TRADER_SLEEP_S = 0.3
RETRY_BACKOFF_S = 7             # observed ~7s recovery after a 429
MAX_RETRIES = 4
TOP_N_DEFAULT = 400
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


def make_session():
    return cf_requests.Session(impersonate='chrome')


def make_post_fn(session, sleep_fn=time.sleep, tries=MAX_RETRIES, backoff_s=RETRY_BACKOFF_S,
                  default_timeout_s=20):
    """Returns `post_fn(url, body, timeout=None) -> dict|None`. Retries with linear
    backoff on any non-200/unparseable response (429s) AND on a transport-level
    exception (timeout, connection reset) raised by `session.post` itself.

    The transport `try/except` used to sit OUTSIDE this retry loop (in the caller),
    so a single slow request raised straight through `paginate_history` and aborted
    the whole trader: `scrape_trader` discarded every page already accumulated in
    `rows`, and the manifest's 'error' status made the resumed run restart that
    trader from page 1 into the very same slow/overloaded path (the timeout-storm
    root cause, Fable-5). Catching it here means a transient timeout only costs one
    retried request, not a trader's worth of already-fetched pages."""
    def _post(url, body, timeout=None):
        for attempt in range(tries):
            try:
                r = session.post(url, json=body, headers=HTTP_HEADERS,
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
    return _post


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def row_from_leaderboard(entry):
    metrics = {m.get('showColumnCode'): m.get('comparedValue')
               for m in entry.get('itemVoList') or []}
    return {
        'traderUid': entry.get('traderUid'),
        'displayName': entry.get('displayName'),
        'followCount': _i(entry.get('followCount'), 0),
        'roi': _f(metrics.get('profit_rate')),
        'total_pnl': _f(metrics.get('total_income')),
        'copier_profit': _f(metrics.get('total_follow_profit')),
        'aum': _f(metrics.get('total_follow_trade_amount')),
        'mdd': _f(metrics.get('max_retracement')),
        'win_rate': _f(metrics.get('winning_rate')),
        'score': _f(metrics.get('score')),
    }


def fetch_leaderboard(post_fn, sleep_fn=time.sleep, page_size=PAGE_SIZE_LEADERBOARD,
                       sleep_s=FETCH_SLEEP_S, max_pages=40):
    """Paginates `uta/traderView`. Stop condition: a page with fewer than
    `page_size` rows (NOT `data.totals`, which lies and echoes the page size —
    verified live 2026-08-30). Returns (rows, max_show_sizes)."""
    rows, seen = [], set()
    max_show = None
    for page in range(1, max_pages + 1):
        d = post_fn(LEADERBOARD_URL, {'pageSize': page_size, 'pageNo': page, 'languageType': 0})
        if d is None or d.get('code') != '200':
            raise RuntimeError(f'leaderboard request failed at page {page}: {d}')
        data = d.get('data') or {}
        page_rows = data.get('rows') or []
        if data.get('maxShowSizes') is not None:
            max_show = data.get('maxShowSizes')
        for entry in page_rows:
            uid = entry.get('traderUid')
            if uid and uid not in seen:
                seen.add(uid)
                rows.append(row_from_leaderboard(entry))
        if len(page_rows) < page_size:
            break
        sleep_fn(sleep_s)
    return rows, max_show


# ---------------------------------------------------------------------------
# Closed positions (historyList)
# ---------------------------------------------------------------------------

def row_from_history(entry, trader_uid, display_name):
    position = entry.get('position')
    return {
        'traderUid': trader_uid, 'displayName': display_name,
        'orderNo': entry.get('orderNo'),
        'symbolId': entry.get('symbolId'), 'productCode': entry.get('productCode'),
        'side': {1: 'long', 0: 'short'}.get(position),
        'position_raw': position, 'positionDesc': entry.get('positionDesc'),
        'openLevel': _f(entry.get('openLevel')),
        'openAvgPrice': _f(entry.get('openAvgPrice')),
        'closeAvgPrice': _f(entry.get('closeAvgPrice')),
        'openDealCount': _f(entry.get('openDealCount')),
        'closeDealCount': _f(entry.get('closeDealCount')),
        'netProfit': _f(entry.get('netProfit')),
        # returnRate ships as a percent string ("11.68" -> stored as fraction 0.1168),
        # matching how Bybit's roi (orderNetProfitRateE4) is stored as a fraction.
        'returnRate': _f(entry.get('returnRate')) / 100.0,
        'openFee': _f(entry.get('openFee')), 'closeFee': _f(entry.get('closeFee')),
        'capitalFee': _f(entry.get('capitalFee')),
        'openMarginCount': _f(entry.get('openMarginCount')),
        'openTime': _i(entry.get('openTime')), 'closeTime': _i(entry.get('closeTime')),
        'marginMode': entry.get('marginMode'),
    }


def paginate_history(trader_uid, post_fn, sleep_fn=time.sleep, page_size=PAGE_SIZE_HISTORY,
                      sleep_s=FETCH_SLEEP_S, max_pages=2000):
    """Paginates historyList. Stop condition: a page with fewer than `page_size`
    rows OR `nextFlag` false (both checked; `totals` was verified honest for the
    busiest trader probed live but is not the sole stop signal). No protection flag
    was ever observed on this endpoint live (see module docstring) but `30066` is
    still handled defensively as 'protected', matching currentList's semantics."""
    rows = []
    for page in range(1, max_pages + 1):
        d = post_fn(HISTORY_URL, {'languageType': 0, 'pageNo': page,
                                   'pageSize': page_size, 'traderUid': trader_uid},
                    timeout=HISTORY_TIMEOUT_S)
        if d is None:
            raise RuntimeError(f'historyList request failed for {trader_uid} page {page}')
        code = d.get('code')
        if code == '30066':
            return [], 'protected'
        if code != '00000':
            raise RuntimeError(f'historyList bad code {code} for {trader_uid} page {page}')
        data = d.get('data') or {}
        page_rows = data.get('rows') or []
        rows.extend(page_rows)
        if len(page_rows) < page_size or not data.get('nextFlag'):
            break
        sleep_fn(sleep_s)
    return rows, 'ok'


# ---------------------------------------------------------------------------
# Open positions (currentList)
# ---------------------------------------------------------------------------

def row_from_open_position(entry, trader_uid, display_name):
    position = entry.get('position')
    return {
        'traderUid': trader_uid, 'displayName': display_name,
        'orderNo': entry.get('orderNo'), 'symbolId': entry.get('symbolId'),
        'side': {1: 'long', 0: 'short'}.get(position),
        'openLevel': _f(entry.get('openLevel')),
        'openAvgPrice': _f(entry.get('openAvgPrice')),
        'openDealCount': _f(entry.get('openDealCount')),
        'openMarginCount': _f(entry.get('openMarginCount')),
        'openTime': _i(entry.get('openTime')),
        # No verified unrealized-pnl field exists on this endpoint (see module
        # docstring) -- deliberately absent, not defaulted to 0.
    }


def fetch_open_positions(trader_uid, post_fn, page_size=PAGE_SIZE_HISTORY):
    d = post_fn(CURRENT_URL, {'languageType': 0, 'pageNo': 1, 'pageSize': page_size,
                               'traderUid': trader_uid})
    if d is None:
        raise RuntimeError(f'currentList request failed for {trader_uid}')
    code = d.get('code')
    if code == '30066':
        return [], 'protected'
    if code != '00000':
        raise RuntimeError(f'currentList bad code {code} for {trader_uid}')
    items = (d.get('data') or {}).get('items') or []
    return items, 'ok'


# ---------------------------------------------------------------------------
# cycleData (90-day drawdown series + native MDD)
# ---------------------------------------------------------------------------

def _series(kline_dto):
    out = []
    for pt in (kline_dto or {}).get('rows') or []:
        ts = _i(pt.get('dataTime'))
        val = _f(pt.get('amount'), default=None)
        if ts is not None and val is not None:
            out.append((ts, val))
    return sorted(out)


def fetch_cycle(trader_uid, post_fn, cycle_time=90):
    d = post_fn(CYCLE_URL, {'triggerUserId': trader_uid, 'cycleTime': cycle_time})
    if d is None:
        raise RuntimeError(f'cycleData request failed for {trader_uid}')
    if d.get('code') != '00000':
        raise RuntimeError(f'cycleData bad code {d.get("code")} for {trader_uid}')
    return d.get('data') or {}


def row_from_cycle(data, trader_uid, display_name, cycle_time):
    stats = data.get('statisticsDTO') or {}
    return {
        'traderUid': trader_uid, 'displayName': display_name, 'cycleTime': cycle_time,
        'roi_rows': _series(data.get('roiRows')),
        'pnl_rows': _series(data.get('pnlRows')),
        'net_profit_kline': _series(data.get('netProfitKlineDTO')),
        'aum': _f(stats.get('aum')),
        'profit_rate': _f(stats.get('profitRate')),
        'max_retracement': _f(stats.get('maxRetracement')),
        'winning_rate': _f(stats.get('winningRate')),
        'total_trades': _i(stats.get('totalTrades')),
        'profit_trades': _i(stats.get('profitTrades')),
        'loss_trades': _i(stats.get('lossTrades')),
        'largest_profit': _f(stats.get('largestProfit')),
        'largest_loss': _f(stats.get('largestLoss')),
    }


# ---------------------------------------------------------------------------
# traderDetailPageV2 (headline cross-check, folded into the manifest)
# ---------------------------------------------------------------------------

def fetch_detail(trader_uid, post_fn):
    d = post_fn(DETAIL_URL, {'languageType': 0, 'traderUid': trader_uid})
    if d is None:
        raise RuntimeError(f'traderDetailPageV2 request failed for {trader_uid}')
    if d.get('code') != '00000':
        raise RuntimeError(f'traderDetailPageV2 bad code {d.get("code")} for {trader_uid}')
    return d.get('data') or {}


def detail_summary(data):
    metrics = {m.get('showColumnCode'): m.get('comparedValue')
               for m in data.get('itemVoList') or []}
    fp = data.get('followProfits') or {}
    return {
        'aum': _f(data.get('aum')),
        'mdd': _f(metrics.get('max_retracement')),
        'roi': _f(metrics.get('profit_rate')),
        'win_rate': _f(metrics.get('total_winning_rate')),
        # itemVoList's showColumnCode 'income' ("Total profit", lifetime, USD) --
        # NOT the same field as the leaderboard row's 'total_income'/'total_pnl',
        # which is empirically NOT lifetime (see analysis/bitget_top5.py docstring).
        'total_income': _f(metrics.get('income')),
        'followers': _i(data.get('followerCount')),
        'profit_share': _f(data.get('distributeRatio')),
        'follow_profit_day7': _f(fp.get('day7')),
        'follow_profit_day30': _f(fp.get('day30')),
        'follow_profit_day90': _f(fp.get('day90')),
        'follow_profit_day180': _f(fp.get('day180')),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scrape_trader(trader, post_fn, sleep_fn=time.sleep, sleep_s=FETCH_SLEEP_S):
    """Scrapes one trader's closed history / open positions / 90d cycle / headline
    detail. Returns a dict with closed/open/cycle rows and a manifest entry, or
    raises on a network/parse failure (caller marks 'error' and moves on)."""
    trader_uid = trader['traderUid']
    display_name = trader.get('displayName')

    hist_rows, hist_status = paginate_history(trader_uid, post_fn, sleep_fn, sleep_s=sleep_s)
    closed = [row_from_history(r, trader_uid, display_name) for r in hist_rows]
    sleep_fn(sleep_s)

    open_items, open_status = fetch_open_positions(trader_uid, post_fn)
    open_rows = [row_from_open_position(r, trader_uid, display_name) for r in open_items]
    sleep_fn(sleep_s)

    cycle_data = fetch_cycle(trader_uid, post_fn, cycle_time=90)
    cycle_row = row_from_cycle(cycle_data, trader_uid, display_name, 90)
    sleep_fn(sleep_s)

    detail_data = fetch_detail(trader_uid, post_fn)
    detail = detail_summary(detail_data)

    manifest = {
        'traderUid': trader_uid, 'displayName': display_name,
        'followCount': trader.get('followCount'),
        'status': 'protected' if hist_status == 'protected' else 'ok',
        'history_status': hist_status, 'n_closed': len(closed),
        'open_status': open_status, 'n_open': len(open_rows),
        **{f'detail_{k}': v for k, v in detail.items()},
    }
    return {'closed': closed, 'open': open_rows, 'cycle': cycle_row, 'manifest': manifest}


def _manifest_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                rec = json.loads(line)
                if rec.get('status') in ('ok', 'protected'):
                    done.add(rec['traderUid'])
            except Exception:
                pass
    return done


def load_universe(path='data/bitget_traders.jsonl'):
    traders, seen = [], set()
    if not os.path.exists(path):
        return traders
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        uid = r.get('traderUid')
        if not uid or uid in seen:
            continue
        seen.add(uid)
        traders.append(r)
    return traders


def run(traders, out_dir='data', post_fn=None, sleep_fn=time.sleep, sleep_s=FETCH_SLEEP_S,
        trader_sleep_s=TRADER_SLEEP_S, max_consecutive_errors=MAX_CONSECUTIVE_ERRORS,
        print_fn=print):
    """Main driver, resumable via the manifest ('ok'/'protected' are terminal and
    skipped on resume; 'error' is retried). Flushes each trader's rows before
    writing its manifest 'done' line (a kill between flush and manifest must not
    duplicate rows on resume — dedup on read by `orderNo` happens in
    `analysis/bitget_flatten.py`)."""
    if post_fn is None:
        raise ValueError('post_fn is required')
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, 'bitget_manifest.jsonl')
    done = _manifest_done(manifest_path)
    todo = [t for t in traders if t['traderUid'] not in done]
    print_fn(f'bitget positions: {len(todo)} traders to fetch | {len(done)} already done', flush=True)

    closed_out = open(os.path.join(out_dir, 'bitget_positions.jsonl'), 'a')
    open_out = open(os.path.join(out_dir, 'bitget_open_positions.jsonl'), 'a')
    cycle_out = open(os.path.join(out_dir, 'bitget_cycle.jsonl'), 'a')
    manifest_out = open(manifest_path, 'a')

    n_done = n_closed = n_open = n_error = n_protected = 0
    consecutive_errors = 0
    t0 = time.time()
    try:
        for trader in todo:
            uid = trader['traderUid']
            try:
                result = scrape_trader(trader, post_fn, sleep_fn, sleep_s=sleep_s)
            except Exception as exc:
                print_fn(f'  ERR {uid} ({trader.get("displayName")}): {exc} - will retry on resume', flush=True)
                manifest_out.write(json.dumps({'traderUid': uid, 'displayName': trader.get('displayName'),
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
            cycle_out.write(json.dumps(result['cycle'], ensure_ascii=False) + '\n')
            closed_out.flush(); open_out.flush(); cycle_out.flush()

            manifest_out.write(json.dumps(result['manifest'], ensure_ascii=False) + '\n')
            manifest_out.flush()

            n_done += 1
            n_closed += len(result['closed'])
            n_open += len(result['open'])
            if result['manifest']['status'] == 'protected':
                n_protected += 1
            if n_done % 25 == 0:
                elapsed = time.time() - t0
                eta_min = (elapsed / n_done) * (len(todo) - n_done) / 60
                print_fn(f'  {n_done}/{len(todo)} traders | {n_closed} closed, {n_open} open '
                         f'positions | {n_protected} protected | {n_error} errors | '
                         f'ETA {eta_min:.1f} min', flush=True)
            sleep_fn(trader_sleep_s)
    finally:
        closed_out.close(); open_out.close(); cycle_out.close(); manifest_out.close()

    return {'processed': n_done, 'closed': n_closed, 'open': n_open,
            'protected': n_protected, 'errors': n_error}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--traders', type=int, default=TOP_N_DEFAULT,
                     help=f'cap on traders to scrape positions for, by follower count '
                          f'descending (default {TOP_N_DEFAULT}; 0 = no cap)')
    ap.add_argument('--out-dir', default='data')
    ap.add_argument('--refresh-leaderboard', action='store_true',
                     help='re-fetch the leaderboard even if data/bitget_traders.jsonl exists')
    args = ap.parse_args()

    session = make_session()
    post_fn = make_post_fn(session)

    traders_path = os.path.join(args.out_dir, 'bitget_traders.jsonl')
    if args.refresh_leaderboard or not os.path.exists(traders_path):
        print('Fetching leaderboard...', flush=True)
        rows, max_show = fetch_leaderboard(post_fn)
        os.makedirs(args.out_dir, exist_ok=True)
        with open(traders_path, 'w') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'universe: {len(rows)} traders scraped, maxShowSizes={max_show}', flush=True)

    traders = load_universe(traders_path)
    traders_sorted = sorted(traders, key=lambda t: t.get('followCount') or 0, reverse=True)
    todo_universe = traders_sorted[:args.traders] if args.traders else traders_sorted
    print(f'scraping positions for top {len(todo_universe)} of {len(traders_sorted)} '
          f'traders by follower count', flush=True)

    counts = run(todo_universe, out_dir=args.out_dir, post_fn=post_fn)
    print('DONE', counts, flush=True)


if __name__ == '__main__':
    main()
