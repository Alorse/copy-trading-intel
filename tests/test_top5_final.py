from analysis import top5_final as t5


def _row(tid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, opened_ms=0,
         dur=2.0, mdd=0.0, aum=0.0, p_roi=0.0, p_pnl=0.0):
    return dict(tid=tid, nick=nick, sym=sym, side=side, pr=pr, pnl=pnl, lev=lev, dur=dur,
                marg=marg, mdd=mdd, aum=aum, p_roi=p_roi, p_pnl=p_pnl, month=month,
                opened_ms=opened_ms)


def _filler(sym, month, side, n=3, pr=0.0):
    """Neutral rows from other traders, giving a cell a leave-self-out 'others' pool
    so a single-trader fixture's alpha isn't dropped as self-dominated."""
    return [_row(f'FILLER{i}', sym, month, side, pr, 0.0) for i in range(n)]


# ---------------------------------------------------------------------------
# compute_alpha: leave-self-out, ported verbatim from analysis/okx_top5.py.
# ---------------------------------------------------------------------------

def test_compute_alpha_is_pr_minus_cell_median():
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    rows.append(_row('B', 'BTCUSDT', '2026-08', 'Long', 0.10, 1.0))
    t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha'] is not None for r in rows)
    assert rows[-1]['alpha'] > 0


def test_compute_alpha_none_when_cell_too_small():
    rows = [_row('A', 'ETHUSDT', '2026-08', 'Short', -0.01, 1.0)]
    t5.compute_alpha(rows, min_cell=8)
    assert rows[0]['alpha'] is None


def test_compute_alpha_leave_self_out_shifts_alpha_in_self_dominated_cell():
    # 9-row cell, 6 rows from A (pr=0.05) and 3 from B (pr=0.01). Self-inclusive
    # median is dragged toward A's own return, making A look average;
    # leave-self-out benchmarks A only against B and reveals A's real edge.
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', 0.05, 1.0) for _ in range(6)]
    rows += [_row('B', 'BTCUSDT', '2026-08', 'Long', 0.01, 1.0) for _ in range(3)]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert dropped == {}
    assert cell_share['A'] == 6 / 9
    assert cell_share['B'] == 3 / 9
    a_rows = [r for r in rows if r['tid'] == 'A']
    assert all(abs(r['alpha_incl']) < 1e-9 for r in a_rows)     # self-inclusive: looks average
    assert all(abs(r['alpha'] - 0.04) < 1e-9 for r in a_rows)   # leave-self-out: real +4% edge


def test_compute_alpha_drops_self_dominated_cell():
    # cell has 8 rows (>= min_cell) but all from the same trader -> no "others"
    # exist, so the leave-self-out alpha is unusable and must be dropped.
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha_incl'] is not None for r in rows)   # self-inclusive still defined
    assert all(r['alpha'] is None for r in rows)             # leave-self-out: unusable
    assert dropped == {'A': 8}
    assert cell_share['A'] == 1.0


def _multi_pair_trader(tid, n=24, base_pnl=10.0, nick='good', month='2026-08'):
    """A trader with alternating small wins/losses across two symbols, no single
    trade dominating -- should survive every hard filter (given loose enough
    n/alpha thresholds). Bundled with neutral filler rows in the same cells so
    the trader's own trades don't dominate the benchmark median."""
    rows = []
    for i in range(n):
        sym = 'BTCUSDT' if i % 2 == 0 else 'ETHUSDT'
        pr = 0.02 if i % 4 else -0.01
        pnl = base_pnl if pr > 0 else -base_pnl * 0.4
        rows.append(_row(tid, sym, month, 'Long', pr, pnl, nick=nick, opened_ms=i))
    for sym in ('BTCUSDT', 'ETHUSDT'):
        rows += [_row('FILLER', sym, month, 'Long', 0.0, 0.0) for _ in range(20)]
    return rows


