import json
from pipeline import scrape


def _fake_post(url, body):
    if "query-list" in url:
        if body["pageNumber"] == 1:
            return {"code": "000000", "data": {"list": [
                {"leadPortfolioId": "P1", "nickname": "alice", "roi": 1, "pnl": 2,
                 "aum": 3, "winRate": 4, "mdd": 5}]}}
        return {"code": "000000", "data": {"list": []}}
    if "position-history" in url:
        if body["pageNumber"] == 1:
            return {"code": "000000", "data": {"list": [{"symbol": "BTCUSDT"}]}}
        return {"code": "000000", "data": {"list": []}}
    raise AssertionError(url)


def _fake_get(url):
    if "user/recommend" in url:
        if "pageNum=1" in url:
            return {"code": 0, "data": {"rows": [
                {"userId": 7, "nickName": "bob", "pnlRate30d": 1, "pnl30d": 2,
                 "tradeWinRate30d": 3, "aum": 4, "followerCount": 5, "mdd30d": 6,
                 "showPosition": True}]}}
        return {"code": 0, "data": {"rows": []}}
    if "position/closed/v2" in url:
        if "pageNum=1" in url:
            return {"code": 0, "data": {"rows": [{"symbol": "ETHUSDT"}]}}
        return {"code": 0, "data": {"rows": []}}
    raise AssertionError(url)


def test_binance_scrape_writes_snapshot(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1
    line = json.loads((tmp_path / "binance_raw.jsonl").read_text().strip())
    assert line["portfolioId"] == "P1" and line["positions"][0]["symbol"] == "BTCUSDT"


def test_binance_scrape_resumes(tmp_path):
    scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 0          # already there, no re-scrape
    lines = (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1                  # no duplicates


def test_network_error_does_not_mark_trader_done(tmp_path):
    def _err_post(url, body):
        if "query-list" in url:
            return _fake_post(url, body)
        return {"code": "ERR"}              # history always fails
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_err_post)
    assert counts["binance"] == 0           # nothing written
    raw = tmp_path / "binance_raw.jsonl"
    assert not raw.exists() or raw.read_text().strip() == ""
    # on retry with a healthy network the trader IS fetched (never marked done)
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1


def test_extra_ids_historical_union(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post,
                        extra_ids_binance=("P_OLD",))
    assert counts["binance"] == 2           # P1 (live listing) + P_OLD (historical)
    lines = [json.loads(l) for l in
             (tmp_path / "binance_raw.jsonl").read_text().strip().splitlines()]
    ids = {l["portfolioId"] for l in lines}
    assert ids == {"P1", "P_OLD"}


def test_phemex_scrape_writes_and_resumes(tmp_path):
    counts = scrape.run(tmp_path, exchanges=("phemex",), http_get=_fake_get)
    assert counts["phemex"] == 1
    line = json.loads((tmp_path / "phemex_raw.jsonl").read_text().strip())
    assert line["userId"] == 7 and line["nick"] == "bob"
    assert line["positions"][0]["symbol"] == "ETHUSDT"
    counts = scrape.run(tmp_path, exchanges=("phemex",), http_get=_fake_get)
    assert counts["phemex"] == 0            # resume: no re-scrape
    lines = (tmp_path / "phemex_raw.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


def test_phemex_network_error_does_not_mark_trader_done(tmp_path):
    def _err_get(url):
        if "user/recommend" in url:
            return _fake_get(url)
        return {"error": "fail"}
    counts = scrape.run(tmp_path, exchanges=("phemex",), http_get=_err_get)
    assert counts["phemex"] == 0
    raw = tmp_path / "phemex_raw.jsonl"
    assert not raw.exists() or raw.read_text().strip() == ""
    assert scrape.run(tmp_path, exchanges=("phemex",), http_get=_fake_get)["phemex"] == 1


def test_api_error_code_does_not_mark_trader_done(tmp_path):
    """A non-ERR API failure used to break the loop and return ok=True, writing a
    truncated history that the resume would never retry."""
    def _bad_code_post(url, body):
        if "query-list" in url:
            return _fake_post(url, body)
        return {"code": "000002", "message": "rate limited"}
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_bad_code_post)
    assert counts["binance"] == 0
    raw = tmp_path / "binance_raw.jsonl"
    assert not raw.exists() or raw.read_text().strip() == ""
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_fake_post)
    assert counts["binance"] == 1


def test_empty_data_is_a_genuine_end_not_a_failure(tmp_path):
    """code 000000 with no payload = a trader with no history: write them as done."""
    def _empty_post(url, body):
        if "query-list" in url:
            return _fake_post(url, body)
        return {"code": "000000", "data": None}
    counts = scrape.run(tmp_path, exchanges=("binance",), http_post=_empty_post)
    assert counts["binance"] == 1
    rec = json.loads((tmp_path / "binance_raw.jsonl").read_text().strip())
    assert rec["positions"] == [] and rec["n_pos"] == 0
