"""Bitget Top-5 candidate ranking. Ports okx_top5.py's / bybit_top5.py's
methodology (leave-self-out alpha vs the symbol x month x side median,
concentration guard, Trampa 1 filter, full Binance reference hard filters,
drawdown screen) to Bitget's fields.

Reads analysis/bitget_positions.csv (run analysis/bitget_flatten.py first) and,
for the drawdown/MDD/headline cross-checks, data/bitget_cycle.jsonl,
data/bitget_traders.jsonl and data/bitget_manifest.jsonl directly.

`net_profit` is Bitget's own field name for net-of-fees PnL. `analysis/
scrape_bitget_positions.py`'s docstring documents the pnl-reconciliation finding
that forces the `pr` basis here: reconstructing a de-leveraged return from
`(close_avg_price/open_avg_price - 1)` disagrees in SIGN with `net_profit` on
10.1% of a 455-row live sample (each `historyList` row is one order/fill, and a
scaled position's simultaneous multi-fill close does not split PnL proportionally
to each fill's own price delta — the allocation logic isn't disclosed). Instead
`pr = return_rate / open_level` is used: `return_rate` is Bitget's own field,
verified self-consistent with `net_profit / margin` to a median 0.8 percentage
point / p90 6.0pp absolute deviation (n=455) — noisier than Bybit's 0.02%/0.16%
precedent but an order of magnitude tighter than the price-derived basis's 10%
sign-flip rate. `open_avg_price`/`close_avg_price` are kept in the CSV for
reference only.

Bitget has no per-trader open-position unrealized-PnL field (verified live: every
`currentList` item carries only entry-side fields). The open-unrealized-loss hard
filter used by OKX/Bybit is therefore never exercised here — same as Bybit's
"untested, not clean" caveat, reported the same way (`has_upl_data` stays False
for the whole universe rather than defaulting to "safe").

Two independent things Bitget DOES disclose that OKX/Bybit didn't in the same
shape:
  - `cycleData`'s 90-day `roiRows` cumulative series -- the drawdown screen basis
    (the Bitget analogue of OKX's weekly `pnlRatios[]` / Bybit's yield-trend), plus
    `statisticsDTO.maxRetracement`, Bitget's own native MDD (NOT peak-to-trough of
    the published series -- an internal formula, reported as a cross-check against
    a computed peak-to-trough of `roiRows`, never treated as identical).
  - The leaderboard's self-reported `total_pnl` -- cross-checked against
    `sum(net_profit)` over EVERY closed row this pipeline scraped for that trader
    (uniform, printed for every candidate, not just the favorable ones -- the
    checklist's "01014588 lesson"). ⚠️ **Not a lifetime figure** (GLM finding,
    empirically re-checked here): across 261 traders with both a leaderboard
    `total_pnl` and a 90d `cycleData` cumulative-pnl curve, `total_pnl` sits closer
    to the 90d curve's endpoint (median ratio 0.77, 16.9% of traders within 5%)
    than to the lifetime `sum(net_profit)` over every scraped row (median ratio
    0.62, 9.5% within 5%) -- consistent with "roughly 90d", but neither basis is an
    exact match, so the ratio is reported with an explicit window label and is
    NEVER treated as a red flag on its own.

## The drawdown screen (GLM-2 / Fable-1 correction)

The original `drawdown_screen` took `min()` of the raw CUMULATIVE `roiRows` curve --
that measures "how far below zero the curve ever got", not a drawdown, and let 196⁄286
traders with a genuine >20pp peak-to-trough hit slip through while rejecting only 5.
Fixed: `drawdown_screen` now walks the same series tracking the running peak and the
deepest peak-to-trough drop (`computed_mdd_pct`'s formula, promoted from report-only
to the actual hard-filter basis). Three drawdown-related hard filters now run,
each with its own window:

  1. **Peak-to-trough of `roiRows`, 90d window** (`dd_covered`) -- reject if the drop
     exceeds `DRAWDOWN_THRESHOLD_PP` (20pp) AND the trader's own visible closed-
     position window doesn't reach back to the trough (the original "01014588
     lesson"). A missing series REJECTS outright (`covered=False`) -- it used to
     silently pass (`covered=True`), i.e. an untested trader was treated as
     verified clean.
  2. **`statisticsDTO.maxRetracement`, same 90d window** (`native_mdd_pct`) --
     Bitget's own MDD figure for the identical series; reject if >20%. Simple
     absolute threshold (no coverage clause needed: it's already scoped to the same
     90d window as #1, unlike #3).
  3. **`detail_mdd`, LIFETIME window, uncovered case only** -- `traderDetailPageV2`'s
     `max_retracement` is an all-time figure on a basis that does NOT reduce to
     peak-to-trough of `roiRows` on any disclosed window: fetching `cycleData` at
     `cycleTime=180` for a 36-trader sample and computing its own peak-to-trough
     gave values in the HUNDREDS to THOUSANDS of percentage points (unbounded
     cumulative-ROI compounding under leverage), while `detail_mdd` for the same
     traders sat in the tens to low hundreds -- not a window difference, a
     different metric entirely (likely equity/AUM-based, not ROI-curve-based).
     Given that ambiguity, the fallback from the checklist's OKX precedent applies:
     reject when `detail_mdd > 20%` AND the trader's closed-position span
     (`span_days`) exceeds the cycle window (`CYCLE_WINDOW_DAYS` = 90) -- i.e. only
     when the visible closed-position history plausibly extends further back than
     what `cycleData` covers, so a large lifetime drawdown could be sitting entirely
     outside the tested window (the exact "01014588 lesson" semantics, generalized
     to a metric whose scale can't otherwise be reconciled).

Position-level concentration groups order rows by
`(trader_uid, symbol_id, close_time // 1000)` -- Bitget serves one row per
order/fill, not one row per logical position (see scrape_bitget_positions.py's
docstring: a single scaled close can span up to 9+ rows sharing an identical
`positionAverage` and a `closeTime` within ~1ms of each other).

Usage: python3 analysis/bitget_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'bitget_positions.csv')
CYCLE_PATH = os.path.join(D, 'bitget_cycle.jsonl')
TRADERS_PATH = os.path.join(D, 'bitget_traders.jsonl')
MANIFEST_PATH = os.path.join(D, 'bitget_manifest.jsonl')

MIN_CELL = 8             # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15                # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8           # min positions with a defined (leave-self-out) alpha
FRESH_START_DAYS = 120    # report-only, mirrors bybit_top5's locate_days flag

# Binance reference hard filters (top5_final.py:48-56), adopted in full as with
# OKX/Bybit/Phemex.
T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5      # 30 minutes

DRAWDOWN_THRESHOLD_PP = 20.0  # peak-to-trough / native_mdd / detail_mdd screens, pp
CYCLE_WINDOW_DAYS = 90         # the cycleData window used everywhere below (load_cycle's
                                # default cycle_time) -- the basis for the detail_mdd
                                # uncovered-window rule
MAX_CELL_SHARE_FLAG = 0.40    # report-only: trader dominates >40% of a benchmark cell


def load_positions(csv_path=CSV_PATH):
    """Returns (rows, drops, n_csv) -- `drops` is a Counter keyed by rejection
    reason ('parse', 'lev<=0', 'side', '|pr|>3') and `n_csv` is the raw row count of
    the CSV. Every CSV row falls into exactly `rows` or exactly one `drops` bucket
    by construction, so `len(rows) + sum(drops.values()) == n_csv` always holds;
    `main()` still checks and shouts if it ever doesn't (Fable-3/GLM-1c: a silent
    parsing regression must not quietly shrink the universe)."""
    rows = []
    drops = collections.Counter()
    n_csv = 0
    for r in csv.DictReader(open(csv_path)):
        n_csv += 1
        try:
            pnl = float(r['net_profit'])
            rr = float(r['return_rate'])
            lev = float(r['open_level'])
            opened = int(r['open_time'])
            closed = int(r['close_time'])
            marg = float(r['margin'])
        except (TypeError, ValueError):
            drops['parse'] += 1
            continue
        if lev <= 0:
            drops['lev<=0'] += 1
            continue
        side = r['side']
        if side not in ('long', 'short'):
            drops['side'] += 1
            continue
        # De-leveraged, net-of-fees return, NOT derived from open/close price (see
        # module docstring: price-derived return disagrees in sign with net_profit
        # on ~10% of rows; return_rate/open_level is the verified, self-consistent
        # basis instead).
        pr = rr / lev
        if abs(pr) > 3:                # guard against bad ticks, same threshold as sibling pipelines
            drops['|pr|>3'] += 1
            continue
        month = dt.datetime.fromtimestamp(opened / 1000, dt.UTC).strftime('%Y-%m')
        dur_h = float(r['dur_h']) if r['dur_h'] not in ('', None) else 0.0
        rows.append(dict(uid=r['trader_uid'], nick=r['display_name'], sym=r['product_code'],
                          symbol_id=r['symbol_id'], side=side, pr=pr, pnl=pnl, lev=lev,
                          dur=dur_h, marg=marg, month=month, started_ms=opened,
                          closed_ms=closed))
    return rows, drops, n_csv


def load_cycle(path=CYCLE_PATH, cycle_time=90):
    """Returns {trader_uid: {roi_series: [(ts, fraction), ...], native_mdd_pct,
    profit_rate_pct, aum, total_trades, profit_trades, loss_trades, winning_rate_pct}}.
    `roiRows` amounts ship as percent numbers (e.g. "-3.43" == -3.43%); converted to
    a fraction here (/100) so `drawdown_screen`'s peak-to-trough walk operates on
    the same units the series is naturally expressed in."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get('cycleTime') != cycle_time:
            continue
        out[r['traderUid']] = dict(
            roi_series=[(ts, val / 100.0) for ts, val in (r.get('roi_rows') or [])],
            native_mdd_pct=r.get('max_retracement'),
            profit_rate_pct=r.get('profit_rate'),
            aum=r.get('aum'),
            total_trades=r.get('total_trades'),
            profit_trades=r.get('profit_trades'),
            loss_trades=r.get('loss_trades'),
            winning_rate_pct=r.get('winning_rate'),
        )
    return out


