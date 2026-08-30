import json
from analysis import bybit_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, started_ms=0):
    return dict(uid=uid, nick=nick, sym=sym, side=side, pr=pr, pnl=pnl,
                lev=lev, dur=2.0, marg=marg, month=month, started_ms=started_ms)


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
    assert rejections['concentration>30% (top-1 trade)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 trade)' not in rejections


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