def _loose_rank(rows, **kw):
    kw.setdefault('min_n', 15)
    kw.setdefault('min_alpha_n', 1)
    kw.setdefault('t_min', 0)
    kw.setdefault('levp90_max', 100)
    kw.setdefault('margin_med_min', 0)
    kw.setdefault('dur_med_min_h', 0)
    return t5.rank_traders(rows, **kw)


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTCUSDT', '2026-08', 'Short', -0.01, -1.0) for _ in range(5)]
    rows += _filler('BTCUSDT', '2026-08', 'Long') + _filler('BTCUSDT', '2026-08', 'Short')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETHUSDT', '2026-08', 'Long', -0.01, -1.0)]   # 1 loser / 20 = 95% wr
    rows += _filler('BTCUSDT', '2026-08', 'Long') + _filler('ETHUSDT', '2026-08', 'Long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-08', 'Long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTCUSDT', '2026-08', 'Long', 0.5, 1000.0))   # one huge trade
    rows += (_filler('BTCUSDT', '2026-08', 'Long') + _filler('ETHUSDT', '2026-08', 'Long'))
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert candidates == []
    assert rejections['concentration>30% (top-1 trade)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDT', '2026-08', 'Long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-08', 'Long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDT', '2026-08', 'Long') + _filler('ETHUSDT', '2026-08', 'Long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 trade)' not in rejections


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert len(candidates) == 1
    assert candidates[0]['tid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


def test_rank_traders_rejects_inactive_in_august():
    rows = _multi_pair_trader('OLD', n=24, month='2026-06')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = _loose_rank(rows)
    assert candidates == []
    assert rejections['inactive in August'] >= 1


def test_rank_traders_reports_headline_vs_computed_cross_check():
    rows = _multi_pair_trader('GOOD', n=24)
    for r in rows:
        if r['tid'] == 'GOOD':
            r['p_pnl'] = 1000.0
    t5.compute_alpha(rows, min_cell=1)
    candidates, _ = _loose_rank(rows)
    d = candidates[0]
    assert d['ranking_pnl'] == 1000.0
    assert abs(d['computed_pnl'] - sum(r['pnl'] for r in rows if r['tid'] == 'GOOD')) < 1e-9
    assert abs(d['pnl_cross_check_ratio'] - d['computed_pnl'] / 1000.0) < 1e-9


def test_rank_traders_exposes_dropped_and_cell_share():
    rows = _multi_pair_trader('GOOD', n=24)
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=1)
    candidates, _ = _loose_rank(rows, dropped_self_dominated=dropped, cell_share_max=cell_share)
    d = candidates[0]
    assert d['n_alpha_dropped_self_dominated'] == dropped.get('GOOD', 0)
    assert d['max_cell_share'] == cell_share.get('GOOD', 0.0)


# ---------------------------------------------------------------------------
# Production-threshold fixture (n>=60, n_alpha>=40, min_cell=20) — mirrors
# okx_top5.py's _threshold_fixture pattern, scaled to Binance's much thicker
# cell requirement.
# ---------------------------------------------------------------------------

def _threshold_fixture(**overrides):
    """60 rows for trader 'T' across 2 symbols x 3 months, 8 wins + 2 losses per
    group (wr=80%, payoff~3.0), each cell backed by 20 neutral filler rows so
    leave-self-out alpha is well-defined (min_cell=20 default)."""
    rows = []
    t_ms = 1_780_000_000_000
    i = 0
    lev = overrides.get('lev', 10.0)
    marg = overrides.get('marg', 100.0)
    dur = overrides.get('dur', 2.0)
    for month in ('2026-06', '2026-07', '2026-08'):
        for sym in ('BTCUSDT', 'ETHUSDT'):
            for j in range(10):
                i += 1
                pr = 0.03 if j < 8 else -0.01
                pnl = 50.0 if pr > 0 else -15.0
                rows.append(_row('T', sym, month, 'Long', pr, pnl, lev=lev, marg=marg,
                                  opened_ms=t_ms + i * 3_600_000))
                rows[-1]['dur'] = dur
            rows += _filler(sym, month, 'Long', n=20)
    return rows


def test_rank_traders_production_thresholds_full_fixture():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)   # every default at production value
    assert len(candidates) == 1
    d = candidates[0]
    assert d['tid'] == 'T'
    assert d['t'] > t5.T_MIN
    assert d['alpha_h2'] > 0
    assert d['levp90'] <= t5.LEVP90_MAX
    assert d['margmed'] >= t5.MARGIN_MED_MIN
    assert d['durmed'] >= t5.DUR_MED_MIN_H
    assert d['n'] == 60 and d['n_syms'] == 2


def test_rank_traders_rejects_leverage_p90_over_25x():
    rows = _threshold_fixture(lev=30.0)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['leverage p90>25x'] >= 1


