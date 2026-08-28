# Reglas soft para BTCUSDT — derivadas y validadas fuera de muestra

> ## ⚠️ LEE ESTO ANTES QUE NADA
>
> **Estas NO son reglas validadas. Son hipótesis con evidencia preliminar.**
>
> El dataset **no** cubre dic-2024 → ago-2026 como afirma la SKILL. **Cero** posiciones cerraron
> antes de abril 2026: las 107,812 se cierran en una ventana de **5 meses** (abr–ago 2026), con
> el 40% solo en agosto. El rango largo de la SKILL sale de fechas de *apertura* de unos pocos
> swings largos.
>
> Por tanto mis "dos períodos de calendario" **no son dos muestras independientes**. Son las dos
> fases de un mismo ciclo:
>
> | | P1 | P2 |
> |---|---|---|
> | apertura mediana | 5-jun-2026 | 3-ago-2026 |
> | ventana real | ~mayo–junio (crash) | **7 semanas** (jul–ago) |
> | movimiento de BTC | +2.6% | **+25.8%** |
>
> Validar "long con momentum fuerte" en un tramo de +25.8% es casi tautológico. **No hay ningún
> régimen lateral ni bajista prolongado en los datos.** Que R-1 aguante también en P1 (que
> contiene el crash) es lo único que la salva de ser pura beta — y es una base delgada.
>
> **Trátalas como candidatas a forward-test, no como reglas listas para arriesgar capital.**


Todo lo de aquí se fijó mirando **solo el período 1** (hasta 2026-07-06) y se evaluó en el
**período 2**. Métrica: retorno neto sobre notional (`closing_pnl/notional`, fees incluidos),
peso igual por posición. Scripts: `entry_rules.py`, `exit_rules.py`, `rule_backtest.py`.

**Qué son estas reglas.** Son un filtro de contexto, no un sistema de trading. Dicen *cuándo
las condiciones se parecen a aquellas en las que este universo de traders ganó*, no *qué
operación abrir*. No hay señal de entrada precisa ni objetivo de precio.

---

## R-1 · Entrada: solo long, y solo en tendencia fuerte ✅ validada

Abrir long únicamente cuando **las tres** se cumplen a la vez, medidas sobre velas de 1h:

| condición | umbral (fijado en P1) |
|---|---|
| momentum 24h | > +0.55% |
| momentum 72h | > +0.63% |
| precio vs MA200h | > −0.02% (es decir, por encima de la media) |

| | filtradas | resto | p |
|---|---|---|---|
| P1 Long | **+0.492%** | −0.099% | 0.0092 |
| P2 Long | **+1.048%** | +0.539% | 0.0004 |

Funciona en ambos períodos, **incluido el crash de mayo-junio que cae en P1** — por eso no es
simplemente "el precio subió". El efecto aparece además en cinco ventanas independientes
(4h, 24h, 72h, distancia a MA200h, posición en el rango de 7 días), todas en la misma dirección.

⚠️ **No hay regla de short validada.** El mismo filtro aplicado a shorts no aporta nada
(p=0.62 en P1, p=0.51 en P2). El espejo correcto sería exigir momentum negativo, y eso no se
probó. Mientras no se pruebe, la regla es long-only.

⚠️ **Los umbrales deben ser ABSOLUTOS, no relativos.** Probé la misma regla con percentiles
móviles (momentum en el percentil ≥67 de los últimos 30 días): el efecto **desaparece en P1**
(p=0.534) y solo sobrevive en P2 (p=0.0002). Con umbrales absolutos aguanta en ambos (p=0.0092
y p=0.0004). Lectura: el edge está en la fuerza **absoluta** de la tendencia — estar en el
tercil alto de un mes malo no sirve. La consecuencia práctica es que en régimen bajista la
regla casi no dispara, y eso es precisamente lo que la hace funcionar. Contrapartida: los
umbrales llevan información sobre el régimen de volatilidad de BTC y habría que recalibrarlos
si ese régimen cambia materialmente.

⚠️ El tercil **medio** de tendencia es consistentemente el peor (z entre −2.8 y −4.2), peor
incluso que el tercil bajo. El enemigo es el **rango sin dirección**, no la caída.

## R-2 · Leverage ≤ 25x ✅ validada (para sobrevivir, no para rendir)

| leverage | MAE mediana | % que consumió >80% del margen |
|---|---|---|
| ≤10x | 0.78% | 2.4% |
| 11-25x | 0.79% | **5.7%** |
| 26-60x | 0.71% | 18.6% |
| >60x | 0.63% | **46.7%** |

El MAE mediano es prácticamente idéntico en todos los tramos (~0.7%): el leverage alto **no**
viene con mejor gestión de riesgo, solo multiplica la probabilidad de ruina. Casi la mitad de
las posiciones a >60x rozaron la liquidación.

Coherente con el comportamiento observado: los traders élite usan **25x** mediana; el resto, **50x**.

