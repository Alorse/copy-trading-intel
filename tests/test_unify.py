import csv
import json
from scripts import unify


def _write_jsonl(path, records):
    with open(path, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')


def test_map_okx_row_splits_named_and_extra_fields():
    rec = {'uniqueCode': 'C1', 'nickName': 'alice', 'pnl': '100', 'pnlRatio': '0.5',
           'aum': '1000', 'copyTraderNum': '5', 'winRatio': '0.6', 'leadDays': '30'}
    row = unify.map_okx_row(rec)
    assert row == {'exchange': 'okx', 'trader_id': 'C1', 'nickname': 'alice',
                    'pnl_usd': '100', 'roi': '0.5', 'aum_usd': '1000', 'followers': '5',
                    'win_rate': '0.6', 'extra_json': '{"leadDays": "30"}'}


def test_map_bybit_row_has_no_aum():
    rec = {'leaderUserId': 'L1', 'nickName': 'bob', 'total_all_follow_profit': 8432.1,
           'roi': 5.54, 'currentFollowerCount': 120, 'win_rate': 62.5, 'leaderLevel': 3}
    row = unify.map_bybit_row(rec)
    assert row['exchange'] == 'bybit'
    assert row['trader_id'] == 'L1'
    assert row['aum_usd'] == ''
    assert json.loads(row['extra_json']) == {'leaderLevel': 3}


def test_load_rows_dedups_by_exchange_and_trader_id_keeping_last(tmp_path):
    _write_jsonl(tmp_path / 'okx_traders.jsonl', [
        {'uniqueCode': 'C1', 'nickName': 'alice-old', 'pnl': '1'},
        {'uniqueCode': 'C1', 'nickName': 'alice-new', 'pnl': '2'},
        {'uniqueCode': 'C2', 'nickName': 'carol', 'pnl': '3'},
    ])
    rows = unify.load_rows(str(tmp_path))
    by_id = {r['trader_id']: r for r in rows}
    assert set(by_id) == {'C1', 'C2'}
    assert by_id['C1']['nickname'] == 'alice-new'      # last one wins


def test_load_rows_ignores_files_not_matching_known_exchanges(tmp_path):
    _write_jsonl(tmp_path / 'okx_traders.jsonl', [{'uniqueCode': 'C1', 'nickName': 'alice'}])
    (tmp_path / 'bitget_orders.jsonl').write_text(
        json.dumps({'traderUid': 'UID1', 'orders': []}) + '\n')   # not *_traders.jsonl
    (tmp_path / 'unknownexchange_traders.jsonl').write_text(
        json.dumps({'foo': 'bar'}) + '\n')                         # no mapper registered
    rows = unify.load_rows(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]['exchange'] == 'okx'


def test_run_writes_csv_with_rows_from_each_source(tmp_path):
    _write_jsonl(tmp_path / 'okx_traders.jsonl', [
        {'uniqueCode': 'C1', 'nickName': 'alice', 'pnl': '100', 'pnlRatio': '0.5',
         'aum': '1000', 'copyTraderNum': '5', 'winRatio': '0.6'}])
    _write_jsonl(tmp_path / 'bybit_traders.jsonl', [
        {'leaderUserId': 'L1', 'nickName': 'bob', 'total_all_follow_profit': 50.0,
         'roi': 1.2, 'currentFollowerCount': 10, 'win_rate': 40.0}])
    n = unify.run(data_dir=str(tmp_path))
    out = tmp_path / 'unified_traders.csv'
    assert n == 2
    rows = list(csv.DictReader(open(out)))
    exchanges = {r['exchange'] for r in rows}
    assert exchanges == {'okx', 'bybit'}
    assert set(rows[0].keys()) == set(unify.COLUMNS)
