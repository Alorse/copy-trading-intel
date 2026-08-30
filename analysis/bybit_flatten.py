"""Flattens data/bybit_positions.jsonl into a flat CSV, one row per closed position.
Downloads nothing: reads only the local data/. Mirrors okx_flatten.py's shape.

`pnl_usd` (orderNetProfitE8/1e8) is Bybit's own field name for it: **NET** of fees
by name, not yet independently reconstructed against gross price return the way
Binance/OKX were (declared, not verified — see scrape_bybit_positions.py's docstring).

`entry_price`/`close_price` are kept for reference only — do not use them to derive
a de-leveraged return: an audit found the position-level entry/close price fields
are shared across every order row of a scaled-in/out position, so a naive
`(close/entry - 1)` reconciles with `pnl_usd`'s sign on only ~84% of rows (16% sign
flips). `analysis/bybit_top5.py` derives its de-leveraged return from `roi/leverage`
instead (`roi` is Bybit's own `orderNetProfitRateE4` field, verified self-consistent
with `pnl_usd/margin` to within ~0.02% median relative error on this dataset).

Dedup key is `orderId` (see `flatten()`'s docstring for the None-orderId edge case)."""
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


def flatten(data_dir=D, out_dir=OUT, print_fn=print):
    """Reads <data_dir>/bybit_positions.jsonl, writes <out_dir>/bybit_positions.csv.
    Returns the row count (0, and no file written, if the input is missing).

    Dedups on read by `orderId` (the natural key — see checklist Phase 3): the
    manifest's resumability model is append-only and can't itself guarantee a
    position is written at most once. A row with a missing/`None` `orderId` cannot
    be deduped this way — treating `None` as an ordinary dedup key would silently
    collapse every such row into one (0/11,409 rows hit this on the current
    dataset, but the scraper's field docs don't guarantee `orderId` is always
    present) — so those rows are written through undeduped and counted/warned
    about instead of silently dropped or merged."""
    in_path = os.path.join(data_dir, 'bybit_positions.jsonl')
    if not os.path.exists(in_path):
        return 0
    n = 0
    n_missing_order_id = 0
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
            if key is None:
                n_missing_order_id += 1
                w.writerow(row_from_position(p))
                n += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            w.writerow(row_from_position(p))
            n += 1
    if n_missing_order_id:
        print_fn(f'WARNING: {n_missing_order_id} rows had no orderId — written '
                  f'without dedup protection (see flatten() docstring)')
    return n


if __name__ == '__main__':
    print('bybit_positions.csv rows:', flatten())
