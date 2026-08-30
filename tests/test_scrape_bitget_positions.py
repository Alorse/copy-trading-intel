import json
from pathlib import Path

from scripts import scrape_bitget_positions as sbp

FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name):
    return json.loads((FIXTURES / name).read_text())


LEADERBOARD_PAGE = _load('bitget_leaderboard_page.json')
HISTORY_PAGE1 = _load('bitget_history_page1.json')
HISTORY_PAGE_LAST = _load('bitget_history_page_last.json')
CURRENT_LIST = _load('bitget_current_list.json')
CURRENT_LIST_PROTECTED = _load('bitget_current_list_protected.json')
CYCLE_DATA = _load('bitget_cycle_data.json')
TRADER_DETAIL = _load('bitget_trader_detail.json')


# --- leaderboard ---

def test_row_from_leaderboard_maps_real_payload():
    entry = LEADERBOARD_PAGE['data']['rows'][0]
    row = sbp.row_from_leaderboard(entry)
    assert row['traderUid'] == entry['traderUid']
    assert row['displayName'] == entry['displayName']
    assert row['followCount'] == entry['followCount']
    metrics = {m['showColumnCode']: m['comparedValue'] for m in entry['itemVoList']}
    assert row['roi'] == float(metrics['profit_rate'])
    assert row['mdd'] == float(metrics['max_retracement'])
    assert row['win_rate'] == float(metrics['winning_rate'])


def test_fetch_leaderboard_stops_on_short_page_not_on_totals():
    # LEADERBOARD_PAGE carries data.totals=5 (the page size) while maxShowSizes=1489
    # (the real universe) -- fetch_leaderboard must key its stop condition off the
    # actual row count of the page, never off `totals` (SKILL.md: totals lies).
    assert LEADERBOARD_PAGE['data']['totals'] != LEADERBOARD_PAGE['data']['maxShowSizes']
    calls = []

    def fake_post(url, body, timeout=None):
        calls.append(body['pageNo'])
        return LEADERBOARD_PAGE if body['pageNo'] == 1 else {'code': '200', 'data': {'rows': []}}

    rows, max_show = sbp.fetch_leaderboard(fake_post, sleep_fn=lambda s: None, page_size=5)
    assert len(rows) == 5
    assert max_show == 1489
    assert calls == [1, 2]   # page 1 is full (5==page_size), page 2 is short (0<5) -> stop


def test_fetch_leaderboard_pages_until_short_page():
    full_page = dict(LEADERBOARD_PAGE)
    full_page['data'] = dict(LEADERBOARD_PAGE['data'])
    full_page['data']['rows'] = LEADERBOARD_PAGE['data']['rows'] * 2  # 10 rows, page_size=10
    empty_page = {'code': '200', 'data': {'rows': [], 'maxShowSizes': 1489}}
    pages = [full_page, empty_page]
    calls = []

    def fake_post(url, body, timeout=None):
        calls.append(body['pageNo'])
        return pages[len(calls) - 1]

    rows, max_show = sbp.fetch_leaderboard(fake_post, sleep_fn=lambda s: None, page_size=10)
    assert len(calls) == 2
    assert max_show == 1489


def test_fetch_leaderboard_dedups_by_trader_uid():
    dup_page = dict(LEADERBOARD_PAGE)
    dup_page['data'] = dict(LEADERBOARD_PAGE['data'])
    dup_page['data']['rows'] = LEADERBOARD_PAGE['data']['rows'] + [LEADERBOARD_PAGE['data']['rows'][0]]

    def fake_post(url, body, timeout=None):
        return dup_page

    rows, _ = sbp.fetch_leaderboard(fake_post, sleep_fn=lambda s: None, page_size=999)
    uids = [r['traderUid'] for r in rows]
    assert len(uids) == len(set(uids))


# --- historyList / row_from_history ---

def test_row_from_history_maps_real_fields():
    entry = HISTORY_PAGE1['data']['rows'][0]
    row = sbp.row_from_history(entry, 'uidX', 'nameX')
    assert row['orderNo'] == entry['orderNo']
    assert row['symbolId'] == entry['symbolId']
    assert row['side'] in ('long', 'short')
    assert row['netProfit'] == float(entry['netProfit'])
    assert abs(row['returnRate'] - float(entry['returnRate']) / 100.0) < 1e-12
    assert row['traderUid'] == 'uidX' and row['displayName'] == 'nameX'


def test_row_from_history_position_1_is_long_0_is_short():
    entry = dict(HISTORY_PAGE1['data']['rows'][0])
    entry['position'] = 1
    assert sbp.row_from_history(entry, 'u', 'n')['side'] == 'long'
    entry['position'] = 0
    assert sbp.row_from_history(entry, 'u', 'n')['side'] == 'short'


