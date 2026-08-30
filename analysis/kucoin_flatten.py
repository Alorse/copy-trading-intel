"""Flattens data/kucoin_positions.jsonl into a flat CSV, one row per closed
position. Downloads nothing: reads only the local data/. Mirrors
bitget_flatten.py's shape and dedup discipline.

`pnl` is KuCoin's own field, verified NET of fees in
`scripts/scrape_kucoin_positions.py`'s docstring (median -12.0bps of notional,
91.6% negative over a 395-row live sample — the same fee-deducted signature as
every other exchange in this project). `analysis/kucoin_top5.py` derives its
de-leveraged return from `pnlRatio / leverage` (verified self-consistent:
`pnlRatio == pnl / posMargin` to a median 5.8e-6 absolute difference, n=395).

Dedup key is `(lead_config_id, symbol, start_time, end_time)` — KuCoin's
`positions/history` rows carry NO natural per-row id (unlike Bitget's
`orderNo` or Bybit's `orderId`); this composite key was verified unique across
a live 260-row single-trader sample (0 collisions). See
`scrape_kucoin_positions.row_from_history`'s docstring.
"""
import json, csv, os, collections

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)

COLS = ['lead_config_id', 'nick_name', 'symbol', 'side', 'position_side',
        'leverage', 'margin_mode', 'pnl', 'pnl_ratio', 'margin', 'close_qty',
        'avg_entry_price', 'avg_close_price', 'multiplier', 'currency',
        'start_time', 'end_time', 'dur_h']


def row_from_position(p):
    started, closed = p.get('startTime'), p.get('endTime')
    dur = (closed - started) / 3600000 if (started and closed) else ''
    return [p.get('leadConfigId'), p.get('nickName'), p.get('symbol'), p.get('side'),
            p.get('positionSide'), p.get('leverage'), p.get('marginMode'),
            p.get('pnl'), p.get('pnlRatio'), p.get('posMargin'), p.get('closeQty'),
            p.get('avgEntryPrice'), p.get('avgClosePrice'), p.get('multiplier'),
            p.get('currency'), started, closed, dur]


def dedup_rows(rows):
    """Dedups on `(leadConfigId, symbol, startTime, endTime)`. Last one in file
    order wins (matches sibling flatteners' resumability precedent: a kill
    between a flush and the manifest 'done' line could otherwise duplicate a
    trader's rows across a resumed run). A row missing any key field bypasses
    dedup entirely and is passed through, counted separately.

    Returns (ordered_rows, n_missing_key)."""
    best = {}
    passthrough = []
    n_missing = 0
    for p in rows:
        lead_id, sym = p.get('leadConfigId'), p.get('symbol')
        start, end = p.get('startTime'), p.get('endTime')
        if lead_id is None or sym is None or start is None or end is None:
            n_missing += 1
            passthrough.append(p)
            continue
        best[(lead_id, sym, start, end)] = p
    return passthrough + list(best.values()), n_missing


def flatten(data_dir=D, out_dir=OUT, print_fn=print):
    """Reads <data_dir>/kucoin_positions.jsonl, writes <out_dir>/kucoin_positions.csv.
    Returns the row count (0, and no file written, if the input is missing)."""
    in_path = os.path.join(data_dir, 'kucoin_positions.jsonl')
    if not os.path.exists(in_path):
        return 0
    rows = [json.loads(line) for line in open(in_path) if line.strip()]
    out_rows, n_missing_key = dedup_rows(rows)
    with open(os.path.join(out_dir, 'kucoin_positions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for p in out_rows:
            w.writerow(row_from_position(p))
    if n_missing_key:
        print_fn(f'WARNING: {n_missing_key} rows had a missing dedup-key field — '
                  f'written without dedup protection (see flatten() docstring)')
    return len(out_rows)


if __name__ == '__main__':
    print('kucoin_positions.csv rows:', flatten())
