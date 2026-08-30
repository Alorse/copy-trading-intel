"""Flattens data/bybit_positions.jsonl into a flat CSV, one row per closed position.
Downloads nothing: reads only the local data/. Mirrors okx_flatten.py's shape.

`pnl_usd` (orderNetProfitE8/1e8) is Bybit's own field name for it: **NET** of fees
by name, not yet independently reconstructed against gross price return the way
Binance/OKX were (declared, not verified — see scrape_bybit_positions.py's docstring).
"""
import json, csv, os

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)

COLS = ['leader_mark', 'leader_user_id', 'nick', 'symbol', 'side', 'leverage',
        'entry_price', 'close_price', 'size', 'margin', 'pnl_usd', 'roi',
        'open_fee', 'close_fee', 'funding_fee', 'started_ms', 'closed_ms', 'dur_h',
        'follower_num', 'full_closed', 'order_id']


def row_from_position(p):
    started, closed = p.get('started_ms'), p.get('closed_ms')
    dur = (closed - started) / 3600000 if (started and closed) else ''
    return [p.get('leaderMark'), p.get('leaderUserId'), p.get('nickName'),
            p.get('symbol'), p.get('side'), p.get('leverage'),
            p.get('entry_price'), p.get('close_price'), p.get('size'),
            p.get('margin'), p.get('pnl_usd'), p.get('roi'),
            p.get('open_fee'), p.get('close_fee'), p.get('funding_fee'),
            started, closed, dur, p.get('follower_num'), p.get('full_closed'),
            p.get('orderId')]


def flatten(data_dir=D, out_dir=OUT):
    """Reads <data_dir>/bybit_positions.jsonl, writes <out_dir>/bybit_positions.csv.
    Returns the row count (0, and no file written, if the input is missing).

    Dedups on read by `orderId` (the natural key — see checklist Phase 3): the
    manifest's resumability model is append-only and can't itself guarantee a
    position is written at most once."""
    in_path = os.path.join(data_dir, 'bybit_positions.jsonl')
    if not os.path.exists(in_path):
        return 0
    n = 0
    seen = set()
    with open(os.path.join(out_dir, 'bybit_positions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for line in open(in_path):
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            key = p.get('orderId')
            if key in seen:
                continue
            seen.add(key)
            w.writerow(row_from_position(p))
            n += 1
    return n


if __name__ == '__main__':
    print('bybit_positions.csv rows:', flatten())
