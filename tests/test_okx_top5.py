import json
from analysis import okx_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', lead_days=200.0, notional=500.0,
         marg=100.0, opened_ms=0):
    # reconstruct open/close price consistent with pr, since compute_alpha only needs pr
    return dict(uid=uid, nick=nick, lead_days=lead_days, sym=sym, side=side, pr=pr, pnl=pnl,
                lev=lev, dur=2.0, notional=notional, marg=marg, month=month, opened_ms=opened_ms)


def _filler(sym, month, side, n=3, pr=0.0):
    """Neutral rows from other traders, giving a cell a leave-self-out 'others' pool
    so a single-trader fixture's alpha isn't dropped as self-dominated."""
    return [_row(f'FILLER{i}', sym, month, side, pr, 0.0) for i in range(n)]


def test_compute_alpha_is_pr_minus_cell_median():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    rows.append(_row('B', 'BTC-USDT-SWAP', '2026-06', 'long', 0.10, 1.0))
    t5.compute_alpha(rows, min_cell=8)
    # cell has 9 rows (>= min_cell=8), so alpha must be defined for all of them
    assert all(r['alpha'] is not None for r in rows)
    # trader B's outlier alpha (vs the other 8 traders, excluding itself) is positive
    assert rows[-1]['alpha'] > 0


def test_compute_alpha_none_when_cell_too_small():
    rows = [_row('A', 'ETH-USDT-SWAP', '2026-06', 'short', -0.01, 1.0)]
    t5.compute_alpha(rows, min_cell=8)
    assert rows[0]['alpha'] is None


def test_compute_alpha_leave_self_out_shifts_alpha_in_self_dominated_cell():
    # 9-row cell, 6 rows from A (pr=0.05) and 3 from B (pr=0.01). Self-inclusive median
    # is dragged to A's own return (0.05) by A's own volume, making A look average;
    # leave-self-out benchmarks A only against B and reveals A's real edge.
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.05, 1.0) for _ in range(6)]
    rows += [_row('B', 'BTC-USDT-SWAP', '2026-06', 'long', 0.01, 1.0) for _ in range(3)]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert dropped == {}
    assert cell_share['A'] == 6 / 9
    assert cell_share['B'] == 3 / 9
    a_rows = [r for r in rows if r['uid'] == 'A']
    assert all(abs(r['alpha_incl']) < 1e-9 for r in a_rows)     # self-inclusive: looks average
    assert all(abs(r['alpha'] - 0.04) < 1e-9 for r in a_rows)   # leave-self-out: real +4% edge


def test_compute_alpha_drops_self_dominated_cell():
    # cell has 8 rows (>= min_cell) but all from the same trader -> no "others" exist,
    # so the leave-self-out alpha is unusable and must be dropped, not silently zero.
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    bench, dropped, cell_share = t5.compute_alpha(rows, min_cell=8)
    assert all(r['alpha_incl'] is not None for r in rows)   # self-inclusive still defined
    assert all(r['alpha'] is None for r in rows)             # leave-self-out: unusable
    assert dropped == {'A': 8}
    assert cell_share['A'] == 1.0


def _multi_pair_trader(uid, n=24, base_pnl=10.0, nick='good'):
    """A trader with alternating small wins/losses across two symbols (always long,
    to keep the benchmark cells simple), no single trade dominating — should survive
    every hard filter. Comes bundled with a large "market" of neutral (pr=0) filler
    rows in the same cells so the trader's own trades don't dominate the benchmark
    median they're compared against."""
    rows = []
    for i in range(n):
        sym = 'BTC-USDT-SWAP' if i % 2 == 0 else 'ETH-USDT-SWAP'
        pr = 0.02 if i % 4 else -0.01     # 75% winners, 25% losers -> wr=75%, payoff=2.0
        pnl = base_pnl if pr > 0 else -base_pnl * 0.4
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick, opened_ms=i))
    for sym in ('BTC-USDT-SWAP', 'ETH-USDT-SWAP'):
        rows += [_row('FILLER', sym, '2026-06', 'long', 0.0, 0.0) for _ in range(20)]
    return rows


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTC-USDT-SWAP', '2026-06', 'short', -0.01, -1.0) for _ in range(5)]
    rows += _filler('BTC-USDT-SWAP', '2026-06', 'long') + _filler('BTC-USDT-SWAP', '2026-06', 'short')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETH-USDT-SWAP', '2026-06', 'long', -0.01, -1.0)]  # 1 loser / 20 = 95% wr
    rows += _filler('BTC-USDT-SWAP', '2026-06', 'long') + _filler('ETH-USDT-SWAP', '2026-06', 'long')
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETH-USDT-SWAP', '2026-06', 'long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTC-USDT-SWAP', '2026-07', 'long', 0.5, 1000.0))  # one huge trade
    rows += (_filler('BTC-USDT-SWAP', '2026-06', 'long') + _filler('ETH-USDT-SWAP', '2026-06', 'long')
             + _filler('BTC-USDT-SWAP', '2026-07', 'long'))
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['concentration>30% (top-1 trade)'] >= 1


