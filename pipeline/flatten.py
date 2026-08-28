"""Aplana los *_raw.jsonl de un snapshot a CSV planos. Sin red."""
import json, csv, os


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


BCOLS = ['portfolio_id','nick','p_roi','p_pnl','aum','win_rate','mdd','symbol','side',
         'leverage','isolated','avg_cost','avg_close','closing_pnl','roi','max_oi',
         'closed_volume','opened_ms','closed_ms','dur_h','notional','margin_est']
PCOLS = ['trader_id','nick','symbol','side','pos_side','size','open_price','close_price',
         'open_val','margin','roi','closed_pnl','realized_pnl','exchange_fee','funding_fee',
         'opened_ms','closed_ms','dur_h']


def _flatten_binance(src, dst):
    n = 0
    with open(dst, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(BCOLS)
        for line in open(src):
            d = json.loads(line)
            for p in d['positions']:
                o, c = p.get('opened'), p.get('closed')
                dur = (c - o) / 3600000 if (o and c) else ''
                lev = _f(p.get('leverage'), 1.0) or 1.0
                notional = _f(p.get('maxOpenInterest')) * _f(p.get('avgCost'))
                w.writerow([d['portfolioId'], d.get('nick'), _f(d.get('roi')),
                            _f(d.get('pnl')), _f(d.get('aum')), _f(d.get('winRate')),
                            _f(d.get('mdd')), p.get('symbol'), p.get('side'), lev,
                            p.get('isolated'), _f(p.get('avgCost')),
                            _f(p.get('avgClosePrice')), _f(p.get('closingPnl')),
                            _f(p.get('roi')), _f(p.get('maxOpenInterest')),
                            _f(p.get('closedVolume')), o, c, dur, notional,
                            notional / lev]); n += 1
    return n


def _flatten_phemex(src, dst):
    n = 0
    with open(dst, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(PCOLS)
        for line in open(src):
            d = json.loads(line)
            for p in d['positions']:
                o = p.get('openedTime') or p.get('createdAt')
                c = p.get('updatedTime') or p.get('closedTime')
                dur = (c - o) / 3600000 if (o and c) else ''
                w.writerow([d['userId'], d['nick'], p.get('symbol'), p.get('side'),
                            p.get('posSide'), _f(p.get('size')), _f(p.get('openPrice')),
                            _f(p.get('closePrice')), _f(p.get('openPositionVal')),
                            _f(p.get('margin')), _f(p.get('roi')), _f(p.get('closedPnl')),
                            _f(p.get('realizedPnl')), _f(p.get('exchangeFee')),
                            _f(p.get('fundingFee')), o, c, dur]); n += 1
    return n


def flatten_snapshot(snap_dir):
    snap_dir = str(snap_dir)
    out = {}
    for ex, fn in (('binance', _flatten_binance), ('phemex', _flatten_phemex)):
        src = os.path.join(snap_dir, f'{ex}_raw.jsonl')
        dst = os.path.join(snap_dir, f'{ex}.csv')
        out[ex] = fn(src, dst) if os.path.exists(src) else 0
    return out
