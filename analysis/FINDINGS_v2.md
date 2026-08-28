# Auditoría `copy-trading-intel` — v2, tras revisión adversarial

Reemplaza a `FINDINGS.md`. Cuatro revisores independientes (Fable, Kimi, Qwen, GLM) más
verificación propia de primera mano. **Todo número aquí fue re-derivado por mí después de
que un revisor lo señalara** — no se relata ningún hallazgo ajeno como hecho.

Snapshot: `~/Projects/trading/copy-trading-intel`. No se re-scrapeó nada.
Único download autorizado: OHLC de BTCUSDT (`ohlc/`, vía `fetch_ohlc.py`).

---

## Correcciones a mi propia v1

**C1 — R6 estaba mal planteado y su titular era insostenible.**
v1 decía *"la habilidad no persiste"* con rho(expectancy)=+0.136 sobre BTC.
Fable y Kimi calcularon **por separado** el techo de ruido de ese test: **0.13 / 0.137**.
Es decir: con persistencia PERFECTA, ese test habría dado ~0.13. Midió su propio ruido.
Yo declaré la limitación (L2) y aun así titulé en contra de ella — exactamente el sesgo
que le achacaba a la SKILL.

**C2 — La persistencia SÍ existe, medida sobre el historial completo.**
Verificado por mí, implementación propia, split por calendario, retorno NETO:

| test agrupado (todos los símbolos) | n | rho | IC 95% | p |
|---|---|---|---|---|
| crudo | 193 | +0.422 | [+0.281, +0.549] | 0.0001 |
| **demean símbolo × lado × mitad** | 190 | **+0.361** | [+0.213, +0.497] | 0.0001 |

Tras controlar por qué par, qué lado y qué período: tercil top en H1 → **+0.855%/posición**
en H2 vs **−0.116%** del tercil bottom. Y la selección por ROI-90D sesga rho **a la baja**
(Berkson), así que +0.36 es un piso. Kimi concluyó "no identificable" pero nunca corrió el
test agrupado. **Fable tenía razón; mi R6 se cae.**

**C3 — Omití la correlación que contradecía mi tesis.** Reporté corr(winrate, payoff)=−0.497
y concluí "el estilo que persiste no paga", sin reportar **corr(winrate, expectancy)=+0.554**
(verificado, n=108), que estaba impresa en la salida de mi propio script. Ambos revisores
lo detectaron. Además Kimi mostró que el −0.497 es en buena parte **identidad contable**:
si expectancy≈0 entonces payoff≈(1−wr)/wr. No era evidencia de nada.

**C4 — `closing_pnl` es NETO, no bruto.** Verificado: `closing_pnl − pnl_bruto_de_precio` =
**−7.84 bps** del notional (p25 −10.0, p75 −4.2), **93% negativo** — el orden de fees taker +
funding. L6 se cierra **al revés** de mi especulación: las expectancies no estaban infladas.

**C5 — Leverage de altcoins es 10x, no 5x.** Verificado: BTC 30x, ETH 30x, SOL 20x, XRP 20x,
resto **10x**. El 5x solo aparece en el subgrupo de pares con mayor retorno mediano.

**C6 — Phemex son 192 traders, no 196.** Marqué "196 ✅ exacto"; hay 192 `trader_id` únicos
(196 es el conteo de la lista con `showPosition`). Falso positivo de mi auditoría.

**C7 — Mi hallazgo "bajista+Long es la única celda mala" NO sobrevive out-of-sample.**
En el período 1 daba −0.033%; en el período 2 dio **+0.281%**. Cambió de signo. Lo retiro.

---

## Lo que se sostiene contra la SKILL

**R1 — El "patrón XRP" de Phemex es un solo hombre.** DugEFresh = **91.3%** del PnL
(con `realized_pnl`; 85.9% con `closed_pnl`), mediana por trader **−1.5**, ganan 27/64.
La SKILL sigue publicando *"XRP la excepción: 64 traders, +38k distribuido"* en sus
"Hallazgos Phemex" pese a corregirlo en una sección posterior. Confirmado por los 3 revisores.

**R2 — "12-24h pierde SIEMPRE (XRP, BTC, ETH)" es falso.** Es el **mejor** bucket en
Phemex-XRP (+41.1k) y en Binance-XRP (+5.0k). Solo pierde en BTC y ETH. La SKILL
sobre-corrigió su propio "sweet spot 12-24h": ninguna de sus dos versiones es cierta.

**R3 — Agregar en USD deja que el tamaño de cuenta decida.** SOL: agregado −32,229 pero
mediana por trader **+21.2**. XRP: −3,966 con mediana **+3.0**. El trader típico ganó; unas
pocas cuentas enormes hundieron el agregado.

