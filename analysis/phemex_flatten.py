"""Flattens data/positions_all.jsonl (Phemex) into a flat CSV, one row per closed
position. Downloads nothing: reads only the local data/. Mirrors okx_flatten.py's
shape where the fields map; Phemex has no `lever`/`mgnMode` fields on the position
row, so `leverage` here is **derived** as `openPositionVal / margin` (declared, not
a field Phemex reports directly — see phemex_top5.py's docstring for the sanity cap).

`realizedPnl` is Phemex's own field name for "net profit" — **verified NET of fees**:
`realizedPnl = closedPnl - exchangeFee - fundingFee` holds exactly (SKILL.md line 32).
`closedPnl` (gross) and the fee columns are kept too, both for the internal
consistency cross-check in phemex_top5.py and so nothing here silently drops a
number that skill has already verified.

Both `side` (Buy/Sell) and `posSide` (Long/Short/**Merged**) are kept: 453 of 7,467
rows (6.1%) report `posSide: "Merged"` (one-way position mode, not a hedge-mode
Long/Short) rather than a directional label — for those, `side` (always Buy or
Sell, never anything else, verified over all 7,467 rows) is the only usable
direction signal, and phemex_top5.py keys off `side`, not `posSide`, for exactly
this reason.
"""
import json, csv, os

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)

COLS = ['user_id', 'nick', 'position_id', 'symbol', 'side', 'pos_side', 'leverage',
        'open_price', 'close_price', 'margin', 'pnl', 'closed_pnl',
        'exchange_fee', 'funding_fee', 'roi', 'size', 'ccy',
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


def row_from_position(user_id, nick, p):
    opened, closed = i(p.get('openedTime')), i(p.get('updatedTime'))
    dur = (closed - opened) / 3600000 if (opened and closed) else ''
    margin = f(p.get('margin'))
    notional = f(p.get('openPositionVal'))
    leverage = notional / margin if margin > 0 else 0.0
    return [user_id, nick, p.get('positionId'), p.get('symbol'), p.get('side'),
            p.get('posSide'), leverage, f(p.get('openPrice')), f(p.get('closePrice')), margin,
            f(p.get('realizedPnl')), f(p.get('closedPnl')), f(p.get('exchangeFee')),
            f(p.get('fundingFee')), f(p.get('roi')), f(p.get('size')),
            p.get('currency'), opened, closed, dur, notional]


def flatten(data_dir=D, out_dir=OUT):
    """Reads <data_dir>/positions_all.jsonl, writes <out_dir>/phemex_positions.csv.
    Returns the row count (0, and no file written, if the input is missing).

    Dedups on read by (user_id, position_id): `positionId` is scoped per user, not
    globally unique (19 collisions across different userIds observed in the current
    196-trader snapshot when deduping by positionId alone)."""
    in_path = os.path.join(data_dir, 'positions_all.jsonl')
    if not os.path.exists(in_path):
        return 0
    n = 0
    seen = set()
    with open(os.path.join(out_dir, 'phemex_positions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for line in open(in_path):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            user_id, nick = r.get('userId'), r.get('nick')
            for p in r.get('positions') or []:
                key = (user_id, p.get('positionId'))
                if key in seen:
                    continue
                seen.add(key)
                w.writerow(row_from_position(user_id, nick, p))
                n += 1
    return n


if __name__ == '__main__':
    print('phemex_positions.csv rows:', flatten())
