#!/usr/bin/env python3
# pipeline.py — entrypoint for the copy-trading-refresh pipeline
"""Usage:
  python3 pipeline.py scrape  [--date YYYY-MM-DD] [--exchange all|binance|phemex]
  python3 pipeline.py analyze [--date YYYY-MM-DD] [--force]
  python3 pipeline.py publish --date YYYY-MM-DD     (the only one that writes analysis/roster.json)
  python3 pipeline.py metrics|detect|trend|rank|report --date YYYY-MM-DD
     (mandatory order: metrics -> detect -> trend -> rank -> report;
      metrics resets flags/trend_bonus — a rank without detect+trend ranks with no flags)
"""
import argparse, csv, datetime as dt, glob, json, os, shutil, sys
from pipeline import db as dbmod, flatten, ingest, metrics, detect, trend, rank, report
from pipeline import scrape as scrape_mod


def _paths(root, date):
    return {'snap': os.path.join(root, 'data', 'snapshots', date),
            'db': os.path.join(root, 'data', 'copytrade.sqlite'),
            'run': os.path.join(root, 'analysis', 'runs', date),
            'latest': os.path.join(root, 'analysis', 'roster.json')}


def _csv_counts(snap_dir, ex):
    """(n_traders, n_positions) from the snapshot CSV, or None if missing/empty."""
    path = os.path.join(snap_dir, f'{ex}.csv')
    if not os.path.exists(path):
        return None
    key = 'portfolio_id' if ex == 'binance' else 'trader_id'
    traders, n = set(), 0
    for r in csv.DictReader(open(path)):
        traders.add(r[key]); n += 1
    return (len(traders), n) if n else None


def _validate_pre(con, snap_dir, date, force):
    """BEFORE ingest, straight from the CSVs — the DB is left untouched on failure."""
    raws = [p for p in glob.glob(os.path.join(snap_dir, '*_raw.jsonl'))
            if os.path.getsize(p) > 0]
    if not os.path.isdir(snap_dir) or not raws:
        print(f"VALIDATION: {snap_dir} does not exist or has no *_raw.jsonl — "
              f"typo in --date?", file=sys.stderr)
        return False                       # not even --force skips this one
    if _csv_counts(snap_dir, 'binance') is None:
        print("VALIDATION: no binance.csv (or empty) — v1 analyses Binance; "
              "carrying on would produce an EMPTY roster", file=sys.stderr)
        return False                       # --force does NOT skip this one either
    ok = True
    for ex in ('binance', 'phemex'):
        prev = con.execute(
            "SELECT snapshot_date, n_traders, n_positions FROM snapshots "
            "WHERE exchange=? AND snapshot_date<? ORDER BY snapshot_date DESC LIMIT 1",
            (ex, date)).fetchone()
        cur = _csv_counts(snap_dir, ex)
        if prev and cur is None:
            print(f"VALIDATION {ex}: had a previous snapshot ({prev['snapshot_date']}) "
                  f"but there is no CSV today — incomplete scrape", file=sys.stderr)
            ok = False
            continue
        if not prev or cur is None:
            continue
        for field, c, p in (('n_traders', cur[0], prev['n_traders']),
                            ('n_positions', cur[1], prev['n_positions'])):
            if p and not (0.5 * p <= c <= 1.5 * p):
                print(f"VALIDATION {ex}.{field}: {c} vs {p} on "
                      f"{prev['snapshot_date']} (outside ±50%)", file=sys.stderr)
                ok = False
    if not ok and not force:
        print("Aborting WITHOUT touching the DB; use --force to continue.",
              file=sys.stderr)
        return False
    return True


def _known_ids(con, snap_dir):
    """Historical union: DB ids not yet downloaded into this snapshot."""
    hist = {r[0] for r in con.execute(
        "SELECT DISTINCT trader_id FROM positions WHERE exchange='binance'")}
    done = set()
    raw = os.path.join(snap_dir, 'binance_raw.jsonl')
    if os.path.exists(raw):
        for line in open(raw):
            try:
                done.add(json.loads(line)['portfolioId'])
            except Exception:
                pass
    return tuple(sorted(hist - done))


