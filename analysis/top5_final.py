"""Binance Top-5 candidate ranking. Mirrors okx_top5.py's corrected methodology
(alpha vs the symbol x month x side median, concentration guard, Trampa 1 filter)
back onto the larger, thicker-celled Binance universe (594 portfolios, measured
2026-08-25).

Reads analysis/binance_positions.csv (run analysis/flatten.py first) and, for the
hidden-drawdown screen, data/binance_portfolios.json directly -- its daily
`chartItems` are each portfolio's own cumulative-ROI curve, which reproduces
Binance's disclosed `mdd` field exactly (verified against all 5 pre-audit Top-5
picks, diff < 1e-3 percentage points; see drawdown_screen()'s docstring). That
snapshot matches the same 594 portfolios in binance_positions.jsonl one-for-one
(verified 2026-08-29).

`closing_pnl` is NET of fees (verified: -7.85 bps residual over 96,994 complete
closes; see SKILL.md).

Adversarial audit corrections applied 2026-08-29 (see the "Adversarial-audit
corrections applied 2026-08-29" section of analysis/TOP5.md), porting the same
corrections already shipped for OKX (analysis/okx_top5.py, TOP5_OKX.md):
  - compute_alpha now measures each trader against the cell median EXCLUDING its
    own rows (leave-self-out). A cell with no other trader's rows at all is
    dropped for that trader (not treated as zero alpha). Both the old
    (self-inclusive) and new alpha/t are reported so the shift is visible, and
    each survivor's max single-cell ownership share is reported (>40% flagged).
  - New hard filter: multi-pair only (H1 -- SKILL.md already states this as a
    project rule, "never judge a trader on a single pair", but it was never
    code-enforced here, unlike okx_top5.py).
  - New hard screen: hidden drawdown, built from data/binance_portfolios.json's
    daily `chartItems` -- the Binance-native equivalent of OKX's weekly
    `pnlRatios[]` screen (the "01014588 lesson"), adapted to a continuous daily
    equity curve instead of discrete weekly period returns.
  - The headline-vs-computed PnL cross-check (ranking `pnl` vs sum of visible
    `closing_pnl`) is now computed and reported for every survivor.

Usage: python3 analysis/top5_final.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'binance_positions.csv')
PORTFOLIOS_PATH = os.path.join(D, 'binance_portfolios.json')

MIN_CELL = 20          # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 60             # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 40       # min positions with a defined (leave-self-out) alpha

T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5    # 30 minutes

DRAWDOWN_THRESHOLD = -0.20   # hidden-drawdown screen, the "01014588 lesson"
MAX_CELL_SHARE_FLAG = 0.40   # report-only: trader dominates >40% of a benchmark cell


def load_positions(csv_path=CSV_PATH):
    rows = []
    for r in csv.DictReader(open(csv_path)):
        try:
            ac = float(r['avg_cost']); acl = float(r['avg_close'])
            notio = float(r['notional']); pnl = float(r['closing_pnl'])
            lev = float(r['leverage']); marg = float(r['margin_est'])
            opened = int(r['opened_ms'])
        except (TypeError, ValueError):
            continue
        if ac <= 0 or acl <= 0 or notio <= 0 or lev <= 0:
            continue
        side = r['side']
        if side not in ('Long', 'Short'):
            continue
        pr = (acl / ac - 1) * (1 if side == 'Long' else -1)
        if abs(pr) > 3:               # guard against bad ticks
            continue
        month = dt.datetime.fromtimestamp(opened / 1000, dt.UTC).strftime('%Y-%m')
        rows.append(dict(tid=r['portfolio_id'], nick=r['nick'], sym=r['symbol'], side=side,
                          pr=pr, pnl=pnl, lev=lev, dur=float(r['dur_h'] or 0), marg=marg,
                          mdd=float(r['mdd'] or 0), aum=float(r['aum'] or 0),
                          p_roi=float(r['p_roi'] or 0), p_pnl=float(r['p_pnl'] or 0),
                          month=month, opened_ms=opened))
    return rows


def load_chart_data(path=PORTFOLIOS_PATH):
    """Returns {portfolio_id: [(ts_ms, cumulative_roi_pct), ...]} from
    data/binance_portfolios.json's daily `chartItems` — used only for the
    hidden-drawdown screen."""
    charts = {}
    if not os.path.exists(path):
        return charts
    for r in json.load(open(path)):
        pid = r.get('leadPortfolioId')
        if not pid:
            continue
        chart = []
        for it in r.get('chartItems') or []:
            try:
                chart.append((int(it['dateTime']), float(it['value'])))
            except (TypeError, ValueError, KeyError):
                continue
        charts[pid] = chart
    return charts


def drawdown_screen(chart, window_start_ms, threshold=DRAWDOWN_THRESHOLD):
    """Checks a portfolio's own daily cumulative-ROI curve for a running
    peak-to-trough drawdown deeper than `threshold` that the visible
    closed-position window doesn't cover.

    `chart` is [(ts_ms, cumulative_roi_pct), ...]; treating equity as
    1 + roi/100 and tracking the running peak reproduces Binance's own
    disclosed `mdd` field exactly (verified 2026-08-29 against Cooma,
    梭哈到世界尽头, 秋高看山势, 牛熊摆渡人 and 重生之我在币圈捡垃圾-: computed vs
    disclosed differ by <1e-3 percentage points in every case), so its
    magnitude is trustworthy. What this adds over the bare `mdd` field is the
    trough's TIMESTAMP, needed to tell a covered drawdown from a hidden one —
    the Binance-native analogue of OKX's weekly `pnlRatios[]` screen (the
    "01014588 lesson"), built from a continuous daily equity curve instead of
    discrete weekly period returns.

    Returns (min_ratio, min_ts, covered), same shape as okx_top5.py's
    drawdown_screen: `min_ratio` is the drawdown as a negative fraction (e.g.
    -0.32), `covered` is True (safe) whenever the drawdown doesn't breach the
    threshold, or when it does but the window's earliest position predates the
    drawdown's deepest point."""
    if not chart:
        return None, None, True
    peak = None
    max_dd, max_dd_ts = 0.0, None
    for ts, value in sorted(chart):
        eq = 1 + value / 100.0
        if peak is None or eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak else 0.0
        if dd > max_dd:
            max_dd, max_dd_ts = dd, ts
    min_ratio = -max_dd
    if min_ratio >= threshold:
        return min_ratio, max_dd_ts, True
    covered = window_start_ms is not None and window_start_ms <= max_dd_ts
    return min_ratio, max_dd_ts, covered


