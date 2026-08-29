"""Reproduce el analisis auditado del 2026-08-25 con el pipeline nuevo.
Referencia: analysis/TOP5.md y FINDINGS_v2.md."""
import json, os, pathlib, pytest
from pipeline import db as dbmod, flatten, ingest, metrics, detect, rank

ROOT = pathlib.Path(__file__).parent.parent
SNAP = ROOT / "data" / "snapshots" / "2026-08-25"

# La data cruda NO se versiona (ver .gitignore): son dumps de las APIs de
# Binance/Phemex y no se redistribuyen. Estos 4 tests son opt-in: corren si
# colocas un snapshot en data/snapshots/2026-08-25/. Sin el, se saltan.
pytestmark = pytest.mark.skipif(
    not (SNAP / "binance_raw.jsonl").exists(),
    reason=f"opt-in: requiere un snapshot crudo en {SNAP.relative_to(ROOT)}/ "
           "(binance_raw.jsonl / phemex_raw.jsonl). Genera el tuyo con "
           "`python3 pipeline.py scrape --date <YYYY-MM-DD>`; los valores "
           "esperados aqui son los del snapshot auditado 2026-08-25.")


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
    """Guarda contra la regresion de escala: mdd es PORCENTUAL (Trampa 5)."""
    con, flags, roster = real
    med = con.execute(
        "SELECT mdd FROM trader_snapshot WHERE snapshot_date='2026-08-25' "
        "AND exchange='binance' AND mdd IS NOT NULL ORDER BY mdd "
        "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM trader_snapshot "
        "WHERE snapshot_date='2026-08-25' AND exchange='binance' "
        "AND mdd IS NOT NULL)").fetchone()[0]
    assert 10 <= med <= 60          # mediana real ~30.15; si sale <1, la escala se rompio


def test_known_top_traders_survive(real):
    con, flags, roster = real
    m = _by_nick(con)
    # 梭哈到世界尽头: n=527, t~6, lev 5x, conc top-1 = 26.1% — sobrevive
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
    # OJO: el nick real en la data lleva sufijo — es 龟兔赛跑985-重新起航
    assert "lottery" in json.loads(m["龟兔赛跑985-重新起航"]["flags"])
    assert "ruin_risk" in json.loads(m["牛熊摆渡人"]["flags"])   # lev p90 / -1173%


def test_roster_is_five_and_sane(real):
    con, flags, roster = real
    assert len(roster["traders"]) <= 5
    total = sum(t["weight"] for t in roster["traders"]) + roster["unallocated"]
    assert abs(total - 1.0) < 1e-9   # asignado + sin asignar = 1.0 (corrida #1
                                     # puede ser todo-B -> unallocated > 0)
