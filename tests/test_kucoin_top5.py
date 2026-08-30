import csv
import json
import os
from analysis import kucoin_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, started_ms=0, closed_ms=None):
    if closed_ms is None:
        closed_ms = started_ms + 3600000
    return dict(uid=uid, nick=nick, sym=sym, side=side, pr=pr, pnl=pnl, lev=lev,
                dur=2.0, marg=marg, month=month, started_ms=started_ms, closed_ms=closed_ms)


def _filler(sym, month, side, n=3, pr=0.0):
    """Neutral rows from other traders, giving a cell a leave-self-out 'others' pool
    so a single-trader fixture's alpha isn't dropped as self-dominated."""
    return [_row(f'FILLER{i}', sym, month, side, pr, 0.0) for i in range(n)]


def _shallow_traders_info(*uids, principal=1000.0):
    """A benign pnl_series_90d/leadPrincipal for every uid -- a missing/degenerate
    drawdown series REJECTS by design (see drawdown_screen's docstring), so every
    test not specifically about the drawdown screen must supply one of these to
    isolate the filter actually under test."""
    return {uid: {'totalPnl': 0.0, 'leadPrincipal': principal,
                  'pnl_series_90d': [0.0, 10.0, 5.0]} for uid in uids}


def test_compute_alpha_is_pr_minus_cell_median():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    rows.append(_row('B', 'BTCUSDTM', '2026-06', 'long', 0.10, 1.0))
    t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha'] is not None for r in rows)
    assert rows[-1]['alpha'] > 0


def test_compute_alpha_none_when_cell_too_small():
    rows = [_row('A', 'ETHUSDTM', '2026-06', 'short', -0.01, 1.0)]
    t5.compute_alpha(rows, min_cell=8)
    assert rows[0]['alpha'] is None


def test_compute_alpha_leave_self_out_shifts_alpha_in_self_dominated_cell():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', 0.05, 1.0) for _ in range(6)]
    rows += [_row('B', 'BTCUSDTM', '2026-06', 'long', 0.01, 1.0) for _ in range(3)]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert dropped == {}
    assert cell_share['A'] == 6 / 9
    a_rows = [r for r in rows if r['uid'] == 'A']
    assert all(abs(r['alpha_incl']) < 1e-9 for r in a_rows)
    assert all(abs(r['alpha'] - 0.04) < 1e-9 for r in a_rows)


def test_compute_alpha_drops_self_dominated_cell():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha_incl'] is not None for r in rows)
    assert all(r['alpha'] is None for r in rows)
    assert dropped == {'A': 8}


