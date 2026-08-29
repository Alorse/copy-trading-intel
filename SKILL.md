---
name: copy-trading-intel
version: 3.0.0
author: Alfredo Ortegón Sepúlveda — con asistencia de agentes LLM y auditoría adversarial
license: MIT
description: "Scrape Phemex+Binance copy-trading public data for patterns. v3: hallazgos corregidos tras auditoría."
---

> **Versión 3.0.0 — vigente.** Reemplaza a `SKILL.v2.md`, que conservamos como registro:
> contiene seis afirmaciones que la auditoría del 2026-08-25 demostró falsas contra su propia
> data. La tabla "Lo que v2 afirma y la data desmiente" (más abajo) es el diff entre ambas.
>
> Todo lo de aquí es reproducible con los scripts de `analysis/` sobre un snapshot propio.
> Evidencia completa en `analysis/FINDINGS_v2.md`, `analysis/RULES.md` y `analysis/TOP5.md`.

# copy-trading-intel

## When to Use
- Analizar copy-trading público de Phemex o Binance (traders, PnL, mejores pares).
- Buscar/validar patrones para una estrategia mono-par.
- Seleccionar traders a copiar (ver `analysis/TOP5.md`).

## Endpoints Phemex (públicos, GET, sin auth)

⚠️ **Usar `api.phemex.com`** — `api10.phemex.com` devuelve 403 (CloudFront) desde algunos hosts.
Headers: `User-Agent` browser, `Origin: https://phemex.com`, `Referer: https://phemex.com/`, `Accept: application/json`.

- **Lista de traders:** `GET /phemex-lb/public/data/v3/user/recommend?hideFullyCopied=false&keyword=&pageNum=1&pageSize=50&showChart=false&sortBy=PnlRate30d`
  - `data.rows[]`: `userId`, `nickName`, `pnlRate30d`, `pnl30d`, `tradeWinRate30d`, `mdd30d`, `aum`, `followerCount`, **`showPosition`** (true = historial visible → único escrapeable).
- **Posiciones cerradas:** `GET /phemex-lb/public/data/position/closed/v2?pageNum=1&pageSize=100&userId=<id>`
  - `data.rows[]`: `symbol`, `side`, `size`, `openPositionVal`, `margin`, `roi`, `closedPnl`, `realizedPnl` (**neto**), `openedTime`/`updatedTime` (ms), `fundingFee`, `exchangeFee`. Paginar hasta `rows < pageSize`.
  - ✅ Verificado: `realizedPnl = closedPnl − exchangeFee − fundingFee`, exacto.
- Otros: `/phemex-lb/public/data/v3/user/symbol-metric`, `user/pnl-chart`, `user/pnl-rate-chart`, `position/current/v2`, `v3/user/leaders`.
- **Posiciones ABIERTAS (sonda 2026-08-28):** `GET /phemex-lb/public/data/position/current/v2?userId=<id>` — ✅ **DISPONIBLE** (`code:0`, `data.total`, `data.rows[]`).
  - Campos: `symbol`, `side` (Buy/Sell), `posSide` (Long/Short), `size`, `value` (notional), `positionMargin`, `avgEntryPrice`, `leverage`, `liquidationPrice`, `realizedPnl`, `positionId`, `transactTime`.
  - ⚠️ **No trae PnL no realizado ni mark price** → `open_loss_divergence` no se puede calcular sin un feed de precios. Por eso NO está integrado en el pipeline v1 (que además solo rankea Binance).

## Endpoints Binance (públicos, POST JSON, sin auth)

Headers: `User-Agent` browser, `Content-Type: application/json`, `clienttype: web`, `Origin`/`Referer` binance.com.

- **Lista de portfolios:** `POST /bapi/futures/v1/friendly/future/copy-trade/home-page/query-list`
  - Body: `{"pageNumber":1,"pageSize":30,"timeRange":"90D","dataType":"ROI","favoriteOnly":false,"hideFull":true,"nickname":"","order":"DESC","userAsset":0,"portfolioType":"PUBLIC"}`
  - ⚠️ pageSize se ignora (cap 30/página). `total` ~8,520 portfolios.
- **Historial de posiciones:** `POST /bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history`
  - Body: `{"portfolioId":"<leadPortfolioId>","pageNumber":1,"pageSize":50}`
  - ⚠️ La variante `/public/` devuelve 0 rows — usar `/friendly/`.
  - ⚠️ **Solo devuelve posiciones CERRADAS.** Las abiertas (y sus pérdidas latentes) son invisibles. Ver "Trampa 1".
  - ✖ **Posiciones ABIERTAS: verificado NO disponible el 2026-08-28.** Sonda `scripts/probe_open_positions.py` sobre `/friendly/future/copy-trade/lead-portfolio/{positions,position-list,current-position,open-positions}` con `portfolioId` real: **HTTP 404 en los 4 candidatos** (con y sin paginación). No hay endpoint público de posiciones abiertas por lead-trader.
  - ✅ `closingPnl` es **NETO** de fees. Verificado sobre 96,994 cierres completos: residuo contra el PnL de precio = **−7.85 bps del notional**, 93.7% negativo (≈ taker ida y vuelta). Fees ≈ **8 bps por round-trip**.