**R4 — Elegir par por rentabilidad dentro de este dataset es circular.** Desapalancando,
**188/197 pares (95%)** tienen retorno mediano por trader positivo. Son los top-600 por ROI:
ganan en todo. El ranking mide supervivencia, no edge del par.

**R5 — El ranking por ROI premia leverage por aritmética** (ROI es sobre margen).
Corregido: majors 30x vs resto 10x, no 5x.

**R7 (nuevo) — "La élite se voltea con el régimen" no se sostiene.** El lado coincide con la
tendencia (precio vs MA200h, calculada desde el OHLC real) en **50.9%** de las posiciones BTC
— una moneda al aire. Kimi además mostró que la SKILL empalmó dos meses distintos: el
"+235k shorts" es de mayo y el "−186k longs" es de junio, y el mix de lado apenas se mueve
(48% → 47% → 48% → 42%). Que los shorts ganen en una caída es beta mecánica.

**R8 (nuevo) — Una fila NO es una operación atómica.** Contrastando `avg_cost` contra la vela
de 1h de su propia apertura: 86.6% cae dentro del rango, 13.4% no. Y las que caen fuera tienen
duración mediana **54.2h vs 3.8h** y **42.1% de cierres parciales vs 5.2%**. Son agregados de
scale-ins/scale-outs. Cualquier "win rate por fila" mide la política de cierre parcial tanto
como el acierto.

---

## R6 reformulado (la conclusión que importa)

**La habilidad persiste, pero solo es medible con el historial completo del trader.**

- Dentro de un solo par, el estimador por trader tiene fiabilidad ~0.13: no sirve para rankear.
- Agrupando todos sus pares: rho ≈ **+0.36 a +0.42**, p=0.0001, robusto a controles de
  símbolo, lado, período y fees.

**Pero — y esto no lo produjo ningún revisor — la ventaja NO se traslada a BTC como retorno
medio.** Seleccionando el tercil élite por expectancy multi-par en P1 y midiendo su BTC en P2:

| BTC out-of-sample | ELITE | RESTO | test |
|---|---|---|---|
| retorno **mediano**/pos | +0.277% | −0.138% | MWU z=**+8.28** ✅ |
| retorno **medio**/pos | +0.261% | +0.284% | permutación **p=0.881** ❌ |
| win rate | 75.0% | 40.6% | |
| payoff | 0.57 | 2.21 | |
| leverage mediana | 25x | 50x | z=−2.75 ✅ |

Seleccionar élite compra **consistencia**, no retorno medio. Aciertan mucho más seguido con
ganancias más chicas; en expectativa por posición empatan. Eso cambia la forma de la curva de
equity y habilita sizing más agresivo — no es alpha gratis.

---

**R9 (nuevo, hallado por GLM y verificado) — El rango temporal de la SKILL es falso.**
La SKILL dice "dic-2024→ago-2026". **Cero** posiciones cerraron antes de abril 2026: las 107,812
se cierran en 5 meses (abr 996, may 12,171, jun 21,751, jul 29,417, ago 43,477). El rango largo
sale de fechas de *apertura* de unos pocos swings. Consecuencia: **todo claim de estabilidad
temporal — de la SKILL y mío — se degrada a "consistencia dentro de un único ciclo de régimen"**.

**Contradicción entre revisores, resuelta.** GLM concluyó que `closing_pnl` es BRUTO; Fable y
Kimi, que es NETO. Verifiqué sobre 96,994 cierres completos: el residuo contra el PnL derivado de
precio es −7.85 bps (93.7% negativo). Si fuera bruto el residuo sería ~0. **GLM midió lo mismo
(−0.079%) e invirtió la inferencia.** Fable y Kimi tienen razón: es NETO. El ground truth de
Phemex lo confirma (`closed_pnl − fee − funding = realized_pnl`, exacto).

## Limitaciones que siguen vivas

- **Sesgo de supervivencia sin control**: los 594 portfolios son el top-600 por ROI 90D. No hay
  grupo de traders fracasados en Binance. Sesga la persistencia a la baja (bueno para C2), pero
  invalida cualquier nivel absoluto de rentabilidad.
- **Identidad de traders**: el nick no identifica humanos; una persona con varios portfolios
  infla el n efectivo.
- **Una fila ≠ una operación** (R8): todo win rate y toda duración están contaminados por la
  política de cierre parcial.
- **Una sola ventana de régimen (R9)**: 5 meses, un crash seguido de un pump. Sin régimen
  lateral ni bajista prolongado. Es la limitación más grave de todas.
- **Sin OHLC no hay reglas de entrada técnicas.** Ya se bajó el de BTC; las reglas de entrada
  siguen siendo proxies de timing, no señales validadas.
