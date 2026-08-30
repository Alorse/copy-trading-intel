import csv
import json
import os

from analysis import bitget_flatten as fl


def _pos(order_no, pnl=1.0, close_time=2000, symbol='BTCUSDT_UMCBL', uid='U1'):
    return {
        'traderUid': uid, 'displayName': 'n', 'orderNo': order_no,
        'symbolId': symbol, 'productCode': 'BTCUSDT', 'side': 'long',
        'position_raw': 1, 'positionDesc': 'multi', 'openLevel': 10.0,
        'openAvgPrice': 100.0, 'closeAvgPrice': 101.0, 'openDealCount': 1.0,
        'closeDealCount': 1.0, 'netProfit': pnl, 'returnRate': 0.1,
        'openFee': 0.0, 'closeFee': 0.0, 'capitalFee': 0.0,
        'openMarginCount': 10.0, 'openTime': 1000, 'closeTime': close_time,
        'marginMode': 2,
    }


def test_row_from_position_maps_real_fields():
    p = {'traderUid': 'bcb04c7e8abb3d53a192', 'displayName': '9hTraderX',
         'orderNo': '1477055319273091072', 'symbolId': 'BTCUSDT_UMCBL',
         'productCode': 'BTCUSDT', 'side': 'short', 'position_raw': 0,
         'positionDesc': 'short', 'openLevel': 35.0, 'openAvgPrice': 80129.5,
         'closeAvgPrice': 77858.8, 'openDealCount': 0.0104, 'closeDealCount': 0.0104,
         'netProfit': 21.8551, 'returnRate': 0.9593, 'openFee': -0.5, 'closeFee': -0.4858,
         'capitalFee': 0.0, 'openMarginCount': 23.8099, 'openTime': 1787883351125,
         'closeTime': 1787936064718, 'marginMode': 2}
    d = dict(zip(fl.COLS, fl.row_from_position(p)))
    assert d['trader_uid'] == 'bcb04c7e8abb3d53a192'
    assert d['symbol_id'] == 'BTCUSDT_UMCBL'
    assert d['net_profit'] == 21.8551
    assert d['return_rate'] == 0.9593
    assert abs(d['dur_h'] - (1787936064718 - 1787883351125) / 3600000) < 1e-9


def test_flatten_writes_csv(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bitget_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos('a')) + '\n')
        fh.write(json.dumps(_pos('b')) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = list(csv.DictReader(open(out_dir / 'bitget_positions.csv')))
    assert len(rows) == 2


def test_flatten_dedups_by_order_no(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bitget_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos('dup')) + '\n')
        fh.write(json.dumps(_pos('dup')) + '\n')
        fh.write(json.dumps(_pos('unique')) + '\n')
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
    assert not (out_dir / 'bitget_positions.csv').exists()


