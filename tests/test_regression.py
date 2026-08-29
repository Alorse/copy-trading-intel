"""Reproduces the audited 2026-08-25 analysis with the new pipeline.
Reference: analysis/TOP5.md and FINDINGS_v2.md."""
import json, os, pathlib, pytest
from pipeline import db as dbmod, flatten, ingest, metrics, detect, rank

ROOT = pathlib.Path(__file__).parent.parent
SNAP = ROOT / "data" / "snapshots" / "2026-08-25"

# The raw data is NOT versioned (see .gitignore): they are dumps of the
# Binance/Phemex APIs and are not redistributed. These 4 tests are opt-in: they
# run if you drop a snapshot into data/snapshots/2026-08-25/. Without it, they skip.
pytestmark = pytest.mark.skipif(
    not (SNAP / "binance_raw.jsonl").exists(),
    reason=f"opt-in: needs a raw snapshot in {SNAP.relative_to(ROOT)}/ "
           "(binance_raw.jsonl / phemex_raw.jsonl). Generate your own with "
           "`python3 pipeline.py scrape --date <YYYY-MM-DD>`; the values "
           "expected here are those of the audited 2026-08-25 snapshot.")


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    con = dbmod.connect(tmp_path_factory.mktemp("db") / "r.sqlite")
    flatten.flatten_snapshot(SNAP)
    ingest.ingest_snapshot(con, SNAP, "2026-08-25")
    metrics.compute(con, "2026-08-25")
    flags = detect.run(con, "2026-08-25")
    roster = rank.run(con, "2026-08-25")
    return con, flags, roster


def _by_nick(con):
    return {r["nick"]: r for r in con.execute(
        "SELECT * FROM trader_metrics WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance'")}


def test_mdd_scale_is_percentage(real):
    """Guards against the scale regression: mdd is a PERCENTAGE (Trap 5)."""
    con, flags, roster = real
    med = con.execute(
        "SELECT mdd FROM trader_snapshot WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance' AND mdd IS NOT NULL ORDER BY mdd "
        "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM trader_snapshot "
        "WHERE snapshot_date='2026-08-25' AND exchange='binance' "
        "AND mdd IS NOT NULL)").fetchone()[0]
    assert 10 <= med <= 60          # real median ~30.15; if <1, the scale broke


def test_known_top_traders_survive(real):
    con, flags, roster = real
    m = _by_nick(con)
    # 梭哈到世界尽头: n=527, t~6, lev 5x, top-1 conc = 26.1% — survives
    s = m["梭哈到世界尽头"]
    assert s["n"] > 400 and s["t_stat"] > 4
    assert s["conc_top1"] < 30
    assert not (set(json.loads(s["flags"])) & detect.DISQUALIFYING)


def test_known_frauds_are_flagged(real):
    con, flags, roster = real
    m = _by_nick(con)
    assert "roi_artifact" in json.loads(m["VickyKaushal"]["flags"]) or \
           "no_alpha" in json.loads(m["VickyKaushal"]["flags"])
    assert "loss_hider" in json.loads(m["GGbond哦"]["flags"])
    # CAREFUL: the real nick in the data carries a suffix — 龟兔赛跑985-重新起航
    assert "lottery" in json.loads(m["龟兔赛跑985-重新起航"]["flags"])
    assert "ruin_risk" in json.loads(m["牛熊摆渡人"]["flags"])   # lev p90 / -1173%


def test_roster_is_five_and_sane(real):
    con, flags, roster = real
    assert len(roster["traders"]) <= 5
    total = sum(t["weight"] for t in roster["traders"]) + roster["unallocated"]
    assert abs(total - 1.0) < 1e-9   # allocated + unallocated = 1.0 (run #1 can
                                     # be all-B -> unallocated > 0)
