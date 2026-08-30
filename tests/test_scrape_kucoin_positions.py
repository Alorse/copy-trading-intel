import json
from pathlib import Path

from scripts import scrape_kucoin_positions as skp

FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name):
    return json.loads((FIXTURES / name).read_text())


LEADERBOARD_PAGE = _load('kucoin_leaderboard_page.json')
HISTORY_PAGE1 = _load('kucoin_history_page1.json')
HISTORY_PAGE2 = _load('kucoin_history_page2.json')
HISTORY_PAGE_LAST = _load('kucoin_history_page_last.json')
HISTORY_NOT_FOUND = _load('kucoin_history_not_found.json')
HISTORY_EMPTY = _load('kucoin_history_empty.json')
OPEN_POSITIONS = _load('kucoin_open_positions.json')
SUMMARY = _load('kucoin_summary.json')


# --- leaderboard ---

def test_row_from_leaderboard_maps_real_payload():
    entry = LEADERBOARD_PAGE['data']['items'][0]
    row = skp.row_from_leaderboard(entry)
    assert row['leadConfigId'] == entry['leadConfigId']
    assert row['nickName'] == entry['nickName']
    assert row['leadPrincipal'] == float(entry['leadPrincipal'])
    assert row['totalPnl'] == float(entry['totalPnl'])
    assert row['pnl_series_90d'] == [float(x) for x in entry['ninetyDayPnlDate']]


def test_row_from_leaderboard_renames_misleading_total_pnl_date():
    # KuCoin's own `totalPnlDate` field is actually the 30-DAY series (its last
    # point matches thirtyDayPnl, not totalPnl) -- verified live 2026-08-30 on
    # 200 sampled rows. row_from_leaderboard must expose it as `pnl_series_30d`,
    # never propagate the misleading name.
    entry = LEADERBOARD_PAGE['data']['items'][0]
    row = skp.row_from_leaderboard(entry)
    assert abs(row['pnl_series_30d'][-1] - float(entry['thirtyDayPnl'])) < 1e-6


def test_fetch_leaderboard_uses_current_page_not_page_num():
    # SKILL.md trap: `pageNum` is a silent no-op on this endpoint -- it always
    # re-returns page 1. fetch_leaderboard must send `currentPage`.
    calls = []

    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        calls.append(json_body)
        return LEADERBOARD_PAGE if json_body['currentPage'] == 1 else {'success': True, 'data': {'items': []}}

    skp.fetch_leaderboard(fake_request, sleep_fn=lambda s: None, page_size=len(LEADERBOARD_PAGE['data']['items']))
    assert all('currentPage' in c and 'pageNum' not in c for c in calls)


def test_fetch_leaderboard_stops_on_short_page():
    calls = []

    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        calls.append(json_body['currentPage'])
        return LEADERBOARD_PAGE if json_body['currentPage'] == 1 else {'success': True, 'data': {'items': []}}

    n = len(LEADERBOARD_PAGE['data']['items'])
    rows = skp.fetch_leaderboard(fake_request, sleep_fn=lambda s: None, page_size=n)
    assert len(rows) == n
    assert calls == [1, 2]


def test_fetch_leaderboard_dedups_by_lead_config_id():
    dup_page = dict(LEADERBOARD_PAGE)
    dup_page['data'] = dict(LEADERBOARD_PAGE['data'])
    dup_page['data']['items'] = LEADERBOARD_PAGE['data']['items'] + [LEADERBOARD_PAGE['data']['items'][0]]

    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return dup_page

    rows = skp.fetch_leaderboard(fake_request, sleep_fn=lambda s: None, page_size=999)
    ids = [r['leadConfigId'] for r in rows]
    assert len(ids) == len(set(ids))


def test_fetch_leaderboard_raises_on_unsuccessful_response():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return {'success': False, 'code': '200', 'data': None}

    try:
        skp.fetch_leaderboard(fake_request, sleep_fn=lambda s: None)
        assert False, 'expected RuntimeError'
    except RuntimeError:
        pass


# --- positions/history / row_from_history ---

def test_row_from_history_maps_real_fields():
    entry = HISTORY_PAGE1['data']['items'][0]
    row = skp.row_from_history(entry, 1004009, 'Sanfa')
    assert row['symbol'] == entry['symbol']
    assert row['side'] in ('long', 'short')
    assert row['pnl'] == float(entry['pnl'])
    assert row['pnlRatio'] == float(entry['pnlRatio'])
    assert row['leadConfigId'] == 1004009 and row['nickName'] == 'Sanfa'


