import csv
import json
from analysis import bybit_flatten
from analysis import bybit_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, started_ms=0,
         closed_ms=None):
    return dict(uid=uid, nick=nick, sym=sym, side=side, pr=pr, pnl=pnl,
                lev=lev, dur=2.0, marg=marg, month=month, started_ms=started_ms,
                closed_ms=closed_ms if closed_ms is not None else started_ms)


def _filler(sym, month, side, n=3, pr=0.0):
    return [_row(f'FILLER{i}', sym, month, side, pr, 0.0) for i in range(n)]


def test_compute_alpha_is_pr_minus_cell_median():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    rows.append(_row('B', 'BTCUSDT', '2026-06', 'long', 0.10, 1.0))
    t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha'] is not None for r in rows)
    assert rows[-1]['alpha'] > 0


def test_compute_alpha_none_when_cell_too_small():
    rows = [_row('A', 'ETHUSDT', '2026-06', 'short', -0.01, 1.0)]
    t5.compute_alpha(rows, min_cell=8)
    assert rows[0]['alpha'] is None


def test_compute_alpha_leave_self_out_shifts_alpha_in_self_dominated_cell():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.05, 1.0) for _ in range(6)]
    rows += [_row('B', 'BTCUSDT', '2026-06', 'long', 0.01, 1.0) for _ in range(3)]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert dropped == {}
    assert cell_share['A'] == 6 / 9
    assert cell_share['B'] == 3 / 9
    a_rows = [r for r in rows if r['uid'] == 'A']
    assert all(abs(r['alpha_incl']) < 1e-9 for r in a_rows)
    assert all(abs(r['alpha'] - 0.04) < 1e-9 for r in a_rows)


def test_compute_alpha_drops_self_dominated_cell():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha_incl'] is not None for r in rows)
    assert all(r['alpha'] is None for r in rows)
    assert dropped == {'A': 8}
    assert cell_share['A'] == 1.0


def _multi_pair_trader(uid, n=24, base_pnl=10.0, nick='good'):
    rows = []
    for i in range(n):
        sym = 'BTCUSDT' if i % 2 == 0 else 'ETHUSDT'
        pr = 0.02 if i % 4 else -0.01
        pnl = base_pnl if pr > 0 else -base_pnl * 0.4
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick, started_ms=i))
    for sym in ('BTCUSDT', 'ETHUSDT'):
        rows += [_row('FILLER', sym, '2026-06', 'long', 0.0, 0.0) for _ in range(20)]
    return rows


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTCUSDT', '2026-06', 'short', -0.01, -1.0) for _ in range(5)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('BTCUSDT', '2026-06', 'short')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -1.0)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTCUSDT', '2026-07', 'long', 0.5, 1000.0))
    rows += (_filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
             + _filler('BTCUSDT', '2026-07', 'long'))
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 position, order-aggregated)' not in rejections


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                                 levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['uid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


def test_rank_traders_flags_and_rejects_large_open_unrealized_loss():
    rows = _multi_pair_trader('RISKY', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'RISKY')
    open_upl = {'RISKY': {'upl_sum': -abs(total_pnl) * 2, 'n_open': 3,
                           'upl_neg_sum': -abs(total_pnl) * 2, 'has_upl_data': True}}
    candidates, rejections, _ = t5.rank_traders(rows, open_upl=open_upl, min_n=15, min_alpha_n=1,
                                                 t_min=0, levp90_max=100, margin_med_min=0,
                                                 dur_med_min_h=0)
    assert candidates == []
    assert rejections['open unrealized loss > 50% of closed PnL'] >= 1


def test_rank_traders_no_upl_data_skips_hard_filter_not_defaults_safe():
    # has_upl_data=False must NOT be treated as "no loss" — the hard filter simply
    # can't fire without data, and any_upl_data (returned separately) reports False
    # so the caller can print an honest "untested" note instead of implying safety.
    rows = _multi_pair_trader('NODATA', n=24)
    t5.compute_alpha(rows, min_cell=1)
    open_upl = {'NODATA': {'upl_sum': 0.0, 'n_open': 2, 'upl_neg_sum': 0.0, 'has_upl_data': False}}
    candidates, rejections, any_upl_data = t5.rank_traders(
        rows, open_upl=open_upl, min_n=15, min_alpha_n=1, t_min=0, levp90_max=100,
        margin_med_min=0, dur_med_min_h=0)
    assert len(candidates) == 1
    assert any_upl_data is False
    assert candidates[0]['has_upl_data'] is False


def test_rank_traders_open_upl_hard_filter_uses_net_not_negative_only():
    rows = _multi_pair_trader('NETPOS', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'NETPOS')
    open_upl = {'NETPOS': {'upl_sum': abs(total_pnl) * 0.1, 'n_open': 2,
                            'upl_neg_sum': -abs(total_pnl) * 2, 'has_upl_data': True}}
    candidates, rejections, _ = t5.rank_traders(rows, open_upl=open_upl, min_n=15, min_alpha_n=1,
                                                 t_min=0, levp90_max=100, margin_med_min=0,
                                                 dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['hidden_loss_flag'] is True   # soft flag still fires off upl_neg_sum


def test_rank_traders_fresh_start_flag_below_120_days():
    rows = _multi_pair_trader('YOUNG', n=24)
    t5.compute_alpha(rows, min_cell=1)
    trader_info = {'YOUNG': {'locate_days': 45}}
    candidates, _, _ = t5.rank_traders(rows, trader_info=trader_info, min_n=15, min_alpha_n=1,
                                        t_min=0, levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates[0]['fresh_start'] is True


def test_load_open_upl_aggregates_negative_and_positive_and_has_data_flag(tmp_path):
    path = tmp_path / 'bybit_open_positions.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'leaderMark': 'A', 'upl': -5.0},
        {'leaderMark': 'A', 'upl': 2.0},
        {'leaderMark': 'B', 'upl': 1.0},
        {'leaderMark': 'C', 'upl': None},
    ]))
    agg = t5.load_open_upl(str(path))
    assert agg['A']['upl_sum'] == -3.0
    assert agg['A']['n_open'] == 2
    assert agg['A']['upl_neg_sum'] == -5.0
    assert agg['A']['has_upl_data'] is True
    assert agg['B']['upl_neg_sum'] == 0.0
    assert agg['C']['has_upl_data'] is False
    assert agg['C']['n_open'] == 1


