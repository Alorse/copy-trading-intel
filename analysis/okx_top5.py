"""OKX Top-5 candidate ranking. Mirrors top5_final.py's methodology (alpha vs the
symbol x month x side median, concentration guard, Trampa 1 filter) adapted to
OKX's fields and its much smaller universe (261 lead traders total, measured
2026-08-29).

Reads analysis/okx_positions.csv (run analysis/okx_flatten.py first) and, for the
open-position hidden-loss check, data/okx_open_positions.jsonl directly. OKX's
public API exposes no portfolio-level `mdd` like Binance/Phemex, so a spotless
closed win rate can only be cross-checked against large negative unrealized PnL
on currently open positions (`upl`) — the OKX analogue of Trampa 1's signature.

`pnl` is NET of fees (verified — see docs/okx_endpoint_facts.md).

Usage: python3 analysis/okx_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'okx_positions.csv')
OPEN_PATH = os.path.join(D, 'okx_open_positions.jsonl')

MIN_CELL = 8          # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15            # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8        # min positions with a defined alpha (i.e. in a trusted cell)
FRESH_START_DAYS = 120


def load_positions(csv_path=CSV_PATH):
    rows = []
    for r in csv.DictReader(open(csv_path)):
        try:
            op = float(r['open_price'])
            cp = float(r['close_price'])
            pnl = float(r['pnl'])
            lev = float(r['leverage'])
            opened = int(r['opened_ms'])
        except (TypeError, ValueError):
            continue
        if op <= 0 or cp <= 0 or lev <= 0:
            continue
        side = r['pos_side']
        if side not in ('long', 'short'):
            continue
        pr = (cp / op - 1) * (1 if side == 'long' else -1)
        if abs(pr) > 3:               # guard against bad ticks, same threshold as top5_final.py
            continue
        month = dt.datetime.fromtimestamp(opened / 1000, dt.UTC).strftime('%Y-%m')
        rows.append(dict(uid=r['unique_code'], nick=r['nick'],
                          lead_days=float(r['lead_days'] or 0), sym=r['symbol'], side=side,
                          pr=pr, pnl=pnl, lev=lev, dur=float(r['dur_h'] or 0),
                          notional=float(r['notional'] or 0), month=month))
    return rows


def load_open_upl(jsonl_path=OPEN_PATH):
    """Returns {unique_code: {'upl_sum': float, 'n_open': int, 'upl_neg_sum': float}}."""
    agg = collections.defaultdict(lambda: {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0})
    if not os.path.exists(jsonl_path):
        return agg
    for line in open(jsonl_path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        try:
            upl = float(r.get('upl', 0) or 0)
        except (TypeError, ValueError):
            upl = 0.0
        a = agg[r['uniqueCode']]
        a['upl_sum'] += upl
        a['n_open'] += 1
        if upl < 0:
            a['upl_neg_sum'] += upl
    return agg


def compute_alpha(rows, min_cell=MIN_CELL):
    cell = collections.defaultdict(list)
    for x in rows:
        cell[(x['sym'], x['month'], x['side'])].append(x['pr'])
    bench = {k: st.median(v) for k, v in cell.items() if len(v) >= min_cell}
    for x in rows:
        b = bench.get((x['sym'], x['month'], x['side']))
        x['alpha'] = x['pr'] - b if b is not None else None
    return bench


def rank_traders(rows, open_upl=None, min_n=MIN_N, min_alpha_n=MIN_ALPHA_N):
    open_upl = open_upl or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['uid']].append(x)

    candidates, rejections = [], collections.Counter()
    for uid, v in by_trader.items():
        al = [z['alpha'] for z in v if z['alpha'] is not None]
        n_syms = len(set(z['sym'] for z in v))
        if len(v) < min_n or len(al) < min_alpha_n:
            rejections['sample too small'] += 1
            continue
        if n_syms < 2:
            rejections['single-pair only (H1: reliability ~0.13)'] += 1
            continue
        wins = [z['pr'] for z in v if z['pr'] > 0]
        losses = [z['pr'] for z in v if z['pr'] < 0]
        if not wins or not losses:
            rejections['no losers on either side (Trampa 1)'] += 1
            continue
        wr = len(wins) / len(v) * 100
        payoff = st.mean(wins) / abs(st.mean(losses))
        total_pnl = sum(z['pnl'] for z in v)
        best_pnl = max(z['pnl'] for z in v)
        conc = (best_pnl / total_pnl * 100) if total_pnl > 0 else 999.0
        mean_alpha = st.mean(al)
        std_alpha = st.pstdev(al)
        t = mean_alpha / (std_alpha / len(al) ** 0.5) if std_alpha > 0 else 0.0
        lead_days = v[0]['lead_days']
        upl_info = open_upl.get(uid, {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0})
        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms, alpha=mean_alpha, t=t,
                 wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v), conc=conc,
                 total_pnl=total_pnl, lead_days=lead_days,
                 notional=st.median(z['notional'] for z in v),
                 fresh_start=lead_days < FRESH_START_DAYS,
                 open_upl_sum=upl_info['upl_sum'], n_open=upl_info['n_open'],
                 hidden_loss_flag=(wr > 92 or upl_info['upl_neg_sum'] < -abs(total_pnl) * 0.2))
        if wr > 92:
            rejections['win rate>92% (Trampa 1)'] += 1
            continue
        if payoff < 0.5:
            rejections['payoff<0.5 (left tail)'] += 1
            continue
        if conc > 30:
            rejections['concentration>30% (top-1 trade)'] += 1
            continue
        if upl_info['upl_neg_sum'] < -abs(total_pnl) * 0.5:
            rejections['open unrealized loss > 50% of closed PnL'] += 1
            continue
        if t < 1.5:
            rejections['t<1.5'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/okx_flatten.py first', flush=True)
        return
    rows = load_positions(CSV_PATH)
    print(f'positions loaded: {len(rows)}')
    compute_alpha(rows)
    open_upl = load_open_upl(OPEN_PATH)
    candidates, rejections = rank_traders(rows, open_upl)

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<45} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'wr%':>6}{'payoff':>7}"
         f"{'lev':>5}{'conc%':>7}{'lead_d':>7}{'notional':>10}{'fresh':>7}{'hidden':>7}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}"
              f"{d['conc']:>7.1f}{d['lead_days']:>7.0f}{d['notional']:>10,.0f}"
              f"{str(d['fresh_start']):>7}{str(d['hidden_loss_flag']):>7}")


if __name__ == '__main__':
    main()
