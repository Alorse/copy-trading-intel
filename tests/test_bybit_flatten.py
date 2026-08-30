import csv
import json
import os

from analysis import bybit_flatten as fl


def _pos(order_id, pnl=1.0, closed_ms=2000, symbol='BTCUSDT', mark='M1'):
    return {
        'leaderMark': mark, 'leaderUserId': '1', 'nickName': 'n', 'orderId': order_id,
        'symbol': symbol, 'side': 'long', 'leverage': 10.0, 'entry_price': 100.0,
        'close_price': 101.0, 'size': 1.0, 'margin': 10.0, 'pnl_usd': pnl, 'roi': 0.1,
        'open_fee': 0.0, 'close_fee': 0.0, 'funding_fee': 0.0, 'started_ms': 1000,
        'closed_ms': closed_ms, 'follower_num': 0, 'full_closed': True,
    }


def test_row_from_position_maps_real_fields():
    p = {'leaderMark': 'CaXlJWDRhdEamYTsZvEWUQ==', 'leaderUserId': '567594578',
         'nickName': 'CRYPTO  K I N G', 'orderId': 'a61e3fac-6020-438e-b074-ea0776d4f6dc',
         'symbol': 'TRBUSDT', 'side': 'long', 'leverage': 10.0, 'entry_price': 21.88,
         'close_price': 16.97699811, 'size': 0.45, 'pnl_usd': -2.35369672, 'roi': -2.3657,
         'margin': 0.99488907, 'open_fee': 0.0054153, 'close_fee': 0.0042018,
         'funding_fee': 0.00046304, 'started_ms': 1787366681012, 'closed_ms': 1787375470711,
         'follower_num': 28, 'full_closed': True}
    d = dict(zip(fl.COLS, fl.row_from_position(p)))
    assert d['leader_mark'] == 'CaXlJWDRhdEamYTsZvEWUQ=='
    assert d['symbol'] == 'TRBUSDT'
    assert d['pnl_usd'] == -2.35369672
    assert d['roi'] == -2.3657
    assert abs(d['dur_h'] - (1787375470711 - 1787366681012) / 3600000) < 1e-9


def test_flatten_writes_csv(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bybit_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos('a')) + '\n')
        fh.write(json.dumps(_pos('b')) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = list(csv.DictReader(open(out_dir / 'bybit_positions.csv')))
    assert len(rows) == 2


def test_flatten_dedups_by_order_id(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bybit_positions.jsonl', 'w') as fh:
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
    assert not (out_dir / 'bybit_positions.csv').exists()


def test_flatten_missing_order_id_written_without_dedup_and_warns(tmp_path, capsys):
    # Fable-6: rows without orderId used to mass-collapse under one `None` dedup
    # key. Two such rows must both survive (not merge), and a warning must fire —
    # silence would make the data loss invisible.
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'bybit_positions.jsonl', 'w') as fh:
        fh.write(json.dumps(_pos(None, pnl=1.0)) + '\n')
        fh.write(json.dumps(_pos(None, pnl=2.0)) + '\n')
        fh.write(json.dumps(_pos('normal', pnl=3.0)) + '\n')
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 3
    rows = list(csv.DictReader(open(out_dir / 'bybit_positions.csv')))
    assert sorted(float(r['pnl_usd']) for r in rows) == [1.0, 2.0, 3.0]
    out = capsys.readouterr().out
    assert 'WARNING' in out and '2' in out


def test_flatten_real_shape_fixture_from_actual_snapshot():
    """tests/fixtures/bybit_positions_sample.jsonl holds 3 real order rows from
    data/bybit_positions.jsonl that all share the same leaderMark/symbol/closed_ms
    (a single TRBUSDT position scaled out across 3 orders) -- the exact real-data
    shape the position-level aggregation fix (bybit_top5.py) exists for."""
    import tempfile, shutil
    fixtures = os.path.join(os.path.dirname(__file__), 'fixtures')
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(fixtures, 'bybit_positions_sample.jsonl'),
                    os.path.join(tmp, 'bybit_positions.jsonl'))
        n = fl.flatten(data_dir=tmp, out_dir=tmp)
        assert n == 3
        rows = list(csv.DictReader(open(os.path.join(tmp, 'bybit_positions.csv'))))
        assert len({r['closed_ms'] for r in rows}) == 1
        assert len({r['order_id'] for r in rows}) == 3
