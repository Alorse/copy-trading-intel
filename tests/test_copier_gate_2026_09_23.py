"""Regression: the 2026-09-23 roster, pinned on the real rows of that run.

The raw snapshot is not versioned (see tests/test_regression.py), so this test
carries the eight portfolios the 2026-09-23 re-audit argued about, exactly as
the pipeline measured them: the six that survive every pre-copier-gate
disqualifier, plus 秋高看山势 and 再也不做空了 as the thin-sample controls. Every
figure below is already published in analysis/COMBINED_RANKING.md.

No network, no raw data: the fixture is the DB rows, and the test runs the real
detect -> trend -> rank over them. The 2026-08-28 half of each row is there
because `trend` adds the cross-snapshot half of `alpha_decay` and feeds
`trend_bonus` into the score: without it the run is not the run.
"""
import json, pathlib
import pytest
from pipeline import detect, rank, trend

D, EX = "2026-09-23", "binance"
FIXTURE = (pathlib.Path(__file__).parent / "fixtures" /
           "binance_2026-09-23_candidates.json")
ROWS = json.loads(FIXTURE.read_text())
BY_LABEL = {r["label"]: r for r in ROWS}


PREV = "2026-08-28"


@pytest.fixture
def run23(con):
    """The eight portfolios loaded into a fresh DB, then detect -> trend -> rank."""
    for d in (PREV, D):
        con.execute("INSERT INTO snapshots VALUES (?,?,8,8,'')", (d, EX))
    for r in ROWS:
        p = r["prev_2026_08_28"]
        if p:
            con.execute(
                f"INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,"
                f"nick,{','.join(p)}) VALUES (?,?,?,?,?,?,?)",
                (PREV, EX, r["trader_id"], r["nick"], *p.values()))
        m = dict(r["metrics"])
        for k in ("score", "tier", "weight", "flags", "trend_bonus"):  # computed
            m.pop(k)
        con.execute(
            f"INSERT INTO trader_metrics (snapshot_date,exchange,trader_id,nick,"
            f"{','.join(m)}) VALUES (?,?,?,?,{','.join('?' * len(m))})",
            (D, EX, r["trader_id"], r["nick"], *m.values()))
        s = r["snapshot"]
        con.execute(
            f"INSERT INTO trader_snapshot (snapshot_date,exchange,trader_id,nick,"
            f"{','.join(s)}) VALUES (?,?,?,?,{','.join('?' * len(s))})",
            (D, EX, r["trader_id"], r["nick"], *s.values()))
        # one position carrying the trader's real realized PnL: that is what the
        # copier gate compares the copiers' loss against
        con.execute(
            "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,"
            "side,opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,"
            "partial,avg_cost,avg_close) VALUES (?,?,?,?,'BTCUSDT','Long',?,?,"
            "1,1,1,1,?,0,1,1)",
            (D, EX, r["trader_id"], r["nick"], r["last_opened_ms"],
             r["last_closed_ms"], r["realized_pnl"]))
    con.commit()
    detect.run(con, D, EX)
    trend.run(con, D, EX)
    roster = rank.run(con, D, EX)
    flags = {r["trader_id"]: json.loads(r["flags"]) for r in con.execute(
        "SELECT trader_id, flags FROM trader_metrics WHERE snapshot_date=?", (D,))}
    return con, flags, roster


def test_copier_gate_removes_exactly_two_of_the_six_survivors(run23):
    _, flags, _ = run23
    gated = {lab for lab, r in BY_LABEL.items()
             if "copiers_losing" in flags[r["trader_id"]]}
    assert gated == {"tangpumao", "zhshengsheng"}


def test_the_gate_spares_the_thin_and_the_shallow(run23):
    """The three negative copier records it must NOT act on: 再也不做空了 (2
    copiers, -$11.79), 秋高看山势 (10 copiers, -$9.72 each) and 黑袍小分队 (19
    copiers, -$9.92 each, 3.8% of the lead's own realized PnL)."""
    _, flags, _ = run23
    for lab in ("zaiyebuzuokongle", "qiugao", "heipao"):
        r = BY_LABEL[lab]
        assert r["snapshot"]["copier_pnl"] < 0, lab       # negative, and spared
        assert "copiers_losing" not in flags[r["trader_id"]], lab


def test_the_2026_09_23_roster(run23):
    """The roster this run publishes: four tier-B traders at the 10% cap and
    60% of the book unallocated. 汤普猫 held 70% before the gate and the cap."""
    _, _, roster = run23
    assert [(t["nick"], t["tier"], t["weight"]) for t in roster["traders"]] == [
        ("梭哈到世界尽头", "B", 0.10),
        ("Cooma", "B", 0.10),
        ("黑袍小分队", "B", 0.10),
        ("狱萝", "B", 0.10)]
    assert roster["unallocated"] == 0.60
    assert all(t["weight"] <= rank.MAX_WEIGHT for t in roster["traders"])


def test_the_gated_leads_are_out_of_the_roster_and_tiered_X(run23):
    con, _, roster = run23
    assert {t["portfolio_id"] for t in roster["traders"]}.isdisjoint(
        {BY_LABEL["tangpumao"]["trader_id"],
         BY_LABEL["zhshengsheng"]["trader_id"]})
    tiers = {r["trader_id"]: r["tier"] for r in con.execute(
        "SELECT trader_id, tier FROM trader_metrics WHERE snapshot_date=?", (D,))}
    # a measured defect, not a gap in the data: X, beside loss_hider
    assert tiers[BY_LABEL["tangpumao"]["trader_id"]] == "X"
    assert tiers[BY_LABEL["zhshengsheng"]["trader_id"]] == "X"


def test_the_fixture_still_matches_the_run_it_was_taken_from(run23):
    """Whatever else changes, these stay the flags of that snapshot's rows."""
    con, flags, _ = run23
    for r in ROWS:
        got = set(flags[r["trader_id"]])
        assert got == set(json.loads(r["metrics"]["flags"])), r["label"]
        score = con.execute(
            "SELECT score FROM trader_metrics WHERE snapshot_date=? "
            "AND trader_id=?", (D, r["trader_id"])).fetchone()[0]
        assert abs(score - r["metrics"]["score"]) < 1e-9, r["label"]
