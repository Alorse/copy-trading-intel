import datetime as dt
import json
from pathlib import Path

from scripts import scrape_bybit_positions as sbp

FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name):
    return json.loads((FIXTURES / name).read_text())


HISTORY_PAGE = _load('bybit_leader_history_page.json')
HISTORY_PROTECTED = _load('bybit_leader_history_protected.json')
HISTORY_EMPTY = _load('bybit_leader_history_empty.json')
OPEN_POSITIONS = _load('bybit_open_positions.json')
TRADER_INFO = _load('bybit_trader_info.json')
YIELD_90D = _load('bybit_yield_trend_90d.json')
YIELD_7D = _load('bybit_yield_trend_7d.json')


# --- E2/E4/E8 decoding ---

def test_e_decodes_scaled_strings():
    assert sbp.e('1000', 2) == 10.0        # leverageE2 "1000" -> 10x
    assert sbp.e('-15800', 4) == -1.58      # orderNetProfitRateE4 "-15800" -> -158%
    assert sbp.e('-4319865989', 8) == -43.19865989


def test_e_handles_missing():
    assert sbp.e(None, 8) == 0.0
    assert sbp.e('', 8) == 0.0
    assert sbp.e('bad', 4, default=None) is None


# --- leader-history row parsing (real captured payload) ---

def test_row_from_history_maps_real_fields():
    entry = HISTORY_PAGE['result']['data'][0]
    row = sbp.row_from_history(entry, 'markX', 'uid1', 'nickX')
    assert row['orderId'] == entry['orderId']
    assert row['symbol'] == 'BICOUSDT'
    assert row['side'] == 'long'          # Buy -> long
    assert row['side_raw'] == 'Buy'
    assert row['leverage'] == 5.0          # leverageE2 "500" -> 5x
    assert row['pnl_usd'] == sbp.e(entry['orderNetProfitE8'], 8)
    assert row['roi'] == sbp.e(entry['orderNetProfitRateE4'], 4)
    assert row['margin'] == sbp.e(entry['orderCostE8'], 8)
    assert row['leaderMark'] == 'markX'
    assert row['leaderUserId'] == 'uid1'
    assert row['nickName'] == 'nickX'


def test_row_from_history_sell_maps_to_short():
    entry = dict(HISTORY_PAGE['result']['data'][0])
    entry['side'] = 'Sell'
    row = sbp.row_from_history(entry, 'm', 'u', 'n')
    assert row['side'] == 'short'


def test_started_time_e3_is_already_unix_ms_not_scaled():
    # Regression: "E3" naming suggests /1000, but the raw value is already a
    # standard 13-digit ms epoch timestamp. Verified live 2026-08-30 against a
    # real capture — dividing would produce a nonsense 1970s date.
    entry = HISTORY_PAGE['result']['data'][0]
    row = sbp.row_from_history(entry, 'm', 'u', 'n')
    started = dt.datetime.fromtimestamp(row['started_ms'] / 1000, dt.timezone.utc)
    assert started.year == 2026


def test_row_from_history_all_20_rows_parse_without_error():
    for entry in HISTORY_PAGE['result']['data']:
        row = sbp.row_from_history(entry, 'm', 'u', 'n')
        assert row['side'] in ('long', 'short')
        assert row['orderId']


# --- pagination-until-empty ---

def test_paginate_history_stops_on_empty_page():
    pages = [HISTORY_PAGE, HISTORY_EMPTY]  # page1 has rows, page2 empty -> stop
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return pages[len(calls) - 1]

    rows, status = sbp.paginate_history('markX', fake_fetch, sleep_fn=lambda s: None)
    assert status == 'ok'
    assert len(rows) == 20
    assert len(calls) == 2
    assert 'page=1' in calls[0]
    assert 'page=2' in calls[1]


def test_paginate_history_detects_protection_flag_on_page1():
    def fake_fetch(url):
        return HISTORY_PROTECTED

    rows, status = sbp.paginate_history('markX', fake_fetch, sleep_fn=lambda s: None)
    assert status == 'protected'
    assert rows == []


def test_paginate_history_ignores_lying_total_count_and_has_next():
    # HISTORY_EMPTY carries totalCount="100" and hasNext=false on an empty page —
    # SKILL.md warns these fields lie. Pagination must key off `data` alone.
    assert HISTORY_EMPTY['result']['totalCount'] == '100'
    assert HISTORY_EMPTY['result']['data'] == []

    def fake_fetch(url):
        return HISTORY_EMPTY

    rows, status = sbp.paginate_history('markX', fake_fetch, sleep_fn=lambda s: None)
    assert rows == []
    assert status == 'ok'


# --- open positions / trader info / yield-trend parsing ---

def test_row_from_open_position_maps_synthetic_row():
    # No non-empty position/list capture was available live (the sampled trader had
    # zero open positions) — field names come from SKILL.md's documented shape.
    # Marked synthetic; revisit once a real non-empty payload is captured.
    entry = {'symbol': 'BTCUSDT', 'side': 'Buy', 'leverageE2': '2500',
              'entryPrice': '65000.5', 'size': '0.1', 'orderCostE8': '260000000000',
              'stopLossPrice': '60000', 'takeProfitPrice': '70000'}
    row = sbp.row_from_open_position(entry, 'm', 'u', 'n')
    assert row['side'] == 'long'
    assert row['leverage'] == 25.0
    assert row['margin'] == 2600.0


def test_open_positions_fixture_shape_has_protection_field():
    result = OPEN_POSITIONS['result']
    assert 'openTradeInfoProtection' in result
    assert result['data'] == []