def load_traders(path=TRADERS_PATH):
    """Returns {trader_uid: {total_pnl, aum, mdd, roi, win_rate, follow_count}}
    from the leaderboard snapshot -- the headline `total_pnl` here is the uniform
    cross-check basis against sum(net_profit) over every closed row scraped."""
    info = {}
    if not os.path.exists(path):
        return info
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        uid = r.get('traderUid')
        if uid:
            info[uid] = r
    return info


def load_manifest(path=MANIFEST_PATH):
    """Returns {trader_uid: manifest_row} for the latest 'ok'/'protected' entry per
    trader (used for n_open / open_status / detail_* headline fields)."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        uid = r.get('traderUid')
        if uid and r.get('status') in ('ok', 'protected'):
            out[uid] = r
    return out


def _peak_to_trough(series):
    """Returns (drop_pct, trough_ts) for the deepest peak-to-trough drawdown of a
    cumulative series (values are fractions, e.g. 0.05 == +5%), `drop_pct` in
    percentage POINTS. None if the series is empty. Shared by `computed_mdd_pct`
    (report-only cross-check figure) and `drawdown_screen` (the hard filter) so the
    two can never drift apart -- see the module docstring's GLM-2/Fable-1 fix: the
    old `drawdown_screen` took `min()` of the raw curve instead of measuring a
    drawdown at all."""
    if not series:
        return None
    ordered = sorted(series)
    peak = ordered[0][1]
    drop_pct, trough_ts = 0.0, ordered[0][0]
    for ts, val in ordered:
        if val > peak:
            peak = val
        drop = (peak - val) * 100.0
        if drop > drop_pct:
            drop_pct, trough_ts = drop, ts
    return drop_pct, trough_ts


def drawdown_screen(series, window_start_ms):
    """Hard filter on the TRUE peak-to-trough drawdown of the disclosed 90d
    `roiRows` series (see module docstring, screen #1 of 3): rejects a >20pp drop
    that the visible closed-position window doesn't cover (the "01014588 lesson").
    A missing series REJECTS (`covered=False`) rather than silently passing -- the
    old code's `if not series: return None, None, True` treated a trader with NO
    drawdown data as if the screen had verified them clean.
    Returns (drop_pct, trough_ts, covered)."""
    detail = _peak_to_trough(series)
    if detail is None:
        return None, None, False
    drop_pct, trough_ts = detail
    if drop_pct < DRAWDOWN_THRESHOLD_PP:
        return drop_pct, trough_ts, True
    covered = window_start_ms is not None and window_start_ms <= trough_ts
    return drop_pct, trough_ts, covered


def computed_mdd_pct(series):
    """Peak-to-trough drawdown of the cumulative roi_series, in percentage POINTS
    (not a fraction of a running dollar peak like phemex_top5's proxy -- roiRows is
    already a cumulative ROI curve, so the natural unit is pp). This IS the basis
    `drawdown_screen` hard-filters on (see `_peak_to_trough`); reported here again
    as a plain scalar for cross-checking against cycleData's native
    `maxRetracement`, which is NOT expected to match exactly (an undisclosed
    internal formula) -- see module docstring for the empirical 180d-window check
    showing `detail_mdd` isn't even on the same scale."""
    detail = _peak_to_trough(series)
    return detail[0] if detail else None


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


def rank_traders(rows, cycle=None, traders_info=None, manifest=None,
                  min_n=MIN_N, min_alpha_n=MIN_ALPHA_N, t_min=T_MIN,
                  levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None,
                  cell_share_max=None):
    cycle = cycle or {}
    traders_info = traders_info or {}
    manifest = manifest or {}
    dropped_self_dominated = dropped_self_dominated or {}
    cell_share_max = cell_share_max or {}
    by_trader = collections.defaultdict(list)
    for x in rows:
        by_trader[x['uid']].append(x)

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
        # Bitget serves one row per order/fill, not one per logical position (see
        # module docstring): group by (symbol_id, close_time rounded to the nearest
        # second) so a scaled position's simultaneous multi-fill close can't dodge
        # the concentration guard just because each fill's own pnl is small.
        pos_pnl = collections.defaultdict(float)
        for z in v:
            pos_pnl[(z['symbol_id'], z['closed_ms'] // 1000)] += z['pnl']
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

        cyc = cycle.get(uid, {})
        series = cyc.get('roi_series', [])
        window_start_ms = v[0]['started_ms']
        dd_pct, dd_trough_ts, dd_covered = drawdown_screen(series, window_start_ms)
        computed_mdd = computed_mdd_pct(series)
        native_mdd_pct = cyc.get('native_mdd_pct')

        tr_info = traders_info.get(uid, {})
        headline_total_pnl = tr_info.get('total_pnl')
        mf = manifest.get(uid, {})
        detail_mdd = mf.get('detail_mdd')
        span_days = (max(z['closed_ms'] for z in v) - min(z['started_ms'] for z in v)) / 86400000.0
        detail_cycle_gap_pp = (detail_mdd - computed_mdd
                                if detail_mdd is not None and computed_mdd is not None else None)

        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v),
                 levp90=levp90, margmed=margmed, durmed=durmed, conc=None,
                 conc_order=(best_pnl_order / total_pnl * 100) if total_pnl else None,
                 total_pnl=total_pnl, headline_total_pnl=headline_total_pnl,
                 headline_ratio=(total_pnl / headline_total_pnl
                                 if headline_total_pnl else None),
                 fresh_start=span_days < FRESH_START_DAYS, span_days=span_days,
                 n_open=mf.get('n_open'), open_status=mf.get('open_status'),
                 has_upl_data=False,     # no verified unrealized-pnl field exists (see docstring)
                 hidden_loss_flag=(wr > 92),
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(uid, 0),
                 max_cell_share=cell_share_max.get(uid, 0.0),
                 dd_peak_to_trough_pct=dd_pct, dd_trough_ts=dd_trough_ts, dd_covered=dd_covered,
                 native_mdd_pct=native_mdd_pct, computed_mdd_pct=computed_mdd,
                 detail_mdd=detail_mdd, detail_cycle_gap_pp=detail_cycle_gap_pp,
                 cycle_winning_rate_pct=cyc.get('winning_rate_pct'),
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
            rejections[f'cycleData {CYCLE_WINDOW_DAYS}d peak-to-trough drawdown '
                       f'>{DRAWDOWN_THRESHOLD_PP:g}pp, uncovered by window'] += 1
            continue
        if native_mdd_pct is not None and native_mdd_pct > DRAWDOWN_THRESHOLD_PP:
            rejections[f'native MDD (cycleData {CYCLE_WINDOW_DAYS}d) '
                       f'>{DRAWDOWN_THRESHOLD_PP:g}%'] += 1
            continue
        if (detail_mdd is not None and detail_mdd > DRAWDOWN_THRESHOLD_PP
                and span_days > CYCLE_WINDOW_DAYS):
            rejections[f'detail_mdd (lifetime) >{DRAWDOWN_THRESHOLD_PP:g}%, uncovered '
                       f'(closed span {CYCLE_WINDOW_DAYS}d+)'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/bitget_flatten.py first', flush=True)
        return
    rows, drops, n_csv = load_positions(CSV_PATH)
    n_dropped = sum(drops.values())
    drop_s = ', '.join(f'{k}={v}' for k, v in drops.most_common()) if drops else 'none'
    print(f'positions loaded: {len(rows)}  (dropped {n_dropped}: {drop_s})')
    if len(rows) + n_dropped != n_csv:
        print(f'*** ACCOUNTING MISMATCH: CSV has {n_csv} rows but '
              f'loaded+dropped = {len(rows) + n_dropped} — investigate before trusting '
              f'anything below ***', flush=True)
    bench, dropped_self_dominated, cell_share_max = compute_alpha(rows)
    cycle = load_cycle(CYCLE_PATH)
    traders_info = load_traders(TRADERS_PATH)
    manifest = load_manifest(MANIFEST_PATH)
    candidates, rejections = rank_traders(
        rows, cycle, traders_info, manifest,
        dropped_self_dominated=dropped_self_dominated, cell_share_max=cell_share_max)

    print('\nNOTE: no trader in this universe has a verified unrealized-pnl field on '
          'currentList (open positions) — the open-unrealized-loss hard filter used '
          'for OKX/Bybit never fires here; treat that as "untested", not "clean" '
          '(see module docstring).')

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<60} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'concOrd%':>9}{'span_d':>7}{'ddP2T%':>8}{'ddcov':>6}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        conc_order = d['conc_order'] if d['conc_order'] is not None else float('nan')
        # ddP2T%: TRUE peak-to-trough of the 90d roiRows series (see drawdown_screen /
        # _peak_to_trough) -- fixed from the old "min of the raw cumulative curve"
        # figure, which was a level, not a drawdown (GLM-2/Fable-1).
        ddp2t = d['dd_peak_to_trough_pct'] if d['dd_peak_to_trough_pct'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}{conc_order:>9.1f}"
              f"{d['span_days']:>7.0f}{ddp2t:>8.1f}{str(d['dd_covered']):>6}")

    print(f'\nUniform headline cross-check (leaderboard total_pnl vs sum(net_profit) over '
          f'every closed row scraped, printed for every candidate). Window label: '
          f'total_pnl is NOT lifetime (empirically closer to the {CYCLE_WINDOW_DAYS}d '
          f'cycleData cumulative pnl than to the lifetime sum across 261 traders — median '
          f'ratio 0.77 vs 0.62 — but neither is an exact match; the ratio below is '
          f'informational, not a red flag):')
    for d in candidates:
        ratio = d['headline_ratio']
        ratio_s = f'{ratio:.3f}x' if ratio is not None else 'n/a'
        print(f"   {d['nick']:<24} computed_lifetime=${d['total_pnl']:>12,.2f}  "
              f"headline_~{CYCLE_WINDOW_DAYS}d=${(d['headline_total_pnl'] or 0):>12,.2f}  "
              f"ratio={ratio_s}")

    print(f'\nMDD cross-check across THREE windows/bases (see module docstring for why '
          f'they are not expected to agree):')
    for d in candidates:
        nat = d['native_mdd_pct']
        comp = d['computed_mdd_pct']
        det = d['detail_mdd']
        gap = d['detail_cycle_gap_pp']
        nat_s = f'{nat:.1f}%' if nat is not None else 'n/a'
        comp_s = f'{comp:.1f}pp' if comp is not None else 'n/a'
        det_s = f'{det:.1f}%' if det is not None else 'n/a'
        gap_s = f'{gap:+.1f}pp' if gap is not None else 'n/a'
        print(f"   {d['nick']:<24} native_mdd({CYCLE_WINDOW_DAYS}d)={nat_s:<8} "
              f"computed_p2t({CYCLE_WINDOW_DAYS}d)={comp_s:<10} detail_mdd(lifetime)={det_s:<8} "
              f"detail-vs-cycle{CYCLE_WINDOW_DAYS} gap={gap_s}")


if __name__ == '__main__':
    main()