Esta regla **no mejora el retorno medio por operación** — es puro control de ruina. Y es la que
hace viable a R-3.

## R-3 · Sin stop-loss fijo ✅ validada (contraintuitiva)

| stop | media P2 | vs sin stop |
|---|---|---|
| **sin stop** | **+0.317%** | — |
| 10.0% | +0.297% | −0.019 pp |
| 5.0% | +0.255% | −0.062 pp |
| 3.0% | +0.156% | −0.161 pp |
| 2.4% | +0.111% | −0.206 pp |
| 1.0% | −0.001% | −0.318 pp |

Monotónico: **cuanto más ajustado el stop, peor el resultado**, en ambos períodos. Un stop en
2.4% preserva el 90% de las ganadoras (p90 del MAE de ganadoras = 2.38%) pero el 10% que mata,
más las recuperaciones que convierte en pérdidas realizadas, cuestan más de lo que ahorra.

Esto contradice el *"SL temprano + trailing"* que recomienda la SKILL actual.

**El control de riesgo viene de R-2 (leverage), no de stops.** Las dos reglas son un paquete:
sin stop y con 50x te liquidan; sin stop y con ≤25x, sobrevives el drawdown.

⚠️ Caveat: la simulación asume que cualquier toque del nivel cierra la posición — es el caso
pesimista. Y las posiciones observadas ya incluyen la gestión de riesgo propia de cada trader.

## R-4 · Duración mínima 1h; el dinero está en 1-3 días ✅ validada

| bucket | P1 med | P2 med | z (P2) |
|---|---|---|---|
| <1h | −0.000% | +0.041% | **−9.80** |
| 1-4h | +0.150% | +0.221% | +1.24 |
| 4-12h | +0.197% | +0.262% | +0.84 |
| 12-24h | +0.182% | +0.318% | +1.83 |
| **1-3d** | +0.415% | +0.379% | **+4.29** |
| 3-7d | +0.666% | +0.378% | +3.04 |
| >7d | +1.073% | +0.449% | +2.92 |

Los scalps de menos de 1 hora son el peor bucket y el más poblado (~25% de las posiciones).
Esto **confirma** la mitad del claim de la SKILL ("scalps <1h pierden") y **refuta** la otra
mitad ("12-24h pierde siempre" — es positivo y consistente).

MFE/MAE se mantiene en ~1.4 en todos los buckets salvo >3d (1.15): el recorrido favorable es
consistentemente ~40% mayor que el adverso.

## R-5 · Salida: el mayor margen de mejora disponible ⚠️ diagnóstico, no regla

Captura mediana del recorrido favorable (MFE): **24.7%** (p25 = −38%, p75 = 57%).
Es decir: dejan tres cuartas partes del movimiento sobre la mesa, y en el cuartil inferior
convierten un movimiento a favor en pérdida.

No derivé una regla de salida validada — **no la inventes**. Lo que dice el dato es que
existe margen, no cómo capturarlo. Requiere probar reglas de trailing contra el OHLC, que es
trabajo pendiente.

---

## Lo que NO debe llegar a las reglas

- **Cualquier cosa derivada de DugEFresh** o de XRP en Phemex: es un solo hombre (91.3% del PnL).
- **El "sweet spot 12-24h"** de la SKILL: era el bucket de DugEFresh, no un patrón.
- **Flipear el lado según el régimen**: el lado coincide con la tendencia en 50.9% de los casos
  — moneda al aire. El claim de la SKILL empalma dos meses distintos.
- **Día de la semana y hora del día**: sobreviven algún z>2 aislado, pero es multiplicidad de
  tests, no señal. No los uses.
- **Copiar el leverage de nadie**: ver R-2.
- **Seleccionar el par por rentabilidad**: 95% de los pares "ganan" en este dataset (supervivientes).
- **Cualquier objetivo de precio**: no hay nada en la data que lo soporte.

## Cómo seleccionar de quién copiar (si vas a copiar)

La habilidad **sí** persiste (rho +0.36 con controles, p=0.0001), pero solo se mide bien sobre
el **historial multi-par completo** del trader, nunca sobre sus operaciones de un solo par
(ahí la fiabilidad del estimador es ~0.13: puro ruido).

**Pero seleccionar élite en BTC compra consistencia, no retorno medio**: mediana +0.277% vs
−0.138% (z=+8.28), pero **media +0.261% vs +0.284% (p=0.881)**. Aciertan mucho más seguido con
ganancias más chicas. Sirve para la forma de la curva de equity y para sizing, no es alpha gratis.

## Qué falta antes de arriesgar dinero

1. **Forward-test — no es opcional.** Toda la evidencia vive en una ventana de 5 meses con un
   solo ciclo de régimen, sobre un snapshot de supervivientes. Sin forward-test en régimen
   lateral y bajista, estas reglas no están probadas.