def _multi_pair_trader(uid, n=24, base_pnl=10.0, nick='good'):
    rows = []
    for i in range(n):
        sym = 'BTCUSDTM' if i % 2 == 0 else 'ETHUSDTM'
        pr = 0.02 if i % 4 else -0.01
        pnl = base_pnl if pr > 0 else -base_pnl * 0.4
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick, started_ms=i * 3600000))
    for sym in ('BTCUSDTM', 'ETHUSDTM'):
        rows += [_row('FILLER', sym, '2026-06', 'long', 0.0, 0.0) for _ in range(20)]
    return rows


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTCUSDTM', '2026-06', 'short', -0.01, -1.0) for _ in range(5)]
    rows += _filler('BTCUSDTM', '2026-06', 'long') + _filler('BTCUSDTM', '2026-06', 'short')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETHUSDTM', '2026-06', 'long', -0.01, -1.0)]
    rows += _filler('BTCUSDTM', '2026-06', 'long') + _filler('ETHUSDTM', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDTM', '2026-06', 'long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTCUSDTM', '2026-07', 'long', 0.5, 1000.0))
    rows += (_filler('BTCUSDTM', '2026-06', 'long') + _filler('ETHUSDTM', '2026-06', 'long')
             + _filler('BTCUSDTM', '2026-07', 'long'))
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['concentration>30% (top-1 position)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDTM', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDTM', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDTM', '2026-06', 'long') + _filler('ETHUSDTM', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 position)' not in rejections


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, traders_info=_shallow_traders_info('GOOD'),
                                              min_n=15, min_alpha_n=1, t_min=0,
                                              levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['uid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


def test_rank_traders_flags_and_rejects_large_open_unrealized_loss():
    rows = _multi_pair_trader('RISKY', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'RISKY')
    open_upl = {'RISKY': {'upl_sum': -abs(total_pnl) * 2, 'n_open': 3,
                           'upl_neg_sum': -abs(total_pnl) * 2}}
    candidates, rejections = t5.rank_traders(rows, open_upl=open_upl, min_n=15, min_alpha_n=1,
                                              t_min=0, levp90_max=100, margin_med_min=0,
                                              dur_med_min_h=0)
    assert candidates == []
    assert rejections['open unrealized loss > 50% of closed PnL'] >= 1


def test_rank_traders_open_upl_hard_filter_uses_net_not_negative_only():
    rows = _multi_pair_trader('NETPOS', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'NETPOS')
    open_upl = {'NETPOS': {'upl_sum': abs(total_pnl) * 0.1, 'n_open': 2,
                            'upl_neg_sum': -abs(total_pnl) * 2}}
    candidates, rejections = t5.rank_traders(rows, open_upl=open_upl,
                                              traders_info=_shallow_traders_info('NETPOS'),
                                              min_n=15, min_alpha_n=1,
                                              t_min=0, levp90_max=100, margin_med_min=0,
                                              dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['hidden_loss_flag'] is True
    assert candidates[0]['has_upl_data'] is True


def test_rank_traders_has_upl_data_false_when_no_open_rows():
    rows = _multi_pair_trader('NOOPEN', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, _ = t5.rank_traders(rows, traders_info=_shallow_traders_info('NOOPEN'),
                                     min_n=15, min_alpha_n=1, t_min=0,
                                     levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert candidates[0]['has_upl_data'] is False


def test_load_open_upl_aggregates_negative_and_positive(tmp_path):
    path = tmp_path / 'kucoin_open_positions.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'leadConfigId': 'A', 'unrealisedPnl': -5.0},
        {'leadConfigId': 'A', 'unrealisedPnl': 2.0},
        {'leadConfigId': 'B', 'unrealisedPnl': 1.0},
    ]))
    agg = t5.load_open_upl(str(path))
    assert agg['A']['upl_sum'] == -3.0
    assert agg['A']['n_open'] == 2
    assert agg['A']['upl_neg_sum'] == -5.0
    assert agg['B']['upl_neg_sum'] == 0.0


def test_load_open_upl_missing_file_returns_empty_defaultdict(tmp_path):
    agg = t5.load_open_upl(str(tmp_path / 'nope.jsonl'))
    assert agg['anything']['n_open'] == 0


def test_load_traders_reads_leaderboard_row(tmp_path):
    path = tmp_path / 'kucoin_traders.jsonl'
    path.write_text(json.dumps({
        'leadConfigId': 5, 'totalPnl': 123.45, 'leadPrincipal': 1000.0,
        'pnl_series_90d': [0.0, 10.0, -5.0],
    }) + '\n')
    info = t5.load_traders(str(path))
    assert info[5]['totalPnl'] == 123.45
    assert info[5]['pnl_series_90d'] == [0.0, 10.0, -5.0]


def test_load_traders_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_traders(str(tmp_path / 'nope.jsonl')) == {}


# ---------------------------------------------------------------------------
# Binance reference hard filters (top5_final.py:48-56), adopted in full.
# ---------------------------------------------------------------------------

def _threshold_fixture(**overrides):
    rows = []
    t_ms = 1_780_000_000_000
    i = 0
    lev = overrides.get('lev', 10.0)
    marg = overrides.get('marg', 100.0)
    dur = overrides.get('dur', 2.0)
    for month in ('2026-06', '2026-07'):
        for sym in ('BTCUSDTM', 'ETHUSDTM'):
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
    candidates, rejections = t5.rank_traders(rows, traders_info=_shallow_traders_info('T'))
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
    candidates, rejections = t5.rank_traders(rows, traders_info=_shallow_traders_info('T'))
    assert candidates == []
    assert rejections['leverage p90>25x'] >= 1


def test_rank_traders_rejects_median_margin_under_50():
    rows = _threshold_fixture(marg=10.0)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows, traders_info=_shallow_traders_info('T'))
    assert candidates == []
    assert rejections['median margin<$50 (not copyable)'] >= 1


def test_rank_traders_rejects_duration_under_30min():
    rows = _threshold_fixture(dur=0.2)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows, traders_info=_shallow_traders_info('T'))
    assert candidates == []
    assert rejections['duration<30min (latency)'] >= 1


