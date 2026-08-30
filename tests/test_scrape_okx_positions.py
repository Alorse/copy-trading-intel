import json
from pathlib import Path
from scripts import scrape_okx_positions as sop

FIXTURES = Path(__file__).parent / 'fixtures'
HISTORY = json.loads((FIXTURES / 'okx_subpositions_history_sample.json').read_text())
NOT_FOUND = json.loads((FIXTURES / 'okx_subpositions_not_found.json').read_text())
CURRENT = json.loads((FIXTURES / 'okx_current_subpositions_sample.json').read_text())
STATS = json.loads((FIXTURES / 'okx_public_stats.json').read_text())
RANK_PAGE1 = json.loads((FIXTURES / 'okx_lead_traders_page1.json').read_text())
RANK_PAGE2_EMPTY = json.loads((FIXTURES / 'okx_lead_traders_page2_empty.json').read_text())


def _fake_get(url):
    if 'public-lead-traders' in url:
        return RANK_PAGE1 if 'page=1' in url else RANK_PAGE2_EMPTY
    if 'public-subpositions-history' in url:
        if 'DA2B29551CBB2AE7' in url:
            return HISTORY
        return NOT_FOUND
    if 'public-current-subpositions' in url:
        if 'DA2B29551CBB2AE7' in url:
            return CURRENT
        return NOT_FOUND
    if 'public-stats' in url:
        return STATS
    raise AssertionError(url)


def test_fetch_closed_and_open_splits_closed_vs_still_open():
    closed, open_rows, status = sop.fetch_closed_and_open('DA2B29551CBB2AE7', _fake_get)
    assert status == 'ok'
    # 3 rows in the fixture: 1 has closeTime=="" (still open), 2 are truly closed
    assert len(closed) == 2
    assert all(r['closeTime'] for r in closed)
    # the still-open history row + the 1 row from public-current-subpositions
    assert len(open_rows) == 2


def test_fetch_closed_and_open_dedupes_by_subPosId():
    # the still-open history row (subPosId ...336768) is NOT the same lot as the
    # current-subpositions row (subPosId ...802496) in the fixtures, so both survive
    closed, open_rows, status = sop.fetch_closed_and_open('DA2B29551CBB2AE7', _fake_get)
    ids = {r['subPosId'] for r in open_rows}
    assert ids == {'3687410355490336768', '3691771538397802496'}


def test_fetch_closed_and_open_not_found_is_terminal_not_error():
    closed, open_rows, status = sop.fetch_closed_and_open('DOES-NOT-EXIST', _fake_get)
    assert status == 'not_found'
    assert closed == [] and open_rows == []


def test_fetch_closed_and_open_network_error_returns_none():
    def _err_get(url):
        if 'public-subpositions-history' in url:
            return {'code': 'ERR'}
        raise AssertionError(url)
    assert sop.fetch_closed_and_open('X', _err_get) is None


def test_history_cap_flagged_in_manifest(tmp_path):
    capped_history = {'code': '0', 'data': [
        {**HISTORY['data'][1], 'subPosId': str(i)} for i in range(sop.HISTORY_CAP)
    ], 'msg': ''}

    def _get(url):
        if 'public-lead-traders' in url:
            return RANK_PAGE1 if 'page=1' in url else RANK_PAGE2_EMPTY
        if 'public-subpositions-history' in url:
            return capped_history
        if 'public-current-subpositions' in url:
            return NOT_FOUND
        raise AssertionError(url)

    sop.run(out_dir=str(tmp_path), pages=5, http_get=_get)
    manifest = [json.loads(l) for l in (tmp_path / 'okx_positions_manifest.jsonl').read_text().splitlines()]
    assert all(m['closed_capped'] for m in manifest)
    assert all(m['n_closed'] == sop.HISTORY_CAP for m in manifest)


def test_run_writes_closed_open_and_manifest(tmp_path):
    counts = sop.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts['processed'] == 2          # both traders in the ranking fixture
    assert counts['closed'] == 2             # only DA2B29551CBB2AE7 has closed rows
    assert counts['open'] == 2

    closed_lines = [json.loads(l) for l in (tmp_path / 'okx_positions.jsonl').read_text().splitlines()]
    assert all(r['uniqueCode'] == 'DA2B29551CBB2AE7' for r in closed_lines)
    assert all('nickName' in r and 'leadDays' in r for r in closed_lines)

    manifest = [json.loads(l) for l in (tmp_path / 'okx_positions_manifest.jsonl').read_text().splitlines()]
    statuses = {m['uniqueCode']: m['status'] for m in manifest}
    assert statuses == {'DA2B29551CBB2AE7': 'ok', 'AB11223344556677': 'not_found'}


def test_run_resumes_via_manifest_not_position_file(tmp_path):
    # AB11223344556677 has zero closed positions and is 'not_found' on both position
    # endpoints -> it must NOT be re-fetched on the next run even though it never wrote
    # a line to okx_positions.jsonl (that file alone can't tell "done" from "not seen yet").
    sop.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    calls = []

    def _counting_get(url):
        calls.append(url)
        return _fake_get(url)

    counts = sop.run(out_dir=str(tmp_path), pages=5, http_get=_counting_get)
    assert counts['processed'] == 0
    assert not any('uniqueCode=AB11223344556677' in c for c in calls)
    assert not any('uniqueCode=DA2B29551CBB2AE7' in c for c in calls)


def test_run_respects_traders_cap(tmp_path):
    counts = sop.run(out_dir=str(tmp_path), pages=5, traders_cap=1, http_get=_fake_get)
    assert counts['processed'] == 1


def test_run_retries_after_error_without_marking_done(tmp_path):
    def _err_get(url):
        if 'public-lead-traders' in url:
            return RANK_PAGE1 if 'page=1' in url else RANK_PAGE2_EMPTY
        return {'code': 'ERR'}

    counts = sop.run(out_dir=str(tmp_path), pages=5, http_get=_err_get)
    assert counts['processed'] == 0
    counts = sop.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts['processed'] == 2


def test_run_optional_stats_reuses_scrape_okx_resumability(tmp_path):
    counts = sop.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get, fetch_stats_flag=True)
    assert counts['stats'] == 2
    stats_lines = [json.loads(l) for l in (tmp_path / 'okx_trader_stats.jsonl').read_text().splitlines()]
    assert {l['uniqueCode'] for l in stats_lines} == {'DA2B29551CBB2AE7', 'AB11223344556677'}