def test_row_from_history_all_rows_parse_without_error():
    for entry in HISTORY_PAGE1['data']['rows']:
        row = sbp.row_from_history(entry, 'u', 'n')
        assert row['side'] in ('long', 'short')
        assert row['orderNo']


def test_pnl_reconciliation_price_basis_sign_flips_on_real_fixture():
    """The finding documented in this module's docstring: reconstructing a
    de-leveraged return from (close_price/open_price - 1) can disagree in SIGN
    with the trader's own `netProfit` on a scaled position's simultaneous
    multi-fill close. Measured live over 455 rows/50 traders: 10.1% sign flips.
    This fixture (20 real rows, including a 9-row scaled BTCUSDT short batch
    sharing one closeTime) reproduces at least one such flip -- proof the failure
    mode is real, not a live-sample artifact, and that `pr` must NOT be
    price-derived (see bitget_top5.load_positions, which uses return_rate/open_level
    instead)."""
    n_flip = 0
    n_checked = 0
    for entry in HISTORY_PAGE1['data']['rows']:
        op = float(entry['openAvgPrice']); cp = float(entry['closeAvgPrice'])
        net = float(entry['netProfit'])
        if net == 0:
            continue
        direction = 1 if entry['position'] == 1 else -1
        price_sign = 1 if (cp - op) * direction > 0 else -1
        net_sign = 1 if net > 0 else -1
        n_checked += 1
        if price_sign != net_sign:
            n_flip += 1
    assert n_checked > 0
    assert n_flip >= 1   # the failure mode is present in real data, not hypothetical


def test_pnl_reconciliation_return_rate_over_open_level_is_self_consistent_with_net_over_margin():
    """The decided fallback basis: return_rate/open_level must track net_profit/
    margin far more tightly than the price-derived basis does (see the module
    docstring's measured 0.8pp median / 6.0pp p90 deviation over 455 live rows).
    On this 20-row fixture every row's absolute deviation must stay well under the
    10%+ relative blowups seen in the price-derived reconciliation."""
    max_pp_dev = 0.0
    for entry in HISTORY_PAGE1['data']['rows']:
        margin = float(entry['openMarginCount'])
        if margin == 0:
            continue
        net = float(entry['netProfit'])
        rr = float(entry['returnRate']) / 100.0
        dev = abs(rr - net / margin)
        max_pp_dev = max(max_pp_dev, dev)
    assert max_pp_dev < 0.10   # generous bound; live median is ~0.008 (0.8pp)


def test_openlevel_times_margin_approx_notional_on_real_rows():
    # openLevel semantics check (verification item #3): margin * leverage ~= notional
    for entry in HISTORY_PAGE1['data']['rows']:
        margin = float(entry['openMarginCount'])
        lev = float(entry['openLevel'])
        notional = float(entry['openAvgPrice']) * float(entry['openDealCount'])
        if margin == 0:
            continue
        assert abs(notional / margin - lev) / lev < 0.02


def test_paginate_history_stops_on_short_page():
    pages = [HISTORY_PAGE1, HISTORY_PAGE_LAST]
    calls = []

    def fake_fetch(url, body, timeout=None):
        calls.append(body['pageNo'])
        return pages[len(calls) - 1]

    rows, status = sbp.paginate_history('uidX', fake_fetch, sleep_fn=lambda s: None)
    assert status == 'ok'
    assert len(rows) == len(HISTORY_PAGE1['data']['rows']) + len(HISTORY_PAGE_LAST['data']['rows'])
    assert len(calls) == 2


def test_paginate_history_detects_protection_code():
    def fake_fetch(url, body, timeout=None):
        return {'code': '30066', 'data': {}}

    rows, status = sbp.paginate_history('uidX', fake_fetch, sleep_fn=lambda s: None)
    assert status == 'protected'
    assert rows == []


def test_paginate_history_raises_on_unexpected_code():
    def fake_fetch(url, body, timeout=None):
        return {'code': 'ERR', 'data': {}}
    try:
        sbp.paginate_history('uidX', fake_fetch, sleep_fn=lambda s: None)
        assert False, 'expected RuntimeError'
    except RuntimeError:
        pass


# --- currentList / row_from_open_position ---

def test_row_from_open_position_maps_real_nonempty_payload():
    entry = CURRENT_LIST['data']['items'][0]
    row = sbp.row_from_open_position(entry, 'uidX', 'nameX')
    assert row['side'] in ('long', 'short')
    assert row['openLevel'] == float(entry['openLevel'])
    assert 'upl' not in row   # no verified unrealized-pnl field exists


def test_fetch_open_positions_protected_flag():
    def fake_fetch(url, body, timeout=None):
        return CURRENT_LIST_PROTECTED
    items, status = sbp.fetch_open_positions('uidX', fake_fetch)
    assert status == 'protected'
    assert items == []


