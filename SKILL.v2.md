---
name: copy-trading-intel
description: "Scrape Phemex+Binance copy-trading public data for patterns."
version: 2.0.0
author: Alfredo Ortegón Sepúlveda — con asistencia de agentes LLM
license: MIT
---

> # ⚠️ VERSIÓN SUPERADA — SOLO REGISTRO HISTÓRICO
>
> La versión vigente es `SKILL.md` (3.0.0). Este archivo se conserva porque la auditoría
> del 2026-08-25 demostró que **seis de sus hallazgos son falsos contra su propia data**
> (rango temporal, concentración de XRP, "la élite flippea con el régimen", buckets de
> duración, efecto del leverage y la recomendación de stops fijos). El diff está en la tabla
> "Lo que v2 afirma y la data desmiente" de `SKILL.md`.
>
> **No uses estos hallazgos.** Sirven para ver qué se creía antes de auditar.

# copy-trading-intel

## When to Use
- Analizar copy-trading público de Phemex o Binance (traders, PnL, mejores pares).
- Buscar/validar patrones para la estrategia mono-par (XRP).
- Re-scrapear posiciones cerradas nuevas antes de un análisis.

Inteligencia del copy-trading público multi-exchange: qué traders hay, qué posiciones
abrieron/cerraron, en qué par ganaron, y qué patrones sobreviven al análisis.
(Sucesor de `phemex-copy-intel`, absorbido al agregar Binance.)

## Endpoints Phemex (públicos, GET, sin auth)

⚠️ **Usar `api.phemex.com`** — `api10.phemex.com` devuelve 403 (CloudFront) desde algunos hosts.
Headers: `User-Agent` browser, `Origin: https://phemex.com`, `Referer: https://phemex.com/`, `Accept: application/json`.

- **Lista de traders:** `GET /phemex-lb/public/data/v3/user/recommend?hideFullyCopied=false&keyword=&pageNum=1&pageSize=50&showChart=false&sortBy=PnlRate30d`
  - `data.rows[]`: `userId`, `nickName`, `pnlRate30d`, `pnl30d`, `tradeWinRate30d`, `mdd30d`, `aum`, `followerCount`, **`showPosition`** (true = historial visible → único escrapeable).
- **Posiciones cerradas:** `GET /phemex-lb/public/data/position/closed/v2?pageNum=1&pageSize=100&userId=<id>`
  - `data.rows[]`: `symbol`, `side`, `size`, `openPositionVal`, `margin`, `roi`, `closedPnl`, `realizedPnl` (neto), `openedTime`/`updatedTime` (ms), `fundingFee`, `exchangeFee`. Paginar hasta `rows < pageSize`.
- Otros: `/phemex-lb/public/data/v3/user/symbol-metric`, `user/pnl-chart`, `user/pnl-rate-chart`, `position/current/v2`, `v3/user/leaders` (hallados en chunks JS `phemex.com/p-114/js/chunk-676ef36f.js`, const `CT_*`).

## Endpoints Binance (públicos, POST JSON, sin auth)

Headers: `User-Agent` browser, `Content-Type: application/json`, `clienttype: web`, `Origin`/`Referer` binance.com.

- **Lista de portfolios:** `POST /bapi/futures/v1/friendly/future/copy-trade/home-page/query-list`
  - Body: `{"pageNumber":1,"pageSize":30,"timeRange":"90D","dataType":"ROI","favoriteOnly":false,"hideFull":true,"nickname":"","order":"DESC","userAsset":0,"portfolioType":"PUBLIC"}`
  - `data.list[]`: `leadPortfolioId`, `nickname`, `roi`, `pnl`, `aum`, `winRate`, `mdd`, `copierPnl`. ⚠️ pageSize se ignora (cap 30/página); paginar con `pageNumber`. `total` ~8,520 portfolios.
  - `dataType`: ROI/PNL/AUM/SHARP_RATIO/WIN_RATE; `timeRange`: 30D/90D/180D/365D — combinar amplía cobertura.
