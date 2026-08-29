# analysis/ — scripts del análisis auditado (2026-08-25)

Cada `.py` de este directorio reproduce números concretos de `FINDINGS_v2.md`,
`RULES.md` y `TOP5.md`. Son **one-offs de investigación**, no una librería: se
conservan como evidencia de que cada afirmación es re-derivable, no como código
mantenido. El pipeline de `pipeline/` copió su lógica; no los importa.

## Cómo correrlos

1. **Necesitas un snapshot crudo.** La data no se versiona (dumps de las APIs de
   Binance/Phemex, no se redistribuyen). Genera el tuyo:

   ```bash
   python3 pipeline.py scrape --date $(date +%F)
   ```

   Los scripts esperan los `.jsonl` en `data/` con los nombres originales
   (`binance_positions.jsonl`, `positions_all.jsonl`).

2. **Aplana primero.** `flatten.py` produce los CSV que leen todos los demás:

   ```bash
   python3 analysis/flatten.py       # -> analysis/binance_positions.csv, phemex_positions.csv
   ```

3. **Los demás corren desde este directorio**, no desde la raíz — abren rutas
   relativas como `binance_positions.csv` y `ohlc/btcusdt_1h.csv`:

   ```bash
   cd analysis && python3 elite_btc.py
   ```

4. Los que necesitan velas (`regime.py`, `entry_rules.py`, `exit_rules.py`,
   `rule_backtest.py`, `rules_oos.py`, `forward_test.py`) requieren correr antes
   `fetch_ohlc.py` y/o `fetch_ohlc_long.py`, que descargan OHLC de BTCUSDT a
   `analysis/ohlc/`.

⚠️ Sobre un snapshot nuevo los números **no** coincidirán con los de
`FINDINGS_v2.md`: aquellos son del snapshot del 2026-08-25, que cubre un único
ciclo de régimen. Ver los caveats de `SKILL.md`.
