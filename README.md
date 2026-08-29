# copy-trading-intel

Inteligencia de copy-trading (Binance + Phemex): análisis auditado de lead-traders
y pipeline `copy-trading-refresh` para mantener un roster de traders a copiar.

## Para el agente que ejecuta el plan

**Empieza aquí:**

1. **Plan de implementación**: `docs/plans/2026-08-28-copy-trading-refresh.md`
   — 14 tasks TDD con código y tests completos. Ejecutar task por task, en orden.
2. **Spec (el yardstick)**: `docs/specs/2026-08-28-copy-trading-refresh-design.md`
3. Ambos ya pasaron **revisión adversarial** (Fable/Kimi/GLM, 2026-08-28); las
   correcciones están incorporadas. La sección "Self-Review + Revisión adversarial"
   del plan lista los 11 cambios mayores — no re-litigar esas decisiones.

**Requisitos:**
- Python ≥ 3.11 (el motor usa `datetime.UTC`); runtime = stdlib puro, **cero deps**.
- `pytest` solo para los tests (dev-only).
- Los tests de regresión (Task 11) usan `data/binance_positions.jsonl` y
  `data/positions_all.jsonl` (incluidos en el repo); los symlinks de
  `data/snapshots/2026-08-25/` los crea el propio Task 11.

**No tocar:** `scripts/` y `analysis/*.py` son los one-offs del análisis auditado
2026-08-25 (evidencia reproducible de `analysis/FINDINGS_v2.md`). El pipeline nuevo
COPIA su lógica, no los importa ni los modifica.

## Mapa del repo

| ruta | qué es |
|---|---|
| `SKILL.md` / `SKILL.v3.md` | skill original (v2) y candidata corregida (v3) con endpoints y trampas de la data |
| `analysis/FINDINGS_v2.md`, `TOP5.md`, `RULES.md` | hallazgos auditados: top-5 traders, reglas, descartes |
| `analysis/*.py` | scripts que reproducen cada número de los findings |
| `scripts/` | scrapers originales (Binance/Phemex) + probe |
| `data/*.jsonl`, `data/binance_portfolios.json` | snapshot crudo 2026-08-25 (192 traders Phemex / 594 portfolios Binance, 108k posiciones) |
| `data/SUMMARY.json`, `aggregate_*.json` | agregados del análisis |
| `pipeline.py`, `pipeline/` | (lo construye el plan) pipeline permanente scrape→SQLite→roster |

## Trampas de data (resumen — detalle en SKILL.v3.md)

- `mdd` de Binance es **porcentaje** (mediana ~30), no fracción.
- El lado real de Phemex está en `pos_side` (Long/Short/Merged), NO en `side` (Buy/Sell).
- La list API de Binance capea a **30/página** aunque pidas 50.
- `closingPnl` (Binance) y `realizedPnl` (Phemex) ya son netos de fees.
- Solo se ven posiciones cerradas: cuidado con los "loss-hiders".
