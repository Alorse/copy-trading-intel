#!/usr/bin/env python3
"""Unifies the new per-exchange trader lists into one CSV pool (phase 1: discovery
only, no ranking/classification across exchanges).

Reads every data/*_traders.jsonl (currently okx_traders.jsonl and
bybit_traders.jsonl — Phemex/Binance use older, differently-shaped files and are
out of scope here; Bitget has no working leaderboard endpoint so it writes
bitget_orders.jsonl, which this glob does not match) and writes
data/unified_traders.csv with columns:
  exchange, trader_id, nickname, pnl_usd, roi, aum_usd, followers, win_rate, extra_json

Dedups by (exchange, trader_id), keeping the last row seen for a given id.
Usage: python3 scripts/unify.py
"""
import csv, glob, json, os

COLUMNS = ['exchange', 'trader_id', 'nickname', 'pnl_usd', 'roi', 'aum_usd',
           'followers', 'win_rate', 'extra_json']

# maps exchange -> (fields consumed into named columns, so the rest goes to extra_json)
_MAPPED_FIELDS = {
    'okx': {'uniqueCode', 'nickName', 'pnl', 'pnlRatio', 'aum', 'copyTraderNum', 'winRatio'},
    'bybit': {'leaderUserId', 'nickName', 'total_all_follow_profit', 'roi',
              'currentFollowerCount', 'win_rate'},
}


def map_okx_row(rec):
    extra = {k: v for k, v in rec.items() if k not in _MAPPED_FIELDS['okx']}
    return {'exchange': 'okx', 'trader_id': rec.get('uniqueCode'),
            'nickname': rec.get('nickName'), 'pnl_usd': rec.get('pnl'),
            'roi': rec.get('pnlRatio'), 'aum_usd': rec.get('aum'),
            'followers': rec.get('copyTraderNum'), 'win_rate': rec.get('winRatio'),
            'extra_json': json.dumps(extra, ensure_ascii=False)}


def map_bybit_row(rec):
    extra = {k: v for k, v in rec.items() if k not in _MAPPED_FIELDS['bybit']}
    return {'exchange': 'bybit', 'trader_id': rec.get('leaderUserId'),
            'nickname': rec.get('nickName'), 'pnl_usd': rec.get('total_all_follow_profit'),
            'roi': rec.get('roi'), 'aum_usd': '',
            'followers': rec.get('currentFollowerCount'), 'win_rate': rec.get('win_rate'),
            'extra_json': json.dumps(extra, ensure_ascii=False)}


MAPPERS = {'okx': map_okx_row, 'bybit': map_bybit_row}


def _exchange_of(path):
    name = os.path.basename(path)
    return name[:-len('_traders.jsonl')] if name.endswith('_traders.jsonl') else None


def load_rows(data_dir='data'):
    """Reads every data/*_traders.jsonl for a known exchange and returns unified
    rows deduped by (exchange, trader_id) — last one seen wins."""
    rows = {}
    for path in sorted(glob.glob(os.path.join(data_dir, '*_traders.jsonl'))):
        exchange = _exchange_of(path)
        mapper = MAPPERS.get(exchange)
        if mapper is None:
            continue
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            row = mapper(rec)
            rows[(row['exchange'], row['trader_id'])] = row
    return list(rows.values())


def run(data_dir='data', out_path=None):
    out_path = out_path or os.path.join(data_dir, 'unified_traders.csv')
    rows = load_rows(data_dir)
    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    n = run()
    print(f'DONE: {n} rows written to data/unified_traders.csv', flush=True)


if __name__ == '__main__':
    main()