## Scripts

- `scripts/scrape_positions.py` — Phemex (resumable).
- `scripts/scrape_binance.py` — Binance (resumable).
- `analysis/flatten.py` — **empieza por aquí.** Aplana los `.jsonl` anidados a CSV planos. Sin red, ~10s.
- `analysis/*.py` — 14 scripts que reproducen cada número de `FINDINGS_v2.md` y `RULES.md`.
- `pipeline.py` — pipeline permanente (ver `docs/specs/2026-08-28-copy-trading-refresh-design.md`). Runbook de invocación: `docs/specs/2026-08-28-copy-trading-refresh-design.md`.

## Dataset (data/) — snapshot 2026-08-25

- `positions_all.jsonl` — Phemex: **192 traders** (no 196), 7,467 posiciones.
- `binance_positions.jsonl` — Binance: 594 portfolios con posiciones (600 líneas), 108,616 posiciones.
- `analysis/ohlc/` — velas de BTCUSDT: `btcusdt_1h.csv` (ventana del dataset) y `btcusdt_1h_long.csv` (2019-2026, para walk-forward).

⚠️ **RANGO TEMPORAL REAL: 5 MESES, NO 20.** v2 dice "dic-2024→ago-2026". **Cero** posiciones
cerraron antes de abril 2026. Cierres por mes: abr 996 · may 12,171 · jun 21,751 · jul 29,417 ·
ago 43,477. El rango largo de v2 sale de fechas de *apertura* de unos pocos swings largos.
**Hay un solo ciclo de régimen**: crash may–jun, pump jul–ago (BTC +25.8% en 7 semanas).
No hay régimen lateral ni bajista prolongado. Todo claim de "estabilidad temporal" es, como
máximo, "consistencia dentro de un ciclo".

---

# Hallazgos corregidos (2026-08-25)

## Lo que v2 afirma y la data desmiente

| claim de v2 | realidad verificada |
|---|---|
| "XRP la excepción: 64 traders, +38k **distribuido**" | DugEFresh = **91.3%** del PnL; mediana por trader **−1.5**; ganan 27/64 |
| "12-24h pierde **SIEMPRE** (XRP, BTC, ETH)" | Es el **mejor** bucket en Phemex-XRP (+41.1k) y Binance-XRP (+5.0k). Solo pierde en BTC/ETH |
| "La élite **flippea con el régimen**" | El lado coincide con la tendencia (MA200h) en **50.9%** — moneda al aire. El mix de lado apenas se mueve: 48→47→48→42% |
| "shorts BTC +235k con longs −186k" | Son **dos meses distintos** empalmados: +235k es mayo, −186k es junio |
| "**6-20x** concentra el PnL; >50x neutral" | Artefacto de rankear por ROI, que premia leverage por aritmética. Majors 30x, resto **10x** (v2 dice 5x) |
| "dic-2024 → ago-2026" | 5 meses reales (ver arriba) |

## Lo que sí se sostiene de v2

- Tokenized stocks de semiconductores concentran PnL real y distribuido (SKHYNIX, MU, SNDK).
- BTC es el par menos concentrado: 437 traders, top-1 solo 15.8% del PnL.
- La masa de Phemex pierde consistente (expectancy −190 USD/trade).
- El "mejor par" de un trader suele ser lotería: revisar concentración siempre.

## Hallazgos nuevos

**H1 — La habilidad SÍ persiste, pero solo medida sobre el historial multi-par completo.**
Split por calendario, retorno neto, demean por símbolo×lado×mitad: **rho = +0.36 a +0.42, p=0.0001**.
Dentro de un solo par la fiabilidad del estimador es **~0.13** — puro ruido. **Nunca rankees a un
trader por sus operaciones de un par.**

**H2 — Seleccionar élite compra consistencia, no retorno medio.** Tercil top vs bottom en BTC
out-of-sample: mediana +0.277% vs −0.138% (MWU z=+8.28), pero **media +0.261% vs +0.284%
(p=0.881)**. Aciertan más seguido con ganancias más chicas.

**H3 — Una fila NO es una operación atómica.** Contrastando `avgCost` contra la vela de 1h de su
apertura: 13.4% cae fuera del rango, y esas tienen duración mediana **54.2h vs 3.8h** y **42.1%
de cierres parciales vs 5.2%**. Son agregados de scale-ins/scale-outs. Todo "win rate por fila"
mide la política de cierre parcial tanto como el acierto.

**H4 — El leverage alto es riesgo de ruina, no gestión.** % de posiciones que consumieron >80%
del margen: ≤10x **2.4%** · 11-25x **5.7%** · 26-60x **18.6%** · >60x **46.7%**. El MAE mediano
es ~0.7% en todos los tramos: el apalancado no arriesga menos por operación.

**H5 — Los stops fijos restan.** Walk-forward 2019-2026 (7 años, 3 ciclos): ningún nivel de stop
mejora el retorno; uno de 5% es peor en 6 de 8 años. **Esto invalida el "SL temprano + trailing"
que recomienda v2.** El control de riesgo sale del leverage (H4), no de los stops. Un stop muy
ajustado (2%) sí baja el drawdown de 55% a 43%, pagando retorno: es un intercambio, no una mejora.

