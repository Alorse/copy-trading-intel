import csv
import json
from analysis import bitget_flatten
from analysis import bitget_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, started_ms=0,
         closed_ms=None, symbol_id=None):
    return dict(uid=uid, nick=nick, sym=sym, symbol_id=symbol_id or (sym + '_UMCBL'),
                side=side, pr=pr, pnl=pnl, lev=lev, dur=2.0, marg=marg, month=month,
                started_ms=started_ms, closed_ms=closed_ms if closed_ms is not None else started_ms)


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


def _multi_pair_trader(uid, n=24, base_pnl=10.0, nick='good'):
    rows = []
    for i in range(n):
        sym = 'BTCUSDT' if i % 2 == 0 else 'ETHUSDT'
        pr = 0.02 if i % 4 else -0.01
        pnl = base_pnl if pr > 0 else -base_pnl * 0.4
        # 2s apart so closed_ms // 1000 (the position-group bucket) never collapses
        # two distinct trades into one -- see the position-level concentration key
        # in rank_traders().
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick, started_ms=i * 2000,
                          closed_ms=i * 2000))
    for sym in ('BTCUSDT', 'ETHUSDT'):
        rows += [_row('FILLER', sym, '2026-06', 'long', 0.0, 0.0) for _ in range(20)]
    return rows


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTCUSDT', '2026-06', 'short', -0.01, -1.0) for _ in range(5)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('BTCUSDT', '2026-06', 'short')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -1.0)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTCUSDT', '2026-07', 'long', 0.5, 1000.0))
    rows += (_filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
             + _filler('BTCUSDT', '2026-07', 'long'))
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 position, order-aggregated)' not in rejections


SHALLOW_CYCLE = {'GOOD': {'roi_series': [(0, 0.0), (1, 0.05)]},
                  'YOUNG': {'roi_series': [(0, 0.0), (1, 0.05)]},
                  'T': {'roi_series': [(0, 0.0), (1, 0.05)]}}


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, cycle=SHALLOW_CYCLE, min_n=15, min_alpha_n=1,
                                              t_min=0, levp90_max=100, margin_med_min=0,
                                              dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['uid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


def test_rank_traders_fresh_start_flag_below_120_days():
    rows = _multi_pair_trader('YOUNG', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, _ = t5.rank_traders(rows, cycle=SHALLOW_CYCLE, min_n=15, min_alpha_n=1,
                                     t_min=0, levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates[0]['fresh_start'] is True


def test_load_cycle_filters_by_cycle_time_and_converts_percent_to_fraction(tmp_path):
    path = tmp_path / 'bitget_cycle.jsonl'
    path.write_text(json.dumps({
        'traderUid': 'A', 'cycleTime': 90,
        'roi_rows': [[1000, 10.0], [2000, -30.0]],
        'max_retracement': 45.91, 'profit_rate': -3.43, 'aum': 51472.02,
        'total_trades': 128, 'profit_trades': 60, 'loss_trades': 68, 'winning_rate': 46.87,
    }) + '\n')
    cyc = t5.load_cycle(str(path))
    assert cyc['A']['roi_series'] == [(1000, 0.10), (2000, -0.30)]
    assert cyc['A']['native_mdd_pct'] == 45.91


def test_load_cycle_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_cycle(str(tmp_path / 'nope.jsonl')) == {}


def test_load_traders_reads_total_pnl(tmp_path):
    path = tmp_path / 'bitget_traders.jsonl'
    path.write_text(json.dumps({'traderUid': 'A', 'total_pnl': 1234.5, 'followCount': 90}) + '\n')
    info = t5.load_traders(str(path))
    assert info['A']['total_pnl'] == 1234.5


def test_load_manifest_keeps_only_ok_or_protected(tmp_path):
    path = tmp_path / 'bitget_manifest.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'traderUid': 'A', 'status': 'ok', 'n_open': 3},
        {'traderUid': 'B', 'status': 'error'},
    ]))
    mf = t5.load_manifest(str(path))
    assert 'A' in mf and mf['A']['n_open'] == 3
    assert 'B' not in mf


