#!/usr/bin/env python3
"""Scrapes OKX public copy-trading position history + open positions for the full
lead-trader universe (verified live 2026-08-29, refining `docs/okx_endpoint_facts.md`).

Endpoints (public, GET, no auth):
  - Ranking: `scrape_okx.fetch_ranking` (unchanged) discovers the universe. Measured
    2026-08-29: **261 traders total** (27 pages, last page has 1 row, page 28 is empty).
  - Closed positions: `/api/v5/copytrading/public-subpositions-history?uniqueCode=<code>`
    ⚠️ **Caps silently at 100 rows.** `page`, `limit`, `before`, `after`, `subPosId` are all
    accepted (code stays "0") but never change the result — confirmed against 3 traders
    who each returned exactly 100 rows regardless of any param combination. There is no
    way to page past it. (Corrects `docs/okx_endpoint_facts.md`'s earlier "~58-row" note:
    that was one trader's *actual* total, not the cap — three other traders hit 100 flat.)
    ⚠️ A minority of rows have `closeTime == ""` — the position is **not actually closed**,
    it is a realized partial-close event on a lot still open. These do not belong in
    "closed positions": they are folded into `okx_open_positions.jsonl` instead.
    ⚠️ A large minority of ranked traders return `{"code":"60004","msg":"Trader doesn't
    exist"}` on this endpoint (and on public-current-subpositions) despite ranking +
    public-stats working fine for the same `uniqueCode`. Measured over the full universe
    (2026-08-29): **79 of 261 (30%)**. Treated as a terminal, non-retryable state
    ('not_found' in the manifest) — not a scrape error.
  - Open positions: `/api/v5/copytrading/public-current-subpositions?uniqueCode=<code>`
    Same 100-row cap observed. Rows carry `upl`/`uplRatio` (unrealized) but no fee field.
  - ✅ **NET vs GROSS (verified 2026-08-29).** `pnl` on public-subpositions-history is NET
    of fees. Reconstructed gross price PnL as `subPos × ctVal × (closeAvgPx − openAvgPx) ×
    side` (ctVal from `/api/v5/public/instruments`, e.g. 0.01 for BTC-USDT-SWAP) and diffed
    against the reported `pnl` over 558 closed BTC-USDT-SWAP rows drawn from the first 5
    ranking pages: the residual is POSITIVE (gross > net, i.e. a fee was subtracted) in
    96.6% of rows, median 6.5 bps of notional — same order of magnitude as Binance's 7.85
    bps and consistent with Phemex's exact fee decomposition (see SKILL.md).
  - `public-stats?lastDays=N` only accepts **N in {1, 2, 3}** — 7/30/90/180 all return error
    51000 regardless of whether `instType=SWAP` is also passed. (The task brief's suggestion
    to "try 90/180" does not hold; `scrape_okx.py` already uses lastDays=3, the max.)

data/okx_positions.jsonl          — one row per CLOSED position (closeTime set), with
                                     uniqueCode/nickName/leadDays embedded.
data/okx_open_positions.jsonl     — one row per OPEN position: public-current-subpositions
                                     rows plus any closeTime=="" rows folded in from history
                                     (deduped by subPosId, current-subpositions wins — it
                                     carries `upl`).
data/okx_positions_manifest.jsonl — resumability ledger, one row per uniqueCode already
                                     attempted: {uniqueCode, nickName, n_closed, n_open,
                                     closed_capped, status}. Needed because a trader with
                                     zero closed positions writes nothing to
                                     okx_positions.jsonl, so "done" can't be derived from
                                     that file alone (unlike scrape_binance.py).

Usage: python3 scripts/scrape_okx_positions.py [--traders N] [--pages N] [--stats]
  --traders N   cap how many NOT-YET-processed traders to fetch this run (default: all)
  --pages N     cap ranking pages passed to fetch_ranking (default: 50, covers the
                measured 27-page universe with room to grow)
  --stats       also fetch public-stats?lastDays=3 per trader into
                data/okx_trader_stats.jsonl (resumable, shares scrape_okx.fetch_stats)
"""
import json, time, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.scrape_okx import get, fetch_ranking, fetch_stats, _done_ids

HIST_URL = 'https://www.okx.com/api/v5/copytrading/public-subpositions-history?uniqueCode={}'
CUR_URL = 'https://www.okx.com/api/v5/copytrading/public-current-subpositions?uniqueCode={}'
HISTORY_CAP = 100


