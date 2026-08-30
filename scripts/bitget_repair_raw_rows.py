#!/usr/bin/env python3
"""One-shot repair for `data/bitget_positions.jsonl`'s raw-row contamination
(Fable-2 / GLM-1). Four traders (Low-Risk-Collat-Mgmt, kitawaraison, 0xice,
TomFält) got stuck on repeated `historyList` transport timeouts (see
`scripts/scrape_bitget_positions.py`'s pre-fix retry bug) and were hand-fetched
straight from the API instead — their rows in `bitget_positions.jsonl` are the raw
API entries (`position` int, `returnRate` as a PERCENT string, numeric fields as
strings, extra `teacherName`/`hm` keys), not the scraper's normalized shape.

This script:
  1. Rewrites `data/bitget_positions.jsonl` IN PLACE, normalizing every raw row via
     `analysis.bitget_flatten.dedup_rows` (which reuses
     `scrape_bitget_positions.row_from_history` — the exact same coercion/percent-
     division logic a normal scrape would have applied, not reimplemented) and
     dropping any raw row that collides with an already-shaped row for the same
     `(trader_uid, order_no)`.
  2. For every trader who had at least one raw row and is not yet `ok`/`protected`
     in `data/bitget_manifest.jsonl`, fetches the missing `cycleData` (90d),
     `currentList` (open positions) and `traderDetailPageV2` (headline) via the
     scraper's own functions, appends the results to `data/bitget_open_positions.
     jsonl` / `data/bitget_cycle.jsonl`, and appends an `ok` manifest entry so
     `analysis/bitget_top5.py` picks these traders up like any other.

Idempotent: re-running is safe. Step 1 is a no-op once every row is shaped (dedup_rows
only ever drops/normalizes, never re-introduces a raw row). Step 2 skips any uid
already `ok`/`protected` in the manifest.

Usage: python3 scripts/bitget_repair_raw_rows.py
"""
import json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from analysis.bitget_flatten import dedup_rows, is_raw_row
from scripts.scrape_bitget_positions import (
    make_session, make_post_fn, fetch_open_positions, row_from_open_position,
    fetch_cycle, row_from_cycle, fetch_detail, detail_summary,
)

POSITIONS_PATH = os.path.join(BASE, 'data', 'bitget_positions.jsonl')
OPEN_PATH = os.path.join(BASE, 'data', 'bitget_open_positions.jsonl')
CYCLE_PATH = os.path.join(BASE, 'data', 'bitget_cycle.jsonl')
MANIFEST_PATH = os.path.join(BASE, 'data', 'bitget_manifest.jsonl')
TRADERS_PATH = os.path.join(BASE, 'data', 'bitget_traders.jsonl')


def repair_positions_file(path=None):
    """Returns (n_total, n_raw, n_dropped, raw_uids) — raw_uids is the set of
    trader_uid that had at least one raw row (candidates for the manifest/cycle/
    open-position backfill in step 2)."""
    path = path or POSITIONS_PATH
    if not os.path.exists(path):
        return 0, 0, 0, set()
    lines = [json.loads(l) for l in open(path) if l.strip()]
    raw_flags = [is_raw_row(p) for p in lines]
    raw_uids = {p.get('traderUid') for p, is_raw in zip(lines, raw_flags) if is_raw}
    out_rows, _ = dedup_rows(lines)
    n_dropped = len(lines) - len(out_rows)
    with open(path, 'w') as fh:
        for p in out_rows:
            fh.write(json.dumps(p, ensure_ascii=False) + '\n')
    return len(lines), sum(raw_flags), n_dropped, raw_uids


def _manifest_ok_uids(path=None):
    path = path or MANIFEST_PATH
    ok = set()
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            if r.get('status') in ('ok', 'protected'):
                ok.add(r['traderUid'])
    return ok


def _n_closed_by_uid(path=None):
    path = path or POSITIONS_PATH
    counts = {}
    for line in open(path):
        r = json.loads(line)
        uid = r.get('traderUid')
        counts[uid] = counts.get(uid, 0) + 1
    return counts


def _load_trader_names(path=None):
    path = path or TRADERS_PATH
    names = {}
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            names[r['traderUid']] = r
    return names


def backfill_trader(uid, display_name, follow_count, n_closed, post_fn):
    """Fetches the missing open/cycle/detail data for one already-repaired trader
    and builds the manifest row exactly like `scrape_trader` would have, minus the
    historyList call (already repaired in step 1)."""
    open_items, open_status = fetch_open_positions(uid, post_fn)
    open_rows = [row_from_open_position(r, uid, display_name) for r in open_items]

    cycle_data = fetch_cycle(uid, post_fn, cycle_time=90)
    cycle_row = row_from_cycle(cycle_data, uid, display_name, 90)

    detail_data = fetch_detail(uid, post_fn)
    detail = detail_summary(detail_data)

    manifest_row = {
        'traderUid': uid, 'displayName': display_name, 'followCount': follow_count,
        'status': 'ok', 'history_status': 'ok', 'n_closed': n_closed,
        'open_status': open_status, 'n_open': len(open_rows),
        **{f'detail_{k}': v for k, v in detail.items()},
    }
    return open_rows, cycle_row, manifest_row


def main():
    n_total, n_raw, n_dropped, raw_uids = repair_positions_file()
    print(f'positions repaired: {n_total} rows scanned, {n_raw} raw rows normalized, '
          f'{n_dropped} duplicate rows dropped', flush=True)

    # Backfill candidates are every trader with position rows but no ok/protected
    # manifest entry -- NOT just `raw_uids` (which goes empty once this script has
    # already repaired the file once, per the idempotency contract: a second run
    # must still find the 4 stuck traders and finish their cycle/open/detail
    # backfill even though their rows are no longer raw).
    already_ok = _manifest_ok_uids()
    pos_uids = {p.get('traderUid') for p in
                (json.loads(l) for l in open(POSITIONS_PATH) if l.strip())}
    todo = sorted(uid for uid in (raw_uids | pos_uids) if uid and uid not in already_ok)
    if not todo:
        print('no traders need cycle/open/detail backfill', flush=True)
        return

    n_closed_by_uid = _n_closed_by_uid()
    trader_names = _load_trader_names()

    session = make_session()
    post_fn = make_post_fn(session)

    with open(OPEN_PATH, 'a') as open_out, open(CYCLE_PATH, 'a') as cycle_out, \
            open(MANIFEST_PATH, 'a') as manifest_out:
        for uid in todo:
            info = trader_names.get(uid, {})
            display_name = info.get('displayName')
            open_rows, cycle_row, manifest_row = backfill_trader(
                uid, display_name, info.get('followCount'),
                n_closed_by_uid.get(uid, 0), post_fn)
            for row in open_rows:
                open_out.write(json.dumps(row, ensure_ascii=False) + '\n')
            cycle_out.write(json.dumps(cycle_row, ensure_ascii=False) + '\n')
            manifest_out.write(json.dumps(manifest_row, ensure_ascii=False) + '\n')
            open_out.flush(); cycle_out.flush(); manifest_out.flush()
            print(f'  backfilled {uid} ({display_name}): n_closed={manifest_row["n_closed"]} '
                  f'n_open={manifest_row["n_open"]} detail_mdd={manifest_row.get("detail_mdd")}',
                  flush=True)
            time.sleep(0.8)

    print(f'DONE: backfilled {len(todo)} traders', flush=True)


if __name__ == '__main__':
    main()
