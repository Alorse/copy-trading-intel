import csv
import json
from analysis import phemex_flatten
from analysis import phemex_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', marg=100.0, dur=2.0, opened_ms=0,
         closed_ms=None):
    return dict(uid=uid, nick=nick, sym=sym, side=side, pr=pr, pnl=pnl, closed_pnl=pnl,
                exch_fee=0.0, fund_fee=0.0, lev=lev, dur=dur, marg=marg, month=month,
                opened_ms=opened_ms, closed_ms=closed_ms if closed_ms is not None else opened_ms)


def _filler(sym, month, side, n=3, pr=0.0):
    """Neutral rows from other traders, giving a cell a leave-self-out 'others' pool
    so a single-trader fixture's alpha isn't dropped as self-dominated."""
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
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick, opened_ms=i))
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
    assert rejections['concentration>30% (top-1 trade)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    rows = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETHUSDT', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTCUSDT', '2026-06', 'long') + _filler('ETHUSDT', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['net-negative closed PnL'] >= 1
    assert 'concentration>30% (top-1 trade)' not in rejections


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0,
                                              levp90_max=100, margin_med_min=0, dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['uid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


# ---------------------------------------------------------------------------
# Binance reference hard filters (top5_final.py:48-56), ported from okx_top5.py.
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
                rows.append(_row('T', sym, month, 'long', pr, pnl, lev=lev, marg=marg, dur=dur,
                                  opened_ms=t_ms + i * 3_600_000))
            rows += _filler(sym, month, 'long', n=10)
    return rows


def test_rank_traders_production_thresholds_full_fixture():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)
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
    candidates, _ = t5.rank_traders(rows)
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
                rows2.append(_row('T', sym, month, 'long', pr, pnl, opened_ms=t_ms + i * 3_600_000))
            rows2 += _filler(sym, month, 'long', n=10)
    t5.compute_alpha(rows2, min_cell=t5.MIN_CELL)
    candidates2, rejections2 = t5.rank_traders(rows2)
    assert candidates2 == []
    assert rejections2['t<2.5'] >= 1


# ---------------------------------------------------------------------------
# Phemex-specific: trade-level drawdown proxy (the enforced screen, self-
# referential — see phemex_top5.py's module docstring for why this differs
# from OKX/Bybit) and the superseded monthly proxy (kept report-only).
# ---------------------------------------------------------------------------

def test_trade_drawdown_proxy_undefined_when_never_positive_peak():
    v = [_row('A', 'BTCUSDT', '2026-06', 'long', -0.01, -10.0, opened_ms=1, closed_ms=1),
         _row('A', 'BTCUSDT', '2026-06', 'long', -0.01, -5.0, opened_ms=2, closed_ms=2)]
    ratio, closed_ms, n = t5.trade_drawdown_proxy(v)
    assert ratio is None
    assert n == 2


def test_trade_drawdown_proxy_catches_mid_window_peak_and_crash():
    # A real intra-month drawdown that a monthly-bucketed proxy cannot see: all
    # three trades close in the same calendar month, so `monthly_drawdown_proxy`
    # only ever sees one net-positive monthly bucket (0% drawdown, no fall
    # possible from a single point) while the trade-level proxy sees the crash.
    v = [_row('A', 'BTCUSDT', '2026-08', 'long', 0.05, 1000.0, opened_ms=1, closed_ms=1),
         _row('A', 'BTCUSDT', '2026-08', 'long', -0.03, -700.0, opened_ms=2, closed_ms=2),
         _row('A', 'BTCUSDT', '2026-08', 'long', 0.02, 200.0, opened_ms=3, closed_ms=3)]
    ratio, closed_ms, n = t5.trade_drawdown_proxy(v)
    assert abs(ratio - (300 - 1000) / 1000) < 1e-9
    assert closed_ms == 2
    assert n == 3
    month_ratio, month, n_months = t5.monthly_drawdown_proxy(v)
    assert month_ratio is None  # single month -> no drawdown measurable at all
    assert n_months == 1


def test_trade_drawdown_proxy_orders_by_closed_ms_not_insertion_order():
    v = [_row('A', 'BTCUSDT', '2026-08', 'long', -0.03, -700.0, opened_ms=2, closed_ms=2),
         _row('A', 'BTCUSDT', '2026-08', 'long', 0.05, 1000.0, opened_ms=1, closed_ms=1)]
    ratio, closed_ms, n = t5.trade_drawdown_proxy(v)
    assert abs(ratio - (300 - 1000) / 1000) < 1e-9
    assert closed_ms == 2


def test_rank_traders_rejects_deep_trade_level_drawdown():
    # Give trader T a >20% peak-to-trough drawdown at trade granularity while
    # still clearing every other filter: wr/payoff are driven by `pr` (price
    # return), the drawdown proxy by `pnl` (dollars) -- decoupling them lets a
    # handful of small-pr, large-dollar losses wipe out most of the peak without
    # tripping the win-rate or payoff filters.
    rows = []
    t_ms = 1_780_000_000_000
    i = 0
    # 20 wins build a ~$2,000 peak, 4 losses (small pr=-0.01, so wr/payoff stay
    # clean) at -$500 each cut deep into it, then 20 more wins recover to a
    # net-positive total (avoids the net-negative bucket).
    schedule = [('2026-06', 0.03, 100.0, 20), ('2026-07', -0.01, -500.0, 4),
                ('2026-08', 0.03, 100.0, 20)]
    for month, pr, pnl, count in schedule:
        for j in range(count):
            i += 1
            sym = 'BTCUSDT' if j % 2 == 0 else 'ETHUSDT'
            ms = t_ms + i * 3_600_000
            rows.append(_row('T', sym, month, 'long', pr, pnl, opened_ms=ms, closed_ms=ms))
    for sym in ('BTCUSDT', 'ETHUSDT'):
        for month in ('2026-06', '2026-07', '2026-08'):
            rows += _filler(sym, month, 'long', n=10)
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows, t_min=0, levp90_max=100,
                                              margin_med_min=0, dur_med_min_h=0)
    assert candidates == []
    assert rejections['trade-level drawdown proxy >20% (self-referential, intra-window)'] >= 1


