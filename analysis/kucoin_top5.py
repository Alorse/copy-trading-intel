"""KuCoin Top-5 candidate ranking. Ports bitget_top5.py's / okx_top5.py's
methodology (leave-self-out alpha vs the symbol x month x side median,
concentration guard, Trampa 1 filter, full Binance reference hard filters,
drawdown screen, open-position upl guard) to KuCoin's fields.

Reads analysis/kucoin_positions.csv (run analysis/kucoin_flatten.py first) and,
for the upl/drawdown/headline cross-checks, data/kucoin_open_positions.jsonl,
data/kucoin_traders.jsonl and data/kucoin_manifest.jsonl directly.

`pnl` is KuCoin's own field name for net-of-fees PnL on closed positions
(`scripts/scrape_kucoin_positions.py`'s docstring: median -12.0bps of notional
residual vs a price-derived gross reconstruction, 91.6% negative, n=395 — the
same fee-deducted signature as every other exchange here). The de-leveraged
return basis is `pr = pnlRatio / leverage`: `pnlRatio` was verified
self-consistent with `pnl / posMargin` (median absolute difference 5.8e-6,
n=395) — i.e. `pnlRatio` is itself the LEVERAGED return on margin, so dividing
by leverage recovers the price-basis return without the sign-flip risk that
forced Bitget/Bybit onto a fallback field (KuCoin's `avgEntryPrice`/
`avgClosePrice` are per-position aggregates already, not per-fill, so no such
risk was found here — but `pr` is still derived from `pnlRatio`, not
`avgClosePrice/avgEntryPrice - 1`, since `pnlRatio` already nets out fees the
same way `pnl` does and price-only would not).

## The open-position upl guard — the first exchange where it has real data

Bitget and Bybit's open-position endpoints exposed no verified unrealized-PnL
field at all (`has_upl_data=False` for their entire universes). KuCoin's
`positions/current` DOES: top-level `pnl`/`pnlRatio` on that endpoint are
UNREALIZED (verified live: identical to the nested `extendPositionResponse.
unrealisedPnl`). Ported verbatim from `okx_top5.py`'s `load_open_upl`/hard
filter: reject if `open_upl_sum < -abs(total_pnl) * 0.5` (open unrealized loss
exceeds 50% of closed PnL); `upl_neg_sum < -abs(total_pnl) * 0.2` is a soft
`hidden_loss_flag`, same threshold as OKX.

## The drawdown screen: no per-point timestamps, so a synthetic date anchor

KuCoin's leaderboard inlines a 90-day cumulative-$-PnL series (`pnl_series_90d`,
see `scrape_kucoin_positions.py`'s docstring for why this — not the 30d ratio
series — is the drawdown-screen basis: no 90d RATIO series is disclosed, and
`leadShow/pnl/history`'s daily `ratio` field blows up to nonsense under naive
compounding). Two things this series does NOT give us that Bitget's `roiRows`
and OKX's `pnlRatios[]` did:

  1. **No per-point timestamp** — just an ordered array, one point per day,
     last point = "as of scrape time". To decide whether a trader's own visible
     closed-position window covers the trough (the "01014588 lesson"'s
     uncovered-window carve-out), `drawdown_screen` synthesizes a timestamp for
     each point by counting backward in whole days from `series_end_ms`
     (approximated in `main()` from `os.path.getmtime(TRADERS_PATH)`, since the
     scrape did not separately record a per-row fetch timestamp). This is an
     approximation good to about a day, immaterial at the 20pp/20-day
     resolution this screen operates at, but it means `dd_trough_ts` values
     here are SYNTHETIC, not exchange-disclosed — never presented as exact.
  2. **Dollar units, not percent** — `pnl_series_90d` is a cumulative $ curve,
     not an ROI curve. Normalized here by `leadPrincipal` (a CURRENT snapshot
     from the same leaderboard row, not a point-in-time equity value) to get a
     percentage-point drawdown. This is the same class of approximation as
     Bitget's AUM-based normalization: a real caveat, reported as such, not
     silently assumed exact. A trader with `leadPrincipal<=0` (degenerate/empty
     account) gets `covered=False` — REJECTED, per the "missing series never
     silently passes" rule, not treated as clean.

## Headline cross-check

`totalPnl` is genuinely LIFETIME once `daysAsLeader>90` (verified: diverges from
`ninetyDayPnl` for older traders, identical to it for younger ones — see
scraper docstring). Since `paginate_history` has no discovered cap and no
Binance-style `startTime` truncation, `sum(pnl)` over every closed row scraped
IS the trader's full realized closed-PnL history — cross-checked uniformly
against `totalPnl`, with the window caveat printed for every candidate (young
leaders' `totalPnl` is only ~90d-equivalent, not truly lifetime).

Usage: python3 analysis/kucoin_top5.py
"""
import csv, json, os, statistics as st, collections, datetime as dt