def main(argv=None, project_root=None):
    root = project_root or os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        epilog='Order of the granular subcommands: metrics -> detect -> trend -> '
               'rank -> report (metrics resets flags/trend_bonus).')
    ap.add_argument('cmd', choices=['scrape', 'analyze', 'publish', 'metrics',
                                    'detect', 'trend', 'rank', 'report'])
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--exchange', default='all')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    P = _paths(root, a.date)

    if a.cmd == 'publish':
        src = os.path.join(P['run'], 'roster.json')
        if not os.path.exists(src):
            print(f"publish: {src} does not exist — run analyze first",
                  file=sys.stderr)
            return 1
        shutil.copy(src, P['latest'])
        print('published:', P['latest'])
        return 0

    os.makedirs(os.path.join(root, 'data'), exist_ok=True)
    con = dbmod.connect(P['db'])
    try:
        if a.cmd == 'scrape':
            ex = ('binance', 'phemex') if a.exchange == 'all' else (a.exchange,)
            extra = _known_ids(con, P['snap']) if 'binance' in ex else ()
            print(scrape_mod.run(P['snap'], exchanges=ex, extra_ids_binance=extra))
            return 0
        if a.cmd == 'analyze':
            print('flatten:', flatten.flatten_snapshot(P['snap'])
                  if os.path.isdir(P['snap']) else 'snapshot dir does not exist')
            if not _validate_pre(con, P['snap'], a.date, a.force):
                return 2
            print('ingest:', ingest.ingest_snapshot(con, P['snap'], a.date))
            print('metrics:', metrics.compute(con, a.date))
            detect.run(con, a.date)
            prev_roster = None
            prev = con.execute(
                "SELECT MAX(snapshot_date) FROM snapshots "
                "WHERE exchange='binance' AND snapshot_date<?",
                (a.date,)).fetchone()[0]
            if prev:
                pr = os.path.join(root, 'analysis', 'runs', prev, 'roster.json')
                if os.path.exists(pr):
                    prev_roster = json.load(open(pr))
            diff = trend.run(con, a.date, prev_roster=prev_roster)
            roster = rank.run(con, a.date, diff=diff, prev_roster=prev_roster)
            os.makedirs(P['run'], exist_ok=True)
            json.dump(roster, open(os.path.join(P['run'], 'roster.json'), 'w'),
                      indent=1, ensure_ascii=False)
            json.dump(diff, open(os.path.join(P['run'], 'diff.json'), 'w'),
                      indent=1, ensure_ascii=False)
            p = report.write(con, a.date, 'binance', roster, diff, P['run'],
                             snap_dir=P['snap'])
            # NOT copied to analysis/roster.json here: that is `publish`, after the gate
            print('report:', p)
            print('material:', diff['material'])
            return 0
        if a.cmd == 'metrics':
            print(metrics.compute(con, a.date)); return 0
        if a.cmd == 'detect':
            print(detect.run(con, a.date)); return 0
        if a.cmd == 'trend':
            print(trend.run(con, a.date)); return 0
        if a.cmd == 'rank':
            print(json.dumps(rank.run(con, a.date), ensure_ascii=False)); return 0
        if a.cmd == 'report':
            # reads the run artifacts — does NOT recompute trend/rank
            # (recomputing without prev_roster would yield a diff unlike analyze's)
            rp = os.path.join(P['run'], 'roster.json')
            dp = os.path.join(P['run'], 'diff.json')
            if not (os.path.exists(rp) and os.path.exists(dp)):
                print("report: roster.json/diff.json missing — run analyze first",
                      file=sys.stderr)
                return 1
            print(report.write(con, a.date, 'binance', json.load(open(rp)),
                               json.load(open(dp)), P['run'], snap_dir=P['snap']))
            return 0
    finally:
        con.close()


if __name__ == '__main__':
    sys.exit(main())