- **Historial de posiciones:** `POST /bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/position-history`
  - Body: `{"portfolioId":"<leadPortfolioId>","pageNumber":1,"pageSize":50}`
  - ⚠️ La variante `/public/` devuelve 0 rows — usar `/friendly/`.
  - `data.list[]`: `symbol`, `side`, **`leverage`**, `isolated` (Cross/Isolated), `avgCost`, `avgClosePrice`, `closingPnl`, `roi`, `maxOpenInterest`, `closedVolume`, `opened`/`closed` (ms). **Incluye leverage real y margen — superior a Phemex.**
- Otros: `lead-portfolio/order-history`, `transfer-history`, `copy-traders`, `lead-portfolio/detail`, `lead-data/positions` (mapa del repo GitHub doppelganger237/gendan).

## Scripts

- `scripts/scrape_positions.py` — Phemex: lista + historial (resumable). `python3 scripts/scrape_positions.py [--refresh]`.
- `scripts/scrape_binance.py` — Binance: lista + historial (resumable). `python3 scripts/scrape_binance.py [--refresh]`. Ampliar cobertura editando `fetch_portfolios()` (pages/timeRange/dataType).

## Dataset (data/)

Snapshot 2026-08-25:
- `positions_all.jsonl` — Phemex raw: 192 traders, 7,467 posiciones (2023-03-03 → 2026-08-25)
- `all_traders.json` — Phemex: 250 traders de la lista (196 con showPosition)
- `binance_portfolios.json` — Binance: 600 portfolios top ROI 90D (de ~8,520)
- `binance_positions.jsonl` — Binance raw: historial por portfolioId
- `best_pair_by_trader.json`, `aggregate_by_symbol.json`, `aggregate_no_lottery.json`, `pattern_focus.json`, `SUMMARY.json` — análisis Phemex 2026-08-25

## Hallazgos Binance (2026-08-25, 594 portfolios / 108,616 posiciones / dic-2024→ago-2026)

⚠️ Sesgo de muestra: top-600 portfolios por ROI 90D = **supervivientes** (no la masa). Datos con leverage y margen reales.

- **La élite gana en majors**: BTC +1.18M (7,204 pos, wr 56%), ETH +299k. Mejor par más frecuente: BTC (91×), ETH (76×).
- **Tokenized stocks semiconductores = veta real**: SOXL +411k (wr 68%), SKHYNIX +380k, SNDK +220k, MU +149k, SPCX +135k, SAMSUNG +108k (wr 82%). Distribuido entre muchos traders, no lotería.
- **SOL pierde** (−32k, 2,150 pos) — consistente con Phemex (−125k).
- Leverage mediana 10x (p90 51x, max 150x); **94% cross** (solo 6% isolated).
- **XRP en Binance PIERDE** (−4k, 760 pos): longs −12k, shorts +6.7k. wr 59% pero avg_loss 1.61× avg_win. Bucket 1-3d el peor (−14.8k); 12-24h el mejor (+5k). PnL por hora inestable.
- **Conclusión Phemex-vs-Binance**: el "patrón XRP" de Phemex era DugEFresh (outlier 50x), no el par. En la élite Binance XRP no genera edge y la masa long pierde.

### Validación patrón BTC/ETH élite (2026-08-25, deep-dive)
- **Distribución real pero top-heavy**: BTC 282/429 traders ganan (top-5 = 47% del PnL); ETH 259/414 (top-5 = 128% — el resto neto pierde). No es 1-hombre (como SUI/ONDO), pero tampoco edge uniforme.
- **El lado sigue al régimen**: long en meses alcistas (jul-ago +163k/+826k BTC), short en el crash de mayo (shorts BTC +235k con longs −186k). La élite NO tiene bias estático: flippea con el régimen. Sin contexto de régimen, "comprar y ya" no replica su edge.
- **Duración**: el dinero está en 1-3d (+255k/+178k) y 7-30d (+566k BTC). Scalps <1h y swing 12-24h pierden SIEMPRE (todas las tablas: XRP, BTC, ETH). Paradoja del "sweet spot 12-24h" del análisis Phemex inicial: era el bucket de DugEFresh, no un patrón universal.
- **Leverage**: 6-20x concentra el PnL (BTC +752k, ETH +320k); >50x es neutral a negativo (ETH −80k) — la élite no gana por apalancamiento extremo sino por gestión.
- **Estabilidad ex-agoosto**: BTC +405k sin agosto (edge no depende del pump). ETH solo +11.5k sin agosto — **el edge de ETH es mayormente EL evento de agosto**.
- **Veredicto**: BTC es el único par con edge amplio, distribuido y estable en el tiempo. ETH es un beta de BTC con muestra contaminada por el evento.