def test_fetch_open_positions_ok():
    def fake_fetch(url, body, timeout=None):
        return CURRENT_LIST
    items, status = sbp.fetch_open_positions('uidX', fake_fetch)
    assert status == 'ok'
    assert len(items) == len(CURRENT_LIST['data']['items'])


# --- cycleData ---

def test_row_from_cycle_real_payload_matches_skill_md_claim():
    # SKILL.md / module docstring: last(roiRows) == statisticsDTO.profitRate exactly.
    data = CYCLE_DATA['data']
    row = sbp.row_from_cycle(data, 'uidX', 'nameX', 90)
    assert len(row['roi_rows']) > 0
    last_ts, last_roi = row['roi_rows'][-1]
    assert abs(last_roi - row['profit_rate']) < 1e-9
    assert row['max_retracement'] == float(data['statisticsDTO']['maxRetracement'])


def test_series_is_sorted_by_timestamp():
    data = CYCLE_DATA['data']
    row = sbp.row_from_cycle(data, 'u', 'n', 90)
    ts = [t for t, _ in row['roi_rows']]
    assert ts == sorted(ts)


def test_fetch_cycle_raises_on_bad_code():
    def fake_fetch(url, body, timeout=None):
        return {'code': 'ERR'}
    try:
        sbp.fetch_cycle('uidX', fake_fetch)
        assert False, 'expected RuntimeError'
    except RuntimeError:
        pass


# --- traderDetailPageV2 ---

def test_detail_summary_real_payload():
    data = TRADER_DETAIL['data']
    summary = sbp.detail_summary(data)
    assert summary['aum'] == float(data['aum'])
    assert summary['followers'] == data['followerCount']
    fp = data['followProfits']
    assert summary['follow_profit_day30'] == float(fp['day30'])
    assert summary['follow_profit_day90'] == float(fp['day90'])


def test_detail_summary_captures_total_income_from_income_column():
    # itemVoList's showColumnCode 'income' ("Total profit") -- distinct from the
    # leaderboard row's 'total_income'/'total_pnl' (see bitget_top5.py's window-pin
    # finding: that field is empirically NOT lifetime).
    data = {'itemVoList': [{'showColumnCode': 'income', 'comparedValue': '1511.84'}]}
    assert sbp.detail_summary(data)['total_income'] == 1511.84


# --- run() orchestration ---