def test_computed_mdd_pct_peak_to_trough():
    series = [(1, 0.0), (2, 0.10), (3, -0.05), (4, 0.20), (5, -0.10)]
    # peaks: 0.10 -> trough -0.05 (drop 15pp); then peak 0.20 -> trough -0.10 (drop 30pp)
    assert abs(t5.computed_mdd_pct(series) - 30.0) < 1e-9


def test_computed_mdd_pct_empty_series_is_none():
    assert t5.computed_mdd_pct([]) is None


# ---------------------------------------------------------------------------
# Binance reference hard filters, ported from okx_top5/bybit_top5.
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
                                  started_ms=t_ms + i * 3_600_000, closed_ms=t_ms + i * 3_600_000))
                rows[-1]['dur'] = dur
            rows += _filler(sym, month, 'long', n=10)
    return rows


def test_rank_traders_production_thresholds_full_fixture():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows, cycle=SHALLOW_CYCLE)
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
    candidates, _ = t5.rank_traders(rows, cycle=SHALLOW_CYCLE)
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
                rows2.append(_row('T', sym, month, 'long', pr, pnl,
                                   started_ms=t_ms + i * 3_600_000, closed_ms=t_ms + i * 3_600_000))
            rows2 += _filler(sym, month, 'long', n=10)
    t5.compute_alpha(rows2, min_cell=t5.MIN_CELL)
    candidates2, rejections2 = t5.rank_traders(rows2)
    assert candidates2 == []
    assert rejections2['t<2.5'] >= 1


# ---------------------------------------------------------------------------
# The "01014588 lesson", ported to Bitget's cycleData roiRows series.
# ---------------------------------------------------------------------------

DD_REJECT_MSG = (f'cycleData {t5.CYCLE_WINDOW_DAYS}d peak-to-trough drawdown '
                 f'>{t5.DRAWDOWN_THRESHOLD_PP:g}pp, uncovered by window')


def test_drawdown_screen_deep_drawdown_uncovered_by_window_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    # peak +30% at t0, trough -25% at t1 -- a genuine 55pp peak-to-trough drop, both
    # BEFORE the visible closed-position window starts.
    cycle = {'T': {'roi_series': [(window_start - 20_000_000, 0.30),
                                   (window_start - 10_000_000, -0.25)]}}
    candidates, rejections = t5.rank_traders(rows, cycle=cycle)
    assert candidates == []
    assert rejections[DD_REJECT_MSG] >= 1


def test_drawdown_screen_deep_drawdown_covered_by_window_passes():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    cycle = {'T': {'roi_series': [(window_start - 10_000_000, 0.30),
                                   (window_start + 10_000_000, -0.25)]}}
    candidates, rejections = t5.rank_traders(rows, cycle=cycle)
    assert len(candidates) == 1
    assert candidates[0]['dd_covered'] is True
    assert abs(candidates[0]['dd_peak_to_trough_pct'] - 55.0) < 1e-9


def test_drawdown_screen_shallow_drawdown_never_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    cycle = {'T': {'roi_series': [(1, 0.05), (2, 0.01)]}}
    candidates, rejections = t5.rank_traders(rows, cycle=cycle)
    assert len(candidates) == 1
    assert DD_REJECT_MSG not in rejections


def test_drawdown_screen_deep_level_no_actual_drop_never_flags():
    # A cumulative curve that never falls BELOW its own peak-to-trough threshold
    # even though its raw value goes negative -- the exact GLM-2/Fable-1 bug: the
    # OLD screen took min(series), which would have flagged this trivially (-0.5 <
    # -0.20). The corrected screen measures an actual drawdown from a peak, and a
    # monotonically-non-rising-then-single-drop-to-a-low-but-still-shallow-relative-
    # to-its-own-peak series must not trip it just for being negative.
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    cycle = {'T': {'roi_series': [(1, -0.55), (2, -0.5)]}}   # peak -0.55 -> trough -0.5: a RISE, 0 drawdown
    candidates, rejections = t5.rank_traders(rows, cycle=cycle)
    assert len(candidates) == 1
    assert candidates[0]['dd_peak_to_trough_pct'] == 0.0
    assert DD_REJECT_MSG not in rejections


