import json

from pipeline import report


def test_report_contains_sections(con, tmp_path):
    con.execute(
        "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n,tier,flags)"
        " VALUES ('2026-09-01','binance','v','vicky',100,'X','[\"roi_artifact\"]')")
    con.execute("INSERT INTO trader_snapshot VALUES "
                "('2026-09-01','binance','v','vicky',5435.9,0,0,0,0,NULL)")
    con.commit()
    roster = {"generated": "2026-09-01", "snapshot": "2026-09-01", "engine": "v1.0",
              "traders": [{"exchange": "binance", "portfolio_id": "1", "nick": "suoha",
                           "tier": "A", "weight": 0.5, "score": 4.1,
                           "metrics": {"alpha": 0.016, "t": 6.11, "payoff": 1.04,
                                       "lev_med": 5, "mdd": 20.1, "n": 527,
                                       "n_alpha": 384, "roi": 412.5},
                           "warnings": ["alpha_decay"]}],
              "removed": []}
    diff = {"snapshot": "2026-09-01", "prev": None, "added_a": [], "removed_a": [],
            "weight_moves": [], "new_disqualified_incumbents": [], "material": True}
    p = report.write(con, "2026-09-01", "binance", roster, diff, tmp_path)
    text = open(p).read()
    assert "suoha" in text and "Changes" in text
    assert "vicky" in text and "roi_artifact" in text
    assert "winner" in text.lower() or "half the" in text
    assert "i.i.d." in text and "clustered" in text
    assert "First run" in text
    # n_alpha disclosed: header and row value
    assert "n_alpha" in text
    assert "| 527 | 384 |" in text
    # headline ROI of the roster itself (not just the excluded ones)
    assert "roi%" in text and "412.5" in text


def _roster(**kw):
    t = {"exchange": "binance", "portfolio_id": "1", "nick": "suoha", "tier": "A",
         "weight": 1.0, "score": 4.1, "warnings": [],
         "metrics": {"alpha": 0.016, "t": 6.11, "payoff": 1.04, "lev_med": 5,
                     "mdd": 20.1, "n": 527, "n_alpha": 384, "roi": 412.5}}
    return {"generated": "2026-09-01", "snapshot": "2026-09-01", "engine": "v1.0",
            "traders": [t], "removed": [], **kw}


DIFF = {"snapshot": "2026-09-01", "prev": None, "added_a": [], "removed_a": [],
        "weight_moves": [], "new_disqualified_incumbents": [], "material": True}


def test_reconciliation_line(con, tmp_path):
    # scraped -> with positions -> with metrics: the funnel must be auditable
    con.execute("INSERT INTO snapshots VALUES ('2026-09-01','binance',590,92932,'')")
    for i in range(3):
        con.execute(
            "INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n) "
            "VALUES ('2026-09-01','binance',?,?,10)", (f"t{i}", f"t{i}"))
    con.commit()
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "binance_list.json").write_text(
        json.dumps([{"leadPortfolioId": str(i)} for i in range(600)]))
    p = report.write(con, "2026-09-01", "binance", _roster(), DIFF, tmp_path,
                     snap_dir=snap)
    text = open(p).read()
    assert "600 portfolios scraped → 590 with positions → 3 with metrics" in text


def test_reconciliation_without_snapshot_dir(con, tmp_path):
    # without the scrape's list.json the line drops the first step and does not blow up
    con.execute("INSERT INTO snapshots VALUES ('2026-09-01','binance',590,92932,'')")
    con.execute("INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,n) "
                "VALUES ('2026-09-01','binance','t','t',10)")
    con.commit()
    p = report.write(con, "2026-09-01", "binance", _roster(), DIFF, tmp_path)
    text = open(p).read()
    assert "590 with positions → 1 with metrics" in text
    assert "scraped" not in text