BASE = os.path.join(os.path.dirname(__file__), '..')
D = os.path.join(BASE, 'data')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'kucoin_positions.csv')
OPEN_PATH = os.path.join(D, 'kucoin_open_positions.jsonl')
TRADERS_PATH = os.path.join(D, 'kucoin_traders.jsonl')
MANIFEST_PATH = os.path.join(D, 'kucoin_manifest.jsonl')

MIN_CELL = 8             # min rows in a (symbol, month, side) cell to trust its median
MIN_N = 15                # min closed positions for a trader to be considered at all
MIN_ALPHA_N = 8           # min positions with a defined (leave-self-out) alpha
FRESH_START_DAYS = 120    # report-only, mirrors sibling pipelines' fresh-start flag

# Binance reference hard filters (top5_final.py:48-56), adopted in full as with
# OKX/Bybit/Phemex/Bitget.
T_MIN = 2.5
LEVP90_MAX = 25.0
MARGIN_MED_MIN = 50.0
DUR_MED_MIN_H = 0.5      # 30 minutes

DRAWDOWN_THRESHOLD_PP = 20.0  # peak-to-trough of pnl_series_90d/leadPrincipal, pp
MAX_CELL_SHARE_FLAG = 0.40    # report-only: trader dominates >40% of a benchmark cell
DAY_MS = 86400000


def load_positions(csv_path=CSV_PATH):
    """Returns (rows, drops, n_csv) -- `drops` is a Counter keyed by rejection
    reason and `n_csv` is the raw row count of the CSV. Every CSV row falls into
    exactly `rows` or exactly one `drops` bucket by construction, so
    `len(rows) + sum(drops.values()) == n_csv` always holds; `main()` checks and
    shouts if it ever doesn't (a silent parsing regression must not quietly
    shrink the universe)."""
    rows = []
    drops = collections.Counter()
    n_csv = 0
    for r in csv.DictReader(open(csv_path)):
        n_csv += 1
        try:
            pnl = float(r['pnl'])
            ratio = float(r['pnl_ratio'])
            lev = float(r['leverage'])
            opened = int(r['start_time'])
            closed = int(r['end_time'])
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
        # De-leveraged, net-of-fees return. pnlRatio is already fee-inclusive
        # and self-consistent with pnl/margin (see module docstring); dividing
        # by leverage recovers the price-basis return.
        pr = ratio / lev
        if abs(pr) > 3:                # guard against bad ticks, same threshold as sibling pipelines
            drops['|pr|>3'] += 1
            continue
        month = dt.datetime.fromtimestamp(opened / 1000, dt.UTC).strftime('%Y-%m')
        dur_h = float(r['dur_h']) if r['dur_h'] not in ('', None) else 0.0
        # `lead_config_id` is numeric (int) in the JSONL sources (kucoin_traders/
        # kucoin_open_positions/kucoin_manifest), but round-trips through the CSV
        # as a string -- cast back to int here so `load_traders`/`load_open_upl`/
        # `load_manifest`'s dict lookups (keyed by the JSONL's native int) actually
        # hit instead of silently returning {} for every trader.
        rows.append(dict(uid=int(r['lead_config_id']), nick=r['nick_name'], sym=r['symbol'],
                          side=side, pr=pr, pnl=pnl, lev=lev, dur=dur_h, marg=marg,
                          month=month, started_ms=opened, closed_ms=closed))
    return rows, drops, n_csv


