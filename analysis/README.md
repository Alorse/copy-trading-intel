# analysis/ — scripts of the audited analysis (2026-08-25)

Every `.py` in this directory reproduces specific figures from `FINDINGS_v2.md`, `RULES.md` and
`TOP5.md`. They are **research one-offs**, not a library: they are kept as evidence that each
claim is re-derivable, not as maintained code. The pipeline in `pipeline/` copied their logic; it
does not import them.

## How to run them

1. **You need a raw snapshot.** The data is not versioned (dumps of the Binance/Phemex APIs, not
   redistributed). Generate your own:

   ```bash
   python3 pipeline.py scrape --date $(date +%F)
   ```

   The scripts expect the `.jsonl` files in `data/` under their original names
   (`binance_positions.jsonl`, `positions_all.jsonl`).

2. **Flatten first.** `flatten.py` produces the CSVs every other script reads:

   ```bash
   python3 analysis/flatten.py       # -> analysis/binance_positions.csv, phemex_positions.csv
   ```

3. **The rest run from this directory**, not from the repo root — they open relative paths like
   `binance_positions.csv` and `ohlc/btcusdt_1h.csv`:

   ```bash
   cd analysis && python3 elite_btc.py
   ```

4. The ones needing candles (`regime.py`, `entry_rules.py`, `exit_rules.py`, `rule_backtest.py`,
   `rules_oos.py`, `forward_test.py`) require running `fetch_ohlc.py` and/or `fetch_ohlc_long.py`
   first, which download BTCUSDT OHLC into `analysis/ohlc/`.

⚠️ On a new snapshot the numbers will **not** match those in `FINDINGS_v2.md`: those come from the
2026-08-25 snapshot, which covers a single regime cycle. See the caveats in `SKILL.md`.
