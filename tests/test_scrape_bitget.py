import json
from pathlib import Path
from scripts import scrape_bitget

FIXTURES = Path(__file__).parent / 'fixtures'
HISTORY_PAGE1 = json.loads((FIXTURES / 'bitget_order_history_page1.json').read_text())


def test_run_without_session_file_is_a_clean_stub(tmp_path):
    status = scrape_bitget.run(out_dir=str(tmp_path))
    assert status['ok'] is False
    assert 'no session file' in status['reason']
    assert not (tmp_path / 'bitget_orders.jsonl').exists()


def test_run_with_session_but_no_uids_is_a_clean_stub(tmp_path):
    status = scrape_bitget.run(out_dir=str(tmp_path), session={'headers': {}, 'trader_uids': []})
    assert status['ok'] is False
    assert 'trader_uids' in status['reason']


def _fake_post(url, body, headers):
    assert body['traderUid'] == 'UID1'
    assert headers.get('dy-token') == 'tok'
    if body['pageNo'] == 1:
        return HISTORY_PAGE1
    return {'code': '00000', 'data': {'rows': [], 'totals': 2, 'nextFlag': False}}


def test_run_fetches_order_history_with_session(tmp_path):
    session = {'headers': {'dy-token': 'tok'}, 'trader_uids': ['UID1']}
    status = scrape_bitget.run(out_dir=str(tmp_path), session=session, http_post=_fake_post)
    assert status == {'ok': True, 'reason': None, 'n_traders': 1, 'n_orders': 2}
    rec = json.loads((tmp_path / 'bitget_orders.jsonl').read_text().strip())
    assert rec['traderUid'] == 'UID1'
    assert rec['n_orders'] == 2
    assert rec['orders'][0]['symbol'] == 'BTCUSDT'


def test_run_reports_stale_tokens_when_every_trader_has_zero_orders(tmp_path):
    def _empty_post(url, body, headers):
        return {'code': '00000', 'data': {'rows': [], 'totals': 0, 'nextFlag': False}}
    session = {'headers': {'dy-token': 'tok'}, 'trader_uids': ['UID1']}
    status = scrape_bitget.run(out_dir=str(tmp_path), session=session, http_post=_empty_post)
    assert status['ok'] is False
    assert 'stale' in status['reason']


def test_fetch_history_network_error_does_not_mark_done():
    def _err_post(url, body, headers):
        return {'code': 'ERR'}
    rows, ok = scrape_bitget.fetch_history('UID1', {}, _err_post)
    assert ok is False
    assert rows == []