def test_rank_traders_t_boundary_2_5():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, _ = t5.rank_traders(rows, traders_info=_shallow_traders_info('T'))
    assert len(candidates) == 1 and candidates[0]['t'] > 2.5

    rows2 = []
    t_ms = 1_780_000_000_000
    i = 0
    for month in ('2026-06', '2026-07'):
        for sym in ('BTCUSDTM', 'ETHUSDTM'):
            for j in range(5):
                i += 1
                pr = 0.03 if j % 2 == 0 else -0.025
                pnl = 50.0 if pr > 0 else -15.0
                rows2.append(_row('T', sym, month, 'long', pr, pnl, started_ms=t_ms + i * 3_600_000))
            rows2 += _filler(sym, month, 'long', n=10)
    t5.compute_alpha(rows2, min_cell=t5.MIN_CELL)
    candidates2, rejections2 = t5.rank_traders(rows2, traders_info=_shallow_traders_info('T'))
    assert candidates2 == []
    assert rejections2['t<2.5'] >= 1


# ---------------------------------------------------------------------------
# The drawdown screen: peak-to-trough of pnl_series_90d / leadPrincipal, with a
# synthetic per-point timestamp anchored on series_end_ms.
# ---------------------------------------------------------------------------

def test_peak_to_trough_indexed_basic():
    # peak at index 1 (10.0), trough at index 3 (-5.0) -> drop = 15.0
    drop, idx = t5._peak_to_trough_indexed([0.0, 10.0, 5.0, -5.0, 0.0])
    assert drop == 15.0 and idx == 3


def test_peak_to_trough_indexed_empty_series():
    assert t5._peak_to_trough_indexed([]) is None


def test_drawdown_screen_missing_series_rejects():
    dd_pct, ts, covered = t5.drawdown_screen(None, 1000.0, 0, 1_000_000)
    assert covered is False and dd_pct is None


def test_drawdown_screen_non_positive_lead_principal_rejects():
    dd_pct, ts, covered = t5.drawdown_screen([0.0, -50.0], 0.0, 0, 1_000_000)
    assert covered is False and dd_pct is None


def test_drawdown_screen_shallow_drawdown_passes():
    # -5% of a $1000 principal = 5pp drop, well under the 20pp threshold
    series = [0.0, 10.0, -50.0]   # peak $10, trough -$50 -> 60pp drop... use a shallow one instead
    shallow = [0.0, 10.0, 5.0]    # peak $10, trough $5 -> 5pp drop on $100 principal
    dd_pct, ts, covered = t5.drawdown_screen(shallow, 100.0, 0, 10 * t5.DAY_MS)
    assert covered is True
    assert abs(dd_pct - 5.0) < 1e-9


def test_drawdown_screen_deep_drawdown_uncovered_by_window_rejects():
    # 90-point series, deep drop happens at index 10 (80 days before series_end_ms).
    series = [0.0] * 10 + [-1000.0] + [0.0] * 79   # peak 0, trough -1000 on $1000 principal -> 100pp
    series_end_ms = 10_000_000_000
    trough_ts = series_end_ms - (len(series) - 1 - 10) * t5.DAY_MS
    window_start_ms = trough_ts + t5.DAY_MS   # window starts AFTER the trough -> hidden
    dd_pct, ts, covered = t5.drawdown_screen(series, 1000.0, window_start_ms, series_end_ms)
    assert covered is False
    assert dd_pct > t5.DRAWDOWN_THRESHOLD_PP


def test_drawdown_screen_deep_drawdown_covered_by_window_passes():
    series = [0.0] * 10 + [-1000.0] + [0.0] * 79
    series_end_ms = 10_000_000_000
    trough_ts = series_end_ms - (len(series) - 1 - 10) * t5.DAY_MS
    window_start_ms = trough_ts - t5.DAY_MS   # window starts BEFORE the trough -> visible
    dd_pct, ts, covered = t5.drawdown_screen(series, 1000.0, window_start_ms, series_end_ms)
    assert covered is True


def test_rank_traders_drawdown_screen_integration_rejects_uncovered():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    # series ends just 5 days after the window starts; the peak (index 0) is
    # immediately followed by the trough (index 1, 88 days before series_end_ms)
    # -> the trough dates to ~83 days before window_start -> uncovered.
    series_end_ms = window_start + 5 * t5.DAY_MS
    series = [0.0, -1000.0] + [0.0] * 88
    traders_info = {'T': {'totalPnl': 100.0, 'leadPrincipal': 1000.0, 'pnl_series_90d': series}}
    candidates, rejections = t5.rank_traders(rows, traders_info=traders_info, series_end_ms=series_end_ms)
    assert candidates == []
    assert any('uncovered by window' in k for k in rejections)


