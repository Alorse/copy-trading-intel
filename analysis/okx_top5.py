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

Adversarial audit corrections applied 2026-08-29 (see analysis/TOP5_OKX.md):
  - Binance's reference hard filters (top5_final.py) are now enforced in full:
    t>=2.5, alpha H2>0, leverage p90<=25x, median margin>=$50, duration>=30min.
  - compute_alpha now measures each trader against the cell median EXCLUDING its
    own rows (leave-self-out); the old self-inclusive number is still reported
    alongside it so the inflation stays visible.
  - A new hard screen rejects any trader whose disclosed weekly pnlRatios[] show
    a >20% drawdown that the visible closed-position window doesn't cover (the
    "01014588 lesson": a pristine recent window sitting on top of a large,
    invisible historical loss).
  - The open-upl hard filter now uses net upl_sum (matching the doc's prose);
    upl_neg_sum is kept only as a soft flag.
  - net-negative closed PnL is its own rejection bucket, checked before
    concentration (previously such traders were silently absorbed into the
    concentration bucket via a sentinel score).

Usage: python3 analysis/okx_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'okx_positions.csv')
OPEN_PATH = os.path.join(D, 'okx_open_positions.jsonl')
TRADERS_PATH = os.path.join(D, 'okx_traders.jsonl')

MIN_CELL = 8           # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15             # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8         # min positions with a defined (leave-self-out) alpha
FRESH_START_DAYS = 120

# Binance reference hard filters (top5_final.py:48-56), adopted in full 2026-08-29.
T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5    # 30 minutes

DRAWDOWN_THRESHOLD = -0.20   # weekly pnlRatios[] screen, the "01014588 lesson"
MAX_CELL_SHARE_FLAG = 0.40   # report-only: trader dominates >40% of a benchmark cell


def load_positions(csv_path=CSV_PATH):
    rows = []
    for r in csv.DictReader(open(csv_path)):
        try:
            op = float(r['open_price'])
            cp = float(r['close_price'])
            pnl = float(r['pnl'])
            lev = float(r['leverage'])
            opened = int(r['opened_ms'])
            marg = float(r['margin'])
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
                          pr=pr, pnl=pnl, lev=lev, dur=float(r['dur_h'] or 0), marg=marg,
                          notional=float(r['notional'] or 0), month=month, opened_ms=opened))
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


def load_trader_meta(path=TRADERS_PATH):
    """Returns {unique_code: {'ranking_pnl': float, 'pnl_ratios': [(begin_ts_ms, ratio), ...]}}
    from data/okx_traders.jsonl (the ranking snapshot)."""
    meta = {}
    if not os.path.exists(path):
        return meta
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        uid = r.get('uniqueCode')
        if not uid:
            continue
        try:
            ranking_pnl = float(r.get('pnl', 0) or 0)
        except (TypeError, ValueError):
            ranking_pnl = 0.0
        ratios = []
        for pr in r.get('pnlRatios') or []:
            try:
                ratios.append((int(pr['beginTs']), float(pr['pnlRatio'])))
            except (TypeError, ValueError, KeyError):
                continue
        meta[uid] = {'ranking_pnl': ranking_pnl, 'pnl_ratios': ratios}
    return meta


def drawdown_screen(pnl_ratios, window_start_ms):
    """Checks a trader's disclosed weekly pnlRatios[] for a >20% drawdown that the
    visible closed-position window doesn't cover. Returns (min_ratio, min_ts, covered):
    `covered` is True (safe) whenever the drawdown doesn't breach the threshold, or
    when it does but the window's earliest position predates the drawdown's deepest
    point (i.e. our own sample already reflects that period, so it isn't hidden)."""
    if not pnl_ratios:
        return None, None, True
    min_ts, min_ratio = min(pnl_ratios, key=lambda p: p[1])
    if min_ratio >= DRAWDOWN_THRESHOLD:
        return min_ratio, min_ts, True
    covered = window_start_ms is not None and window_start_ms <= min_ts
    return min_ratio, min_ts, covered


