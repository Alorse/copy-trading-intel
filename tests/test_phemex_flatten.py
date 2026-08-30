import csv
import json
from analysis import phemex_flatten as fl


def test_row_from_position_maps_fields_and_derives_leverage():
    p = {'positionId': 372961, 'symbol': 'BTCUSDT', 'currency': 'USDT', 'side': 'Buy',
         'posSide': 'Long', 'size': '21.092', 'closedPnl': '-19130.8545',
         'exchangeFee': '985.19494435', 'fundingFee': '0',
         'realizedPnl': '-20116.04944435', 'openPrice': '79082.69146596',
         'openPositionVal': '1648881.2738999312', 'closePrice': '78175.6720036',
         'margin': '28860.273139207108', 'roi': '-0.69701521',
         'openedTime': 1787656282978, 'updatedTime': 1787665880530}
    row = fl.row_from_position(9999, 'trader1', p)
    d = dict(zip(fl.COLS, row))
    assert d['user_id'] == 9999
    assert d['nick'] == 'trader1'
    assert d['side'] == 'Buy'
    assert d['pos_side'] == 'Long'
    assert d['pnl'] == -20116.04944435
    assert d['closed_pnl'] == -19130.8545
    # leverage is derived: openPositionVal / margin, not a reported field
    assert abs(d['leverage'] - 1648881.2738999312 / 28860.273139207108) < 1e-6
    assert abs(d['dur_h'] - (1787665880530 - 1787656282978) / 3600000) < 1e-9
    assert d['notional'] == 1648881.2738999312


def test_row_from_position_zero_margin_gives_zero_leverage_not_crash():
    p = {'positionId': 1, 'symbol': 'BTCUSDT', 'side': 'Buy', 'posSide': 'Long',
         'margin': '0', 'openPositionVal': '100', 'openPrice': '1', 'closePrice': '1',
         'realizedPnl': '0', 'closedPnl': '0', 'exchangeFee': '0', 'fundingFee': '0',
         'openedTime': 1000, 'updatedTime': 2000}
    row = fl.row_from_position(1, 'n', p)
    d = dict(zip(fl.COLS, row))
    assert d['leverage'] == 0.0


def test_row_from_position_merged_pos_side_keeps_side_for_direction():
    # posSide "Merged" (one-way mode) carries no Long/Short label -> `side` (Buy/Sell)
    # is the only usable direction signal (see phemex_flatten.py's docstring).
    p = {'positionId': 2, 'symbol': 'BTCUSDT', 'side': 'Buy', 'posSide': 'Merged',
         'margin': '10', 'openPositionVal': '100', 'openPrice': '100', 'closePrice': '101',
         'realizedPnl': '1', 'closedPnl': '1', 'exchangeFee': '0', 'fundingFee': '0',
         'openedTime': 1000, 'updatedTime': 2000}
    row = fl.row_from_position(1, 'n', p)
    d = dict(zip(fl.COLS, row))
    assert d['side'] == 'Buy'
    assert d['pos_side'] == 'Merged'


def test_flatten_writes_csv(tmp_path):
    trader = {'userId': 42, 'nick': 'n1', 'n_pos': 2, 'positions': [
        {'positionId': 1, 'symbol': 'BTCUSDT', 'side': 'Buy', 'posSide': 'Long',
         'margin': '50', 'openPositionVal': '500', 'openPrice': '100', 'closePrice': '110',
         'realizedPnl': '5', 'closedPnl': '6', 'exchangeFee': '1', 'fundingFee': '0',
         'currency': 'USDT', 'roi': '0.1', 'size': '5', 'openedTime': 1000, 'updatedTime': 4600000},
        {'positionId': 2, 'symbol': 'ETHUSDT', 'side': 'Sell', 'posSide': 'Short',
         'margin': '40', 'openPositionVal': '200', 'openPrice': '2000', 'closePrice': '1900',
         'realizedPnl': '20', 'closedPnl': '21', 'exchangeFee': '1', 'fundingFee': '0',
         'currency': 'USDT', 'roi': '0.05', 'size': '0.1', 'openedTime': 2000, 'updatedTime': 3602000},
    ]}
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'positions_all.jsonl', 'w') as fh:
        fh.write(json.dumps(trader) + '\n')

    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2
    rows = list(csv.DictReader(open(out_dir / 'phemex_positions.csv')))
    assert len(rows) == 2
    assert rows[0]['symbol'] == 'BTCUSDT'
    assert float(rows[0]['notional']) == 500.0
    assert float(rows[0]['leverage']) == 10.0    # 500 / 50


def test_flatten_dedups_by_user_id_and_position_id_not_position_id_alone(tmp_path):
    # positionId is scoped per-user, not globally unique (verified against the real
    # snapshot: 19 collisions across different userIds) -> dedup key must be the pair.
    pos = {'positionId': 7, 'symbol': 'BTCUSDT', 'side': 'Buy', 'posSide': 'Long',
           'margin': '50', 'openPositionVal': '500', 'openPrice': '100', 'closePrice': '110',
           'realizedPnl': '5', 'closedPnl': '6', 'exchangeFee': '1', 'fundingFee': '0',
           'currency': 'USDT', 'roi': '0.1', 'size': '5', 'openedTime': 1000, 'updatedTime': 4600000}
    traders = [
        {'userId': 1, 'nick': 'a', 'n_pos': 1, 'positions': [pos]},
        {'userId': 2, 'nick': 'b', 'n_pos': 1, 'positions': [pos]},  # same positionId, different user
    ]
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    with open(data_dir / 'positions_all.jsonl', 'w') as fh:
        for t in traders:
            fh.write(json.dumps(t) + '\n')

    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 2   # both kept: different users, same per-user positionId

    # a genuine duplicate line for the same user must still be deduped
    with open(data_dir / 'positions_all.jsonl', 'a') as fh:
        fh.write(json.dumps(traders[0]) + '\n')
    n2 = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n2 == 2


def test_flatten_missing_input_writes_nothing(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    n = fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    assert n == 0
    assert not (out_dir / 'phemex_positions.csv').exists()


def test_flatten_real_shape_fixture_from_actual_snapshot():
    """tests/fixtures/phemex_positions_sample.jsonl holds the first 3 positions of 3
    real traders taken from data/positions_all.jsonl (no live network) -- exercises
    the real field shapes, including a "Merged" posSide trader (one-way mode)."""
    import os
    fixtures = os.path.join(os.path.dirname(__file__), 'fixtures')
    # flatten() reads 'positions_all.jsonl' by name; point it at our sample by
    # temporarily copying, since the fixture is named phemex_positions_sample.jsonl.
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(fixtures, 'phemex_positions_sample.jsonl'),
                    os.path.join(tmp, 'positions_all.jsonl'))
        n = fl.flatten(data_dir=tmp, out_dir=tmp)
        assert n == 9   # 3 traders x 3 positions
        rows = list(csv.DictReader(open(os.path.join(tmp, 'phemex_positions.csv'))))
        assert len(rows) == 9
        pos_sides = {r['pos_side'] for r in rows}
        assert 'Merged' in pos_sides   # confirms the real-data quirk is present
        sides = {r['side'] for r in rows}
        assert sides <= {'Buy', 'Sell'}
        for r in rows:
            assert float(r['leverage']) > 0
