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


def _start_times(snap_dir, exchange):
    """portfolio_id -> startTime (ms) from the scrape listing.

    startTime is when the lead portfolio opened. Binance only serves positions
    opened at or after it (verified 2026-08-28: 0 of 590 portfolios had an older
    one, against 177 of 485 three days earlier), so it is the hard floor of every
    visible track record -- see "Trap 7" in SKILL.md.
    """
    path = os.path.join(snap_dir, f'{exchange}_list.json')
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
    except (ValueError, OSError):
        return {}
    key = 'leadPortfolioId' if exchange == 'binance' else 'userId'
    return {str(r[key]): r['startTime'] for r in data
            if isinstance(r, dict) and r.get(key) is not None and r.get('startTime')}


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
        starts = _start_times(snap_dir, ex)
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
            "INSERT INTO trader_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
            list(trader_rows.values()))
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?,'')",
                    (snapshot_date, ex, len(traders), len(pos_rows)))
        con.commit()
        counts[ex] = len(pos_rows)
    return counts
