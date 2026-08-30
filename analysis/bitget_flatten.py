"""Flattens data/bitget_positions.jsonl into a flat CSV, one row per closed
order/fill. Downloads nothing: reads only the local data/. Mirrors
bybit_flatten.py's shape and dedup discipline.

`net_profit` is Bitget's own field (net of `open_fee`+`close_fee`+`capital_fee` by
construction of the exchange's own accounting, not independently reconstructed
from prices here — see scrape_bitget_positions.py's docstring for why: price-based
reconstruction disagreed in SIGN with `net_profit` on 10.1% of a 455-row live
sample). `analysis/bitget_top5.py` derives its de-leveraged return from
`return_rate / open_level` instead (verified self-consistent against
`net_profit / margin` to a median 0.8pp / p90 6.0pp absolute deviation on that same
sample — the decided fallback basis, weaker than Bybit's 0.02%/0.16% but an order
of magnitude better than the price-derived basis's 10% sign-flip rate).

`open_avg_price`/`close_avg_price` are kept in the CSV for reference only — do not
derive a return from them (see above).

Dedup key is `(trader_uid, order_no)` (see `flatten()`'s docstring for the missing-key
edge case).

## Raw vs shaped rows (Fable-2 / GLM-1)

`data/bitget_positions.jsonl` can carry TWO row shapes. Most rows are "shaped": the
output of `scrape_bitget_positions.row_from_history` (numeric fields coerced,
`side`/`position_raw` instead of a bare `position` int, `returnRate` already a
fraction). A minority were hand-fetched straight from the `historyList` API response
during an outage (four traders whose scrape got stuck on repeated transport timeouts,
see `scripts/bitget_repair_raw_rows.py`) and are "raw": the untouched API entry, with
`position` (1/0, not `side`), `returnRate` as a PERCENT string ("558" == 558%, not
5.58), numeric fields as strings, and extra keys (`teacherName`, `hm`, ...) that a
shaped row never has. `is_raw_row`/`normalize_row` detect and fix this on read, here
and in the one-shot repair script, both by reusing `row_from_history` (never
reimplementing the coercion/percent-division logic).

`dedup_rows` also carries the "going forward" rule: on a `(trader_uid, order_no)`
collision, a shaped row always wins over a raw one (a proper scrape supersedes a
hand-fetched placeholder), and among same-shapedness duplicates the last one in file
order wins. This makes `flatten()` robust to raw rows reappearing later (e.g. another
manual hand-fetch during a future outage) without needing another repair pass.
"""
import json, csv, os, sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)
if BASE not in sys.path:            # so `python3 analysis/bitget_flatten.py` (run
    sys.path.insert(0, BASE)        # from repo root, cwd on sys.path, not BASE) can
                                     # still `from scripts... import row_from_history`

COLS = ['trader_uid', 'display_name', 'symbol_id', 'product_code', 'side',
        'open_level', 'open_avg_price', 'close_avg_price', 'open_deal_count',
        'close_deal_count', 'margin', 'net_profit', 'return_rate', 'open_fee',
        'close_fee', 'capital_fee', 'open_time', 'close_time', 'dur_h',
        'margin_mode', 'order_no']


def row_from_position(p):
    started, closed = p.get('openTime'), p.get('closeTime')
    try:
        started = int(started) if started not in (None, '') else None
        closed = int(closed) if closed not in (None, '') else None
    except (TypeError, ValueError):
        started = closed = None
    dur = (closed - started) / 3600000 if (started and closed) else ''
    return [p.get('traderUid'), p.get('displayName'), p.get('symbolId'),
            p.get('productCode'), p.get('side'), p.get('openLevel'),
            p.get('openAvgPrice'), p.get('closeAvgPrice'), p.get('openDealCount'),
            p.get('closeDealCount'), p.get('openMarginCount'), p.get('netProfit'),
            p.get('returnRate'), p.get('openFee'), p.get('closeFee'),
            p.get('capitalFee'), started, closed, dur, p.get('marginMode'),
            p.get('orderNo')]


def is_raw_row(p):
    """A raw, un-normalized historyList entry (hand-fetched, bypassing
    `scrape_bitget_positions.row_from_history`) carries the API's own `position`
    key (1/0) and/or `teacherName` — fields a normalized row never has (normalized
    rows store `position_raw` instead, see `row_from_history`)."""
    return 'position' in p or 'teacherName' in p


def normalize_row(p):
    """Passes shaped rows through unchanged; repairs a raw row via
    `scrape_bitget_positions.row_from_history` (reused, not reimplemented) so the
    percent-encoded `returnRate` and string-typed numeric fields get the exact same
    coercion a normal scrape would have applied."""
    if not is_raw_row(p):
        return p
    from scripts.scrape_bitget_positions import row_from_history
    return row_from_history(p, p.get('traderUid') or p.get('teacherId'),
                             p.get('displayName') or p.get('teacherName'))


def dedup_rows(rows):
    """Normalizes raw rows and dedups on `(trader_uid, order_no)`. On a collision a
    shaped row always wins over a raw one ("going forward" rule, see module
    docstring); among same-shapedness duplicates the last one in file order wins.
    A row with a missing/`None` `order_no` bypasses dedup entirely (the natural key
    doesn't exist) and is passed through, matching bybit_flatten.py's precedent of
    counting rather than silently dropping it.

    Returns (ordered_rows, n_missing_order_no)."""
    best = {}
    passthrough = []
    n_missing = 0
    for p in rows:
        was_raw = is_raw_row(p)
        norm = normalize_row(p)
        order_no = norm.get('orderNo')
        if order_no is None:
            n_missing += 1
            passthrough.append(norm)
            continue
        key = (norm.get('traderUid'), order_no)
        existing = best.get(key)
        if existing is not None and existing[1] and was_raw:
            continue    # keep the existing shaped row, drop this raw duplicate
        best[key] = (norm, not was_raw)
    return passthrough + [p for p, _ in best.values()], n_missing


def flatten(data_dir=D, out_dir=OUT, print_fn=print):
    """Reads <data_dir>/bitget_positions.jsonl, writes <out_dir>/bitget_positions.csv.
    Returns the row count (0, and no file written, if the input is missing).

    Dedups via `dedup_rows` (the natural key, checklist Phase 3): the manifest's
    resumability model is append-only and can't itself guarantee a row is written
    at most once."""
    in_path = os.path.join(data_dir, 'bitget_positions.jsonl')
    if not os.path.exists(in_path):
        return 0
    rows = [json.loads(line) for line in open(in_path) if line.strip()]
    out_rows, n_missing_order_no = dedup_rows(rows)
    with open(os.path.join(out_dir, 'bitget_positions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for p in out_rows:
            w.writerow(row_from_position(p))
    if n_missing_order_no:
        print_fn(f'WARNING: {n_missing_order_no} rows had no order_no — written '
                  f'without dedup protection (see flatten() docstring)')
    return len(out_rows)


if __name__ == '__main__':
    print('bitget_positions.csv rows:', flatten())