def test_rank_traders_rejects_median_margin_under_50():
    rows = _threshold_fixture(marg=10.0)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['median margin<$50 (not copyable)'] >= 1


def test_rank_traders_rejects_duration_under_30min():
    rows = _threshold_fixture(dur=0.2)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)
    assert candidates == []
    assert rejections['duration<30min (latency)'] >= 1


def test_rank_traders_t_boundary_2_5():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, _ = t5.rank_traders(rows)
    assert len(candidates) == 1 and candidates[0]['t'] > 2.5

    rows2 = []
    t_ms = 1_780_000_000_000
    i = 0
    for month in ('2026-06', '2026-07', '2026-08'):
        for sym in ('BTCUSDT', 'ETHUSDT'):
            for j in range(10):
                i += 1
                pr = 0.03 if j % 2 == 0 else -0.025
                pnl = 50.0 if pr > 0 else -15.0
                rows2.append(_row('T', sym, month, 'Long', pr, pnl, opened_ms=t_ms + i * 3_600_000))
            rows2 += _filler(sym, month, 'Long', n=20)
    t5.compute_alpha(rows2, min_cell=t5.MIN_CELL)
    candidates2, rejections2 = t5.rank_traders(rows2)
    assert candidates2 == []
    assert rejections2['t<2.5'] >= 1


# ---------------------------------------------------------------------------
# Hidden-drawdown screen, built from data/binance_portfolios.json's daily
# chartItems — the Binance-native analogue of OKX's weekly pnlRatios[] screen.
# ---------------------------------------------------------------------------

def test_drawdown_screen_empty_chart_is_safe():
    assert t5.drawdown_screen([], 1000) == (None, None, True)


def test_drawdown_screen_computes_running_peak_to_trough():
    # equity: 1.0 -> 0.70 -> 1.10 : a 30% drawdown at ts=2000, then a new peak
    chart = [(1000, 0.0), (2000, -30.0), (3000, 10.0)]
    min_ratio, min_ts, covered = t5.drawdown_screen(chart, window_start_ms=500)
    assert abs(min_ratio - (-0.30)) < 1e-9
    assert min_ts == 2000
    assert covered is True    # window (500) predates the trough (2000) -> visible


def test_drawdown_screen_deep_drawdown_uncovered_by_window_is_hidden():
    chart = [(1000, 0.0), (2000, -30.0), (3000, 10.0)]
    min_ratio, min_ts, covered = t5.drawdown_screen(chart, window_start_ms=2500)
    assert covered is False   # window starts AFTER the trough -> our sample never saw it


def test_drawdown_screen_shallow_drawdown_never_flags():
    chart = [(1000, 0.0), (2000, -10.0), (3000, 5.0)]   # 10% dip, above -20% threshold
    min_ratio, min_ts, covered = t5.drawdown_screen(chart, window_start_ms=2500)
    assert covered is True


def test_rank_traders_hidden_drawdown_rejects_when_uncovered():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['opened_ms'] for r in rows if r['tid'] == 'T')
    chart_data = {'T': [(window_start - 20_000_000, 0.0),
                         (window_start - 10_000_000, -50.0),   # deep drawdown, before the window
                         (window_start - 5_000_000, 20.0)]}
    candidates, rejections = t5.rank_traders(rows, chart_data=chart_data)
    assert candidates == []
    assert rejections['hidden drawdown >20%, uncovered by window'] >= 1


def test_rank_traders_hidden_drawdown_passes_when_covered():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['opened_ms'] for r in rows if r['tid'] == 'T')
    chart_data = {'T': [(window_start - 20_000_000, 0.0),
                         (window_start + 10_000_000, -50.0),   # deep drawdown, INSIDE the window
                         (window_start + 20_000_000, 20.0)]}
    candidates, rejections = t5.rank_traders(rows, chart_data=chart_data)
    assert len(candidates) == 1
    assert candidates[0]['dd_covered'] is True


def test_load_chart_data_reads_chartitems(tmp_path):
    path = tmp_path / 'binance_portfolios.json'
    path.write_text(
        '[{"leadPortfolioId": "A", "chartItems": '
        '[{"dateTime": "1000", "value": "0"}, {"dateTime": "2000", "value": "-30"}]}]')
    charts = t5.load_chart_data(str(path))
    assert charts['A'] == [(1000, 0.0), (2000, -30.0)]


def test_load_chart_data_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_chart_data(str(tmp_path / 'nope.json')) == {}