**H6 — Entrar por momentum NO es un edge.** La regla "long con momentum fuerte + sobre MA200h"
parecía funcionar dentro del dataset. En walk-forward 2019-2026: **p=0.244 contra entradas
aleatorias**, equity ×5.59 contra **×7.72 de comprar y aguantar**, y +0.966%/op en años alcistas
de BTC contra **−0.322% en los bajistas**. Es beta direccional. Parecía edge porque el dataset es
un único ciclo alcista.

---

# Trampas (leer antes de cualquier análisis nuevo)

**Trampa 1 — Traders que esconden las perdedoras.** El historial solo muestra posiciones
**cerradas**. Un trader que nunca cierra una perdedora se ve perfecto y acumula pérdida no
realizada. **Firma: win rate de cerradas ≥95% junto a un `mdd` de portfolio alto.**
Ejemplos reales: GGbond哦 (98.5% aciertos, mdd 50.5%), 无人在稻 (98.9%, payoff 0.39),
Una躺平记_ (**0 perdedoras en 174 cierres**, mdd 63.7%), NepNeptune (0 en 43, mdd 42.4%).
**Encabezan cualquier ranking ingenuo.** Filtra `win_rate_cerradas ≤ 92%` y `payoff ≥ 0.5`.

**Trampa 2 — El ROI y el PnL en USD no miden habilidad.** Los tres mejores por ROI del dataset:
VickyKaushal (**+5,436%** → alpha **−0.72%**, t=−2.88), Omofun (+4,844% → alpha **−1.23%**),
龟兔赛跑985 (+2,382% → **96.9% de su PnL es UN trade** a 145x). Por PnL absoluto:
道亦有道 1994 ($551k → alpha +0.11%, t=0.46), 风雪哥 ($207k → alpha −0.16%, top-3 = 93% del PnL),
geddong ($228k → alpha **−1.50%, t=−12.11**).
**Usa alpha desapalancado contra la mediana de su mismo símbolo×mes×lado.**

**Trampa 3 — Rankear pares por rentabilidad es circular.** Desapalancando, **188/197 pares (95%)**
tienen retorno mediano por trader positivo: el dataset son los top-600 por ROI, ganan en todo.
El ranking mide supervivencia, no edge del par.

**Trampa 4 — Agregar en USD deja que el tamaño de cuenta decida.** SOL: agregado −32,229 pero
mediana por trader **+21.2**. XRP: −3,966 con mediana **+3.0**. El trader típico ganó.

**Trampa 5 — `mdd` es porcentaje, no fracción** (mediana 30.2, máx 102.7). Y el campo `win_rate`
de Binance **no** es comparable con el win rate de posiciones cerradas: mide otra ventana.

**Trampa 6 — Sesgo de supervivencia sin control.** Top-600 por ROI 90D. La selección es sobre
rendimiento reciente, lo que **atenúa** las correlaciones H1→H2 (juega a favor de H1, en contra
de cualquier nivel absoluto).

---

# Reglas operativas

- ⚠️ **NUNCA renombrar/mover/borrar este árbol mientras un scraper background esté escribiendo.**
  Hacer `process(list)` primero; esperar o matar y relanzar (son resumables). Incidente 2026-08-25:
  rename con scraper corriendo → 440 portfolios perdidos y 45 min de re-scrape. Un `cp` no salva:
  crea inodos nuevos y lo que el proceso escriba después muere con el original.
- **NO re-scrapear por defecto.** v2 decía "re-scrapear antes de cualquier análisis nuevo"; eso
  destruiría la base reproducible de `analysis/`. Re-scrapea solo cuando necesites datos **nuevos**,
  y a un directorio nuevo. Para reproducir lo existente: `python3 analysis/flatten.py`.
- **SIEMPRE revisar concentración** antes de declarar ganador a un par **o a un trader**
  (lecciones SUI/ONDO y DugEFresh). Umbral usado: top-1 trade < 30% del PnL neto.
- **Nunca rankear por ROI ni por PnL en USD.** Ver Trampa 2.
- **Nunca evaluar a un trader por un solo par.** Ver H1.
- **Declarar siempre si una cifra es neta o bruta**, y qué columna se usó.
- Cualquier regla con expectancy **< 0.10-0.15% del notional es inoperable**: se la comen las fees
  (8 bps round-trip). Por eso los scalps de <1h (+0.04%) no son viables.

# Estado del proyecto

- `analysis/FINDINGS_v2.md` — la auditoría completa, con lo que se sostiene y lo que se cae.
- `analysis/RULES.md` — reglas candidatas para BTCUSDT + resultado del walk-forward.
- `analysis/TOP5.md` — 5 traders a copiar, consenso de 4 análisis independientes, con descartados.
- **Lo que falta**: forward-test real con datos nuevos (todo lo anterior vive en un solo ciclo de
  régimen), una regla de salida validada, y observar a los candidatos en un bajista prolongado.