def fetch_closed_and_open(unique_code, get_fn):
    """Returns (closed_rows, open_rows, status) for one trader, or None on a
    retryable failure (network/API error on either endpoint — NOT 60004)."""
    h = get_fn(HIST_URL.format(unique_code))
    h_missing = h.get('code') == '60004'
    if not h_missing and h.get('code') != '0':
        return None
    hist_rows = (h.get('data') or []) if not h_missing else []
    closed = [r for r in hist_rows if r.get('closeTime')]
    open_from_hist = [r for r in hist_rows if not r.get('closeTime')]

    c = get_fn(CUR_URL.format(unique_code))
    c_missing = c.get('code') == '60004'
    if not c_missing and c.get('code') != '0':
        return None
    cur_rows = (c.get('data') or []) if not c_missing else []

    seen = {r['subPosId'] for r in cur_rows if r.get('subPosId')}
    open_rows = cur_rows + [r for r in open_from_hist if r.get('subPosId') not in seen]
    status = 'not_found' if (h_missing and c_missing) else 'ok'
    return closed, open_rows, status


def _manifest_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                rec = json.loads(line)
                if rec.get('status') in ('ok', 'not_found'):
                    done.add(rec['uniqueCode'])
            except Exception:
                pass
    return done


def run(out_dir='data', pages=50, traders_cap=None, http_get=None, fetch_stats_flag=False):
    get_fn = http_get or get
    os.makedirs(out_dir, exist_ok=True)

    ranking = fetch_ranking(pages, get_fn)
    print(f'okx universe: {len(ranking)} traders (ranking capped at {pages} pages)', flush=True)

    manifest_path = os.path.join(out_dir, 'okx_positions_manifest.jsonl')
    done = _manifest_done(manifest_path)
    todo = [r for r in ranking if r['uniqueCode'] not in done]
    if traders_cap is not None:
        todo = todo[:traders_cap]
    print(f'positions to fetch: {len(todo)} | already done: {len(done)}', flush=True)

    closed_out = open(os.path.join(out_dir, 'okx_positions.jsonl'), 'a')
    open_out = open(os.path.join(out_dir, 'okx_open_positions.jsonl'), 'a')
    manifest_out = open(manifest_path, 'a')
    stats_out, stats_done = None, set()
    if fetch_stats_flag:
        stats_path = os.path.join(out_dir, 'okx_trader_stats.jsonl')
        stats_done = _done_ids(stats_path, 'uniqueCode')
        stats_out = open(stats_path, 'a')

    n_closed = n_open = n_done = n_stats = 0
    t0 = time.time()
    for r in todo:
        code = r['uniqueCode']
        result = fetch_closed_and_open(code, get_fn)
        if result is None:
            print(f'  ERR positions {code} - will be retried on resume', flush=True)
            time.sleep(0.4)
            continue
        closed, open_rows, status = result
        for row in closed:
            closed_out.write(json.dumps({'uniqueCode': code, 'nickName': r.get('nickName'),
                                          'leadDays': r.get('leadDays'), **row},
                                         ensure_ascii=False) + '\n')
        for row in open_rows:
            open_out.write(json.dumps({'uniqueCode': code, 'nickName': r.get('nickName'), **row},
                                       ensure_ascii=False) + '\n')
        closed_out.flush()
        open_out.flush()
        manifest_out.write(json.dumps({
            'uniqueCode': code, 'nickName': r.get('nickName'), 'n_closed': len(closed),
            'n_open': len(open_rows), 'closed_capped': len(closed) >= HISTORY_CAP,
            'status': status,
        }, ensure_ascii=False) + '\n')
        manifest_out.flush()
        n_closed += len(closed)
        n_open += len(open_rows)
        n_done += 1

        if fetch_stats_flag and code not in stats_done:
            stats, ok = fetch_stats(code, get_fn)
            if ok:
                stats_out.write(json.dumps({'uniqueCode': code, 'nickName': r.get('nickName'),
                                             **(stats or {})}, ensure_ascii=False) + '\n')
                stats_out.flush()
                n_stats += 1
            time.sleep(0.3)

        if n_done % 25 == 0:
            elapsed = time.time() - t0
            eta_min = (elapsed / n_done) * (len(todo) - n_done) / 60
            print(f'  {n_done}/{len(todo)} traders | {n_closed} closed, {n_open} open '
                  f'positions | ETA {eta_min:.1f} min', flush=True)
        time.sleep(0.4)

    closed_out.close()
    open_out.close()
    manifest_out.close()
    if stats_out:
        stats_out.close()
    return {'traders': len(ranking), 'processed': n_done, 'closed': n_closed,
            'open': n_open, 'stats': n_stats}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    argv = sys.argv[1:]
    pages = 50
    if '--pages' in argv:
        pages = int(argv[argv.index('--pages') + 1])
    traders_cap = None
    if '--traders' in argv:
        traders_cap = int(argv[argv.index('--traders') + 1])
    fetch_stats_flag = '--stats' in argv
    counts = run(pages=pages, traders_cap=traders_cap, fetch_stats_flag=fetch_stats_flag)
    print(f"DONE: {counts['processed']} traders processed | {counts['closed']} closed "
          f"positions | {counts['open']} open positions | {counts['stats']} stats rows",
          flush=True)


if __name__ == '__main__':
    main()