def test_row_from_trader_info_real_payload():
    row = sbp.row_from_trader_info(TRADER_INFO['result'], 'markX', 'nickX')
    assert row['win_rate_7d'] == 1.0          # "10000" -> 100%
    assert row['win_rate_3w'] == 0.5909
    assert row['profit_count'] == 31
    assert row['loss_count'] == 23
    assert row['locate_days'] == 308
    assert row['cum_history_transactions_count'] == 54


def test_yield_trend_series_real_payload_90d():
    series = sbp.yield_trend_series(YIELD_90D['result'])
    assert len(series) == 90
    # sorted by ts ascending
    assert all(series[i][0] <= series[i + 1][0] for i in range(len(series) - 1))
    ts, rate = series[0]
    assert isinstance(rate, float)


def test_yield_trend_series_real_payload_7d():
    series = sbp.yield_trend_series(YIELD_7D['result'])
    assert len(series) > 0


# --- run() orchestration (fixture-backed fake fetch, no live network) ---

def test_run_writes_files_and_manifest(tmp_path):
    leaders = [{'leaderMark': 'markA', 'leaderUserId': 'u1', 'nickName': 'nickA'}]

    def fake_fetch(url):
        if 'leader-history' in url:
            return HISTORY_EMPTY if 'page=2' in url else HISTORY_PAGE
        if 'position/list' in url:
            return OPEN_POSITIONS
        if 'pub-leader/info' in url:
            return TRADER_INFO
        if 'yield-trend' in url and 'NINETY' in url:
            return YIELD_90D
        if 'yield-trend' in url:
            return YIELD_7D
        raise AssertionError(f'unexpected url {url}')

    counts = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=fake_fetch,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 1
    assert counts['closed'] == 20
    assert counts['errors'] == 0

    manifest = [json.loads(l) for l in open(tmp_path / 'bybit_positions_manifest.jsonl')]
    assert manifest[0]['status'] == 'ok'
    assert manifest[0]['n_closed'] == 20

    closed_rows = [json.loads(l) for l in open(tmp_path / 'bybit_positions.jsonl')]
    assert len(closed_rows) == 20
    info_rows = [json.loads(l) for l in open(tmp_path / 'bybit_trader_info.jsonl')]
    assert len(info_rows) == 1
    yield_rows = [json.loads(l) for l in open(tmp_path / 'bybit_yield_trend.jsonl')]
    assert len(yield_rows) == 2  # 90D + 7D


def test_run_skips_already_done_leaders_on_resume(tmp_path):
    manifest_path = tmp_path / 'bybit_positions_manifest.jsonl'
    manifest_path.write_text(json.dumps({'leaderMark': 'markA', 'status': 'ok'}) + '\n')
    leaders = [{'leaderMark': 'markA', 'leaderUserId': 'u1', 'nickName': 'nickA'}]

    def fail_fetch(url):
        raise AssertionError('should not be called for an already-done leader')

    counts = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=fail_fetch,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['processed'] == 0


def test_run_marks_protected_leader_terminal_not_error(tmp_path):
    leaders = [{'leaderMark': 'markP', 'leaderUserId': 'u2', 'nickName': 'bluntz'}]

    def fake_fetch(url):
        if 'leader-history' in url:
            return HISTORY_PROTECTED
        if 'position/list' in url:
            return OPEN_POSITIONS
        if 'pub-leader/info' in url:
            return TRADER_INFO
        if 'yield-trend' in url and 'NINETY' in url:
            return YIELD_90D
        return YIELD_7D

    counts = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=fake_fetch,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts['closed'] == 0
    manifest = [json.loads(l) for l in open(tmp_path / 'bybit_positions_manifest.jsonl')]
    assert manifest[0]['status'] == 'protected'
    # resumable: a second run must skip it, not retry
    counts2 = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=lambda u: (_ for _ in ()).throw(AssertionError()),
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 0


def test_run_retries_error_leaders_on_resume(tmp_path):
    leaders = [{'leaderMark': 'markE', 'leaderUserId': 'u3', 'nickName': 'errNick'}]
    calls = {'n': 0}

    def flaky_fetch(url):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('network blip')
        if 'leader-history' in url:
            return HISTORY_EMPTY
        if 'position/list' in url:
            return OPEN_POSITIONS
        if 'pub-leader/info' in url:
            return TRADER_INFO
        if 'yield-trend' in url and 'NINETY' in url:
            return YIELD_90D
        return YIELD_7D

    counts1 = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=flaky_fetch,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts1['errors'] == 1
    assert counts1['processed'] == 0

    counts2 = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=flaky_fetch,
                       sleep_fn=lambda s: None, print_fn=lambda *a, **k: None)
    assert counts2['processed'] == 1


def test_run_stops_after_max_consecutive_errors(tmp_path):
    leaders = [{'leaderMark': f'mark{i}', 'leaderUserId': str(i), 'nickName': f'n{i}'}
               for i in range(5)]

    def always_fail(url):
        raise RuntimeError('down')

    counts = sbp.run(leaders, out_dir=str(tmp_path), fetch_fn=always_fail,
                      sleep_fn=lambda s: None, print_fn=lambda *a, **k: None,
                      max_consecutive_errors=3)
    assert counts['errors'] == 3
    assert counts['processed'] == 0


def test_load_universe_dedups_by_leader_mark(tmp_path):
    path = tmp_path / 'traders.jsonl'
    path.write_text(
        json.dumps({'leaderMark': 'm1', 'leaderUserId': '1', 'nickName': 'a'}) + '\n' +
        json.dumps({'leaderMark': 'm1', 'leaderUserId': '1', 'nickName': 'a'}) + '\n' +
        json.dumps({'leaderMark': 'm2', 'leaderUserId': '2', 'nickName': 'b'}) + '\n'
    )
    leaders = sbp.load_universe(str(path))
    assert len(leaders) == 2