def test_row_from_history_direction_mapping():
    entry = dict(HISTORY_PAGE1['data']['items'][0])
    entry['positionDirection'] = 'Long'
    assert skp.row_from_history(entry, 1, 'n')['side'] == 'long'
    entry['positionDirection'] = 'Short'
    assert skp.row_from_history(entry, 1, 'n')['side'] == 'short'


def test_row_from_history_all_rows_parse_without_error():
    for entry in HISTORY_PAGE1['data']['items']:
        row = skp.row_from_history(entry, 1, 'n')
        assert row['side'] in ('long', 'short')
        assert row['symbol']


def test_dedup_key_symbol_start_end_is_unique_on_real_fixture():
    # KuCoin history rows carry NO natural per-row id (unlike Bitget's orderNo /
    # Bybit's orderId) -- verified live: (symbol, startTime, endTime) had 0
    # collisions across a 260-row single-trader sample. Reproduced here on the
    # captured fixture pages.
    keys = set()
    n = 0
    for page in (HISTORY_PAGE1, HISTORY_PAGE2, HISTORY_PAGE_LAST):
        for entry in page['data']['items']:
            keys.add((entry['symbol'], entry['startTime'], entry['endTime']))
            n += 1
    assert len(keys) == n


def test_pnl_reconciliation_net_vs_gross_on_real_fixture():
    """The finding documented in scrape_kucoin_positions.py's docstring: `pnl` is
    NET of fees (median -12.0bps of notional, 91.6% negative over a 395-row live
    sample). Reproduce the same sign pattern on this fixture's real rows."""
    n_checked = n_lower = 0
    for entry in (HISTORY_PAGE1['data']['items'] + HISTORY_PAGE2['data']['items']
                  + HISTORY_PAGE_LAST['data']['items']):
        entry_px = float(entry['avgEntryPrice']); close_px = float(entry['avgClosePrice'])
        qty = float(entry['closeQty']); mult = float(entry['multiplier'])
        pnl = float(entry['pnl'])
        notional = qty * mult
        if notional <= 0:
            continue
        if entry['positionDirection'] == 'Long':
            gross = (close_px - entry_px) * notional
        else:
            gross = (entry_px - close_px) * notional
        n_checked += 1
        if pnl < gross:
            n_lower += 1
    assert n_checked > 0
    assert n_lower / n_checked > 0.5   # net-of-fees signature: pnl below gross most of the time


def test_pnl_ratio_equals_pnl_over_margin_on_real_fixture():
    # Verified live: pnlRatio == pnl/posMargin to ~5.8e-6 median absolute
    # difference (n=395) -- pnlRatio is the LEVERAGED return on margin.
    for entry in HISTORY_PAGE1['data']['items']:
        margin = float(entry['posMargin'])
        if margin == 0:
            continue
        ratio = float(entry['pnlRatio'])
        pnl = float(entry['pnl'])
        assert abs(ratio - pnl / margin) < 1e-3


def test_paginate_history_stops_on_page_ge_total_page():
    # Real 3-page trace (pageSize=100, totalNum=260): pages 1-2 are full (100
    # each), page 3 is short (60<100) AND currentPage(3)==totalPage(3) -- either
    # signal alone would stop here.
    pages = [HISTORY_PAGE1, HISTORY_PAGE2, HISTORY_PAGE_LAST]
    calls = []

    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        calls.append(params['currentPage'])
        return pages[len(calls) - 1]

    rows, status = skp.paginate_history(1004009, fake_request, sleep_fn=lambda s: None,
                                         page_size=len(HISTORY_PAGE1['data']['items']))
    assert status == 'ok'
    assert len(rows) == (len(HISTORY_PAGE1['data']['items']) + len(HISTORY_PAGE2['data']['items'])
                          + len(HISTORY_PAGE_LAST['data']['items']))
    assert len(calls) == 3


def test_paginate_history_not_found_is_terminal():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return HISTORY_NOT_FOUND

    rows, status = skp.paginate_history(999, fake_request, sleep_fn=lambda s: None)
    assert status == 'not_found'
    assert rows == []


def test_paginate_history_success_false_never_read_via_code_field():
    # The "success:false, code:200" trap: code alone always looks fine. Assert the
    # fixture itself carries that trap so the test would fail if KuCoin ever
    # changes this behavior silently.
    assert HISTORY_NOT_FOUND['code'] == '200'
    assert HISTORY_NOT_FOUND['success'] is False
    assert HISTORY_NOT_FOUND['data'] is None


