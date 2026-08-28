# Top 5 de traders a copiar — consenso de 4 análisis independientes

Fuentes: Fable, Kimi, GLM y mi propio ranking, cada uno con criterio distinto.
**Todos los números de abajo los re-derivé yo**; ningún dato de un agente se reporta sin verificar.
Métrica central: **alpha = retorno de precio desapalancado − mediana de su mismo símbolo×mes×lado.**
Neutraliza las tres injusticias: tamaño de cuenta, apalancamiento y beta de régimen. Ir long en
el pump de agosto puntúa cero por construcción: solo cuenta ganarle a quien hizo lo mismo.

`closing_pnl` es NETO de fees (verificado: −7.85 bps de residuo en 96,994 cierres completos).

## El consenso

| # | trader | votos | n | alpha med | t | payoff | lev | ruina | top3 | mdd | notional |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Cooma** | GLM#1 + mío | 127 | +1.75% | **5.01** | 0.64 | 10x | **−92%** | 37% | 32 | $1,999 |
| 2 | **梭哈到世界尽头** | GLM#5 + mío | **527** | +1.60% | **6.11** | 1.04 | **5x** | −398% | 59% | 20 | $506 |
| 3 | **秋高看山势** | Fable#1 + Kimi#4 | 270 | +1.08%* | 3.14 | **1.55** | 10x | −231% | 33% | **15** | $41 |
| 4 | **牛熊摆渡人** | GLM#2 + mío | 90 | **+6.89%** | 4.15 | **1.40** | 20x | −1173% | 49% | 75 | $627 |
| 5 | **重生之我在币圈捡垃圾-** | Fable#5 + mío | 298 | +0.60%* | 3.36 | 0.82 | 6x | **−75%** | **9%** | 64 | $6,030 |

*alpha medio. "ruina" = peor pérdida de precio × leverage mediano, en % del margen.

**Ninguno apareció en 3 de las 4 listas.** Eso ya dice algo: con 5 meses de datos, el ranking
depende fuertemente del criterio. Trátalo como una cartera de apuestas correlacionadas, no como
cinco certezas.

### Por qué cada uno

**1. Cooma** — el más equilibrado. Es el único cuya peor pérdida (−92% del margen) es
sobrevivible en margen aislado, con leverage plano de 10x (no escala agresividad cuando gana),
notional de $2k (copiable de verdad) y t=5.01. GLM verificó que gana en ambos regímenes:
+1.23% en el crash, +2.22% en el pump.
*Riesgo:* payoff 0.64 — su pérdida media es 1.6× su ganancia media. Vive de acertar el 85%.

**2. 梭哈到世界尽头** — la mejor evidencia estadística: **527 posiciones**, la muestra más grande
del consenso, con t=6.11 y el leverage más conservador (5x). mdd 20%.
*Riesgo:* sus 3 mejores trades son el **59% del PnL** — la concentración más alta del Top 5.
Y su alpha decae suavemente (H1 +1.95% → H2 +1.37%): es el único con tendencia bajista.

**3. 秋高看山势** — el que **mejora mes a mes sin excepción**: +0.2 → +1.5 → +1.7 → +1.8.
El único del grupo con payoff >1.5 y win rate moderado (69%), o sea que gana por captura, no por
acumular micro-aciertos. mdd 15%, el más bajo.
*Riesgo:* notional mediano **$41**. Opera micro-caps con cuenta de $679. Su edge puede
evaporarse en slippage al escalar — es la razón por la que mi filtro lo excluyó.

**4. 牛熊摆渡人** — el alpha más alto del consenso (+6.89%) **con payoff 1.40**, combinación rara:
acierta el 80% *y* sus ganancias superan sus pérdidas. Flippea de lado según régimen. Sizing
responsable: $627 por trade en cuenta de $56k.
*Riesgo:* el más peligroso de los cinco. mdd **74.9%**, peor pérdida = **−1173% del margen**,
solo 90 posiciones y su primera cierra el 19-jun: **66 días de historial**. Peso mínimo.