def test_load_open_upl_missing_file_returns_empty_defaultdict(tmp_path):
    agg = t5.load_open_upl(str(tmp_path / 'nope.jsonl'))
    assert agg['anything']['n_open'] == 0
    assert agg['anything']['has_upl_data'] is False


def test_load_trader_info_reads_locate_days_and_win_rates(tmp_path):
    path = tmp_path / 'bybit_trader_info.jsonl'
    path.write_text(json.dumps({
        'leaderMark': 'A', 'locate_days': 308, 'win_rate_7d': 1.0, 'win_rate_3w': 0.5909,
        'profit_count': 31, 'loss_count': 23,
    }) + '\n')
    info = t5.load_trader_info(str(path))
    assert info['A']['locate_days'] == 308
    assert info['A']['win_rate_7d'] == 1.0


def test_load_trader_info_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_trader_info(str(tmp_path / 'nope.jsonl')) == {}


def test_load_yield_series_filters_by_duration(tmp_path):
    path = tmp_path / 'bybit_yield_trend.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'leaderMark': 'A', 'duration': '90D', 'series': [[1000, 0.1], [2000, -0.3]]},
        {'leaderMark': 'A', 'duration': '7D', 'series': [[3000, 0.05]]},
    ]))
    series_90 = t5.load_yield_series(str(path), duration='90D')
    assert series_90['A'] == [(1000, 0.1), (2000, -0.3)]
    series_7 = t5.load_yield_series(str(path), duration='7D')
    assert series_7['A'] == [(3000, 0.05)]


# ---------------------------------------------------------------------------
# Binance reference hard filters, ported from okx_top5.
# ---------------------------------------------------------------------------

def _threshold_fixture(**overrides):
    rows = []
    t_ms = 1_780_000_000_000
    i = 0
    lev = overrides.get('lev', 10.0)
    marg = overrides.get('marg', 100.0)
    dur = overrides.get('dur', 2.0)
    for month in ('2026-06', '2026-07'):
        for sym in ('BTCUSDT', 'ETHUSDT'):
            for j in range(5):
                i += 1
                pr = 0.03 if j < 4 else -0.01
                pnl = 50.0 if pr > 0 else -15.0
                rows.append(_row('T', sym, month, 'long', pr, pnl, lev=lev, marg=marg,
                                  started_ms=t_ms + i * 3_600_000))
                rows[-1]['dur'] = dur
            rows += _filler(sym, month, 'long', n=10)
    return rows


