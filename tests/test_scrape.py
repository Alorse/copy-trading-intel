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


# --- lead-portfolio/detail: the LIFETIME copier record (2026-09-23) ----------
# The listing row carries a `copierPnl` too, but it is WINDOW-scoped (the same
# portfolio returns +116 / +147 / +242 / +273 for timeRange 7D/30D/90D/180D
# while `detail` returns -6,117 lifetime). Only `detail` answers "did the people
# who copied this lead make money".

DETAIL_OK = {"code": "000000", "data": {
    "leadPortfolioId": "P1", "nickname": "alice", "status": "ACTIVE",
    "currentCopyCount": 2, "totalCopyCount": 47,
    "marginBalance": "2001.39704602", "aumAmount": "2340.26751620",
    "copierPnl": "-6117.10893387", "fixedAmountMinCopyUsd": 10.0,
    "lastTradeTime": 1790179695096, "positionShow": False}}


def test_detail_writes_one_record_per_portfolio(tmp_path):
    n = scrape.run_detail(tmp_path, ["P1"], http_get_binance=lambda u: DETAIL_OK)
    assert n == 1
    rec = json.loads((tmp_path / "binance_detail.jsonl").read_text().strip())
    assert rec["portfolioId"] == "P1" and rec["status"] == "ACTIVE"
    assert rec["copierPnl"] == -6117.10893387     # string -> float
    assert rec["currentCopyCount"] == 2 and rec["totalCopyCount"] == 47
    assert rec["marginBalance"] == 2001.39704602
    assert rec["aumAmount"] == 2340.26751620
    assert rec["retired"] is False


def test_detail_resumes_without_duplicating(tmp_path):
    scrape.run_detail(tmp_path, ["P1"], http_get_binance=lambda u: DETAIL_OK)
    n = scrape.run_detail(tmp_path, ["P1"], http_get_binance=lambda u: DETAIL_OK)
    assert n == 0
    assert len((tmp_path / "binance_detail.jsonl").read_text().splitlines()) == 1


def test_detail_records_a_retired_portfolio(tmp_path):
    """Code 11012028 (牛熊摆渡人) is an ANSWER, not a failure: the portfolio is
    gone. It is written as done, with every field NULL and retired=True."""
    n = scrape.run_detail(tmp_path, ["DEAD"], http_get_binance=lambda u: {
        "code": "11012028", "data": None})
    assert n == 1
    rec = json.loads((tmp_path / "binance_detail.jsonl").read_text().strip())
    assert rec["retired"] is True and rec["code"] == "11012028"
    assert rec["copierPnl"] is None and rec["totalCopyCount"] is None


def test_detail_missing_fields_stay_null_never_zero(tmp_path):
    """The flatten.py 0.0-default mistake: an absent copierPnl that reaches SQL
    as 0.0 reads as 'copiers broke even', and 0 is not < 0, so the gate would
    silently pass a lead nobody measured."""
    n = scrape.run_detail(tmp_path, ["P2"], http_get_binance=lambda u: {
        "code": "000000", "data": {"leadPortfolioId": "P2", "status": "ACTIVE"}})
    assert n == 1
    rec = json.loads((tmp_path / "binance_detail.jsonl").read_text().strip())
    assert rec["copierPnl"] is None and rec["totalCopyCount"] is None
    assert rec["marginBalance"] is None and rec["aumAmount"] is None


def test_detail_network_failure_does_not_mark_done(tmp_path):
    n = scrape.run_detail(tmp_path, ["P1"], http_get_binance=lambda u: {"code": "ERR"})
    assert n == 0
    path = tmp_path / "binance_detail.jsonl"
    assert not path.exists() or path.read_text().strip() == ""
    # the resume picks it up again
    assert scrape.run_detail(tmp_path, ["P1"],
                             http_get_binance=lambda u: DETAIL_OK) == 1


def test_detail_backs_off_on_the_rate_limit_code_and_retries(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(scrape.time, "sleep", slept.append)
    calls = []

    def _get(url):
        calls.append(url)
        return {"code": "11012005"} if len(calls) < 3 else DETAIL_OK

    assert scrape.run_detail(tmp_path, ["P1"], http_get_binance=_get) == 1
    assert len(calls) == 3
    # the two back-offs grow and are both longer than the normal pacing
    backoffs = [s for s in slept if s > scrape.DETAIL_SLEEP]
    assert len(backoffs) == 2 and backoffs[1] > backoffs[0]


def test_detail_paces_at_least_the_configured_delay(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(scrape.time, "sleep", slept.append)
    scrape.run_detail(tmp_path, ["P1", "P2", "P3"],
                      http_get_binance=lambda u: DETAIL_OK)
    assert scrape.DETAIL_SLEEP >= 1.5
    assert len([s for s in slept if s >= scrape.DETAIL_SLEEP]) >= 3