def load_open_upl(path=OPEN_PATH):
    """Returns {lead_config_id: {upl_sum, n_open, upl_neg_sum}} from
    kucoin_open_positions.jsonl's `unrealisedPnl` field -- verified real
    (unlike Bitget/Bybit's open endpoints, which had no such field). Ported
    verbatim from okx_top5.load_open_upl."""
    agg = collections.defaultdict(lambda: {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0})
    if not os.path.exists(path):
        return agg
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        try:
            upl = float(r.get('unrealisedPnl', 0) or 0)
        except (TypeError, ValueError):
            upl = 0.0
        a = agg[r['leadConfigId']]
        a['upl_sum'] += upl
        a['n_open'] += 1
        if upl < 0:
            a['upl_neg_sum'] += upl
    return agg


def load_traders(path=TRADERS_PATH):
    """Returns {lead_config_id: leaderboard_row} -- the row already carries
    `pnl_series_90d`/`leadPrincipal` (drawdown-screen basis) and `totalPnl`
    (headline cross-check basis); no extra network call needed."""
    info = {}
    if not os.path.exists(path):
        return info
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        lid = r.get('leadConfigId')
        if lid is not None:
            info[lid] = r
    return info


def load_manifest(path=MANIFEST_PATH):
    """Returns {lead_config_id: manifest_row} for the latest 'ok'/'not_found'
    entry per trader (open_status / n_open / summary_* fields)."""
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        lid = r.get('leadConfigId')
        if lid is not None and r.get('status') in ('ok', 'not_found'):
            out[lid] = r
    return out


def _peak_to_trough_indexed(series):
    """Returns (drop, trough_index) for the deepest peak-to-trough drawdown of a
    cumulative series already in the desired units (percentage points here).
    None if the series is empty."""
    if not series:
        return None
    peak = series[0]
    drop, trough_idx = 0.0, 0
    for i, val in enumerate(series):
        if val > peak:
            peak = val
        d = peak - val
        if d > drop:
            drop, trough_idx = d, i
    return drop, trough_idx


def drawdown_screen(pnl_series_90d, lead_principal, window_start_ms, series_end_ms):
    """Hard filter on the peak-to-trough drawdown of `pnl_series_90d` normalized
    by `leadPrincipal` (see module docstring for why: no 90d RATIO series is
    disclosed, so a $ series over a current-principal snapshot is the best
    available basis). A missing series OR a non-positive `leadPrincipal`
    REJECTS (`covered=False`) rather than silently passing -- an untested or
    degenerate trader must never be treated as pre-verified clean.
    Returns (drop_pct, trough_ts_ms, covered); `trough_ts_ms` is SYNTHETIC (see
    module docstring's timestamp-anchoring caveat)."""
    if not pnl_series_90d or not lead_principal or lead_principal <= 0:
        return None, None, False
    pct_series = [v / lead_principal * 100.0 for v in pnl_series_90d]
    detail = _peak_to_trough_indexed(pct_series)
    if detail is None:
        return None, None, False
    drop_pct, trough_idx = detail
    if drop_pct < DRAWDOWN_THRESHOLD_PP:
        return drop_pct, None, True    # shallow: no need to date the trough at all
    if series_end_ms is None:
        return drop_pct, None, False   # can't date the trough -> can't prove coverage -> reject
    days_ago = (len(pct_series) - 1) - trough_idx
    trough_ts_ms = series_end_ms - days_ago * DAY_MS
    covered = window_start_ms is not None and window_start_ms <= trough_ts_ms
    return drop_pct, trough_ts_ms, covered