def test_rank_traders_drawdown_screen_integration_passes_when_shallow():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['started_ms'] for r in rows if r['uid'] == 'T')
    series_end_ms = window_start + 200 * t5.DAY_MS
    series = [0.0, 1.0, 0.5]   # shallow drop
    traders_info = {'T': {'totalPnl': 100.0, 'leadPrincipal': 1000.0, 'pnl_series_90d': series}}
    candidates, rejections = t5.rank_traders(rows, traders_info=traders_info, series_end_ms=series_end_ms)
    assert len(candidates) == 1
    assert candidates[0]['dd_covered'] is True


# ---------------------------------------------------------------------------
# Headline cross-check
# ---------------------------------------------------------------------------

def test_rank_traders_headline_ratio_computed():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    traders_info = {'T': {'totalPnl': 700.0, 'leadPrincipal': 1000.0, 'pnl_series_90d': [0.0]}}
    candidates, _ = t5.rank_traders(rows, traders_info=traders_info)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'T')
    assert abs(candidates[0]['headline_ratio'] - total_pnl / 700.0) < 1e-9


# ---------------------------------------------------------------------------
# The lead_config_id type-round-trip regression: `leadConfigId` is numeric
# (int) in every JSONL source (kucoin_traders/kucoin_open_positions/
# kucoin_manifest) but comes back as a STRING after a real CSV round-trip via
# analysis/kucoin_flatten.py. If load_positions() doesn't cast it back to int,
# every cross-check dict lookup (load_traders/load_open_upl/load_manifest)
# silently misses and returns {} for every trader -- caught live 2026-08-30:
# the drawdown screen rejected 100% of the real universe because of exactly
# this mismatch, undetected by the string-uid-only unit fixtures above.
# ---------------------------------------------------------------------------

def test_load_positions_casts_lead_config_id_to_int_matching_jsonl_types(tmp_path):
    from analysis import kucoin_flatten as fl
    csv_path = tmp_path / 'kucoin_positions.csv'
    with open(csv_path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(fl.COLS)
        w.writerow([1004009, 'Sanfa', 'SOLUSDTM', 'short', 'BOTH', 10.0, 'ISOLATED',
                    1.5, 0.03, 47.19, 50.0, 94.379, 93.971, 0.1, 'USDT',
                    1780000000000, 1780003600000, 1.0])
    rows, drops, n_csv = t5.load_positions(str(csv_path))
    assert len(rows) == 1
    assert rows[0]['uid'] == 1004009
    assert isinstance(rows[0]['uid'], int)


def test_rank_traders_integration_finds_traders_info_after_real_csv_round_trip(tmp_path):
    """End-to-end: flatten a real-shaped position through the CSV, then confirm
    rank_traders' drawdown screen actually reaches (and doesn't blanket-reject)
    the matching kucoin_traders.jsonl row -- the exact failure mode of the bug
    this test suite is guarding against."""
    from analysis import kucoin_flatten as fl
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    lead_id = 777
    t_ms = 1_780_000_000_000
    with open(data_dir / 'kucoin_positions.jsonl', 'w') as fh:
        for i in range(20):
            sym = 'BTCUSDTM' if i % 2 == 0 else 'ETHUSDTM'
            pnl = 5.0 if i % 5 else -2.0
            fh.write(json.dumps({
                'leadConfigId': lead_id, 'nickName': 'RoundTrip', 'symbol': sym,
                'side': 'long', 'positionSide': 'BOTH', 'leverage': 10.0,
                'marginMode': 'ISOLATED', 'pnl': pnl, 'pnlRatio': 0.05, 'posMargin': 100.0,
                'closeQty': 1.0, 'avgEntryPrice': 100.0, 'avgClosePrice': 105.0,
                'multiplier': 1.0, 'currency': 'USDT',
                'startTime': t_ms + i * 3_600_000, 'endTime': t_ms + i * 3_600_000 + 1_800_000,
            }) + '\n')
    fl.flatten(data_dir=str(data_dir), out_dir=str(out_dir))
    csv_path = out_dir / 'kucoin_positions.csv'
    rows, drops, n_csv = t5.load_positions(str(csv_path))
    assert all(isinstance(r['uid'], int) for r in rows)
    t5.compute_alpha(rows, min_cell=1)
    traders_info = {lead_id: {'totalPnl': 100.0, 'leadPrincipal': 1000.0,
                               'pnl_series_90d': [0.0, 1.0, 0.5]}}   # shallow, well under threshold
    candidates, rejections = t5.rank_traders(rows, traders_info=traders_info, min_n=15,
                                              min_alpha_n=1, t_min=0, levp90_max=100,
                                              margin_med_min=0, dur_med_min_h=0)
    assert not any('uncovered by window' in k for k in rejections)
    if candidates:
        assert candidates[0]['dd_covered'] is True