2. **Una regla de salida real** (R-5 solo dice que hay margen).
3. **Costos de ejecución propios**: slippage y fees de tu cuenta, no los de ellos. Referencia
   medida: las fees de estos traders son ~**8 bps del notional** por round-trip (taker ida y
   vuelta). Ya están dentro de los retornos que reporto (`closing_pnl` es NETO, verificado sobre
   96,994 cierres completos). Implicación dura: **cualquier regla cuya expectancy sea <0.10-0.15%
   del notional es inoperable** — por eso R-4 descarta los scalps <1h (+0.04%).
4. **Un short-side validado**, o asumir long-only explícitamente.
5. **Recalibrar los umbrales de R-1 si cambia el régimen de volatilidad de BTC.** Ya verifiqué
   que expresarlos en percentiles móviles NO funciona (el efecto se cae en P1): tienen que ser
   absolutos. Eso los ata al rango de volatilidad de 2025-2026.

---

# RESULTADO DEL FORWARD-TEST (2019-2026, 61,036 velas, 6.9 años)

R-1, R-3 y R-4 se probaron como reglas de precio autónomas sobre `ohlc/btcusdt_1h_long.csv`,
que cubre tres ciclos completos incluyendo el bear de 2022 (−64%) y 2025 (−6%).
Fees de 8 bps round-trip incluidas (medidas sobre 96,994 cierres reales). Script: `forward_test.py`.

## ❌ R-1 NO SOBREVIVE — es beta direccional, no alpha

| | resultado |
|---|---|
| vs 200 simulaciones de entrada aleatoria | supera a 152/200, **p ≈ 0.244 (no significativo)** |
| equity 6.9 años | ×5.59 contra **×7.72 de comprar y aguantar** |
| drawdown máximo | 54.7% (buy & hold: 77.2%) |
| media/operación en años **alcistas** de BTC (2020, 21, 23, 24) | **+0.966%** |
| media/operación en años **bajistas** de BTC (2019, 22, 25, 26) | **−0.322%** |

Pierde dinero en **todos** los años bajistas y rinde menos que comprar y aguantar. Lo que
parecía un edge era el reflejo de haberse derivado dentro de un único ciclo alcista de 7 semanas.

**R-1 queda retirada como estrategia.** Puede seguir teniendo valor como *filtro* sobre
posiciones copiadas (el test intra-trader mostró que 67% de los traders mejoran en condiciones
filtradas contra sus propias no filtradas), pero **no es una fuente de rentabilidad por sí sola**
y no debe usarse para decidir cuándo entrar al mercado por cuenta propia.

## ✅ R-3 SOBREVIVE — los stops fijos restan, y no solo en 2026

| stop | media/op | equity | MDD |
|---|---|---|---|
| **sin stop** | **+0.485%** | **5.59** | 54.7% |
| 2% | +0.376% | 4.37 | **42.8%** |
| 3% | +0.331% | 3.23 | 56.3% |
| 5% | +0.432% | 4.77 | 59.6% |
| 8% | +0.397% | 3.74 | 56.6% |
| 12% | +0.407% | 3.79 | 54.2% |
| 20% | +0.434% | 4.14 | 59.4% |

Ningún nivel de stop mejora el retorno, en 7 años y tres regímenes. Comparado año a año, un
stop de 5% es peor en **6 de 8 años**. El resultado de la ventana de 2026 no era un artefacto.

Matiz honesto: un stop **muy ajustado (2%)** sí reduce el drawdown de 54.7% a 42.8%. Eso es un
intercambio real —pagas retorno por dormir mejor—, no una mejora. Elígelo con los ojos abiertos.

## ✅ R-2 no necesita forward-test

Es aritmética, no una hipótesis de mercado: el leverage multiplica el MAE contra el margen.
Con MAE mediano de ~0.7% igual en todos los tramos, pasar de 25x a 60x multiplica por 3 la
probabilidad de tocar liquidación (5.7% → 18.6% → 46.7% a >60x). Se sostiene sola.

## ~ R-4 parcialmente confirmada

Sensibilidad al holding en 7 años (media por operación): 24h +0.128%, 48h +0.286%,
**72h +0.485%**, 120h +0.816% pero con mediana **−0.313%** (unos pocos aciertos grandes).
Los holdings cortos rinden peor, consistente con lo observado en la data de copy-trading.
El 72h (≈3 días) es el mejor punto por media con mediana positiva.

---

## Qué queda en pie, honestamente

1. **No hay regla de entrada validada.** R-1 murió en el forward-test. Entrar por momentum es
   trend-following con peor rendimiento que comprar y aguantar.
2. **Sí hay reglas de gestión validadas**: leverage ≤25x (R-2) y no usar stops fijos (R-3),
   más holdings de días y no de minutos (R-4).
3. **La habilidad de los traders sí persiste** (rho +0.36) — pero medida sobre su historial
   multi-par completo, y compra consistencia más que retorno medio.

La lectura práctica: **el valor no está en encontrar cuándo entrar, sino en a quién copiar y
cómo gestionar la posición una vez dentro.**