def test_rank_traders_production_thresholds_full_fixture():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections, _ = t5.rank_traders(rows)
    assert len(candidates) == 1
    d = candidates[0]
    assert d['uid'] == 'T'
    assert d['t'] > t5.T_MIN
    assert d['alpha_h2'] > 0
    assert d['levp90'] <= t5.LEVP90_MAX
    assert d['margmed'] >= t5.MARGIN_MED_MIN
    assert d['durmed'] >= t5.DUR_MED_MIN_H
    assert d['n'] == 20 and d['n_syms'] == 2


def test_rank_traders_rejects_leverage_p90_over_25x():
    rows = _threshold_fixture(lev=30.0)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections, _ = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['leverage p90>25x'] >= 1


def test_rank_traders_rejects_median_margin_under_50():
    rows = _threshold_fixture(marg=10.0)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections, _ = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['median margin<$50 (not copyable)'] >= 1


def test_rank_traders_rejects_duration_under_30min():
    rows = _threshold_fixture(dur=0.2)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections, _ = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['duration<30min (latency)'] >= 1


def test_rank_traders_t_boundary_2_5():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, _, _ = t5.rank_traders(rows)
    assert len(candidates) == 1 and candidates[0]['t'] > 2.5

    rows2 = []
    t_ms = 1_780_000_000_000
    i = 0
    for month in ('2026-06', '2026-07'):
        for sym in ('BTCUSDT', 'ETHUSDT'):
            for j in range(5):
                i += 1
                pr = 0.03 if j % 2 == 0 else -0.025
                pnl = 50.0 if pr > 0 else -15.0
                rows2.append(_row('T', sym, month, 'long', pr, pnl, started_ms=t_ms + i * 3_600_000))
            rows2 += _filler(sym, month, 'long', n=10)
    t5.compute_alpha(rows2, min_cell=t5.MIN_CELL)
    candidates2, rejections2, _ = t5.rank_traders(rows2)
    assert candidates2 == []
    assert rejections2['t<2.5'] >= 1


# ---------------------------------------------------------------------------
# The "01014588 lesson", ported to Bybit's yield-trend series.
# ---------------------------------------------------------------------------

def test_drawdown_screen_deep_drawdown_uncovered_by_window_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    yield_series = {'T': [(window_start - 10_000_000, -0.5)]}
    candidates, rejections, _ = t5.rank_traders(rows, yield_series=yield_series)
    assert candidates == []
    assert rejections['yield-trend drawdown >20%, uncovered by window'] >= 1


def test_drawdown_screen_deep_drawdown_covered_by_window_passes():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    yield_series = {'T': [(window_start + 10_000_000, -0.5)]}
    candidates, rejections, _ = t5.rank_traders(rows, yield_series=yield_series)
    assert len(candidates) == 1
    assert candidates[0]['dd_covered'] is True
    assert candidates[0]['dd_min_ratio'] == -0.5


def test_drawdown_screen_shallow_drawdown_never_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    yield_series = {'T': [(1, -0.05)]}
    candidates, rejections, _ = t5.rank_traders(rows, yield_series=yield_series)
    assert len(candidates) == 1
    assert 'yield-trend drawdown >20%, uncovered by window' not in rejections


# ---------------------------------------------------------------------------
# `pr` basis: roi/leverage, NOT entry/close price (Fable-2/GLM-2).
# ---------------------------------------------------------------------------

def _csv_row(order_id, leader_mark='M1', nick='n', symbol='BTCUSDT', side='long',
             leverage=10.0, entry_price=100.0, close_price=101.0, size=1.0, margin=10.0,
             pnl_usd=5.0, roi=0.5, started_ms=1000, closed_ms=2000, follower_num=0,
             full_closed=True):
    return [leader_mark, '1', nick, symbol, side, leverage, entry_price, close_price,
            size, margin, pnl_usd, roi, 0.0, 0.0, 0.0, started_ms, closed_ms,
            (closed_ms - started_ms) / 3_600_000, follower_num, full_closed, order_id]


