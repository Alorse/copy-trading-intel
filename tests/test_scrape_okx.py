import json
from pathlib import Path
from scripts import scrape_okx

FIXTURES = Path(__file__).parent / 'fixtures'
PAGE1 = json.loads((FIXTURES / 'okx_lead_traders_page1.json').read_text())
PAGE2_EMPTY = json.loads((FIXTURES / 'okx_lead_traders_page2_empty.json').read_text())
STATS = json.loads((FIXTURES / 'okx_public_stats.json').read_text())


def _fake_get(url):
    if 'public-lead-traders' in url:
        assert 'sortType' not in url          # any sortType -> 51000 on the real API
        if 'page=1' in url:
            return PAGE1
        return PAGE2_EMPTY
    if 'public-stats' in url:
        assert 'lastDays=3' in url             # only {1,2,3} are valid
        return STATS
    raise AssertionError(url)


def test_fetch_ranking_stops_at_empty_page():
    rows = scrape_okx.fetch_ranking(pages=5, get_fn=_fake_get)
    assert len(rows) == 2
    codes = {r['uniqueCode'] for r in rows}
    assert codes == {'DA2B29551CBB2AE7', 'AB11223344556677'}


def test_fetch_ranking_respects_pages_cap():
    calls = []

    def _counting_get(url):
        calls.append(url)
        return _fake_get(url)
    scrape_okx.fetch_ranking(pages=1, get_fn=_counting_get)
    assert len(calls) == 1                     # never asked for page 2


def test_run_writes_traders_and_stats(tmp_path):
    counts = scrape_okx.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts == {'ranking': 2, 'stats': 2}
    lines = (tmp_path / 'okx_traders.jsonl').read_text().strip().splitlines()
    assert len(lines) == 2
    stats_lines = [json.loads(l) for l in
                   (tmp_path / 'okx_trader_stats.jsonl').read_text().strip().splitlines()]
    assert {l['uniqueCode'] for l in stats_lines} == {'DA2B29551CBB2AE7', 'AB11223344556677'}
    assert stats_lines[0]['winRatio'] == '0.5714'


def test_run_resumes_stats(tmp_path):
    scrape_okx.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    counts = scrape_okx.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts['stats'] == 0                # already have both uniqueCodes
    lines = (tmp_path / 'okx_trader_stats.jsonl').read_text().strip().splitlines()
    assert len(lines) == 2                     # no duplicates


def test_stats_network_error_does_not_mark_trader_done(tmp_path):
    def _err_get(url):
        if 'public-lead-traders' in url:
            return _fake_get(url)
        return {'code': 'ERR'}
    counts = scrape_okx.run(out_dir=str(tmp_path), pages=5, http_get=_err_get)
    assert counts['stats'] == 0
    path = tmp_path / 'okx_trader_stats.jsonl'
    assert not path.exists() or path.read_text().strip() == ''
    counts = scrape_okx.run(out_dir=str(tmp_path), pages=5, http_get=_fake_get)
    assert counts['stats'] == 2                 # retried, not skipped