**5. 重生之我在币圈捡垃圾-** — la mejor gestión de cola del grupo: peor pérdida −75% del margen y
**top-3 = solo 9% del PnL** (nadie depende menos de trades afortunados). 298 posiciones, mejora
sostenida (+0.0 → +0.4 → +0.5 → +1.3), notional $6k.
*Riesgo:* mdd **63.8%** — en algún punto de estos 5 meses habrías visto desaparecer dos tercios
de la cuenta. Y opera a 0.5h de duración mediana: sensible a latencia de copia.

## Descartados — tan importante como el Top 5

**Los tres mejores por ROI son los peores por habilidad:**

| trader | ROI | alpha real | qué lo mata |
|---|---|---|---|
| VickyKaushal | **+5,436%** | **−0.72%** (t=−2.88) | payoff 0.13; el ROI es margen diminuto, no habilidad |
| Omofun | **+4,844%** | **−1.23%** (t=−2.44) | payoff 0.07 |
| 龟兔赛跑985 | +2,382% | +1.21% | **96.9% del PnL es UN trade**, a 145x |

**Por PnL absoluto:**
- **道亦有道 1994** — $551k de PnL, 309 copiers. alpha +0.11% con **t=0.46**: sin habilidad medible.
  **15% de sus 486 posiciones consumieron >80% del margen**, leverage p90 75x.
- **风雪哥** — $207k. alpha mediano **−0.16%**, y su top-3 explica el **93.2%** del PnL.
- **geddong** — $228k en 2,000 trades. alpha **−1.50% con t=−12.11**: pierde por operación antes
  de apalancar. Es volumen con edge negativo.

**Los que esconden las pérdidas** (detectado independientemente por Fable, GLM y por mí):
**GGbond哦** (98.5% de aciertos, mdd 50.5%), **无人在稻** (98.9%, payoff 0.39), **Una躺平记_**
(0 perdedoras en 174 cierres, mdd 63.7%), **NepNeptune** (0 en 43, mdd 42.4%).
El historial solo muestra posiciones **cerradas**. Un trader que nunca cierra una perdedora se ve
perfecto y acumula pérdida no realizada. Un mdd alto con un historial de cierres impecable es
la firma. **Son los que encabezan cualquier ranking ingenuo.**

**El mejor alpha del dataset, no copiable:** **The Scalper King** — alpha mediano **+8.96%**,
t=9.50, payoff 1.55, mdd 16.6%. Pero notional mediano **$50** y peor pérdida −715% del margen.
GLM y yo llegamos a la misma conclusión por separado: si su sizing fuera copiable sería el #1.

## Confianza: baja-moderada

- **5 meses, un solo ciclo de régimen.** Ninguno ha sido observado en lateral ni en bajista
  prolongado. El demean por símbolo×mes×lado quita la beta, pero no inventa regímenes ausentes.
- **Winner's curse.** Se filtraron cientos de traders; con ~300 candidatos, unos 4-6 superarían
  t≈2.5 por puro azar. Regla práctica de Fable, que comparto: **esperar la mitad del alpha** de
  estas tablas y tomar como éxito que siga siendo positivo.
- **Supervivencia**: top-600 por ROI 90D, sin grupo de control.
- **Solo se ven posiciones cerradas**: toda pérdida latente en posiciones abiertas hoy es invisible.
  El filtro de win rate mitiga, no elimina.
- **El más frágil: 牛熊摆渡人** (66 días de historial, mdd 75%). **El de mayor severidad si falla:
  重生之我在币圈捡垃圾-** (mdd 64% ya demostrado).

**Operativa sugerida:** pesos 30/25/20/15/10 en el orden dado, no repartir parejo. Revisar el
alpha mensual contra celda (reproducible con `top5_final.py`) y descopiar a cualquiera con dos
meses seguidos de alpha negativo.