def test_run_writes_files_and_manifest(tmp_path):
    traders = [{'traderUid': 'uidX', 'displayName': 'nameX', 'followCount': 10}]

    def fake_post(url, body, timeout=None):
        if 'historyList' in url:
            return HISTORY_PAGE_LAST      # short page -> single call, terminal
        if 'currentList' in url:
            return CURRENT_LIST
        if 'cycleData' in url:
            return CYCLE_DATA
        if 'traderDetailPageV2' in url:
            return TRADER_DETAIL
        raise AssertionError(f'unexpected url {url}')

    counts = sbp.run(traders, out_dir=str(tmp_path), post_fn=fake_post,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 1
    assert counts['closed'] == len(HISTORY_PAGE_LAST['data']['rows'])
    assert counts['errors'] == 0

    manifest = [json.loads(l) for l in open(tmp_path / 'bitget_manifest.jsonl')]
    assert manifest[0]['status'] == 'ok'
    assert manifest[0]['n_closed'] == len(HISTORY_PAGE_LAST['data']['rows'])
    assert 'detail_aum' in manifest[0]

    closed_rows = [json.loads(l) for l in open(tmp_path / 'bitget_positions.jsonl')]
    assert len(closed_rows) == len(HISTORY_PAGE_LAST['data']['rows'])
    cycle_rows = [json.loads(l) for l in open(tmp_path / 'bitget_cycle.jsonl')]
    assert len(cycle_rows) == 1


def test_run_skips_already_done_traders_on_resume(tmp_path):
    manifest_path = tmp_path / 'bitget_manifest.jsonl'
    manifest_path.write_text(json.dumps({'traderUid': 'uidX', 'status': 'ok'}) + '\n')
    traders = [{'traderUid': 'uidX', 'displayName': 'nameX', 'followCount': 10}]

    def fail_post(url, body, timeout=None):
        raise AssertionError('should not be called for an already-done trader')

    counts = sbp.run(traders, out_dir=str(tmp_path), post_fn=fail_post,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 0


def test_run_marks_history_protected_terminal_not_error(tmp_path):
    traders = [{'traderUid': 'uidP', 'displayName': 'protectedName', 'followCount': 5}]

    def fake_post(url, body, timeout=None):
        if 'historyList' in url:
            return {'code': '30066', 'data': {}}
        if 'currentList' in url:
            return CURRENT_LIST_PROTECTED
        if 'cycleData' in url:
            return CYCLE_DATA
        if 'traderDetailPageV2' in url:
            return TRADER_DETAIL
        raise AssertionError(url)

    counts = sbp.run(traders, out_dir=str(tmp_path), post_fn=fake_post,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['closed'] == 0
    manifest = [json.loads(l) for l in open(tmp_path / 'bitget_manifest.jsonl')]
    assert manifest[0]['status'] == 'protected'

    counts2 = sbp.run(traders, out_dir=str(tmp_path),
                       post_fn=lambda u, b: (_ for _ in ()).throw(AssertionError()),
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 0


def test_run_retries_error_traders_on_resume(tmp_path):
    traders = [{'traderUid': 'uidE', 'displayName': 'errName', 'followCount': 1}]
    calls = {'n': 0}

    def flaky_post(url, body, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('network blip')
        if 'historyList' in url:
            return HISTORY_PAGE_LAST
        if 'currentList' in url:
            return CURRENT_LIST
        if 'cycleData' in url:
            return CYCLE_DATA
        if 'traderDetailPageV2' in url:
            return TRADER_DETAIL
        raise AssertionError(url)

    counts1 = sbp.run(traders, out_dir=str(tmp_path), post_fn=flaky_post,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts1['errors'] == 1 and counts1['processed'] == 0

    counts2 = sbp.run(traders, out_dir=str(tmp_path), post_fn=flaky_post,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 1


def test_run_stops_after_max_consecutive_errors(tmp_path):
    traders = [{'traderUid': f'uid{i}', 'displayName': f'n{i}', 'followCount': i}
               for i in range(5)]

    def always_fail(url, body, timeout=None):
        raise RuntimeError('down')

    counts = sbp.run(traders, out_dir=str(tmp_path), post_fn=always_fail,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None,
                      max_consecutive_errors=3)
    assert counts['errors'] == 3
    assert counts['processed'] == 0


def test_load_universe_dedups_by_trader_uid(tmp_path):
    path = tmp_path / 'traders.jsonl'
    path.write_text(
        json.dumps({'traderUid': 't1', 'displayName': 'a', 'followCount': 1}) + '\n' +
        json.dumps({'traderUid': 't1', 'displayName': 'a', 'followCount': 1}) + '\n' +
        json.dumps({'traderUid': 't2', 'displayName': 'b', 'followCount': 2}) + '\n'
    )
    traders = sbp.load_universe(str(path))
    assert len(traders) == 2


def test_make_post_fn_retries_on_empty_body_then_succeeds():
    calls = []

    class FakeResp:
        def __init__(self, status_code, content, payload=None):
            self.status_code = status_code
            self.content = content
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError('no body')
            return self._payload

    class FakeSession:
        def post(self, url, json, headers, timeout):
            calls.append(1)
            if len(calls) < 3:
                return FakeResp(429, b'')
            return FakeResp(200, b'{}', {'code': '00000'})

    sleeps = []
    post_fn = sbp.make_post_fn(FakeSession(), sleep_fn=lambda s: sleeps.append(s), backoff_s=1)
    result = post_fn('http://x', {})
    assert result == {'code': '00000'}
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_make_post_fn_retries_when_post_raises_then_succeeds():
    # Fable-5: the transport try/except used to sit outside the retry loop, so one
    # raised timeout aborted the whole trader and discarded already-fetched pages.
    # It must now be caught INSIDE make_post_fn's own retry loop.
    calls = []

    class FakeResp:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'code': '00000'}

    class FlakySession:
        def post(self, url, json, headers, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError('Operation timed out after 20002 milliseconds')
            return FakeResp()

    sleeps = []
    post_fn = sbp.make_post_fn(FlakySession(), sleep_fn=lambda s: sleeps.append(s), backoff_s=1)
    result = post_fn('http://x', {})
    assert result == {'code': '00000'}
    assert len(calls) == 2
    assert sleeps == [1]


def test_make_post_fn_honors_per_call_timeout_override():
    seen_timeouts = []

    class FakeResp:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'code': '00000'}

    class RecordingSession:
        def post(self, url, json, headers, timeout):
            seen_timeouts.append(timeout)
            return FakeResp()

    post_fn = sbp.make_post_fn(RecordingSession(), sleep_fn=lambda s: None)
    post_fn('http://x', {})
    post_fn('http://x', {}, timeout=sbp.HISTORY_TIMEOUT_S)
    assert seen_timeouts == [20, 30]


def test_make_post_fn_gives_up_after_max_retries():
    class FakeResp:
        status_code = 429
        content = b''

    class FakeSession:
        def post(self, url, json, headers, timeout):
            return FakeResp()

    post_fn = sbp.make_post_fn(FakeSession(), sleep_fn=lambda s: None, tries=2, backoff_s=0)
    assert post_fn('http://x', {}) is None