def compute_alpha(rows, min_cell=MIN_CELL):
    """Sets x['alpha'] (leave-self-out: measured against the cell median EXCLUDING
    the trader's own rows) and x['alpha_incl'] (the old self-inclusive number, kept
    for reporting the inflation) on every row. A cell only yields a leave-self-out
    alpha for a trader if at least one OTHER trader's row remains in it after
    excluding the trader's own; if a qualifying cell (>=min_cell rows) is entirely
    one trader's own trades, that trader's rows in it get alpha=None (dropped) and
    are counted in the returned per-trader drop counter.

    Returns (bench, dropped_self_dominated, cell_share_max):
      bench                 {(sym, month, side): median} — self-inclusive, as before
      dropped_self_dominated {uid: n_rows_dropped_for_self_domination}
      cell_share_max         {uid: max(own_rows / total_rows) over the trader's cells}
    """
    cell = collections.defaultdict(list)   # key -> [(uid, pr), ...]
    for x in rows:
        cell[(x['sym'], x['month'], x['side'])].append((x['uid'], x['pr']))
    bench = {k: st.median(pr for _, pr in v) for k, v in cell.items() if len(v) >= min_cell}

    dropped_self_dominated = collections.Counter()
    cell_share_max = collections.defaultdict(float)

    for x in rows:
        key = (x['sym'], x['month'], x['side'])
        b_incl = bench.get(key)
        x['alpha_incl'] = x['pr'] - b_incl if b_incl is not None else None
        if b_incl is None:
            x['alpha'] = None
            continue
        v = cell[key]
        others = [pr for uid, pr in v if uid != x['uid']]
        share = (len(v) - len(others)) / len(v)
        if share > cell_share_max[x['uid']]:
            cell_share_max[x['uid']] = share
        if not others:
            x['alpha'] = None
            dropped_self_dominated[x['uid']] += 1
            continue
        x['alpha'] = x['pr'] - st.median(others)
    return bench, dict(dropped_self_dominated), dict(cell_share_max)