def computed_mdd_pct(pnl_series_90d, lead_principal):
    """Peak-to-trough drawdown of `pnl_series_90d`, normalized to percentage
    POINTS of `leadPrincipal`. This IS the basis `drawdown_screen` hard-filters
    on; reported here again as a plain scalar for the report table."""
    if not pnl_series_90d or not lead_principal or lead_principal <= 0:
        return None
    pct_series = [v / lead_principal * 100.0 for v in pnl_series_90d]
    detail = _peak_to_trough_indexed(pct_series)
    return detail[0] if detail else None


def compute_alpha(rows, min_cell=MIN_CELL):
    """Identical algorithm to okx_top5.compute_alpha / bitget_top5.compute_alpha
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


def rank_traders(rows, open_upl=None, traders_info=None, manifest=None, series_end_ms=None,
                  min_n=MIN_N, min_alpha_n=MIN_ALPHA_N, t_min=T_MIN,
                  levp90_max=LEVP90_MAX, margin_med_min=MARGIN_MED_MIN,
                  dur_med_min_h=DUR_MED_MIN_H, dropped_self_dominated=None,
                  cell_share_max=None):
    open_upl = open_upl or {}
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
        best_pnl = max(z['pnl'] for z in v)   # one row == one full closed position (no fill-splitting found)

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

        upl_info = open_upl.get(uid, {'upl_sum': 0.0, 'n_open': 0, 'upl_neg_sum': 0.0})
        tr_info = traders_info.get(uid, {})
        window_start_ms = v[0]['started_ms']
        dd_pct, dd_trough_ts, dd_covered = drawdown_screen(
            tr_info.get('pnl_series_90d'), tr_info.get('leadPrincipal'),
            window_start_ms, series_end_ms)
        computed_mdd = computed_mdd_pct(tr_info.get('pnl_series_90d'), tr_info.get('leadPrincipal'))

        headline_total_pnl = tr_info.get('totalPnl')
        mf = manifest.get(uid, {})
        span_days = (max(z['closed_ms'] for z in v) - min(z['started_ms'] for z in v)) / 86400000.0

        d = dict(uid=uid, nick=v[0]['nick'], n=len(v), n_syms=n_syms,
                 alpha=mean_alpha, t=t, alpha_incl=mean_alpha_incl, t_incl=t_incl,
                 alpha_h2=alpha_h2, wr=wr, payoff=payoff, lev=st.median(z['lev'] for z in v),
                 levp90=levp90, margmed=margmed, durmed=durmed, conc=None,
                 total_pnl=total_pnl, headline_total_pnl=headline_total_pnl,
                 headline_ratio=(total_pnl / headline_total_pnl
                                 if headline_total_pnl else None),
                 fresh_start=span_days < FRESH_START_DAYS, span_days=span_days,
                 open_upl_sum=upl_info['upl_sum'], n_open=upl_info['n_open'],
                 has_upl_data=upl_info['n_open'] > 0,
                 hidden_loss_flag=(wr > 92 or upl_info['upl_neg_sum'] < -abs(total_pnl) * 0.2),
                 n_alpha_dropped_self_dominated=dropped_self_dominated.get(uid, 0),
                 max_cell_share=cell_share_max.get(uid, 0.0),
                 dd_peak_to_trough_pct=dd_pct, dd_trough_ts=dd_trough_ts, dd_covered=dd_covered,
                 computed_mdd_pct=computed_mdd, lead_principal=tr_info.get('leadPrincipal'),
                 open_status=mf.get('open_status'), n_open_manifest=mf.get('n_open'),
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
            rejections['concentration>30% (top-1 position)'] += 1
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
            rejections[f'90d pnl_series peak-to-trough drawdown '
                       f'>{DRAWDOWN_THRESHOLD_PP:g}pp, uncovered by window'] += 1
            continue
        candidates.append(d)
    return candidates, rejections


def main():
    if not os.path.exists(CSV_PATH):
        print(f'{CSV_PATH} not found — run analysis/kucoin_flatten.py first', flush=True)
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
    open_upl = load_open_upl(OPEN_PATH)
    traders_info = load_traders(TRADERS_PATH)
    manifest = load_manifest(MANIFEST_PATH)
    # Synthetic "now" anchor for the drawdown screen's trough-date approximation
    # (pnl_series_90d carries no per-point timestamp -- see module docstring).
    series_end_ms = (int(os.path.getmtime(TRADERS_PATH) * 1000)
                      if os.path.exists(TRADERS_PATH) else None)
    candidates, rejections = rank_traders(
        rows, open_upl, traders_info, manifest, series_end_ms,
        dropped_self_dominated=dropped_self_dominated, cell_share_max=cell_share_max)

    print(f'\nNOTE: open-position upl guard uses REAL unrealisedPnl data (first exchange '
          f'in this project where that guard is not a no-op) -- see module docstring.')

    print('\nRejections by filter:')
    for k, n in rejections.most_common():
        print(f'   {k:<60} {n}')
    print(f'\nSURVIVE THE HARD FILTERS: {len(candidates)}\n')

    candidates.sort(key=lambda d: -(d['t'] * 0.5 + d['alpha'] * 100 * 0.3 + d['payoff'] * 0.2))
    h = (f"{'nick':<24}{'n':>5}{'syms':>5}{'alpha%':>8}{'t':>6}{'a_old%':>8}{'t_old':>6}"
         f"{'aH2%':>7}{'wr%':>6}{'payoff':>7}{'lev':>5}{'levp90':>7}{'marg$':>8}{'dur_h':>7}"
         f"{'conc%':>7}{'span_d':>7}{'ddP2T%':>8}{'ddcov':>6}{'uplSum$':>10}")
    print(h)
    print('-' * len(h))
    for d in candidates:
        a_old = d['alpha_incl'] * 100 if d['alpha_incl'] is not None else float('nan')
        ddp2t = d['dd_peak_to_trough_pct'] if d['dd_peak_to_trough_pct'] is not None else float('nan')
        print(f"{d['nick'][:23]:<24}{d['n']:>5}{d['n_syms']:>5}{d['alpha']*100:>8.2f}"
              f"{d['t']:>6.2f}{a_old:>8.2f}{d['t_incl']:>6.2f}{d['alpha_h2']*100:>7.2f}"
              f"{d['wr']:>6.1f}{d['payoff']:>7.2f}{d['lev']:>5.0f}{d['levp90']:>7.0f}"
              f"{d['margmed']:>8.0f}{d['durmed']:>7.2f}{d['conc']:>7.1f}"
              f"{d['span_days']:>7.0f}{ddp2t:>8.1f}{str(d['dd_covered']):>6}"
              f"{d['open_upl_sum']:>10.1f}")

    print(f'\nUniform headline cross-check (leaderboard totalPnl vs sum(pnl) over '
          f'every closed row scraped, printed for every candidate. Window label: '
          f'totalPnl is genuinely LIFETIME once daysAsLeader>90, else identical to '
          f'the 90d figure -- see module docstring):')
    for d in candidates:
        ratio = d['headline_ratio']
        ratio_s = f'{ratio:.3f}x' if ratio is not None else 'n/a'
        print(f"   {d['nick']:<24} computed=${d['total_pnl']:>12,.2f}  "
              f"headline_totalPnl=${(d['headline_total_pnl'] or 0):>12,.2f}  ratio={ratio_s}")

    print(f"\nOpen-position upl guard, per candidate (unrealisedPnl summed over "
          f"kucoin_open_positions.jsonl -- REAL data, not a no-op):")
    for d in candidates:
        print(f"   {d['nick']:<24} open_upl_sum=${d['open_upl_sum']:>12,.2f}  "
              f"n_open={d['n_open']:>3}  hidden_loss_flag={d['hidden_loss_flag']}")


if __name__ == '__main__':
    main()
