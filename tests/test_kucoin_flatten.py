import csv
import json

from analysis import kucoin_flatten as fl


def _pos(lead_id='L1', symbol='SOLUSDTM', start=1000, end=2000, pnl=1.0, nick='n'):
    return {
        'leadConfigId': lead_id, 'nickName': nick, 'symbol': symbol, 'side': 'short',
        'positionSide': 'BOTH', 'leverage': 10.0, 'marginMode': 'ISOLATED',
        'pnl': pnl, 'pnlRatio': 0.03, 'posMargin': 47.19, 'closeQty': 50.0,
        'avgEntryPrice': 94.379, 'avgClosePrice': 93.971, 'multiplier': 0.1,
        'currency': 'USDT', 'startTime': start, 'endTime': end,
    }


def test_row_from_position_maps_real_fields():
    p = {'leadConfigId': 1004009, 'nickName': 'Sanfa', 'symbol': 'SOLUSDTM',
         'side': 'short', 'positionSide': 'BOTH', 'leverage': 9.99355589110000000000,
         'marginMode': 'ISOLATED', 'pnl': 1.49631374, 'pnlRatio': 0.0317,
         'posMargin': 47.1895, 'closeQty': 50.0, 'avgEntryPrice': 94.3790001,
         'avgClosePrice': 93.97142, 'multiplier': 0.1, 'currency': 'USDT',
         'startTime': 1787421965000, 'endTime': 1787445032000}
    d = dict(zip(fl.COLS, fl.row_from_position(p)))
    assert d['lead_config_id'] == 1004009
    assert d['symbol'] == 'SOLUSDTM'
    assert d['pnl'] == 1.49631374
    assert d['pnl_ratio'] == 0.0317
    assert abs(d['dur_h'] - (1787445032000 - 1787421965000) / 3600000) < 1e-9


def test_flatten_writes_csv(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'kucoin_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos(symbol='SOLUSDTM', start=1000, end=2000)) + '\n')
        fh.write(json.dumps(_pos(symbol='BTCUSDTM', start=1000, end=2000)) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = list(csv.DictReader(open(out_dir / 'kucoin_positions.csv')))
    assert len(rows) == 2


def test_flatten_dedups_by_lead_symbol_start_end(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'kucoin_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos(pnl=1.0)) + '\n')
        fh.write(json.dumps(_pos(pnl=1.0)) + '\n')   # identical natural key -> collapses
        fh.write(json.dumps(_pos(symbol='BTCUSDTM', pnl=2.0)) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2


def test_flatten_missing_input_writes_nothing(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 0
    assert not (out_dir / 'kucoin_positions.csv').exists()


def test_flatten_missing_key_field_written_without_dedup_and_warns(tmp_path, capsys):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'kucoin_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos(start=None, pnl=1.0)) + '\n')
        fh.write(json.dumps(_pos(start=None, pnl=2.0)) + '\n')
        fh.write(json.dumps(_pos(symbol='BTCUSDTM', pnl=3.0)) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 3
    rows = list(csv.DictReader(open(out_dir / 'kucoin_positions.csv')))
    assert sorted(float(r['pnl']) for r in rows) == [1.0, 2.0, 3.0]
    out = capsys.readouterr().out
    assert 'WARNING' in out and '2' in out


def test_dedup_rows_composite_key_includes_lead_config_id():
    a = _pos(lead_id='L1', pnl=1.0)
    b = _pos(lead_id='L2', pnl=2.0)
    out, n_missing = fl.dedup_rows([a, b])
    assert len(out) == 2 and n_missing == 0   # different trader -> not a collision


def test_flatten_real_shape_fixture(tmp_path):
    """tests/fixtures/kucoin_history_page1.json holds real positions/history rows
    (live capture, trader 1004009) -- confirms the flattener survives real field
    types/precision (string-typed decimal fields) without crashing."""
    import os
    fixtures = os.path.join(os.path.dirname(__file__), 'fixtures')
    data = json.loads(open(os.path.join(fixtures, 'kucoin_history_page1.json')).read())
    items = data['data']['items']
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'kucoin_positions.jsonl', 'w') as fh:
        for it in items:
            row = {
                'leadConfigId': 1004009, 'nickName': 'Sanfa', 'symbol': it['symbol'],
                'side': {'Long': 'long', 'Short': 'short'}.get(it['positionDirection']),
                'positionSide': it['positionSide'], 'leverage': float(it['leverage']),
                'marginMode': it['marginMode'], 'pnl': float(it['pnl']),
                'pnlRatio': float(it['pnlRatio']), 'posMargin': float(it['posMargin']),
                'closeQty': float(it['closeQty']), 'avgEntryPrice': float(it['avgEntryPrice']),
                'avgClosePrice': float(it['avgClosePrice']), 'multiplier': float(it['multiplier']),
                'currency': it['currency'], 'startTime': it['startTime'], 'endTime': it['endTime'],
            }
            fh.write(json.dumps(row) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == len(items)
    rows = list(csv.DictReader(open(out_dir / 'kucoin_positions.csv')))
    assert len(rows) == len(items)
    assert all(r['side'] in ('long', 'short') for r in rows)
