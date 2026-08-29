# Auditoría de `copy-trading-intel` SKILL.md vs la data — 2026-08-25

Snapshot local: la raíz de este repo.
Reproducible: `flatten.py` → `phemex_positions.csv` (7,467 filas) / `binance_positions.csv` (108,616 filas).
Luego `pair_select.py`, `pair_select2.py`, `btc_behavior.py`, `persistence.py`, `style_vs_skill.py`.
No se re-scrapeó nada.

**Objetivo del usuario**: reglas concretas de entrada/salida para UN par, copiando *patrones* (no operaciones)
de traders que ya ganan. Reglas soft, no hard-rules.

## Lo que se confirma de la SKILL

| Claim | Veredicto |
|---|---|
| 7,467 pos Phemex / 196 traders | ✅ exacto |
| 108,616 pos Binance / 594 portfolios | ✅ exacto (600 líneas, 6 sin posiciones) |
| Sin DugEFresh, XRP-Phemex no es operable | ✅ DugEFresh = 91.3% del PnL, mediana/trader −1.5, 27/64 ganan |
| BTC es el par menos concentrado | ✅ top1 = 15.8%, 437 traders, mediana/trader +128 |
| XRP-Binance PnL agregado negativo | ✅ −3,966 USD en 771 pos |

## Lo que se refuta

**R1 — Contradicción interna sobre XRP.** "Hallazgos Phemex" afirma *"XRP la excepción: 64 traders,
+38k distribuido"*. No es distribuido: DugEFresh es 91.3%, la mediana por trader es −1.5 y solo
27/64 ganan. La sección posterior lo corrige pero el bullet original sigue publicado.

**R2 — "12-24h pierde SIEMPRE (todas las tablas: XRP, BTC, ETH)".** Falso.
12-24h es el MEJOR bucket en Phemex-XRP (+40.1k) y también en Binance-XRP (+5.0k). Solo pierde en BTC.
La skill sobre-corrigió su propio "sweet spot 12-24h": ninguna de las dos versiones es cierta.

**R3 — Agregar PnL en USD deja que el tamaño de cuenta decida la conclusión.**
SOL y XRP tienen PnL agregado NEGATIVO pero mediana por trader POSITIVA (+21 y +3.0):
el trader típico ganó, unas pocas cuentas enormes hundieron el agregado. Para copiar *patrones*
esa es la lectura invertida.

**R4 — Elegir par por rentabilidad dentro de este dataset es circular.**
Desapalancando (retorno de precio con signo, sin ROI-sobre-margen), **188 de 197 pares (95%)
tienen retorno mediano por trader POSITIVO**. El dataset son los top-600 por ROI 90D: ganan en todo.
El ranking de pares mide supervivencia, no edge del par.

**R5 — El ranking por ROI está contaminado por leverage.** ROI es sobre margen, así que ranquear
por ROI premia leverage alto por aritmética. Mediana de leverage: BTC/ETH 30x, altcoins 5x.
BTC domina en USD con solo 0.33% de movimiento mediano de precio. Esto también choca con el claim
de la skill "6-20x concentra el PnL; >50x es neutral a negativo".

**R6 — LO MÁS IMPORTANTE: la habilidad no persiste.** Test out-of-sample, ranqueando a cada trader
con su primera mitad de historial y midiendo la segunda (retorno de precio, desapalancado):

| métrica | rho H1→H2 (BTC, n=59 con ≥30 pos) |
|---|---|
| win rate | **+0.805** |
| payoff | +0.186 |
| **expectancy** | **+0.136** |

Lo que persiste es el win rate; lo que paga (expectancy) no. Y `corr(winrate, payoff)`
Spearman = **−0.497**: win rate y payoff son un trade-off de ESTILO (cerrar parcial / tomar
ganancia temprano), no niveles de habilidad. Confirmado en el corte por cuartiles: el cuartil
top tiene win rate 81.9% pero payoff 1.08, contra 37.9% y 1.15 del cuartil bottom — ganancia y
pérdida medianas casi idénticas (0.49%/0.41% vs 0.45%/0.39%), duración casi idéntica (4.9h vs 4.7h),
%long casi idéntico (52.5% vs 56.4%).

**Implicación para el objetivo**: "identificar traders que ganan y copiar sus patrones" no tiene
soporte en esta data. Ganar no persiste. Lo que persiste es un parámetro de estilo que por sí solo
no es rentable.

## Limitaciones que yo mismo declaro (atacar aquí)

- **L1** El test de persistencia parte el historial de CADA trader por su propia mediana, no por
  calendario. Traders distintos caen en regímenes distintos → confound de régimen.
- **L2** n=59 traders. El error estándar de Spearman es ~1/√58 ≈ 0.13, así que rho=+0.136 es ~1 SE:
  **ausencia de evidencia de persistencia, no evidencia de ausencia**. El test está subpotenciado.
- **L3** 10.9% de las filas de BTC muestran cierre parcial (|closedVolume − maxOpenInterest| > 2%).
  `avgCost`/`avgClosePrice` son promedios sobre scale-ins/scale-outs → el win rate por fila puede
  ser un artefacto de agregación, no una operación real.
- **L4** No hay OHLC en la data. Solo posiciones (entry, exit, timestamps, leverage). No se pueden
  derivar reglas de entrada técnicas sin bajar velas.
- **L5** Todo el set son supervivientes (top-600 por ROI 90D). No hay grupo de control de traders
  fracasados en Binance. Phemex sí tiene la masa perdedora y podría servir de control, pero es otro
  exchange, otro período y otro mix de pares.
- **L6** `closingPnl` es neto o bruto de fees/funding? No verificado. Si es bruto, toda expectancy
  está sobreestimada.

## Preguntas para los revisores

1. ¿R6 (la habilidad no persiste) sobrevive? ¿O L1/L2/L3 lo tumban?
2. ¿Hay un test de persistencia mejor con esta data (alineado por calendario, con más potencia)?
3. Si el edge no persiste, ¿qué SÍ es copiable? ¿Parámetros estructurales (duración, leverage,
   sizing, cross/isolated, adaptación de lado al régimen)?
4. ¿BTCUSDT es la elección correcta de par, dado que la elección por rentabilidad es circular (R4)?
5. ¿Qué reglas soft de entrada/salida se sostienen, y cuáles serían overfitting a este snapshot?
