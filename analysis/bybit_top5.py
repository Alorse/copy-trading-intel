"""Bybit Top-5 candidate ranking. Ports okx_top5.py's methodology (leave-self-out
alpha vs the symbol x month x side median, concentration guard, Trampa 1 filter,
full Binance reference hard filters, drawdown screen) to Bybit's fields.

Reads analysis/bybit_positions.csv (run analysis/bybit_flatten.py first) and, for
the hidden-loss / drawdown checks, data/bybit_open_positions.jsonl and
data/bybit_yield_trend.jsonl directly.

`pnl_usd` (orderNetProfitE8/1e8) is Bybit's own field name for "net profit" — NET
of fees by name, not yet independently reconstructed against gross price return
the way Binance/OKX were (see scrape_bybit_positions.py's docstring: this is a
documented open item, not a verified fact — report it as such).

`pr` (the de-leveraged return alpha is computed against) is `roi / leverage`, NOT
derived from `entry_price`/`close_price`. An audit (Fable-2/GLM-2) found Bybit's
position-level entry/close price fields are shared across every order row of a
scaled-in/out position, so `(close/entry - 1)` disagrees in *sign* with `pnl_usd`
on ~16% of rows (1,815/11,409) — unusable as a return basis. `roi` (Bybit's own
`orderNetProfitRateE4` field) is independently self-consistent: `roi ≈ pnl_usd /
margin` to within a 0.02% median relative error (0.16% at p90) across the dataset,
and already bakes in direction (long/short) via `pnl_usd`'s sign, so `roi /
leverage` is a verified, net-of-fees, de-leveraged return with no extra sign
handling needed. `entry_price`/`close_price` are kept in the CSV for reference only.

Bybit has no portfolio-level `mdd` field. Two proxies are used instead, both
weaker than Binance/Phemex's mdd:
  - net open `upl_sum` from position/list, when available (SKILL.md documents no
    unrealized-pnl field on this endpoint; scrape_bybit_positions.py's
    row_from_open_position leaves `upl=None` when no known key is present — the
    hard filter is skipped, not defaulted to "safe", whenever no trader in the
    universe has usable upl data, and this is reported explicitly).
  - the yield-trend `totalYieldRateE4` series (the Bybit analogue of OKX's weekly
    pnlRatios[]) for the >20%-uncovered-drawdown screen (the "01014588 lesson").

`locate_days` (account age, from pub-leader/info) stands in for OKX's `leadDays`
for the fresh_start flag.

Usage: python3 analysis/bybit_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'bybit_positions.csv')
OPEN_PATH = os.path.join(D, 'bybit_open_positions.jsonl')
INFO_PATH = os.path.join(D, 'bybit_trader_info.jsonl')
YIELD_PATH = os.path.join(D, 'bybit_yield_trend.jsonl')

MIN_CELL = 8            # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15               # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8          # min positions with a defined (leave-self-out) alpha
FRESH_START_DAYS = 120

# Binance reference hard filters (top5_final.py:48-56), adopted in full as with OKX.
T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5     # 30 minutes

DRAWDOWN_THRESHOLD = -0.20    # yield-trend totalYieldRateE4 screen, the "01014588 lesson"
MAX_CELL_SHARE_FLAG = 0.40    # report-only: trader dominates >40% of a benchmark cell


def load_positions(csv_path=CSV_PATH):
    rows = []
    for r in csv.DictReader(open(csv_path)):
        try:
            pnl = float(r['pnl_usd'])
            roi = float(r['roi'])
            lev = float(r['leverage'])
            started = int(r['started_ms'])
            closed = int(r['closed_ms'])
            marg = float(r['margin'])
        except (TypeError, ValueError):
            continue
        if lev <= 0:
            continue
        side = r['side']
        if side not in ('long', 'short'):
            continue
        # De-leveraged, net-of-fees return, NOT derived from entry/close price (see
        # module docstring: Bybit's price fields disagree in sign with pnl_usd on
        # ~16% of rows; roi/leverage is the verified, self-consistent basis instead).
        pr = roi / lev
        if abs(pr) > 3:                # guard against bad ticks, same threshold as okx_top5.py
            continue
        month = dt.datetime.fromtimestamp(started / 1000, dt.UTC).strftime('%Y-%m')
        dur_h = float(r['dur_h']) if r['dur_h'] not in ('', None) else 0.0
        rows.append(dict(uid=r['leader_mark'], nick=r['nick'], sym=r['symbol'], side=side,
                          pr=pr, pnl=pnl, lev=lev, dur=dur_h, marg=marg,
                          month=month, started_ms=started, closed_ms=closed))
    return rows


def load_open_upl(jsonl_path=OPEN_PATH):
    """Returns {leader_mark: {'upl_sum': float, 'n_open': int, 'upl_neg_sum': float,
    'has_upl_data': bool}}. `has_upl_data` is False whenever every open row for that
    trader had `upl=None` (SKILL.md: no verified unrealized-pnl field on this
    endpoint) — the caller must not treat that as "safe", only as "unknown"."""
    agg = collections.defaultdict(lambda: {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0,
                                            'has_upl_data': False})
    if not os.path.exists(jsonl_path):
        return agg
    for line in open(jsonl_path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        a = agg[r['leaderMark']]
        a['n_open'] += 1
        upl = r.get('upl')
        if upl is not None:
            a['has_upl_data'] = True
            a['upl_sum'] += upl
            if upl < 0:
                a['upl_neg_sum'] += upl
    return agg


def load_trader_info(path=INFO_PATH):
    """Returns {leader_mark: {locate_days, win_rate_7d, win_rate_3w, profit_count,
    loss_count, cum_history_transactions_count}} from data/bybit_trader_info.jsonl."""
    info = {}
    if not os.path.exists(path):
        return info
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        mark = r.get('leaderMark')
        if mark:
            info[mark] = r
    return info


def load_yield_series(path=YIELD_PATH, duration='90D'):
    """Returns {leader_mark: [(ts_ms, total_yield_rate), ...]} for the given
    duration ('90D' or '7D') from data/bybit_yield_trend.jsonl."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get('duration') == duration:
            out[r['leaderMark']] = [(ts, rate) for ts, rate in (r.get('series') or [])]
    return out