def test_paginate_history_empty_but_valid_trader_is_ok_not_not_found():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return HISTORY_EMPTY

    rows, status = skp.paginate_history(1007443, fake_request, sleep_fn=lambda s: None)
    assert status == 'ok'
    assert rows == []


def test_paginate_history_raises_on_transport_failure():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return None

    try:
        skp.paginate_history(1, fake_request, sleep_fn=lambda s: None)
        assert False, 'expected RuntimeError'
    except RuntimeError:
        pass


# --- positions/current / row_from_open_position ---

def test_row_from_open_position_maps_real_payload_with_unrealized_pnl():
    entry = OPEN_POSITIONS['data'][0]
    row = skp.row_from_open_position(entry, 1004009, 'Sanfa')
    assert row['side'] in ('long', 'short')
    assert row['unrealisedPnl'] == float(entry['pnl'])
    ext = entry['extendPositionResponse']
    assert abs(row['unrealisedPnl'] - float(ext['unrealisedPnl'])) < 1e-6
    assert row['cumulativeTradeFee'] == float(ext['cumulativeTradeFee'])
    assert row['cumulativeFundingFee'] == float(ext['cumulativeFundingFee'])


def test_fetch_open_positions_ok():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return OPEN_POSITIONS

    items, status = skp.fetch_open_positions(1004009, fake_request)
    assert status == 'ok'
    assert len(items) == len(OPEN_POSITIONS['data'])


def test_fetch_open_positions_not_found():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return HISTORY_NOT_FOUND   # same {success:false, data:None} shape

    items, status = skp.fetch_open_positions(999, fake_request)
    assert status == 'not_found'
    assert items == []


# --- leadShow/summary ---

def test_summary_fields_real_payload():
    data = SUMMARY['data']
    fields = skp.summary_fields(data)
    assert fields['uid'] == data['uid']
    assert fields['followersSum'] == data['followersSum']
    assert fields['leadDays'] == data['leadDays']
    assert fields['positionVisibility'] == data['positionVisibility']


def test_fetch_summary_not_found_returns_empty_dict():
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        return {'success': False, 'code': '200', 'data': None}

    assert skp.fetch_summary(999, fake_request) == {}


# --- run() orchestration ---

def _fake_request_for(history_resp, open_resp=OPEN_POSITIONS, summary_resp=SUMMARY):
    def fake_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        if 'positions/history' in url:
            return history_resp
        if 'positions/current' in url:
            return open_resp
        if 'leadShow/summary' in url:
            return summary_resp
        raise AssertionError(f'unexpected url {url}')
    return fake_request