def test_drawdown_screen_200_to_50_pct_curve_old_screen_passed_new_must_flag():
    # The old screen's `min(series) >= DRAWDOWN_THRESHOLD` check: min=+0.50 >= -0.20
    # -> "covered=True, passes" even though the curve fell 150pp peak-to-trough.
    # The corrected screen must flag this as a >20pp drawdown.
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    series = [(window_start - 20_000_000, 2.0), (window_start - 10_000_000, 0.5)]
    old_screen_min_ratio = min(v for _, v in series)
    assert old_screen_min_ratio >= -0.20   # the old (buggy) threshold check would have passed this
    cycle = {'T': {'roi_series': series}}
    candidates, rejections = t5.rank_traders(rows, cycle=cycle)
    assert candidates == []
    assert rejections[DD_REJECT_MSG] >= 1


def test_drawdown_screen_missing_series_rejects_not_silently_passes():
    # Fable-3/GLM-1: a trader with NO cycleData series must be rejected, not waved
    # through as if the screen had verified them clean.
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows, cycle={})
    assert candidates == []
    assert rejections[DD_REJECT_MSG] >= 1


def test_peak_to_trough_helper_matches_computed_mdd_pct():
    series = [(1, 0.0), (2, 0.30), (3, -0.25), (4, 0.10)]
    drop_pct, trough_ts = t5._peak_to_trough(series)
    assert abs(drop_pct - 55.0) < 1e-9 and trough_ts == 3
    assert abs(t5.computed_mdd_pct(series) - 55.0) < 1e-9


# ---------------------------------------------------------------------------
# `pr` basis: return_rate/open_level, NOT open/close price (pnl-reconciliation
# finding, see scrape_bitget_positions.py's docstring).
# ---------------------------------------------------------------------------

def _csv_row(order_no, trader_uid='M1', nick='n', symbol_id='BTCUSDT_UMCBL',
             product_code='BTCUSDT', side='long', open_level=10.0, open_avg_price=100.0,
             close_avg_price=101.0, open_deal_count=1.0, close_deal_count=1.0, margin=10.0,
             net_profit=5.0, return_rate=0.5, open_time=1000, close_time=2000):
    return [trader_uid, nick, symbol_id, product_code, side, open_level, open_avg_price,
            close_avg_price, open_deal_count, close_deal_count, margin, net_profit,
            return_rate, 0.0, 0.0, 0.0, open_time, close_time,
            (close_time - open_time) / 3_600_000, 2, order_no]


