import json
import pytest
from pipeline import db as dbmod


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
    (d / "binance_raw.jsonl").write_text(json.dumps(brec) + "\n")
    (d / "phemex_raw.jsonl").write_text(json.dumps(prec) + "\n")
    return d
