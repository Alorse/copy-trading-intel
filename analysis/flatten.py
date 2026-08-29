"""Flattens the nested .jsonl into flat CSVs, one row per closed position.
Downloads nothing: reads only the local data/."""
import json, csv, os

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
OUT = os.path.dirname(__file__)

def f(x, default=0.0):
    try: return float(x)
    except (TypeError, ValueError): return default

# ---------- Phemex ----------
cols = ['trader_id','nick','symbol','side','pos_side','size','open_price','close_price',
        'open_val','margin','roi','closed_pnl','realized_pnl','exchange_fee','funding_fee',
        'opened_ms','closed_ms','dur_h']
with open(os.path.join(OUT,'phemex_positions.csv'),'w',newline='') as fh:
    w = csv.writer(fh); w.writerow(cols); n=0
    for line in open(os.path.join(D,'positions_all.jsonl')):
        d = json.loads(line)
        for p in d['positions']:
            o, c = p.get('openedTime') or p.get('createdAt'), p.get('updatedTime') or p.get('closedTime')
            dur = (c-o)/3600000 if (o and c) else ''
            w.writerow([d['userId'], d['nick'], p.get('symbol'), p.get('side'), p.get('posSide'),
                        f(p.get('size')), f(p.get('openPrice')), f(p.get('closePrice')),
                        f(p.get('openPositionVal')), f(p.get('margin')), f(p.get('roi')),
                        f(p.get('closedPnl')), f(p.get('realizedPnl')),
                        f(p.get('exchangeFee')), f(p.get('fundingFee')), o, c, dur]); n+=1
print('phemex_positions.csv rows:', n)

# ---------- Binance ----------
bcols = ['portfolio_id','nick','p_roi','p_pnl','aum','win_rate','mdd','symbol','side','leverage',
         'isolated','avg_cost','avg_close','closing_pnl','roi','max_oi','closed_volume',
         'opened_ms','closed_ms','dur_h','notional','margin_est']
with open(os.path.join(OUT,'binance_positions.csv'),'w',newline='') as fh:
    w = csv.writer(fh); w.writerow(bcols); n=0
    for line in open(os.path.join(D,'binance_positions.jsonl')):
        d = json.loads(line)
        for p in d['positions']:
            o, c = p.get('opened'), p.get('closed')
            dur = (c-o)/3600000 if (o and c) else ''
            lev = f(p.get('leverage'), 1.0) or 1.0
            notional = f(p.get('maxOpenInterest')) * f(p.get('avgCost'))
            w.writerow([d['portfolioId'], d.get('nick'), f(d.get('roi')), f(d.get('pnl')),
                        f(d.get('aum')), f(d.get('winRate')), f(d.get('mdd')),
                        p.get('symbol'), p.get('side'), lev, p.get('isolated'),
                        f(p.get('avgCost')), f(p.get('avgClosePrice')), f(p.get('closingPnl')),
                        f(p.get('roi')), f(p.get('maxOpenInterest')), f(p.get('closedVolume')),
                        o, c, dur, notional, notional/lev if lev else '']); n+=1
print('binance_positions.csv rows:', n)
