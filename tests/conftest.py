import json
import pytest
from pipeline import db as dbmod


def insert_trader_snapshot(con, date, exchange, tid, nick=None, roi=50.0, pnl=0.0,
                           aum=0.0, win_rate=0.0, mdd=0.0, start_time=None,
                           listed=1):
    """One row of trader_snapshot, by column name.

    Spelled out here rather than in each test file so that adding a column is a
    one-line change: `listed` cost four identical edits across test files that
    do not care about it. tests/test_db.py deliberately does NOT use this -- it
    hand-writes a pre-migration 9-column table as its fixture.
    """
    con.execute(
        "INSERT INTO trader_snapshot (snapshot_date,exchange,trader_id,nick,"
        "roi,pnl,aum,win_rate,mdd,start_time,listed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (date, exchange, tid, tid if nick is None else nick, roi, pnl, aum,
         win_rate, mdd, start_time, listed))
    con.commit()


@pytest.fixture
def con(tmp_path):
    c = dbmod.connect(tmp_path / "t.sqlite")
    yield c
    c.close()


@pytest.fixture
def snap_dir(tmp_path):
    d = tmp_path / "2026-09-01"
    d.mkdir()
    brec = {"portfolioId": "P1", "nick": "alice", "roi": 100.0, "pnl": 50.0,
            "aum": 1000.0, "winRate": 60.0, "mdd": 0.2, "n_pos": 1,
            "positions": [{"symbol": "BTCUSDT", "side": "Long", "leverage": "5",
                           "isolated": "Cross", "avgCost": "100", "avgClosePrice": "110",
                           "closingPnl": "10", "roi": "0.5", "maxOpenInterest": "2",
                           "closedVolume": "2", "opened": 1756000000000,
                           "closed": 1756003600000}]}
    prec = {"userId": 7, "nick": "bob", "n_pos": 1,
            "positions": [{"symbol": "ETHUSDT", "side": "Sell", "posSide": "Short",
                           "size": "1", "openPrice": "2000", "closePrice": "1900",
                           "openPositionVal": "2000", "margin": "200", "roi": "0.5",
                           "closedPnl": "100", "realizedPnl": "99", "exchangeFee": "1",
                           "fundingFee": "0", "openedTime": 1756000000000,
                           "updatedTime": 1756007200000}]}
    # the real scrape also saves the listing; startTime lives only there
    (d / "binance_list.json").write_text(json.dumps(
        [{"leadPortfolioId": "P1", "startTime": 1735689600000}]))   # 2025-01-01
    (d / "binance_raw.jsonl").write_text(json.dumps(brec) + "\n")
    (d / "phemex_raw.jsonl").write_text(json.dumps(prec) + "\n")
    return d