def rank_traders(rows, open_upl=None, trader_meta=None, min_n=MIN_N, min_alpha_n=MIN_ALPHA_N,
                  t_min=T_MIN, levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None, cell_share_max=None):
    open_upl = open_upl or {}
    trader_meta = trader_meta or {}
    dropped_self_dominated = dropped_self_dominated or {}
    cell_share_max = cell_share_max or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['uid']].append(x)

    candidates, rejections = [], collections.Counter()
    for uid, v in by_trader.items():
        v = sorted(v, key=lambda z: z['opened_ms'])
        al = [z['alpha'] for z in v if z['alpha'] is not None]           # leave-self-out
        al_incl = [z['alpha_incl'] for z in v if z['alpha_incl'] is not None]  # old, self-inclusive
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

        mean_alpha = st.mean(al)
        std_alpha = st.pstdev(al)
        t = mean_alpha / (std_alpha / len(al) ** 0.5) if std_alpha > 0 else 0.0
        mean_alpha_incl = st.mean(al_incl) if al_incl else None
        std_alpha_incl = st.pstdev(al_incl) if al_incl else 0.0
        t_incl = (mean_alpha_incl / (std_alpha_incl / len(al_incl) ** 0.5)
                  if al_incl and std_alpha_incl > 0 else 0.0)
        k = len(al) // 2
        alpha_h2 = st.mean(al[k:]) if al[k:] else 0.0

        levp90 = sorted(z['lev'] for z in v)[int(.9 * len(v))]
        margmed = st.median(z['marg'] for z in v)
        durmed = st.median(z['dur'] for z in v)

        lead_days = v[0]['lead_days']
        upl_info = open_upl.get(uid, {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0})
        meta = trader_meta.get(uid, {'ranking_pnl': 0.0, 'pnl_ratios': []})
        window_start_ms = v[0]['opened_ms']
        dd_min_ratio, dd_min_ts, dd_covered = drawdown_screen(meta['pnl_ratios'], window_start_ms)
        ranking_pnl = meta['ranking_pnl']

        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v),
                 levp90=levp90, margmed=margmed, durmed=durmed, conc=None,
                 total_pnl=total_pnl, lead_days=lead_days,
                 notional=st.median(z['notional'] for z in v),
                 fresh_start=lead_days < FRESH_START_DAYS,
                 open_upl_sum=upl_info['upl_sum'], n_open=upl_info['n_open'],
                 hidden_loss_flag=(wr > 92 or upl_info['upl_neg_sum'] < -abs(total_pnl) * 0.2),
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(uid, 0),
                 max_cell_share=cell_share_max.get(uid, 0.0),
                 ranking_pnl=ranking_pnl, computed_pnl=total_pnl,
                 pnl_cross_check_ratio=(total_pnl / ranking_pnl if ranking_pnl else None),
                 dd_min_ratio=dd_min_ratio, dd_min_ts=dd_min_ts, dd_covered=dd_covered,
                 window_start_ms=window_start_ms)

        if wr > 92:
            rejections['win rate>92% (Trampa 1)'] += 1
            continue
        if payoff < 0.5:
            rejections['payoff<0.5 (left tail)'] += 1
            continue
        if total_pnl <= 0:
            rejections['net-negative closed PnL'] += 1
            continue
        conc = (best_pnl / total_pnl * 100)
        d['conc'] = conc
        if conc > 30:
            rejections['concentration>30% (top-1 trade)'] += 1
            continue
        if upl_info['upl_sum'] < -abs(total_pnl) * 0.5:
            rejections['open unrealized loss > 50% of closed PnL'] += 1
            continue
        if t < t_min:
            rejections[f't<{t_min}'] += 1
            continue
        if alpha_h2 <= 0:
            rejections['alpha H2<=0'] += 1
            continue
        if levp90 > levp90_max:
            rejections[f'leverage p90>{levp90_max:g}x'] += 1
            continue
        if margmed < margin_med_min:
            rejections[f'median margin<${margin_med_min:g} (not copyable)'] += 1
            continue
        if durmed < dur_med_min_h:
            rejections['duration<30min (latency)'] += 1
            continue
        if not dd_covered:
            rejections['weekly pnlRatios drawdown >20%, uncovered by window'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/okx_flatten.py first', flush=True)
        return
    rows = load_positions(CSV_PATH)
    print(f'positions loaded: {len(rows)}')
    bench, dropped_self_dominated, cell_share_max = compute_alpha(rows)
    open_upl = load_open_upl(OPEN_PATH)
    trader_meta = load_trader_meta(TRADERS_PATH)
    candidates, rejections = rank_traders(rows, open_upl, trader_meta,
                                           dropped_self_dominated=dropped_self_dominated,
                                           cell_share_max=cell_share_max)

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<55} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'lead_d':>7}{'ddmin%':>8}{'ddcov':>6}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        ddmin = d['dd_min_ratio'] * 100 if d['dd_min_ratio'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}{d['lead_days']:>7.0f}"
              f"{ddmin:>8.1f}{str(d['dd_covered']):>6}")

    print('\nHeadline (ranking) pnl vs computed (sum of visible closed pnl) — every survivor:')
    for d in candidates:
        ratio = d['pnl_cross_check_ratio']
        ratio_s = f'{ratio:.2f}x' if ratio is not None else 'n/a'
        print(f"   {d['nick']:<24} ranking=${d['ranking_pnl']:>12,.0f}  "
              f"computed=${d['computed_pnl']:>12,.0f}  ratio(computed/ranking)={ratio_s}")


if __name__ == '__main__':
    main()