def compute_alpha(rows, min_cell=MIN_CELL):
    """Sets x['alpha'] (leave-self-out: measured against the cell median EXCLUDING
    the trader's own rows) and x['alpha_incl'] (the old self-inclusive number, kept
    for reporting the inflation) on every row. A cell only yields a leave-self-out
    alpha for a trader if at least one OTHER trader's row remains in it after
    excluding the trader's own; if a qualifying cell (>=min_cell rows) is entirely
    one trader's own trades, that trader's rows in it get alpha=None (dropped) and
    are counted in the returned per-trader drop counter.

    Returns (bench, dropped_self_dominated, cell_share_max):
      bench                  {(sym, month, side): median} — self-inclusive, as before
      dropped_self_dominated {tid: n_rows_dropped_for_self_domination}
      cell_share_max         {tid: max(own_rows / total_rows) over the trader's cells}
    """
    cell = collections.defaultdict(list)   # key -> [(tid, pr), ...]
    for x in rows:
        cell[(x['sym'], x['month'], x['side'])].append((x['tid'], x['pr']))
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
        others = [pr for tid, pr in v if tid != x['tid']]
        share = (len(v) - len(others)) / len(v)
        if share > cell_share_max[x['tid']]:
            cell_share_max[x['tid']] = share
        if not others:
            x['alpha'] = None
            dropped_self_dominated[x['tid']] += 1
            continue
        x['alpha'] = x['pr'] - st.median(others)
    return bench, dict(dropped_self_dominated), dict(cell_share_max)


def rank_traders(rows, chart_data=None, min_n=MIN_N, min_alpha_n=MIN_ALPHA_N,
                  t_min=T_MIN, levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None, cell_share_max=None):
    chart_data = chart_data or {}
    dropped_self_dominated = dropped_self_dominated or {}
    cell_share_max = cell_share_max or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['tid']].append(x)

    candidates, rejections = [], collections.Counter()
    for tid, v in by_trader.items():
        v = sorted(v, key=lambda z: z['opened_ms'])
        al = [z['alpha'] for z in v if z['alpha'] is not None]            # leave-self-out
        al_incl = [z['alpha_incl'] for z in v if z['alpha_incl'] is not None]  # old, self-inclusive
        n_syms = len(set(z['sym'] for z in v))
        if len(v) < min_n or len(al) < min_alpha_n:
            rejections['sample too small (n<60, or <40 with a defined leave-self-out alpha)'] += 1
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
        ruin = min(losses) * st.median(z['lev'] for z in v) * 100
        months = sorted(set(z['month'] for z in v))
        margmed = st.median(z['marg'] for z in v)
        durmed = st.median(z['dur'] for z in v)

        window_start_ms = v[0]['opened_ms']
        dd_min_ratio, dd_min_ts, dd_covered = drawdown_screen(
            chart_data.get(tid, []), window_start_ms)
        ranking_pnl = v[0]['p_pnl']

        d = dict(tid=tid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff,
                 lev=st.median(z['lev'] for z in v), levp90=levp90, ruin=ruin,
                 margmed=margmed, durmed=durmed, conc=None, total_pnl=total_pnl,
                 mdd=v[0]['mdd'], aum=v[0]['aum'], roi=v[0]['p_roi'],
                 months=len(months), aug='2026-08' in months,
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(tid, 0),
                 max_cell_share=cell_share_max.get(tid, 0.0),
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
        if not d['aug']:
            rejections['inactive in August'] += 1
            continue
        if not dd_covered:
            rejections['hidden drawdown >20%, uncovered by window'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/flatten.py first', flush=True)
        return
    rows = load_positions(CSV_PATH)
    print(f'positions loaded: {len(rows)}')
    bench, dropped_self_dominated, cell_share_max = compute_alpha(rows)
    chart_data = load_chart_data(PORTFOLIOS_PATH)
    candidates, rejections = rank_traders(rows, chart_data,
                                           dropped_self_dominated=dropped_self_dominated,
                                           cell_share_max=cell_share_max)

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<65} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'mdd':>6}{'ddmin%':>8}{'ddcov':>6}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        ddmin = d['dd_min_ratio'] * 100 if d['dd_min_ratio'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}{d['mdd']:>6.1f}"
              f"{ddmin:>8.1f}{str(d['dd_covered']):>6}")

    print('\nHeadline (ranking) pnl vs computed (sum of visible closed pnl) — every survivor:')
    for d in candidates:
        ratio = d['pnl_cross_check_ratio']
        ratio_s = f'{ratio:.2f}x' if ratio is not None else 'n/a'
        print(f"   {d['nick']:<24} ranking=${d['ranking_pnl']:>12,.0f}  "
              f"computed=${d['computed_pnl']:>12,.0f}  ratio(computed/ranking)={ratio_s}")


if __name__ == '__main__':
    main()