### Re-análisis Phemex sin DugEFresh (2026-08-25, filtros anti-sesgo)
Criterios: ≥10 posiciones, ≥5 traders, ≥3 ganadores independientes, top-trader <60% del PnL, mediana de trader >0.
- **Resultado: 0 de 15 pares positivos pasan.** Todos fallan por concentración (SUI top=95%, TAO 101%, XRP 111%) o mediana negativa.
- Sin DugEFresh, XRP en Phemex queda en +3.3k pero top-trader=111% del PnL y mediana de trader NEGATIVA: la mayoría que tocó XRP perdió; 2 outliers (Rocky +3.7k, Number1 +3.6k en 1 trade c/u) pintan el agregado.
- "Near-misses" menos sesgados: XLM (1.5k, 10/15 ganan, pero 24 trades y 1.3k del top) y SNDK (1k, 5/7) — muestras demasiado chicas para operar.
- La masa de Phemex pierde consistente en BTC −173k, SOL −79k, ETH −25k, ZEC −19k.
- **Conclusión**: en Phemex NO hay par operable tras quitar outliers — todo "par ganador" era 1-2 hombres. La señal útil de Phemex es la INVERSA (dónde pierde la masa). La señal positiva real está en la élite Binance (BTC).

## Hallazgos Phemex (2026-08-25)

- Expectancy de la masa: **−190 USD/trade** (wr 46%, avg_loss 2.6× avg_win). PnL neto −1.4M.
- Peores pares: BTC (−368k sin loterías), SOL (−125k), POPCAT (−602k).
- "Mejores pares" = lotería casi siempre: SUI/ONDO = 1 trader con shorts de 127-157 días; TAO, XBR = 1 trader cada uno.
- **XRP la excepción**: 64 traders, +38k distribuido.

## Patrones XRPUSDT (Phemex, 299 posiciones) — base mono-par

1. **Sesgo LONG**: longs +39.4k vs shorts −1.3k.
2. **EVENT-DRIVEN**: casi todo el PnL del pump 19-23 ago 2026 (DugEFresh: 9 trades +35.8k wr 78% en ruptura; fuera de evento wr 24% −1k).
3. **Sweet spot 12-24h** (+40k); `<1h` y `4-12h` pierden (ruido/salida a mitad).
4. **Asimetría**: avg_loss/avg_win 0.21; perdedor máx 76h; nunca martingala.
5. **Piramidar en fuerza**: size 10× solo tras confirmación del pump (~50x leverage — NO replicable).
6. Domingo único día claramente negativo; horario sin patrón estable.

### Estrategia mono-par (XRP) — validar en forward-test
- Solo rupturas/momentum confirmado, long-bias. Ride 12-24h. SL temprano + trailing.
- Sin evento activo → NO operar. ⚠️ Nunca copiar el 50x: transferible es timing + gestión a 2-3x.

## Reglas

- ⚠️ **NUNCA renombrar/mover/borrar este árbol (ni ningún dataset) mientras un scraper background esté escribiendo**: hacer `process(list)` primero, esperar o matar y relanzar (los scrapers son resumables). Incidente 2026-08-25: rename con scraper corriendo → 440 portfolios perdidos y re-scrape de 45 min. Un `cp` no salva nada: crea inodos nuevos y lo que el proceso escriba después muere con el original.
- Re-scrapear antes de cualquier análisis nuevo.
- SIEMPRE revisar concentración por trader antes de declarar "par ganador" (lección SUI/ONDO).
- ROI de copy-trading incluye leverage alto: ROI de posición ≠ edge replicable.
