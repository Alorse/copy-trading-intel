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


def test_row_from_leader_maps_metric_columns_by_position():
    entry = PAGE1['result']['leaderDetails'][0]
    cols = PAGE1['result']['metricColumns']
    row = scrape_bybit.row_from_leader(entry, cols, page=1)
    assert row['leaderUserId'] == '1001'
    assert row['roi'] == 5.54
    assert row['drawdown'] == -12.30
    assert row['total_all_follow_profit'] == 8432.10
    assert row['win_rate'] == 62.5
    assert row['pl_ratio'] == 1.8
    assert row['sharpe'] == 1.2
    assert row['follower_yield'] == 5.538          # 553800000 / 1e8


def test_row_from_leader_handles_missing_metric_values():
    entry = PAGE1['result']['leaderDetails'][1]
    cols = PAGE1['result']['metricColumns']
    row = scrape_bybit.row_from_leader(entry, cols, page=1)
    assert row['win_rate'] is None                 # "-"
    assert row['sharpe'] is None                   # "N/A"
    assert row['follower_yield'] == -1.0


def _fake_get(url):
    assert 'dataDuration=DATA_DURATION_SEVEN_DAY' in url
    if 'pageNo=1' in url:
        return PAGE1
    return {'retCode': 0, 'result': {'leaderDetails': [], 'metricColumns': []}}


def test_fetch_leaders_stops_at_empty_page():
    rows = scrape_bybit.fetch_leaders(pages=5, get_fn=_fake_get)
    assert {r['leaderUserId'] for r in rows} == {'1001', '1002'}


def test_fetch_leaders_returns_empty_on_403_without_raising():
    def _blocked_get(url):
        return {'retCode': 403}
    rows = scrape_bybit.fetch_leaders(pages=3, get_fn=_blocked_get)
    assert rows == []


def test_run_writes_and_resumes(tmp_path):
    counts = scrape_bybit.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts == {'fetched': 2, 'written': 2}
    lines = (tmp_path / 'bybit_traders.jsonl').read_text().strip().splitlines()
    assert len(lines) == 2
    counts = scrape_bybit.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts == {'fetched': 2, 'written': 0}    # already have both ids
    lines = (tmp_path / 'bybit_traders.jsonl').read_text().strip().splitlines()
    assert len(lines) == 2                            # no duplicates


def test_replay_get_reads_prefetched_pages(tmp_path):
    prefetch = tmp_path / 'prefetched.jsonl'
    prefetch.write_text(json.dumps(PAGE1) + '\n')
    get_fn = scrape_bybit._replay_get(str(prefetch))
    rows = scrape_bybit.fetch_leaders(pages=3, get_fn=get_fn)
    assert {r['leaderUserId'] for r in rows} == {'1001', '1002'}
