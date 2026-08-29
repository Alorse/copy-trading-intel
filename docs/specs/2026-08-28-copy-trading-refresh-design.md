# copy-trading-refresh — Diseño

**Fecha:** 2026-08-28 · **Estado:** aprobado en diseño, pendiente de plan de implementación
**Contexto previo:** sesión 8d3bb88a (auditoría adversarial del skill copy-trading-intel v2), `analysis/FINDINGS_v2.md`, `analysis/TOP5.md`, `SKILL.v3.md`.

## Objetivo

Mantener actualizado, con una corrida manual 1–2 veces al mes, un listado de los mejores
lead-traders de copy-trading (Binance principal; **Phemex se archiva pero NO se rankea en v1**
— ver Alcance Phemex) mediante un pipeline
repetible que: scrapea data fresca, la analiza con el motor estadístico ya auditado,
detecta traders que inflan sus números, mide quién mejora/empeora entre corridas, y
publica un roster machine-readable + un reporte humano. El mirror-bot (VPS) consume el
roster cuando el operador lo apunte — el pipeline **no** ejecuta ni configura trading por sí solo.

## Decisiones tomadas (con el operador)

1. **Salida:** `TOP_YYYY-MM.md` (reporte humano) + `roster.json` (machine-readable). El operador conecta el mirror-bot manualmente.
2. **Tendencia:** snapshots fechados + diff entre corridas, **y** buckets mensuales intra-snapshot (funciona desde la corrida #1).
3. **Motor:** determinista siempre; consejo adversarial LLM (Fable/Kimi/GLM vía skill `adversarial-review`) **solo** si el roster cambia materialmente.
4. **Ejecución:** local en la Mac, manual, vía skill `/copy-trading-refresh`. Portabilidad futura al VPS deseable → **cero dependencias**: Python stdlib + **SQLite** (descartado DuckDB explícitamente por footprint/deps en VPS).
5. **Enfoque:** A+C combinados — orquestación por stages (A) con capa analítica SQL (C, SQLite).

## Arquitectura

### Capas de datos

```
data/
  snapshots/YYYY-MM-DD/            ← CAPA CRUDA (inmutable, re-ingestable)
    binance_raw.jsonl              ← scrape crudo Binance
    phemex_raw.jsonl               ← scrape crudo Phemex
    binance.csv  phemex.csv        ← salida de flatten
  copytrade.sqlite                 ← CAPA ANALÍTICA (histórico de todas las corridas)
analysis/
  runs/YYYY-MM-DD/
    TOP_YYYY-MM.md                 ← reporte humano
    roster.json                    ← roster de la corrida
    diff.json                      ← cambios vs corrida anterior (input del gate)
  roster.json                      ← copia "latest" del roster publicado
```

- La DB es **derivada**: se puede reconstruir por completo re-ingiriendo `data/snapshots/`.
- Ingest idempotente: clave por `(snapshot_date, exchange)`; re-correr un ingest reemplaza ese snapshot, nunca duplica.
- El universo de traders es la **unión histórica** de todos los snapshots (se sigue a individuos en el tiempo, no solo al top-600 vigente). **Implementación:** `scrape` recibe los `trader_id` históricos conocidos (distinct de la DB) y baja el historial también de los que ya no aparecen en la lista viva — así el de-copy ve decaer a un trader justo cuando sale del ranking.

### Alcance Phemex (v1)

Phemex se **scrapea, aplana e ingiere** (archivo histórico + spike de abiertas), pero
`metrics/detect/trend/rank/report` operan **solo sobre Binance** en v1. Razones: el lado real
de Phemex vive en `pos_side` (`Long/Short/Merged` — 453 filas `Merged` inclasificables) y su
`side` es `Buy/Sell`, así que rankearlo exige un mapeo propio que se pospone. El `ingest` de
Phemex ya almacena `side` mapeado desde `pos_side` para que un análisis futuro no herede el
signo invertido.

### Esquema SQLite

| tabla | grano | columnas clave |
|---|---|---|
| `snapshots` | corrida × exchange | `snapshot_date, exchange, n_traders, n_positions, notes` |
| `positions` | 1 trade | `snapshot_date, exchange, trader_id, nick, symbol, side, opened_ms, closed_ms, notional, leverage, margin, closing_pnl, price_return, alpha, dur_h, partial` |
| `open_positions` | 1 posición abierta (si el spike funciona) | `snapshot_date, exchange, trader_id, symbol, side, notional, unrealized_pnl` |
| `trader_metrics` | trader × snapshot | `snapshot_date, exchange, trader_id, nick, n, alpha, t_stat, payoff, wr, conc_top1, ruin, mdd, lev_med, lev_p90, marg_med, dur_med, months_active, trend_bonus, score, tier, weight, flags` (flags = JSON array) |

Tendencia: window functions de SQLite (`LAG ... OVER (PARTITION BY trader_id ORDER BY snapshot_date)`).
Stats pesadas (t-stat, medianas, benchmark por celda) se calculan en Python (como hoy en `top5_final.py`), no en SQL.

### Stages

```
scrape → flatten → ingest → metrics → detect → trend → rank → report → [council]
         └── CAPA CRUDA ──┘ └────────────── sobre SQLite ─────────────┘
```

Un solo entrypoint `pipeline.py` con subcomandos; cada stage un módulo en `pipeline/`:

| stage | hace | red | notas |
|---|---|---|---|
| `scrape` | Reusa lógica de `scripts/scrape_binance.py` y `scripts/scrape_positions.py`, adaptada para escribir a `data/snapshots/<hoy>/` (NO appendear a un jsonl global). Resumable dentro del snapshot del día. | sí | Incluye intento de posiciones **abiertas** (spike, ver abajo). |
| `flatten` | Refactor de `analysis/flatten.py`: jsonl anidado → CSV plano en el dir del snapshot. | no | |
| `ingest` | CSV → SQLite, idempotente por snapshot. | no | |
| `metrics` | Refactor de `top5_final.py` a módulo: `price_return`, benchmark por celda símbolo×mes×lado (mediana, n≥20), **alpha**, t-stat, payoff, wr, conc, ruin, lev, marg, dur, buckets mensuales. Escribe `trader_metrics`. | no | Métrica central intacta: alpha = retorno des-apalancado − mediana de celda. |
| `detect` | Batería de flags (sección Criterios). Escribe `flags` en `trader_metrics`. | no | |
| `trend` | Diff vs snapshot(s) previo(s): Δrank, Δalpha, altas/bajas, regla de-copy (2 snapshots consecutivos alpha<0 → fuera), `style_drift`. Calcula `trend_bonus`. Produce `diff.json`. | no | Corrida #1: solo intra-snapshot (pendiente de alpha mensual). |
| `rank` | Score + tiers + pesos → `roster.json`. | no | |
| `report` | `TOP_YYYY-MM.md` con roster, cambios ▲▼, excluidos notables con motivo, caveats fijos. | no | |
| `council` | No es código: lo orquesta el agente vía skill `adversarial-review` cuando el gate lo pide. | LLMs | |

`pipeline.py analyze` = flatten+ingest+metrics+detect+trend+rank+report en una pasada (segundos, sin red).

## Criterios de detección (stage `detect`)

Cada criterio emite un flag por trader × snapshot. Umbrales calibrados con los casos reales de la auditoría 2026-08-25.

### Descalificantes (fuera del roster)

| flag | señal | caso de referencia |
|---|---|---|
| `loss_hider` | WR cerrado >92% con n≥20, o cero perdedoras con n≥20 (sin condición de wr — un break-even no exime), o (payoff <0.5 y mdd >35) | GGbond哦 (98.5% wr, mdd 50.5), Una躺平记_ (0 perdedoras/174) |
| `open_loss_divergence` | *(si hay data de abiertas)* unrealized muy negativo vs realized | detección directa del anterior |
| `lottery` | el MEJOR trade (top-1) >30% del PnL total — el umbral auditado de `top5_final.py`. (Top-3>30 fue descartado en revisión adversarial: descalificaba a 5 de los 6 supervivientes auditados, 梭哈 top-3=59.4% pero top-1=26.1%.) | 龟兔赛跑985 (96.9% en 1 trade a 145x) |
| `roi_artifact` | ROI de portada alto con alpha ≤0 o t<2 | VickyKaushal (+5,436% ROI, alpha −0.72%) |
| `ruin_risk` | lev p90 >25x, o peor pérdida × lev mediano < −500% del margen | 牛熊摆渡人 (−1173%) |
| `not_copyable` | marg mediano <$50 o duración mediana <30 min | Scalper King ($50), 秋高看山势 ($41) |
| `insufficient` | n<60, o <40 con alpha, o <3 meses activo | |
| `no_alpha` | t-stat <2.5 | winner's curse: comunicar "espera la mitad del alpha mostrado" |

### Advertencias (penalizan score, no expulsan)

| flag | señal |
|---|---|
| `alpha_decay` | alpha H2<H1 intra-snapshot, o alpha del snapshot actual < alpha del snapshot previo (lo aplica `trend`) |
| `inactive` | sin cierres en 30 días |
| `style_drift` | lev mediano o marg mediano cambia >2× vs snapshot previo |
| `regime_onesided` | alpha positivo solo en un sub-régimen de la ventana |
| `mdd_high` | mdd 35–60 |

⚠️ **Escala de mdd (Binance): PORCENTUAL, no fraccional** — mediana ~30.15, máx ~102.7
(GGbond哦=50.5, 牛熊摆渡人=74.85). Es la "Trampa 5" de `SKILL.v3.md`; los umbrales 35/60 son
en esa escala. Un test de regresión debe assertar la escala (mediana del snapshot ∈ [10,60]).

### Regla de de-copy (vive en `trend`)
Dos snapshots consecutivos con alpha negativo → fuera del roster, sin importar otros flags.

## Scoring, tiers y pesos (stage `rank`)

```
score = 0.40·t_stat + 0.25·alpha·100 + 0.20·payoff + 0.15·trend_bonus
        − 10% del score por cada flag de advertencia
```

`trend_bonus`: pendiente normalizada del alpha mensual (intra-snapshot en corrida #1; combinada con diff entre snapshots desde la #2).

El roster (tiers A+B) se capea en **5 traders** — los 5 mejores por score entre los que
sobreviven los descalificantes; el resto va a W.

| tier | criterio | peso |
|---|---|---|
| A — Copiar | dentro del top-5 por score, 0 warnings, ≥2 snapshots visto (o n>300 en el 1º) | ~70% del total, proporcional al score |
| B — Peso mínimo | pasa filtros, 1–2 warnings o historial corto | ~30%, cap 10% por trader |
| W — Watchlist | prometedor pero insufficient o señales mixtas | 0% |
| X — Excluido | flag descalificante | 0%, motivo registrado |

Pesos redondeados a 5%.

Casos borde: si el roster es **todo tier B** (típico de la corrida #1), el cap del 10% se
respeta igual y el remanente queda **sin asignar** (la suma puede ser <1.0; el reporte lo
dice) — jamás se vuelca el exceso sobre un solo trader. Solo entran al roster scores >0.
El criterio "n>300" para tier A aplica únicamente cuando el pipeline tiene un solo snapshot
(primera corrida); después, tier A exige ≥2 snapshots visto. `insufficient` como único flag
descalificante va a tier **W** (no X): W = novatos/prometedores, X = fraudes.

## Formatos de salida

### roster.json
```json
{ "generated": "YYYY-MM-DD", "snapshot": "YYYY-MM-DD", "engine": "v1.0",
  "traders": [
    { "exchange": "binance", "portfolio_id": "…", "nick": "…",
      "tier": "A", "weight": 0.25, "score": 4.12,
      "metrics": { "alpha": 0.016, "t": 6.11, "payoff": 1.04, "lev_med": 5, "mdd": 20 },
      "warnings": ["alpha_decay"],
      "trend": { "rank_prev": 2, "rank_now": 1, "alpha_delta": -0.002 } } ],
  "removed": [ { "nick": "…", "reason": "2 snapshots alpha<0" } ] }
```

### TOP_YYYY-MM.md
Tabla del roster con métricas · **Cambios vs corrida anterior** (▲▼, altas/bajas con motivo) ·
**Excluidos notables** (qué rechazó el motor y por qué) · **Caveats fijos** (ventana de régimen
única, survivorship del top-600, winner's curse ≈ mitad del alpha, solo posiciones cerradas
visibles salvo que el spike funcione).

### diff.json (input del gate)
Altas/bajas por tier, Δweight por titular, flags nuevos sobre titulares, y un booleano
`material` calculado por el propio stage.

## Skill orquestadora — `/copy-trading-refresh`

Skill personal en una skill de agente (fuera del repo). Runbook para el agente:

1. `cd ~/Projects/trading/copy-trading-intel`
2. `python3 pipeline.py scrape` — si falla a mitad, re-correr (resumable). Un trader cuyo historial falló por red NO se marca como hecho (se reintenta en el resume).
3. `python3 pipeline.py analyze` — valida **ANTES de ingerir** (desde los CSV): snapshot dir existente y no vacío, y n_traders/n_posiciones dentro de ±50% del snapshot previo (un exchange con snapshot previo que hoy no trae CSV también falla). Si la validación falla → exit 2 **sin tocar la DB**; reportar al operador, `--force` solo con su aprobación. `analyze` NUNCA escribe `analysis/roster.json` (el latest).
4. Leer `analysis/runs/<hoy>/diff.json`.
5. **Gate**: `material == true` → lanzar consejo (skill `adversarial-review`: Fable, Kimi, GLM; cada uno recibe diff + CSVs + pregunta concreta, con mandato de refutar y re-derivar números). `material == false` → publicar directo (paso 7).
6. Merge de veredictos del consejo al `TOP_*.md` (columna confirma/objeta). Si el consejo objeta una promoción a tier A, **no publicar** ese cambio sin decisión del operador.
7. **Publicar**: `python3 pipeline.py publish --date <hoy>` — copia el roster de la corrida a `analysis/roster.json`. Es el ÚNICO paso que toca el latest, y solo se ejecuta tras pasar el gate (o tras la decisión del operador si hubo objeciones).
8. Presentar al operador: tabla, ▲▼, altas/bajas, objeciones del consejo si las hubo.

### Cambio material (dispara consejo) — cualquiera de:
- Alta o baja en tier A.
- **Cualquier titular (A o B) que sale del roster** (cae a W/X o desaparece del universo).
- Flag descalificante nuevo sobre un titular del roster.
- Peso de un titular se mueve >10 puntos (una salida cuenta como prev→0).
- Primera corrida contra un universo nuevo (p. ej. nuevo exchange).

El matching titular↔corrida se hace por **`portfolio_id`** (estable), nunca por nick
(renombrable).

## Spike incluido en la implementación

Probar endpoints de posiciones **abiertas**:
- Binance: buscar `position/current` (o similar) en la familia `/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/`.
- Phemex: `position/current/v2` (confirmado que existe en SKILL.v3).

Si funciona → `open_positions` se llena y `open_loss_divergence` es medición directa.
Si no → el proxy WR/mdd queda como titular. El resultado del spike se documenta en el SKILL del proyecto.

## Manejo de errores

- Scrape interrumpido → resumable dentro del snapshot del día.
- Endpoint roto (Binance rota APIs sin aviso) → el stage falla ruidoso con HTTP status; la skill reporta al operador en lugar de publicar roster con data parcial.
- `analyze` nunca toca red; siempre reproducible desde la capa cruda.

## Fuera de alcance (YAGNI explícito)

- Ejecución automática por cron (diseñado portable al VPS, pero no se instala ahora).
- Integración directa con el mirror-bot (el operador conecta el roster a mano).
- Más exchanges que Binance + Phemex.
- Dashboard web (el reporte es Markdown).
- DuckDB / cualquier dependencia fuera del stdlib de Python.

## Testing

- Unit tests por stage con fixtures pequeñas (CSV sintéticos con casos conocidos: un loss_hider fabricado, un lottery, un trader limpio) — los detectores deben flaggear exactamente lo esperado.
- Test de regresión del motor: correr `metrics`+`detect`+`rank` contra el snapshot 2026-08-25 existente y verificar que reproduce el Top 5 y los excluidos conocidos (VickyKaushal, GGbond哦, etc.).
- Test de idempotencia de `ingest` (doble ingest = mismo estado).
- Test de `trend` con dos snapshots sintéticos (regla de-copy, style_drift).