def test_rank_traders_rejects_net_negative_pnl_before_concentration():
    # every trade is a small, evenly split loss -> total_pnl<=0, and no single trade
    # is anywhere near 30% of (an abs-valued) total, so this must land in its own
    # 'net-negative closed PnL' bucket, not get swept into 'concentration'.
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.01, -10.0) for _ in range(10)]
    rows += [_row('A', 'ETH-USDT-SWAP', '2026-06', 'long', -0.01, -10.0) for _ in range(10)]
    rows += _filler('BTC-USDT-SWAP', '2026-06', 'long') + _filler('ETH-USDT-SWAP', '2026-06', 'long')
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
    # net upl_sum is positive (gains on other open positions outweigh the loss), even
    # though upl_neg_sum alone looks catastrophic -> the hard filter (net) must NOT reject.
    rows = _multi_pair_trader('NETPOS', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows if r['uid'] == 'NETPOS')
    open_upl = {'NETPOS': {'upl_sum': abs(total_pnl) * 0.1, 'n_open': 2,
                            'upl_neg_sum': -abs(total_pnl) * 2}}
    candidates, rejections = t5.rank_traders(rows, open_upl=open_upl, min_n=15, min_alpha_n=1,
                                              t_min=0, levp90_max=100, margin_med_min=0,
                                              dur_med_min_h=0)
    assert len(candidates) == 1
    assert candidates[0]['hidden_loss_flag'] is True   # soft flag still fires off upl_neg_sum


def test_rank_traders_fresh_start_flag_below_120_days():
    rows = _multi_pair_trader('YOUNG', n=24)
    for r in rows:
        if r['uid'] == 'YOUNG':
            r['lead_days'] = 45.0
    t5.compute_alpha(rows, min_cell=1)
    candidates, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1, t_min=0, levp90_max=100,
                                     margin_med_min=0, dur_med_min_h=0)
    assert candidates[0]['fresh_start'] is True


def test_load_open_upl_aggregates_negative_and_positive(tmp_path):
    path = tmp_path / 'okx_open_positions.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in [
        {'uniqueCode': 'A', 'upl': '-5.0'},
        {'uniqueCode': 'A', 'upl': '2.0'},
        {'uniqueCode': 'B', 'upl': '1.0'},
    ]))
    agg = t5.load_open_upl(str(path))
    assert agg['A']['upl_sum'] == -3.0
    assert agg['A']['n_open'] == 2
    assert agg['A']['upl_neg_sum'] == -5.0
    assert agg['B']['upl_neg_sum'] == 0.0


def test_load_open_upl_missing_file_returns_empty_defaultdict(tmp_path):
    agg = t5.load_open_upl(str(tmp_path / 'nope.jsonl'))
    assert agg['anything']['n_open'] == 0


def test_load_trader_meta_reads_pnl_and_pnl_ratios(tmp_path):
    path = tmp_path / 'okx_traders.jsonl'
    path.write_text(json.dumps({
        'uniqueCode': 'A', 'pnl': '123.45',
        'pnlRatios': [{'beginTs': '1000', 'pnlRatio': '0.1'}, {'beginTs': '2000', 'pnlRatio': '-0.3'}],
    }) + '\n')
    meta = t5.load_trader_meta(str(path))
    assert meta['A']['ranking_pnl'] == 123.45
    assert meta['A']['pnl_ratios'] == [(1000, 0.1), (2000, -0.3)]


