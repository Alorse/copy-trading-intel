"""Snapshot CSVs -> SQLite. Idempotent per (snapshot_date, exchange)."""
import csv, json, os
from pipeline import db as dbmod


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _listing(snap_dir, exchange):
    """The <exchange>_list.json rows, or None if there is no listing file."""
    path = os.path.join(snap_dir, f'{exchange}_list.json')
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, list) else None


def _listing_index(snap_dir, exchange):
    """(start_times, listed_ids) from <exchange>_list.json, in ONE read.

    `start_times` is portfolio_id -> startTime (ms). startTime is when the lead
    portfolio opened. Binance only serves positions opened at or after it
    (verified 2026-08-28: 0 of 590 portfolios had an older one, against 177 of
    485 three days earlier), so it is the hard floor of every visible track
    record -- see "Trap 7" in SKILL.md.

    `listed_ids` is every id the listing returned, or None when there is no
    listing file: None means "not known", not "not listed" -- Phemex ships no
    listing, and a snapshot taken before this field existed has none either. A
    trader absent from a listing that DOES exist was reached only through the
    historical-union `extra_ids` path, so every listing-only field (roi, mdd,
    startTime) is missing for them -- which silently disables three detect
    screens. The two are not interchangeable: a listed row carrying no
    startTime is in `listed_ids` but not in `start_times`.
    """
    data = _listing(snap_dir, exchange)
    if data is None:
        return {}, None
    key = 'leadPortfolioId' if exchange == 'binance' else 'userId'
    rows = {str(r[key]): r for r in data
            if isinstance(r, dict) and r.get(key) is not None}
    return ({k: r['startTime'] for k, r in rows.items() if r.get('startTime')},
            set(rows))


# trader_snapshot column <- binance_detail.jsonl key. Everything here is NULL
# when the `detail` pass has not run for that trader: `detail` is a second,
# paced pass over the ranked candidates, not part of the universe sweep, so
# "not fetched" is the normal state for most of the snapshot and must never be
# confused with "measured at zero".
_DETAIL_COLS = (('copier_pnl', 'copierPnl'),
                ('copier_count_current', 'currentCopyCount'),
                ('copier_count_total', 'totalCopyCount'),
                ('aum_amount', 'aumAmount'),
                ('margin_balance', 'marginBalance'),
                ('min_copy_usd', 'fixedAmountMinCopyUsd'))


def _detail_index(snap_dir, exchange):
    """portfolio_id -> the detail row's DB values, from <exchange>_detail.jsonl.

    Only Binance publishes `lead-portfolio/detail`; for any other exchange, and
    for a snapshot taken before the detail pass existed, the index is empty and
    every column stays NULL.
    """
    path = os.path.join(snap_dir, f'{exchange}_detail.jsonl')
    if not os.path.exists(path):
        return {}
    out = {}
    for line in open(path):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        pid = rec.get('portfolioId')
        if pid is None:
            continue
        out[str(pid)] = (*(rec.get(k) for _, k in _DETAIL_COLS),
                         int(bool(rec.get('retired'))))
    return out


def ingest_snapshot(con, snap_dir, snapshot_date):
    snap_dir = str(snap_dir)
    counts = {}
    for ex in ('binance', 'phemex'):
        # ALWAYS clear: if the CSV vanished on a re-ingest, that exchange's old
        # data must not survive in the DB
        dbmod.clear_snapshot(con, snapshot_date, ex)
        path = os.path.join(snap_dir, f'{ex}.csv')
        if not os.path.exists(path):
            counts[ex] = 0
            continue
        starts, listed = _listing_index(snap_dir, ex)
        detail = _detail_index(snap_dir, ex)
        no_detail = (None,) * (len(_DETAIL_COLS) + 1)
        traders, pos_rows, trader_rows = set(), [], {}
        for r in csv.DictReader(open(path)):
            if ex == 'binance':
                tid = r['portfolio_id']
                max_oi, cv = _f(r['max_oi'], 0), _f(r['closed_volume'], 0)
                pos_rows.append((snapshot_date, ex, tid, r['nick'], r['symbol'],
                                 r['side'], _i(r['opened_ms']), _i(r['closed_ms']),
                                 _f(r['dur_h']), _f(r['notional']), _f(r['leverage']),
                                 _f(r['margin_est']), _f(r['closing_pnl']),
                                 1 if (max_oi and cv < max_oi) else 0,
                                 _f(r['avg_cost']), _f(r['avg_close'])))
                trader_rows[tid] = (snapshot_date, ex, tid, r['nick'], _f(r['p_roi']),
                                    _f(r['p_pnl']), _f(r['aum']), _f(r['win_rate']),
                                    _f(r['mdd']), _i(starts.get(tid)))
            else:
                tid = r['trader_id']
                marg, oval = _f(r['margin'], 0), _f(r['open_val'], 0)
                lev = oval / marg if marg else 0
                # the REAL side of the position is pos_side (Long/Short/Merged);
                # the CSV's side is Buy/Sell and is NOT the position side
                pos_rows.append((snapshot_date, ex, tid, r['nick'], r['symbol'],
                                 r['pos_side'], _i(r['opened_ms']), _i(r['closed_ms']),
                                 _f(r['dur_h']), oval, lev, marg,
                                 _f(r['realized_pnl']), 0,
                                 _f(r['open_price']), _f(r['close_price'])))
                trader_rows[tid] = (snapshot_date, ex, tid, r['nick'],
                                    None, None, None, None, None,
                                    _i(starts.get(tid)))
            traders.add(tid)
        con.executemany(
            "INSERT INTO positions (snapshot_date,exchange,trader_id,nick,symbol,side,"
            "opened_ms,closed_ms,dur_h,notional,leverage,margin,closing_pnl,partial,"
            "avg_cost,avg_close) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pos_rows)
        con.executemany(
            "INSERT INTO trader_snapshot (snapshot_date,exchange,trader_id,nick,"
            "roi,pnl,aum,win_rate,mdd,start_time,listed,"
            + ",".join(c for c, _ in _DETAIL_COLS) + ",retired) "
            "VALUES (" + ",".join("?" * (11 + len(_DETAIL_COLS) + 1)) + ")",
            [(*row, None if listed is None else int(tid in listed),
              *detail.get(tid, no_detail))
             for tid, row in trader_rows.items()])
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?,'')",
                    (snapshot_date, ex, len(traders), len(pos_rows)))
        con.commit()
        counts[ex] = len(pos_rows)
    return counts