def test_flatten_missing_order_no_written_without_dedup_and_warns(tmp_path, capsys):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bitget_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos(None, pnl=1.0)) + '\n')
        fh.write(json.dumps(_pos(None, pnl=2.0)) + '\n')
        fh.write(json.dumps(_pos('normal', pnl=3.0)) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 3
    rows = list(csv.DictReader(open(out_dir / 'bitget_positions.csv')))
    assert sorted(float(r['net_profit']) for r in rows) == [1.0, 2.0, 3.0]
    out = capsys.readouterr().out
    assert 'WARNING' in out and '2' in out


# ---------------------------------------------------------------------------
# Raw-row repair (Fable-2 / GLM-1): hand-fetched historyList rows, un-normalized.
# ---------------------------------------------------------------------------

def _raw_row(order_no, position=1, return_rate='50', net_profit='5.0', trader_uid='RAWU'):
    return {
        'traderUid': trader_uid, 'teacherId': trader_uid, 'displayName': 'rawname',
        'teacherName': 'rawname', 'hm': 2, 'orderNo': order_no, 'symbolId': 'BTCUSDT_UMCBL',
        'productCode': 'BTCUSDT', 'position': position, 'positionDesc': '多仓',
        'openLevel': '10', 'openAvgPrice': '100.0', 'closeAvgPrice': '101.0',
        'openDealCount': '1.0', 'closeDealCount': '1.0', 'netProfit': net_profit,
        'returnRate': return_rate, 'openFee': '0.0', 'closeFee': '0.0', 'capitalFee': '0.0',
        'openMarginCount': '10.0', 'openTime': '1000', 'closeTime': '2000', 'marginMode': 2,
    }


def test_is_raw_row_detects_hand_fetched_shape():
    assert fl.is_raw_row(_raw_row('a'))
    assert not fl.is_raw_row(_pos('a'))


def test_normalize_row_leaves_shaped_rows_untouched():
    shaped = _pos('a')
    assert fl.normalize_row(shaped) is shaped


def test_normalize_row_repairs_raw_row_percent_returnrate_and_string_types():
    # returnRate ships as a PERCENT string ("558" == 558%, not 5.58) on raw rows --
    # the exact trap documented in scrape_bitget_positions.row_from_history.
    norm = fl.normalize_row(_raw_row('a', position=1, return_rate='558', net_profit='2.8256'))
    assert norm['side'] == 'long'
    assert abs(norm['returnRate'] - 5.58) < 1e-9
    assert norm['netProfit'] == 2.8256
    assert norm['openLevel'] == 10.0
    assert norm['traderUid'] == 'RAWU' and norm['displayName'] == 'rawname'


def test_normalize_row_position_0_is_short():
    norm = fl.normalize_row(_raw_row('a', position=0))
    assert norm['side'] == 'short'


def test_dedup_rows_shaped_wins_over_raw_regardless_of_order():
    shaped = _pos('dup', pnl=1.0, uid='U1')
    raw = _raw_row('dup', trader_uid='U1', net_profit='999.0')
    out1, _ = fl.dedup_rows([raw, shaped])
    out2, _ = fl.dedup_rows([shaped, raw])
    assert len(out1) == 1 and out1[0]['netProfit'] == 1.0
    assert len(out2) == 1 and out2[0]['netProfit'] == 1.0


def test_dedup_rows_composite_key_is_trader_and_order_no():
    a = _pos('same_order_no', pnl=1.0, uid='U1')
    b = _pos('same_order_no', pnl=2.0, uid='U2')
    out, _ = fl.dedup_rows([a, b])
    assert len(out) == 2   # different trader_uid -> not a collision


def test_flatten_repairs_raw_rows_end_to_end(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bitget_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_raw_row('raw1')) + '\n')
        fh.write(json.dumps(_pos('shaped1')) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = {r['order_no']: r for r in csv.DictReader(open(out_dir / 'bitget_positions.csv'))}
    assert rows['raw1']['side'] == 'long'
    assert abs(float(rows['raw1']['return_rate']) - 0.5) < 1e-9


def test_flatten_real_shape_fixture_scaled_position():
    """tests/fixtures/bitget_positions_sample.jsonl holds 3 real order rows
    (via scrape_bitget_positions.row_from_history, live capture) from a single
    scaled BTCUSDT short: same trader/symbol/close_time (within 1ms), three
    distinct order_no and distinct open_avg_price/net_profit per fill — the
    exact real-data shape the position-level aggregation in bitget_top5.py
    exists to catch."""
    import tempfile, shutil
    fixtures = os.path.join(os.path.dirname(__file__), 'fixtures')
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(fixtures, 'bitget_positions_sample.jsonl'),
                    os.path.join(tmp, 'bitget_positions.jsonl'))
        n = fl.flatten(data_dir=tmp, out_dir=tmp)
        assert n == 3
        rows = list(csv.DictReader(open(os.path.join(tmp, 'bitget_positions.csv'))))
        assert len({r['symbol_id'] for r in rows}) == 1
        assert len({int(r['close_time']) // 1000 for r in rows}) == 1
        assert len({r['order_no'] for r in rows}) == 3