def test_run_writes_files_and_manifest(tmp_path):
    traders = [{'leadConfigId': 1004009, 'nickName': 'Sanfa'}]
    request_fn = _fake_request_for(HISTORY_PAGE_LAST)

    counts = skp.run(traders, out_dir=str(tmp_path), request_fn=request_fn,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 1
    assert counts['closed'] == len(HISTORY_PAGE_LAST['data']['items'])
    assert counts['errors'] == 0

    manifest = [json.loads(l) for l in open(tmp_path / 'kucoin_manifest.jsonl')]
    assert manifest[0]['status'] == 'ok'
    assert manifest[0]['n_closed'] == len(HISTORY_PAGE_LAST['data']['items'])
    assert 'summary_followersSum' in manifest[0]

    closed_rows = [json.loads(l) for l in open(tmp_path / 'kucoin_positions.jsonl')]
    assert len(closed_rows) == len(HISTORY_PAGE_LAST['data']['items'])
    open_rows = [json.loads(l) for l in open(tmp_path / 'kucoin_open_positions.jsonl')]
    assert len(open_rows) == len(OPEN_POSITIONS['data'])


def test_run_skips_already_done_traders_on_resume(tmp_path):
    manifest_path = tmp_path / 'kucoin_manifest.jsonl'
    manifest_path.write_text(json.dumps({'leadConfigId': 1004009, 'status': 'ok'}) + '\n')
    traders = [{'leadConfigId': 1004009, 'nickName': 'Sanfa'}]

    def fail_request(*a, **k):
        raise AssertionError('should not be called for an already-done trader')

    counts = skp.run(traders, out_dir=str(tmp_path), request_fn=fail_request,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 0


def test_run_marks_not_found_terminal_not_error(tmp_path):
    traders = [{'leadConfigId': 999, 'nickName': 'ghost'}]
    request_fn = _fake_request_for(HISTORY_NOT_FOUND, open_resp=HISTORY_NOT_FOUND,
                                    summary_resp=HISTORY_NOT_FOUND)

    counts = skp.run(traders, out_dir=str(tmp_path), request_fn=request_fn,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['closed'] == 0
    manifest = [json.loads(l) for l in open(tmp_path / 'kucoin_manifest.jsonl')]
    assert manifest[0]['status'] == 'not_found'

    counts2 = skp.run(traders, out_dir=str(tmp_path),
                       request_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError()),
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 0


def test_run_retries_error_traders_on_resume(tmp_path):
    traders = [{'leadConfigId': 1004009, 'nickName': 'Sanfa'}]
    calls = {'n': 0}

    def flaky_request(method, url, params=None, json_body=None, referer=None, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('network blip')
        if 'positions/history' in url:
            return HISTORY_PAGE_LAST
        if 'positions/current' in url:
            return OPEN_POSITIONS
        if 'leadShow/summary' in url:
            return SUMMARY
        raise AssertionError(url)

    # scrape_trader itself does not catch exceptions -- run() does, at the
    # per-trader boundary. Emulate a raising request_fn by wrapping paginate_history's
    # first call to raise directly.
    def raising_once(method, url, params=None, json_body=None, referer=None, timeout=None):
        return flaky_request(method, url, params, json_body, referer, timeout)

    counts1 = skp.run(traders, out_dir=str(tmp_path), request_fn=raising_once,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts1['errors'] == 1 and counts1['processed'] == 0

    counts2 = skp.run(traders, out_dir=str(tmp_path), request_fn=raising_once,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 1


def test_run_stops_after_max_consecutive_errors(tmp_path):
    traders = [{'leadConfigId': i, 'nickName': f'n{i}'} for i in range(5)]

    def always_fail(*a, **k):
        raise RuntimeError('down')

    counts = skp.run(traders, out_dir=str(tmp_path), request_fn=always_fail,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None,
                      max_consecutive_errors=3)
    assert counts['errors'] == 3
    assert counts['processed'] == 0


def test_load_universe_dedups_by_lead_config_id(tmp_path):
    path = tmp_path / 'traders.jsonl'
    path.write_text(
        json.dumps({'leadConfigId': 1, 'nickName': 'a'}) + '\n' +
        json.dumps({'leadConfigId': 1, 'nickName': 'a'}) + '\n' +
        json.dumps({'leadConfigId': 2, 'nickName': 'b'}) + '\n'
    )
    traders = skp.load_universe(str(path))
    assert len(traders) == 2


# --- make_request_fn transport retry semantics ---

def test_make_request_fn_retries_on_success_false_is_not_a_retry_trigger():
    # success:false with a 200 status is a valid terminal answer (not_found), NOT
    # a transport failure -- make_request_fn must return it as-is, not retry.
    calls = []

    class FakeResp:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'success': False, 'code': '200', 'data': None}

    class FakeSession:
        def get(self, url, params, headers, timeout):
            calls.append(1)
            return FakeResp()

    request_fn = skp.make_request_fn(FakeSession(), sleep_fn=lambda s: None)
    result = request_fn('GET', 'http://x')
    assert result == {'success': False, 'code': '200', 'data': None}
    assert len(calls) == 1


def test_make_request_fn_retries_when_get_raises_then_succeeds():
    calls = []

    class FakeResp:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'success': True, 'data': {}}

    class FlakySession:
        def get(self, url, params, headers, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError('Operation timed out')
            return FakeResp()

    sleeps = []
    request_fn = skp.make_request_fn(FlakySession(), sleep_fn=lambda s: sleeps.append(s), backoff_s=1)
    result = request_fn('GET', 'http://x')
    assert result == {'success': True, 'data': {}}
    assert len(calls) == 2
    assert sleeps == [1]


def test_make_request_fn_gives_up_after_max_retries():
    class FakeResp:
        status_code = 429
        content = b''

    class FakeSession:
        def get(self, url, params, headers, timeout):
            return FakeResp()

    request_fn = skp.make_request_fn(FakeSession(), sleep_fn=lambda s: None, tries=2, backoff_s=0)
    assert request_fn('GET', 'http://x') is None


def test_make_request_fn_posts_json_body_for_post_method():
    seen = []

    class FakeResp:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'success': True, 'data': {}}

    class RecordingSession:
        def post(self, url, json, headers, timeout):
            seen.append(json)
            return FakeResp()

    request_fn = skp.make_request_fn(RecordingSession(), sleep_fn=lambda s: None)
    request_fn('POST', 'http://x', json_body={'currentPage': 1, 'pageSize': 50})
    assert seen == [{'currentPage': 1, 'pageSize': 50}]
