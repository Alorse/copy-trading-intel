import json
import shutil
from pathlib import Path

from scripts import bitget_repair_raw_rows as repair

FIXTURES = Path(__file__).parent / 'fixtures'


def _shaped(order_no, uid='U1', pnl=1.0):
    return {
        'traderUid': uid, 'displayName': 'n', 'orderNo': order_no,
        'symbolId': 'BTCUSDT_UMCBL', 'productCode': 'BTCUSDT', 'side': 'long',
        'position_raw': 1, 'positionDesc': 'multi', 'openLevel': 10.0,
        'openAvgPrice': 100.0, 'closeAvgPrice': 101.0, 'openDealCount': 1.0,
        'closeDealCount': 1.0, 'netProfit': pnl, 'returnRate': 0.1,
        'openFee': 0.0, 'closeFee': 0.0, 'capitalFee': 0.0,
        'openMarginCount': 10.0, 'openTime': 1000, 'closeTime': 2000,
        'marginMode': 2,
    }


def _raw(order_no, uid='RAWU', return_rate='50', net_profit='5.0'):
    return {
        'traderUid': uid, 'teacherId': uid, 'displayName': 'rawname',
        'teacherName': 'rawname', 'hm': 2, 'orderNo': order_no, 'symbolId': 'BTCUSDT_UMCBL',
        'productCode': 'BTCUSDT', 'position': 1, 'positionDesc': '多仓',
        'openLevel': '10', 'openAvgPrice': '100.0', 'closeAvgPrice': '101.0',
        'openDealCount': '1.0', 'closeDealCount': '1.0', 'netProfit': net_profit,
        'returnRate': return_rate, 'openFee': '0.0', 'closeFee': '0.0', 'capitalFee': '0.0',
        'openMarginCount': '10.0', 'openTime': '1000', 'closeTime': '2000', 'marginMode': 2,
    }


def test_repair_positions_file_normalizes_raw_rows_round_trip(tmp_path):
    path = tmp_path / 'bitget_positions.jsonl'
    with open(path, 'w') as fh:
        fh.write(json.dumps(_raw('a', return_rate='558', net_profit='2.8256')) + '\n')
        fh.write(json.dumps(_shaped('b')) + '\n')

    n_total, n_raw, n_dropped, raw_uids = repair.repair_positions_file(str(path))
    assert n_total == 2 and n_raw == 1 and n_dropped == 0
    assert raw_uids == {'RAWU'}

    rows = [json.loads(l) for l in open(path)]
    repaired = next(r for r in rows if r['orderNo'] == 'a')
    assert repaired['side'] == 'long'
    assert abs(repaired['returnRate'] - 5.58) < 1e-9
    assert 'teacherName' not in repaired and 'hm' not in repaired


def test_repair_positions_file_is_idempotent(tmp_path):
    path = tmp_path / 'bitget_positions.jsonl'
    with open(path, 'w') as fh:
        fh.write(json.dumps(_raw('a')) + '\n')
    repair.repair_positions_file(str(path))
    n_total, n_raw, n_dropped, raw_uids = repair.repair_positions_file(str(path))
    assert n_total == 1 and n_raw == 0 and n_dropped == 0 and raw_uids == set()


def test_repair_positions_file_drops_raw_duplicate_of_already_shaped_row(tmp_path):
    path = tmp_path / 'bitget_positions.jsonl'
    with open(path, 'w') as fh:
        fh.write(json.dumps(_shaped('dup', uid='RAWU', pnl=1.0)) + '\n')
        fh.write(json.dumps(_raw('dup', uid='RAWU', net_profit='999.0')) + '\n')
    n_total, n_raw, n_dropped, raw_uids = repair.repair_positions_file(str(path))
    assert n_total == 2 and n_raw == 1 and n_dropped == 1
    rows = [json.loads(l) for l in open(path)]
    assert len(rows) == 1 and rows[0]['netProfit'] == 1.0


def test_repair_positions_file_missing_file_is_noop(tmp_path):
    assert repair.repair_positions_file(str(tmp_path / 'nope.jsonl')) == (0, 0, 0, set())