def test_monthly_drawdown_proxy_undefined_with_fewer_than_2_months():
    v = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.01, 10.0)]
    ratio, month, n_months = t5.monthly_drawdown_proxy(v)
    assert ratio is None
    assert n_months == 1


def test_monthly_drawdown_proxy_undefined_when_never_positive_peak():
    # cumulative pnl is negative throughout -> no peak to fall from -> None, not a
    # spurious "0% drawdown" or division by a non-positive number.
    v = [_row('A', 'BTCUSDT', m, 'long', -0.01, -10.0) for m in ('2026-06', '2026-07')]
    ratio, month, n_months = t5.monthly_drawdown_proxy(v)
    assert ratio is None
    assert n_months == 2


def test_monthly_drawdown_proxy_computes_peak_to_trough_fraction():
    v = [_row('A', 'BTCUSDT', '2026-06', 'long', 0.05, 100.0),   # cum=100 (peak)
         _row('A', 'BTCUSDT', '2026-07', 'long', -0.05, -60.0),  # cum=40 (trough vs peak 100)
         _row('A', 'BTCUSDT', '2026-08', 'long', 0.02, 10.0)]    # cum=50, no new trough
    ratio, month, n_months = t5.monthly_drawdown_proxy(v)
    assert abs(ratio - (40 - 100) / 100) < 1e-9
    assert month == '2026-07'
    assert n_months == 3