def _write_csv(path, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(bitget_flatten.COLS)
        for r in rows:
            w.writerow(r)


def test_load_positions_pr_is_return_rate_over_open_level_not_price_derived(tmp_path):
    # Entry/close prices here would imply a *negative* return ((99/100 - 1) for a
    # long) while return_rate/open_level says positive -- exactly the kind of sign
    # conflict measured on ~10% of real rows. pr must follow return_rate/open_level.
    path = tmp_path / 'bitget_positions.csv'
    _write_csv(path, [_csv_row('a', side='long', open_level=10.0, open_avg_price=100.0,
                                close_avg_price=99.0, return_rate=0.8, net_profit=0.8)])
    rows, drops, n_csv = t5.load_positions(str(path))
    assert len(rows) == 1 and n_csv == 1 and sum(drops.values()) == 0
    assert abs(rows[0]['pr'] - 0.08) < 1e-9   # 0.8 / 10, not price-derived


def test_load_positions_pr_matches_leverage_scaling(tmp_path):
    path = tmp_path / 'bitget_positions.csv'
    _write_csv(path, [_csv_row('a', open_level=25.0, return_rate=-2.5)])
    rows, drops, n_csv = t5.load_positions(str(path))
    assert abs(rows[0]['pr'] - (-0.1)) < 1e-9   # -2.5 / 25


def test_load_positions_carries_closed_ms(tmp_path):
    path = tmp_path / 'bitget_positions.csv'
    _write_csv(path, [_csv_row('a', open_time=1000, close_time=5000)])
    rows, drops, n_csv = t5.load_positions(str(path))
    assert rows[0]['closed_ms'] == 5000


# ---------------------------------------------------------------------------
# load_positions drop accounting (Fable-3 / GLM-1c): every dropped CSV row must
# land in a counted bucket, and rows+drops must reconcile to the CSV row count.
# ---------------------------------------------------------------------------

def test_load_positions_counts_parse_drops():
    path_rows = [_csv_row('a', net_profit='not-a-number')]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/p.csv'
        _write_csv(path, path_rows)
        rows, drops, n_csv = t5.load_positions(path)
    assert rows == [] and drops['parse'] == 1 and n_csv == 1


def test_load_positions_counts_lev_drops():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/p.csv'
        _write_csv(path, [_csv_row('a', open_level=0.0)])
        rows, drops, n_csv = t5.load_positions(path)
    assert rows == [] and drops['lev<=0'] == 1


def test_load_positions_counts_side_drops():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/p.csv'
        _write_csv(path, [_csv_row('a', side='both')])
        rows, drops, n_csv = t5.load_positions(path)
    assert rows == [] and drops['side'] == 1


def test_load_positions_counts_extreme_pr_drops():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/p.csv'
        _write_csv(path, [_csv_row('a', open_level=1.0, return_rate=400.0)])   # pr=400
        rows, drops, n_csv = t5.load_positions(path)
    assert rows == [] and drops['|pr|>3'] == 1


def test_load_positions_rows_plus_drops_reconciles_to_csv_row_count():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f'{tmp}/p.csv'
        _write_csv(path, [
            _csv_row('a'),                                  # kept
            _csv_row('b', net_profit='bad'),                 # parse
            _csv_row('c', open_level=0.0),                   # lev<=0
            _csv_row('d', side='?'),                          # side
            _csv_row('e', open_level=1.0, return_rate=500.0),  # |pr|>3
        ])
        rows, drops, n_csv = t5.load_positions(path)
    assert n_csv == 5
    assert len(rows) + sum(drops.values()) == n_csv
    assert len(rows) == 1


def test_main_prints_drop_accounting(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / 'bitget_positions.csv'
    _write_csv(str(csv_path), [_csv_row('a'), _csv_row('b', net_profit='bad')])
    monkeypatch.setattr(t5, 'CSV_PATH', str(csv_path))
    monkeypatch.setattr(t5, 'CYCLE_PATH', str(tmp_path / 'nope_cycle.jsonl'))
    monkeypatch.setattr(t5, 'TRADERS_PATH', str(tmp_path / 'nope_traders.jsonl'))
    monkeypatch.setattr(t5, 'MANIFEST_PATH', str(tmp_path / 'nope_manifest.jsonl'))
    t5.main()
    out = capsys.readouterr().out
    assert 'positions loaded: 1' in out
    assert 'dropped 1' in out and 'parse=1' in out
    assert 'ACCOUNTING MISMATCH' not in out


# ---------------------------------------------------------------------------
# Position-level pnl aggregation for concentration: a scaled-in/out position
# split across multiple order rows must not slip past the concentration guard
# just because each order's individual pnl is small.
# ---------------------------------------------------------------------------

def test_rank_traders_concentration_uses_position_level_not_order_level_pnl():
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
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                              levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1


def test_rank_traders_position_level_conc_exceeds_order_level_conc():
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
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                              levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1


def test_rank_traders_groups_position_by_symbol_and_close_time_second_bucket():
    # Two rows 500ms apart (same second when floor-divided) must aggregate into one
    # position group -- the exact real-data jitter observed live (see
    # scrape_bitget_positions.py's docstring: ~1ms intra-batch jitter).
    rows = [_row('J', 'BTCUSDT', '2026-06', 'long', 0.05, 200.0,
                  started_ms=1_000, closed_ms=10_000, symbol_id='BTCUSDT_UMCBL'),
            _row('J', 'BTCUSDT', '2026-06', 'long', 0.05, 200.0,
                  started_ms=1_500, closed_ms=10_500, symbol_id='BTCUSDT_UMCBL')]
    for i in range(20):
        rows.append(_row('J', 'ETHUSDT', '2026-06', 'long', 0.01, 5.0,
                          started_ms=i, closed_ms=i))
    for i in range(5):
        rows.append(_row('J', 'ETHUSDT', '2026-06', 'long', -0.02, -10.0,
                          started_ms=50 + i, closed_ms=50 + i))
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                              levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position, order-aggregated)'] >= 1
