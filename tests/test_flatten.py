import csv
from pipeline import flatten


def test_flatten_writes_both_csvs(snap_dir):
    counts = flatten.flatten_snapshot(snap_dir)
    assert counts == {"binance": 1, "phemex": 1}
    rows = list(csv.DictReader(open(snap_dir / "binance.csv")))
    assert rows[0]["portfolio_id"] == "P1"
    assert float(rows[0]["notional"]) == 200.0          # 2 * 100
    assert float(rows[0]["margin_est"]) == 40.0         # 200 / 5
    assert abs(float(rows[0]["dur_h"]) - 1.0) < 1e-9
    prows = list(csv.DictReader(open(snap_dir / "phemex.csv")))
    assert prows[0]["trader_id"] == "7"


def test_flatten_missing_file_is_zero(snap_dir):
    (snap_dir / "phemex_raw.jsonl").unlink()
    counts = flatten.flatten_snapshot(snap_dir)
    assert counts["phemex"] == 0
