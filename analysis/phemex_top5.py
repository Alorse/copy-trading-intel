"""Phemex Top-5 candidate ranking. Ports okx_top5.py's methodology (leave-self-out
alpha vs the symbol x month x side median, concentration guard, Trampa 1 filter,
full Binance reference hard filters) to Phemex's fields, over the existing
`data/positions_all.jsonl` snapshot (196 traders, 7,467 closed positions — no
re-scraping was done for this pipeline).

Reads analysis/phemex_positions.csv (run analysis/phemex_flatten.py first) and,
opportunistically, `data/snapshots/2026-08-28/phemex_list.json` (the public
recommend-list response) for `showPosition` (universe honesty) and the
self-disclosed `mdd30`/`pnl30`/`roi30`/`wr30` (report-only cross-checks — see below).

`realizedPnl` is Phemex's own NET field — verified exactly:
`realizedPnl = closedPnl - exchangeFee - fundingFee` (SKILL.md line 32, and
re-verified below as the "internal consistency" cross-check for every survivor).

Differences from okx_top5.py / bybit_top5.py, all forced by what this dataset
actually contains:

  - **No open-position data for Phemex in this dataset at all** (positions_all.jsonl
    holds only `finished: true` rows; there is no `data/phemex_open_positions.jsonl`).
    The open-unrealized-loss hard filter used by OKX/Bybit is therefore **not
    applicable** here, not just "skipped" — it cannot be approximated even softly
    from this snapshot. This means Trap 1 (traders who hide losers by never closing
    them) can only be caught by this pipeline via the closed win-rate/payoff filters
    below, or via the recommend-list's self-disclosed `mdd30` when a survivor happens
    to still be present in that separately-scraped snapshot. A trader sitting on a
    large *currently open* unrealized loss behind a spotless closed record would slip
    through undetected by this run — the same blind spot Binance's lead-portfolio
    history has (SKILL.md "Trap 1" / the 2026-08-25 OKX audit's "01014588 lesson"),
    here with no proxy at all rather than a weak one.
  - **No independent, pre-window disclosure series exists for Phemex** (unlike OKX's
    weekly `pnlRatios[]` or Bybit's `totalYieldRateE4` trend, both of which extend
    *before* the visible closed-position window and can catch a drawdown the window
    itself doesn't cover). In its place, `monthly_drawdown_proxy()` below derives a
    **coarse, self-referential** proxy: the peak-to-trough drawdown of each trader's
    own *cumulative net realizedPnl by month*, built from the exact same rows already
    used for alpha. This can flag a large realized-money swing *within* the visible
    window (e.g. a big drawdown followed by recovery) but, by construction, can
    **never** reveal anything hidden *before* the window starts — it is strictly
    weaker than the OKX/Bybit screens and is reported as such, not represented as
    equivalent.
  - **Leverage is derived, not reported.** Phemex's closed-position rows carry no
    `lever` field; `phemex_flatten.py` computes `leverage = openPositionVal / margin`
    per row. Distribution sanity-checked over all 7,467 rows: p50=10x, p90=51x,
    p99=101x, max=112x — no zero/negative/absurd outliers, consistent with Phemex's
    advertised leverage tiers, so no additional capping is applied beyond the
    standard `lev > 0` row guard shared with okx_top5.py/bybit_top5.py.

Usage: python3 analysis/phemex_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'phemex_positions.csv')
LIST_PATH = os.path.join(D, 'snapshots', '2026-08-28', 'phemex_list.json')

MIN_CELL = 8             # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15                # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8           # min positions with a defined (leave-self-out) alpha

# Binance reference hard filters (top5_final.py:48-56), adopted in full as with OKX/Bybit.
T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5      # 30 minutes

DRAWDOWN_THRESHOLD = -0.20     # monthly-cum-PnL proxy screen (coarse — see module docstring)
MAX_CELL_SHARE_FLAG = 0.40     # report-only: trader dominates >40% of a benchmark cell


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
        # `side` (Buy/Sell), not `posSide`: 453/7467 rows report posSide="Merged"
        # (one-way mode) rather than Long/Short — see phemex_flatten.py's docstring.
        raw_side = r['side']
        pos_side = {'Buy': 'long', 'Sell': 'short'}.get(raw_side)
        if pos_side is None:
            continue
        pr = (cp / op - 1) * (1 if pos_side == 'long' else -1)
        if abs(pr) > 3:                # guard against bad ticks, same threshold as okx_top5.py
            continue
        month = dt.datetime.fromtimestamp(opened / 1000, dt.UTC).strftime('%Y-%m')
        dur_h = float(r['dur_h']) if r['dur_h'] not in ('', None) else 0.0
        rows.append(dict(uid=r['user_id'], nick=r['nick'], sym=r['symbol'], side=pos_side,
                          pr=pr, pnl=pnl, closed_pnl=float(r['closed_pnl']),
                          exch_fee=float(r['exchange_fee']), fund_fee=float(r['funding_fee']),
                          lev=lev, dur=dur_h, marg=marg, month=month, opened_ms=opened))
    return rows


def load_recommend_list(path=LIST_PATH):
    """Returns {user_id: {show_position, mdd30, pnl30, roi30, wr30, aum, followers}}
    from the recommend-list snapshot (a separately-scraped file from the same date
    range as positions_all.jsonl, not the position rows themselves — this is where
    `showPosition` actually lives; positions_all.jsonl only ever contains traders for
    whom it was True at scrape time, per SKILL.md)."""
    info = {}
    if not os.path.exists(path):
        return info
    for r in json.load(open(path)):
        uid = r.get('userId')
        if uid is None:
            continue

        def pf(key):
            try:
                return float(r.get(key))
            except (TypeError, ValueError):
                return None
        info[uid] = dict(show_position=bool(r.get('showPosition')),
                          mdd30=pf('mdd30'), pnl30=pf('pnl30'), roi30=pf('roi30'),
                          wr30=pf('wr30'), aum=pf('aum'), followers=r.get('followers'))
    return info


def monthly_drawdown_proxy(v):
    """Coarse, self-referential drawdown proxy (see module docstring): cumulative net
    realizedPnl by month for one trader's own rows, then the largest peak-to-trough
    drop as a fraction of the running peak. Returns (min_ratio, min_month, n_months):
    `min_ratio` is None when the trader never had a positive cumulative peak to fall
    from (already net-negative — caught separately by the net-negative filter) or
    trades fewer than 2 distinct months (no drawdown is measurable)."""
    by_month = collections.defaultdict(float)
    for z in v:
        by_month[z['month']] += z['pnl']
    months = sorted(by_month)
    if len(months) < 2:
        return None, None, len(months)
    cum = 0.0
    peak = 0.0
    min_ratio, min_month = None, None
    for m in months:
        cum += by_month[m]
        if cum > peak:
            peak = cum
        if peak > 0:
            ratio = (cum - peak) / peak
            if min_ratio is None or ratio < min_ratio:
                min_ratio, min_month = ratio, m
    return min_ratio, min_month, len(months)


def compute_alpha(rows, min_cell=MIN_CELL):
    """Identical algorithm to okx_top5.compute_alpha / bybit_top5.compute_alpha
    (leave-self-out cell median). Returns (bench, dropped_self_dominated, cell_share_max)."""
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


def rank_traders(rows, recommend=None, min_n=MIN_N, min_alpha_n=MIN_ALPHA_N,
                  t_min=T_MIN, levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None,
                  cell_share_max=None):
    recommend = recommend or {}
    dropped_self_dominated = dropped_self_dominated or {}
    cell_share_max = cell_share_max or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['uid']].append(x)

    candidates, rejections = [], collections.Counter()
    for uid, v in by_trader.items():
        v = sorted(v, key=lambda z: z['opened_ms'])
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

        dd_min_ratio, dd_min_month, dd_n_months = monthly_drawdown_proxy(v)
        # Self-referential by construction (see module docstring): the proxy is built
        # from the same window used everywhere else, so it can never be "uncovered" the
        # way OKX/Bybit's independent pre-window series can. `dd_covered` is kept only
        # for interface symmetry with okx_top5/bybit_top5's drawdown_screen() output.
        dd_covered = dd_min_ratio is None or dd_min_ratio >= DRAWDOWN_THRESHOLD

        rl = recommend.get(uid, {})
        computed_pnl_check = sum(z['closed_pnl'] - z['exch_fee'] - z['fund_fee'] for z in v)

        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v),
                 levp90=levp90, margmed=margmed, durmed=durmed, conc=None,
                 total_pnl=total_pnl,
                 hidden_loss_flag=(wr > 92 or (rl.get('mdd30') is not None and rl['mdd30'] > 0.4)),
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(uid, 0),
                 max_cell_share=cell_share_max.get(uid, 0.0),
                 dd_min_ratio=dd_min_ratio, dd_min_month=dd_min_month,
                 dd_n_months=dd_n_months, dd_covered=dd_covered,
                 show_position=rl.get('show_position'), mdd30=rl.get('mdd30'),
                 pnl30=rl.get('pnl30'), roi30=rl.get('roi30'), wr30=rl.get('wr30'),
                 computed_pnl=total_pnl, computed_pnl_check=computed_pnl_check,
                 pnl_internal_ratio=(total_pnl / computed_pnl_check
                                      if computed_pnl_check else None))

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
        if not dd_covered:
            rejections['monthly-cum-PnL drawdown proxy >20% (coarse, self-referential)'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/phemex_flatten.py first', flush=True)
        return
    rows = load_positions(CSV_PATH)
    print(f'positions loaded: {len(rows)}')
    bench, dropped_self_dominated, cell_share_max = compute_alpha(rows)
    recommend = load_recommend_list(LIST_PATH)
    if not recommend:
        print(f'NOTE: {LIST_PATH} not found — showPosition/mdd30 cross-checks unavailable this run.')
    candidates, rejections = rank_traders(rows, recommend,
                                           dropped_self_dominated=dropped_self_dominated,
                                           cell_share_max=cell_share_max)

    print('\nNOTE: no open-position data exists for Phemex in this dataset — the '
          'open-unrealized-loss hard filter used for OKX/Bybit is inapplicable here, '
          'not merely skipped (see module docstring). Trap 1 coverage for this run '
          'rests entirely on the closed win-rate/payoff filters plus the report-only '
          'mdd30 cross-check where a survivor happens to appear in the recommend-list '
          'snapshot.')

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<60} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'ddmin%':>8}{'mdd30%':>7}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        ddmin = d['dd_min_ratio'] * 100 if d['dd_min_ratio'] is not None else float('nan')
        mdd30 = d['mdd30'] * 100 if d['mdd30'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}"
              f"{ddmin:>8.1f}{mdd30:>7.1f}")

    print('\nInternal consistency cross-check (sum(realizedPnl) vs sum(closedPnl-fees)) — '
          'no external headline PnL exists per trader in this dataset, so this checks '
          'the field-level identity SKILL.md verified (realizedPnl = closedPnl - '
          'exchangeFee - fundingFee) holds at the aggregate level too, for every survivor:')
    for d in candidates:
        ratio = d['pnl_internal_ratio']
        ratio_s = f'{ratio:.4f}x' if ratio is not None else 'n/a'
        print(f"   {d['nick']:<24} realizedPnl=${d['computed_pnl']:>12,.2f}  "
              f"closedPnl-fees=${d['computed_pnl_check']:>12,.2f}  ratio={ratio_s}")


if __name__ == '__main__':
    main()