def test_monthly_drawdown_proxy_can_hide_what_trade_level_catches():
    # Regression for the GLM-1 audit finding: a real peak-to-trough drawdown
    # that falls entirely inside one calendar month is invisible to the monthly
    # proxy (only one bucket exists -> no fall is measurable) but is exactly
    # what the trade-level proxy (the enforced screen) is built to catch.
    v = [_row('A', 'BTCUSDT', '2026-08', 'long', 0.05, 1000.0, opened_ms=1, closed_ms=1),
         _row('A', 'BTCUSDT', '2026-08', 'long', -0.03, -700.0, opened_ms=2, closed_ms=2)]
    month_ratio, _, _ = t5.monthly_drawdown_proxy(v)
    trade_ratio, _, _ = t5.trade_drawdown_proxy(v)
    assert month_ratio is None
    assert trade_ratio is not None and trade_ratio < t5.DRAWDOWN_THRESHOLD


def test_load_recommend_list_reads_show_position_and_mdd(tmp_path):
    path = tmp_path / 'phemex_list.json'
    path.write_text(json.dumps([
        {'userId': 1, 'nick': 'a', 'showPosition': True, 'mdd30': '0.505', 'pnl30': '100.0',
         'roi30': '1.5', 'wr30': '0.5', 'aum': '10', 'followers': 3},
        {'userId': 2, 'nick': 'b', 'showPosition': False, 'mdd30': '0.1'},
    ]))
    info = t5.load_recommend_list(str(path))
    # Keys are `str`, not the JSON's native `int` -- see load_recommend_list's
    # docstring: rank_traders looks these up with the CSV-derived `str` uid, and a
    # type mismatch here silently produced 0/305 overlap in production before the fix.
    assert isinstance(next(iter(info)), str)
    assert info['1']['show_position'] is True
    assert info['1']['mdd30'] == 0.505
    assert info['2']['show_position'] is False


def test_load_recommend_list_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_recommend_list(str(tmp_path / 'nope.json')) == {}


def test_recommend_list_keying_integration_csv_to_rank_traders(tmp_path):
    """Regression for the int-vs-string userId bug (Fable-1): build a minimal CSV
    with one real-shape trader plus filler rows, and a recommend-list snapshot with
    that trader's userId as a JSON int (as the live endpoint returns it), and check
    mdd30 actually reaches the trader's output dict through rank_traders — not just
    that load_recommend_list parses in isolation."""
    csv_path = tmp_path / 'phemex_positions.csv'
    with open(csv_path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(phemex_flatten.COLS)
        t_ms = 1_780_000_000_000
        i = 0
        for month in ('2026-06', '2026-07'):
            for sym in ('BTCUSDT', 'ETHUSDT'):
                for j in range(5):
                    i += 1
                    pr_win = j < 4
                    op, cp = (100.0, 103.0) if pr_win else (100.0, 99.0)
                    pnl = 50.0 if pr_win else -15.0
                    ms = t_ms + i * 3_600_000
                    w.writerow(['777', 'realuid', i, sym, 'Buy', 'Long', 22.0, op, cp, 100.0,
                                pnl, pnl, 0.0, 0.0, 0.0, 1.0, 'USD', ms, ms + 3_600_000, 2.0, 0.0])
                for k in range(10):
                    i += 1
                    ms = t_ms + i * 3_600_000
                    w.writerow([f'FILLER{k}', 'filler', i, sym, 'Buy', 'Long', 10.0, 100.0, 100.0,
                                100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 'USD', ms, ms + 3_600_000,
                                2.0, 0.0])

    list_path = tmp_path / 'phemex_list.json'
    list_path.write_text(json.dumps([
        {'userId': 777, 'nick': 'realuid', 'showPosition': True, 'mdd30': '0.05',
         'pnl30': '500.0', 'roi30': '0.5', 'wr30': '0.8', 'aum': '10', 'followers': 3},
    ]))

    rows = t5.load_positions(str(csv_path))
    bench, dropped, cell_share = t5.compute_alpha(rows)
    recommend = t5.load_recommend_list(str(list_path))
    candidates, _ = t5.rank_traders(rows, recommend, t_min=0, levp90_max=100,
                                     margin_med_min=0, dur_med_min_h=0, dd_threshold=-1.0,
                                     dropped_self_dominated=dropped, cell_share_max=cell_share)
    real = next(d for d in candidates if d['uid'] == '777')
    assert real['mdd30'] == 0.05