def _write_csv(path, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(bybit_flatten.COLS)
        for r in rows:
            w.writerow(r)


def test_load_positions_pr_is_roi_over_leverage_not_price_derived(tmp_path):
    # Entry/close prices here would imply a *negative* return ((99/100 - 1) for a
    # long) while roi/leverage says positive -- exactly the kind of sign conflict
    # the audit found on ~16% of real rows. pr must follow roi/leverage.
    path = tmp_path / 'bybit_positions.csv'
    _write_csv(path, [_csv_row('a', side='long', leverage=10.0, entry_price=100.0,
                                close_price=99.0, roi=0.8, pnl_usd=0.8)])
    rows = t5.load_positions(str(path))
    assert len(rows) == 1
    assert abs(rows[0]['pr'] - 0.08) < 1e-9   # 0.8 / 10, not price-derived


def test_load_positions_pr_matches_leverage_scaling(tmp_path):
    path = tmp_path / 'bybit_positions.csv'
    _write_csv(path, [_csv_row('a', leverage=25.0, roi=-2.5)])
    rows = t5.load_positions(str(path))
    assert abs(rows[0]['pr'] - (-0.1)) < 1e-9   # -2.5 / 25


def test_load_positions_carries_closed_ms(tmp_path):
    path = tmp_path / 'bybit_positions.csv'
    _write_csv(path, [_csv_row('a', started_ms=1000, closed_ms=5000)])
    rows = t5.load_positions(str(path))
    assert rows[0]['closed_ms'] == 5000


# ---------------------------------------------------------------------------
# Position-level pnl aggregation for concentration (GLM-2): a scaled-in/out
# position split across multiple order rows must not slip past the
# concentration guard just because each order's individual pnl is small.
# ---------------------------------------------------------------------------

def test_rank_traders_concentration_uses_position_level_not_order_level_pnl():
    # Trader SCALED has one dominant BTCUSDT position worth $900, split across 3
    # order rows (same symbol + closed_ms, real-shape per the fixture in
    # tests/fixtures/bybit_positions_sample.jsonl) at $300 each -- individually
    # each row is well under 30% of any plausible total, but combined the single
    # position is 100% of net PnL. The remaining rows keep wr at 72% and payoff
    # above 0.5 so no earlier filter fires.
    rows = [_row('SCALED', 'BTCUSDT', '2026-06', 'long', 0.05, 300.0,
                  started_ms=1, closed_ms=100) for _ in range(3)]
    for i in range(10):
        rows.append(_row('SCALED', 'ETHUSDT', '2026-06', 'long', 0.01, 20.0,
                          started_ms=i, closed_ms=i))
    for i in range(5):
        rows.append(_row('SCALED', 'ETHUSDT', '2026-06', 'long', -0.02, -40.0,
                          started_ms=50 + i, closed_ms=50 + i))
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                                 levp90_max=100, margin_med_min=0,
                                                 dur_med_min_h=0)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1


def test_rank_traders_position_level_conc_exceeds_order_level_conc():
    # Demonstrates this is a genuine behavior change, not just a relabeling: for
    # the same scaled-position trader, the order-level figure alone would have
    # passed the 30% gate (each row is a minority of net PnL) while the
    # position-level figure (the one now enforced) fails it.
    rows = [_row('SCALED2', 'BTCUSDT', '2026-06', 'long', 0.05, 150.0,
                  started_ms=1, closed_ms=100) for _ in range(3)]
    for i in range(10):
        rows.append(_row('SCALED2', 'ETHUSDT', '2026-06', 'long', 0.01, 20.0,
                          started_ms=i, closed_ms=i))
    rows[-1] = _row('SCALED2', 'ETHUSDT', '2026-06', 'long', 0.02, 70.0,
                     started_ms=99, closed_ms=99)
    for i in range(5):
        rows.append(_row('SCALED2', 'ETHUSDT', '2026-06', 'long', -0.02, -30.0,
                          started_ms=50 + i, closed_ms=50 + i))
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'SCALED2')
    order_level_best = 150.0
    position_level_best = 450.0
    assert order_level_best / total_pnl < 0.30
    assert position_level_best / total_pnl > 0.30
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                                 levp90_max=100, margin_med_min=0,
                                                 dur_med_min_h=0)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1
