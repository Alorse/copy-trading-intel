import csv
import json
from analysis import okx_flatten as fl


def test_row_from_position_maps_fields_and_computes_duration_and_notional():
    p = {'uniqueCode': 'ABC', 'nickName': 'trader1', 'leadDays': '96',
         'instId': 'BTC-USDT-SWAP', 'posSide': 'long', 'lever': '5E+1', 'mgnMode': 'cross',
         'openAvgPx': '58559.4', 'closeAvgPx': '59709.6', 'margin': '5855.94',
         'pnl': '31.72', 'pnlRatio': '0.0054', 'subPos': '500', 'ccy': 'USDT',
         'openTime': '1780688463641', 'closeTime': '1780692063641'}
    row = fl.row_from_position(p)
    d = dict(zip(fl.COLS, row))
    assert d['unique_code'] == 'ABC'
    assert d['leverage'] == 50.0                # "5E+1" parses via float()
    assert d['pos_side'] == 'long'
    assert abs(d['dur_h'] - 1.0) < 1e-9          # (closeTime - openTime) / 3600000
    assert d['notional'] == 5855.94 * 50.0
    assert d['margin'] == 5855.94


def test_row_from_position_open_position_has_blank_duration():
    p = {'uniqueCode': 'ABC', 'openTime': '1780688463641', 'closeTime': '', 'lever': '10'}
    row = fl.row_from_position(p)
    d = dict(zip(fl.COLS, row))
    assert d['dur_h'] == ''
    assert d['closed_ms'] is None


def test_flatten_writes_csv(tmp_path):
    positions = [
        {'uniqueCode': 'A', 'subPosId': 'S1', 'nickName': 'n1', 'leadDays': '10',
         'instId': 'BTC-USDT-SWAP', 'posSide': 'long', 'lever': '10', 'mgnMode': 'cross',
         'openAvgPx': '100', 'closeAvgPx': '110', 'margin': '50', 'pnl': '5', 'pnlRatio': '0.1',
         'subPos': '1', 'ccy': 'USDT', 'openTime': '1000', 'closeTime': '4600000'},
        {'uniqueCode': 'A', 'subPosId': 'S2', 'nickName': 'n1', 'leadDays': '10',
         'instId': 'ETH-USDT-SWAP', 'posSide': 'short', 'lever': '5', 'mgnMode': 'cross',
         'openAvgPx': '2000', 'closeAvgPx': '1900', 'margin': '400', 'pnl': '20',
         'pnlRatio': '0.05', 'subPos': '2', 'ccy': 'USDT', 'openTime': '2000',
         'closeTime': '3602000'},
    ]
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'okx_positions.jsonl', 'w') as fh:
        for p in positions:
            fh.write(json.dumps(p) + '\n')

    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = list(csv.DictReader(open(out_dir / 'okx_positions.csv')))
    assert len(rows) == 2
    assert rows[0]['symbol'] == 'BTC-USDT-SWAP'
    assert float(rows[0]['notional']) == 500.0   # 50 margin * 10x


def test_flatten_dedups_by_unique_code_and_subpos_id(tmp_path):
    position = {'uniqueCode': 'A', 'subPosId': 'S1', 'nickName': 'n1', 'leadDays': '10',
                'instId': 'BTC-USDT-SWAP', 'posSide': 'long', 'lever': '10', 'mgnMode': 'cross',
                'openAvgPx': '100', 'closeAvgPx': '110', 'margin': '50', 'pnl': '5',
                'pnlRatio': '0.1', 'subPos': '1', 'ccy': 'USDT', 'openTime': '1000',
                'closeTime': '4600000'}
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'okx_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(position) + '\n')
        fh.write(json.dumps(position) + '\n')  # duplicate line, e.g. from a resumed run

    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 1
    rows = list(csv.DictReader(open(out_dir / 'okx_positions.csv')))
    assert len(rows) == 1


def test_flatten_missing_input_writes_nothing(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 0
    assert not (out_dir / 'okx_positions.csv').exists()