def drawdown_screen(series, window_start_ms):
    """Same logic as okx_top5.drawdown_screen: rejects a >20% drawdown in the
    disclosed yield-trend series that the visible closed-position window doesn't
    cover. Returns (min_ratio, min_ts, covered)."""
    if not series:
        return None, None, True
    min_ts, min_ratio = min(series, key=lambda p: p[1])
    if min_ratio >= DRAWDOWN_THRESHOLD:
        return min_ratio, min_ts, True
    covered = window_start_ms is not None and window_start_ms <= min_ts
    return min_ratio, min_ts, covered


def compute_alpha(rows, min_cell=MIN_CELL):
    """Identical algorithm to okx_top5.compute_alpha (leave-self-out cell median).
    Returns (bench, dropped_self_dominated, cell_share_max)."""
    cell = collections.defaultdict(list)
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


def rank_traders(rows, open_upl=None, trader_info=None, yield_series=None,
                  min_n=MIN_N, min_alpha_n=MIN_ALPHA_N, t_min=T_MIN,
                  levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None,
                  cell_share_max=None):
    open_upl = open_upl or {}
    trader_info = trader_info or {}
    yield_series = yield_series or {}
    dropped_self_dominated = dropped_self_dominated or {}
    cell_share_max = cell_share_max or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['uid']].append(x)

    any_upl_data = any(v['has_upl_data'] for v in open_upl.values())

    candidates, rejections = [], collections.Counter()
    for uid, v in by_trader.items():
        v = sorted(v, key=lambda z: z['started_ms'])
        al = [z['alpha'] for z in v if z['alpha'] is not None]
        al_incl = [z['alpha_incl'] for z in v if z['alpha_incl'] is not None]
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
        best_pnl_order = max(z['pnl'] for z in v)
        # GLM-2: a single scaled-in/out position can be split across many order
        # rows (verified: 2,009 of 6,944 (symbol, closed_ms) groups in the current
        # dataset are multi-row, covering 6,474/11,409 rows) -- each row's pnl_usd
        # is small enough to pass the concentration guard individually even when
        # the position as a whole dominates the account. Aggregate to position
        # level (leaderMark is already fixed per-trader here; group by symbol +
        # closed_ms) for the concentration hard filter; the order-level figure is
        # kept too, for comparison, but is not what gates a trader out.
        pos_pnl = collections.defaultdict(float)
        for z in v:
            pos_pnl[(z['sym'], z['closed_ms'])] += z['pnl']
        best_pnl = max(pos_pnl.values())

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

        info = trader_info.get(uid, {})
        locate_days = info.get('locate_days') or 0
        upl_info = open_upl.get(uid, {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0,
                                       'has_upl_data': False})
        series = yield_series.get(uid, [])
        window_start_ms = v[0]['started_ms']
        dd_min_ratio, dd_min_ts, dd_covered = drawdown_screen(series, window_start_ms)

        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v),
                 levp90=levp90, margmed=margmed, durmed=durmed, conc=None,
                 conc_order=(best_pnl_order / total_pnl * 100) if total_pnl else None,
                 total_pnl=total_pnl, locate_days=locate_days,
                 fresh_start=locate_days < FRESH_START_DAYS,
                 open_upl_sum=upl_info['upl_sum'], n_open=upl_info['n_open'],
                 has_upl_data=upl_info['has_upl_data'],
                 hidden_loss_flag=(wr > 92 or (upl_info['has_upl_data'] and
                                                upl_info['upl_neg_sum'] < -abs(total_pnl) * 0.2)),
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(uid, 0),
                 max_cell_share=cell_share_max.get(uid, 0.0),
                 win_rate_7d=info.get('win_rate_7d'), win_rate_3w=info.get('win_rate_3w'),
                 profit_count=info.get('profit_count'), loss_count=info.get('loss_count'),
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
            rejections['concentration>30% (top-1 position, order-aggregated)'] += 1
            continue
        if upl_info['has_upl_data'] and upl_info['upl_sum'] < -abs(total_pnl) * 0.5:
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
            rejections['yield-trend drawdown >20%, uncovered by window'] += 1
            continue
        candidates.append(d)
    return candidates, rejections, any_upl_data


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/bybit_flatten.py first', flush=True)
        return
    rows = load_positions(CSV_PATH)
    print(f'positions loaded: {len(rows)}')
    bench, dropped_self_dominated, cell_share_max = compute_alpha(rows)
    open_upl = load_open_upl(OPEN_PATH)
    trader_info = load_trader_info(INFO_PATH)
    yield_series = load_yield_series(YIELD_PATH, duration='90D')
    candidates, rejections, any_upl_data = rank_traders(
        rows, open_upl, trader_info, yield_series,
        dropped_self_dominated=dropped_self_dominated, cell_share_max=cell_share_max)

    if not any_upl_data:
        print('\nNOTE: no trader in this universe had a usable open-position upl field '
              '(position/list documents no verified pnl key) — the open-unrealized-loss '
              'hard filter never fired this run; treat that as "untested", not "clean".')

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<55} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'concOrd%':>9}{'days':>6}{'ddmin%':>8}{'ddcov':>6}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        conc_order = d['conc_order'] if d['conc_order'] is not None else float('nan')
        ddmin = d['dd_min_ratio'] * 100 if d['dd_min_ratio'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}{conc_order:>9.1f}"
              f"{d['locate_days']:>6.0f}{ddmin:>8.1f}{str(d['dd_covered']):>6}")

    print('\nTrader-info cross-check (Bybit self-reported 7d win rate vs our computed closed win rate):')
    for d in candidates:
        wr7 = f"{d['win_rate_7d']*100:.1f}%" if d['win_rate_7d'] is not None else 'n/a'
        print(f"   {d['nick']:<24} computed_wr={d['wr']:.1f}%  bybit_7d_wr={wr7}")


if __name__ == '__main__':
    main()
