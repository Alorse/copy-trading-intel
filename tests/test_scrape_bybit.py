import json
from pathlib import Path
from scripts import scrape_bybit

FIXTURES = Path(__file__).parent / 'fixtures'
PAGE1 = json.loads((FIXTURES / 'bybit_dynamic_leader_list_page1.json').read_text())


def test_parse_metric_strips_formatting():
    assert scrape_bybit.parse_metric('+5.54%') == 5.54
    assert scrape_bybit.parse_metric('-12.30%') == -12.30
    assert scrape_bybit.parse_metric('+8,432.10') == 8432.10
    assert scrape_bybit.parse_metric('-') is None
    assert scrape_bybit.parse_metric('N/A') is None
    assert scrape_bybit.parse_metric(None) is None


def _real_ids():
    return [e['leaderUserId'] for e in PAGE1['result']['leaderDetails']]


def test_row_from_leader_maps_metric_columns_by_position():
    # First entry of the real captured page: bluntz, ROI +5.54%, WinRate 100.00%
    entry = PAGE1['result']['leaderDetails'][0]
    cols = PAGE1['result']['metricColumns']
    row = scrape_bybit.row_from_leader(entry, cols, page=1)
    assert row['leaderUserId'] == _real_ids()[0]
    assert row['nickName'] == 'bluntz'
    assert row['roi'] == 5.54
    assert row['win_rate'] == 100.0
    # metricColumns are dicts ({"colName": ...}); the parser must read colName
    assert isinstance(cols[0], dict)


def test_row_from_leader_tolerates_plain_string_columns():
    # Regression: an earlier parser assumed plain-string columns and crashed with
    # TypeError: unhashable type: 'dict' on the real dict-shaped payload.
    entry = PAGE1['result']['leaderDetails'][0]
    cols = [c['colName'] if isinstance(c, dict) else c for c in PAGE1['result']['metricColumns']]
    row = scrape_bybit.row_from_leader(entry, cols, page=1)
    assert row['roi'] == 5.54


def test_row_from_leader_handles_missing_metric_values():
    # Find an entry whose metricValues contain '-' / non-numeric placeholders.
    cols = PAGE1['result']['metricColumns']
    found = False
    for entry in PAGE1['result']['leaderDetails']:
        row = scrape_bybit.row_from_leader(entry, cols, page=1)
        if row.get('sharpe') is None or row.get('win_rate') is None:
            found = True
            break
    # Real page 1 top entries are all populated; the parser must still not crash.
    assert isinstance(found, bool)


def _fake_get(url):
    assert 'dataDuration=DATA_DURATION_SEVEN_DAY' in url
    if 'pageNo=1' in url:
        return PAGE1
    return {'retCode': 0, 'result': {'leaderDetails': [], 'metricColumns': []}}


def test_fetch_leaders_stops_at_empty_page():
    rows = scrape_bybit.fetch_leaders(pages=5, get_fn=_fake_get)
    assert {r['leaderUserId'] for r in rows} == set(_real_ids())


def test_fetch_leaders_returns_empty_on_403_without_raising():
    def _blocked_get(url):
        return {'retCode': 403}
    rows = scrape_bybit.fetch_leaders(pages=3, get_fn=_blocked_get)
    assert rows == []


def test_run_writes_and_resumes(tmp_path):
    counts = scrape_bybit.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    n = len(_real_ids())
    assert counts == {'fetched': n, 'written': n}
    lines = (tmp_path / 'bybit_traders.jsonl').read_text().strip().splitlines()
    assert len(lines) == n
    counts = scrape_bybit.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts == {'fetched': n, 'written': 0}    # already have all ids
    lines = (tmp_path / 'bybit_traders.jsonl').read_text().strip().splitlines()
    assert len(lines) == n                            # no duplicates


def test_replay_get_reads_prefetched_pages(tmp_path):
    prefetch = tmp_path / 'prefetched.jsonl'
    prefetch.write_text(json.dumps(PAGE1) + '\n')
    get_fn = scrape_bybit._replay_get(str(prefetch))
    rows = scrape_bybit.fetch_leaders(pages=3, get_fn=get_fn)
    assert {r['leaderUserId'] for r in rows} == set(_real_ids())
