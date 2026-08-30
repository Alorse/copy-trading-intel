"""Flattens data/okx_positions.jsonl into a flat CSV, one row per closed position.
Downloads nothing: reads only the local data/. Mirrors flatten.py's Binance/Phemex
columns where the fields map; OKX has no `avg_close`/`side` split like Binance
(it has `posSide` long/short instead) and reports `margin` directly (no notional
inversion needed).

`pnl` is NET of fees — see docs/okx_endpoint_facts.md and scrape_okx_positions.py's
docstring for the verification (96.6% of 558 closed BTC-USDT-SWAP rows show a positive
fee residual, median 6.5 bps of notional)."""
import json, csv, os

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)

COLS = ['unique_code', 'nick', 'lead_days', 'symbol', 'pos_side', 'leverage', 'mgn_mode',
        'open_price', 'close_price', 'margin', 'pnl', 'pnl_ratio', 'size', 'ccy',
        'opened_ms', 'closed_ms', 'dur_h', 'notional']


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def i(x, default=None):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def row_from_position(p):
    o, c = i(p.get('openTime')), i(p.get('closeTime'))
    dur = (c - o) / 3600000 if (o and c) else ''
    lev = f(p.get('lever'), 1.0) or 1.0
    margin = f(p.get('margin'))
    return [p.get('uniqueCode'), p.get('nickName'), p.get('leadDays'),
            p.get('instId'), p.get('posSide'), lev, p.get('mgnMode'),
            f(p.get('openAvgPx')), f(p.get('closeAvgPx')), margin,
            f(p.get('pnl')), f(p.get('pnlRatio')), f(p.get('subPos')),
            p.get('ccy'), o, c, dur, margin * lev]


def flatten(data_dir=D, out_dir=OUT):
    """Reads <data_dir>/okx_positions.jsonl, writes <out_dir>/okx_positions.csv.
    Returns the row count (0, and no file written, if the input is missing).

    Dedups on read by (uniqueCode, subPosId): the manifest's resumability model
    (append-only, driven off a separate ledger file) can't itself guarantee a
    position is written at most once, so this is a defensive belt-and-suspenders
    check, not evidence that duplicates are expected in practice."""
    in_path = os.path.join(data_dir, 'okx_positions.jsonl')
    if not os.path.exists(in_path):
        return 0
    n = 0
    seen = set()
    with open(os.path.join(out_dir, 'okx_positions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for line in open(in_path):
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            key = (p.get('uniqueCode'), p.get('subPosId'))
            if key in seen:
                continue
            seen.add(key)
            w.writerow(row_from_position(p))
            n += 1
    return n


if __name__ == '__main__':
    print('okx_positions.csv rows:', flatten())