def test_load_trader_meta_missing_file_returns_empty_dict(tmp_path):
    assert t5.load_trader_meta(str(tmp_path / 'nope.jsonl')) == {}


# ---------------------------------------------------------------------------
# Binance reference hard filters (top5_final.py:48-56), adopted 2026-08-29.
# Each test below uses the same base fixture (t5.rank_traders' production
# defaults hold except for the one dimension under test, isolated via the
# other filters' kwargs so only the filter being tested can fire).
# ---------------------------------------------------------------------------

def _threshold_fixture(**overrides):
    """20 rows for trader 'T' across 2 symbols x 2 months, 4 wins + 1 loss per
    group (wr=80%, payoff~3.0), each cell backed by 10 neutral filler rows from
    other traders so leave-self-out alpha is well-defined (min_cell=8 default)."""
    rows = []
    t_ms = 1_780_000_000_000
    i = 0
    lev = overrides.get('lev', 10.0)
    marg = overrides.get('marg', 100.0)
    dur = overrides.get('dur', 2.0)
    for month in ('2026-06', '2026-07'):
        for sym in ('BTC-USDT-SWAP', 'ETH-USDT-SWAP'):
            for j in range(5):
                i += 1
                pr = 0.03 if j < 4 else -0.01
                pnl = 50.0 if pr > 0 else -15.0
                rows.append(_row('T', sym, month, 'long', pr, pnl, lev=lev, marg=marg,
                                  opened_ms=t_ms + i * 3_600_000))
                rows[-1]['dur'] = dur
            rows += _filler(sym, month, 'long', n=10)
    return rows


def test_rank_traders_production_thresholds_full_fixture():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, rejections = t5.rank_traders(rows)   # every default at production value
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
    # baseline fixture: strong, low-variance edge -> t well above 2.5 -> survives
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    candidates, _ = t5.rank_traders(rows)
    assert len(candidates) == 1 and candidates[0]['t'] > 2.5

    # noisier edge (bigger, more balanced swings) -> t drops below 2.5 -> rejected
    rows2 = []
    t_ms = 1_780_000_000_000
    i = 0
    for month in ('2026-06', '2026-07'):
        for sym in ('BTC-USDT-SWAP', 'ETH-USDT-SWAP'):
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
# The "01014588 lesson": weekly pnlRatios[] drawdown screen.
# ---------------------------------------------------------------------------

def test_drawdown_screen_deep_drawdown_uncovered_by_window_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['opened_ms'] for r in rows if r['uid'] == 'T')
    # drawdown's deepest point predates the window -> hidden, not covered -> reject
    trader_meta = {'T': {'ranking_pnl': 100.0,
                          'pnl_ratios': [(window_start - 10_000_000, -0.5)]}}
    candidates, rejections = t5.rank_traders(rows, trader_meta=trader_meta)
    assert candidates == []
    assert rejections['weekly pnlRatios drawdown >20%, uncovered by window'] >= 1


def test_drawdown_screen_deep_drawdown_covered_by_window_passes():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    window_start = min(r['opened_ms'] for r in rows if r['uid'] == 'T')
    # window already starts before/at the drawdown's deepest point -> visible, not hidden
    trader_meta = {'T': {'ranking_pnl': 100.0,
                          'pnl_ratios': [(window_start + 10_000_000, -0.5)]}}
    candidates, rejections = t5.rank_traders(rows, trader_meta=trader_meta)
    assert len(candidates) == 1
    assert candidates[0]['dd_covered'] is True
    assert candidates[0]['dd_min_ratio'] == -0.5


def test_drawdown_screen_shallow_drawdown_never_rejects():
    rows = _threshold_fixture()
    t5.compute_alpha(rows, min_cell=t5.MIN_CELL)
    trader_meta = {'T': {'ranking_pnl': 100.0, 'pnl_ratios': [(1, -0.05)]}}  # above -20% line
    candidates, rejections = t5.rank_traders(rows, trader_meta=trader_meta)
    assert len(candidates) == 1
    assert 'weekly pnlRatios drawdown >20%, uncovered by window' not in rejections
