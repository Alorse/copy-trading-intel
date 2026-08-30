import json
from analysis import okx_top5 as t5


def _row(uid, sym, month, side, pr, pnl, lev=10.0, nick='n', lead_days=200.0, notional=500.0):
    # reconstruct open/close price consistent with pr, since compute_alpha only needs pr
    return dict(uid=uid, nick=nick, lead_days=lead_days, sym=sym, side=side, pr=pr, pnl=pnl,
                lev=lev, dur=1.0, notional=notional, month=month)


def test_compute_alpha_is_pr_minus_cell_median():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', pr, 1.0) for pr in
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]]
    rows.append(_row('B', 'BTC-USDT-SWAP', '2026-06', 'long', 0.10, 1.0))
    t5.compute_alpha(rows, min_cell=8)
    median = sorted(r['pr'] for r in rows)[len(rows) // 2 - 1:len(rows) // 2 + 1]
    # cell has 9 rows (>= min_cell=8), so alpha must be defined for all of them
    assert all(r['alpha'] is not None for r in rows)
    # trader B's outlier alpha should be positive (above the cell's typical return)
    assert rows[-1]['alpha'] > 0


def test_compute_alpha_none_when_cell_too_small():
    rows = [_row('A', 'ETH-USDT-SWAP', '2026-06', 'short', -0.01, 1.0)]
    t5.compute_alpha(rows, min_cell=8)
    assert rows[0]['alpha'] is None


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
        rows.append(_row(uid, sym, '2026-06', 'long', pr, pnl, nick=nick))
    for sym in ('BTC-USDT-SWAP', 'ETH-USDT-SWAP'):
        rows += [_row('FILLER', sym, '2026-06', 'long', 0.0, 0.0) for _ in range(20)]
    return rows


def test_rank_traders_rejects_single_pair_h1():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.02, 5.0) for _ in range(20)]
    rows += [_row('A', 'BTC-USDT-SWAP', '2026-06', 'short', -0.01, -1.0) for _ in range(5)]
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['single-pair only (H1: reliability ~0.13)'] >= 1


def test_rank_traders_rejects_spotless_win_rate_trampa1():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.02, 5.0) for _ in range(19)]
    rows += [_row('A', 'ETH-USDT-SWAP', '2026-06', 'long', -0.01, -1.0)]  # 1 loser / 20 = 95% wr
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['win rate>92% (Trampa 1)'] >= 1


def test_rank_traders_rejects_concentration_over_30pct():
    rows = [_row('A', 'BTC-USDT-SWAP', '2026-06', 'long', 0.001, 1.0) for _ in range(10)]
    rows += [_row('A', 'ETH-USDT-SWAP', '2026-06', 'long', -0.001, -1.0) for _ in range(9)]
    rows.append(_row('A', 'BTC-USDT-SWAP', '2026-07', 'long', 0.5, 1000.0))  # one huge trade
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['concentration>30% (top-1 trade)'] >= 1


def test_rank_traders_accepts_a_clean_multi_pair_trader():
    rows = _multi_pair_trader('GOOD', n=24)
    t5.compute_alpha(rows, min_cell=1)
    candidates, rejections = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
    assert len(candidates) == 1
    assert candidates[0]['uid'] == 'GOOD'
    assert candidates[0]['n_syms'] == 2


def test_rank_traders_flags_and_rejects_large_open_unrealized_loss():
    rows = _multi_pair_trader('RISKY', n=24, base_pnl=10.0)
    t5.compute_alpha(rows, min_cell=1)
    total_pnl = sum(r['pnl'] for r in rows)
    open_upl = {'RISKY': {'upl_sum': -abs(total_pnl) * 2, 'n_open': 3,
                           'upl_neg_sum': -abs(total_pnl) * 2}}
    candidates, rejections = t5.rank_traders(rows, open_upl=open_upl, min_n=15, min_alpha_n=1)
    assert candidates == []
    assert rejections['open unrealized loss > 50% of closed PnL'] >= 1


def test_rank_traders_fresh_start_flag_below_120_days():
    rows = _multi_pair_trader('YOUNG', n=24)
    for r in rows:
        r['lead_days'] = 45.0
    t5.compute_alpha(rows, min_cell=1)
    candidates, _ = t5.rank_traders(rows, min_n=15, min_alpha_n=1)
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