def test_backfill_trader_writes_open_cycle_manifest(tmp_path):
    current_list = json.loads((FIXTURES / 'bitget_current_list.json').read_text())
    cycle_data = json.loads((FIXTURES / 'bitget_cycle_data.json').read_text())
    trader_detail = json.loads((FIXTURES / 'bitget_trader_detail.json').read_text())

    def fake_post(url, body, timeout=None):
        if 'currentList' in url:
            return current_list
        if 'cycleData' in url:
            return cycle_data
        if 'traderDetailPageV2' in url:
            return trader_detail
        raise AssertionError(url)

    open_rows, cycle_row, manifest_row = repair.backfill_trader(
        'uidX', 'nameX', 7, 42, fake_post)

    assert len(open_rows) == len(current_list['data']['items'])
    assert cycle_row['traderUid'] == 'uidX' and cycle_row['cycleTime'] == 90
    assert manifest_row['status'] == 'ok'
    assert manifest_row['n_closed'] == 42
    assert manifest_row['n_open'] == len(open_rows)
    assert 'detail_mdd' in manifest_row


def test_main_backfills_only_uids_not_already_ok(tmp_path, monkeypatch):
    data_dir = tmp_path
    (data_dir / 'bitget_positions.jsonl').write_text(
        json.dumps(_raw('a', uid='NEEDS_BACKFILL')) + '\n' +
        json.dumps(_shaped('b', uid='ALREADY_OK')) + '\n'
    )
    (data_dir / 'bitget_manifest.jsonl').write_text(
        json.dumps({'traderUid': 'ALREADY_OK', 'status': 'ok'}) + '\n'
    )
    (data_dir / 'bitget_traders.jsonl').write_text(
        json.dumps({'traderUid': 'NEEDS_BACKFILL', 'displayName': 'needsit', 'followCount': 3}) + '\n'
    )
    (data_dir / 'bitget_open_positions.jsonl').write_text('')
    (data_dir / 'bitget_cycle.jsonl').write_text('')

    current_list = json.loads((FIXTURES / 'bitget_current_list.json').read_text())
    cycle_data = json.loads((FIXTURES / 'bitget_cycle_data.json').read_text())
    trader_detail = json.loads((FIXTURES / 'bitget_trader_detail.json').read_text())

    def fake_post(url, body, timeout=None):
        if 'currentList' in url:
            return current_list
        if 'cycleData' in url:
            return cycle_data
        if 'traderDetailPageV2' in url:
            return trader_detail
        raise AssertionError(f'ALREADY_OK trader must not be re-fetched: {url} {body}')

    monkeypatch.setattr(repair, 'POSITIONS_PATH', str(data_dir / 'bitget_positions.jsonl'))
    monkeypatch.setattr(repair, 'OPEN_PATH', str(data_dir / 'bitget_open_positions.jsonl'))
    monkeypatch.setattr(repair, 'CYCLE_PATH', str(data_dir / 'bitget_cycle.jsonl'))
    monkeypatch.setattr(repair, 'MANIFEST_PATH', str(data_dir / 'bitget_manifest.jsonl'))
    monkeypatch.setattr(repair, 'TRADERS_PATH', str(data_dir / 'bitget_traders.jsonl'))
    monkeypatch.setattr(repair, 'make_session', lambda: None)
    monkeypatch.setattr(repair, 'make_post_fn', lambda session: fake_post)
    monkeypatch.setattr(repair.time, 'sleep', lambda s: None)

    repair.main()

    manifest = [json.loads(l) for l in open(data_dir / 'bitget_manifest.jsonl')]
    uids = {r['traderUid'] for r in manifest}
    assert uids == {'ALREADY_OK', 'NEEDS_BACKFILL'}
    new_entry = next(r for r in manifest if r['traderUid'] == 'NEEDS_BACKFILL')
    assert new_entry['status'] == 'ok' and new_entry['n_closed'] == 1

    # Regression: a second run must still find NEEDS_BACKFILL even though its rows
    # are no longer raw (repair_positions_file already normalized them on the first
    # run) -- `todo` must not be derived from `raw_uids` alone, which goes empty
    # once the file is fully repaired.
    repair.main()
    manifest2 = [json.loads(l) for l in open(data_dir / 'bitget_manifest.jsonl')]
    assert {r['traderUid'] for r in manifest2} == {'ALREADY_OK', 'NEEDS_BACKFILL'}
