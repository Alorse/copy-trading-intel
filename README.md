# copy-trading-intel

Análisis del copy-trading público de **Binance y Phemex**: quién gana de verdad, quién solo
lo parece, y por qué casi todo "trader top" no lo es.

Las dos plataformas exponen públicamente el historial de sus lead-traders. Este repo scrapea
esa data, la audita contra sus propios sesgos y produce un roster reproducible de candidatos a
copiar — junto con el registro de los hallazgos que se cayeron al verificarlos.

> ⚠️ **Esto no es asesoría financiera ni una recomendación de inversión.** Lee
> [DISCLAIMER.md](DISCLAIMER.md) antes de usar nada de aquí.

## La idea en una línea

**ROI y PnL en USD no miden habilidad.** Premian apalancamiento, tamaño de cuenta y suerte de
régimen. La métrica del repo es:

```
alpha = retorno de precio desapalancado − mediana de su misma celda (símbolo × mes × lado)
```

Neutraliza las tres injusticias a la vez. Ir long en el pump de agosto puntúa **cero** por
construcción: solo cuenta ganarle a todos los que hicieron exactamente lo mismo.

Los tres mejores traders por ROI del snapshot auditado, medidos así: **alpha −0.72%, −1.23% y
un 96.9% del PnL en un solo trade a 145x.**

## Qué hay aquí

| ruta | qué es |
|---|---|
| `pipeline/` + `pipeline.py` | pipeline permanente: `scrape → SQLite → métricas → flags → tendencia → roster` |
| `SKILL.md` | referencia viva: endpoints de ambos exchanges, hallazgos vigentes y las 6 trampas de esta data |
| `SKILL.v2.md` | versión anterior, **archivada**: seis de sus hallazgos resultaron falsos contra su propia data |
| `analysis/FINDINGS_v2.md` | la auditoría completa: qué se sostuvo, qué se cayó y con qué evidencia |
| `analysis/TOP5.md` | los 5 traders del consenso, con el razonamiento y los descartados |
| `analysis/RULES.md` | reglas candidatas para BTCUSDT y el resultado del walk-forward 2019-2026 |
| `analysis/*.py` | los one-offs que reproducen cada número (ver `analysis/README.md`) |
| `scripts/` | scrapers originales + la sonda de posiciones abiertas |
| `docs/specs`, `docs/plans` | diseño e implementación del pipeline (documentos históricos) |

## Requisitos

- **Python ≥ 3.11** (el motor usa `datetime.UTC`).
- **Cero dependencias de runtime**: solo stdlib (`sqlite3`, `json`, `csv`, `urllib`, `statistics`).
- `pytest` únicamente para los tests: `pip install -r requirements-dev.txt`.

## Quickstart

```bash
git clone https://github.com/Alorse/copy-trading-intel.git
cd copy-trading-intel
pytest                                    # 46 tests; los 4 de regresión son opt-in (ver abajo)

python3 pipeline.py scrape  --date $(date +%F)   # ~600 portfolios Binance + Phemex (lento, resumable)
python3 pipeline.py analyze --date $(date +%F)   # -> analysis/runs/<fecha>/{TOP_YYYY-MM.md,roster.json,diff.json}
python3 pipeline.py publish --date $(date +%F)   # único paso que toca analysis/roster.json
```

`analyze` **valida antes de ingerir**: si el snapshot trae ±50% de traders o posiciones respecto
del anterior, sale con código 2 sin tocar la base de datos. `--force` lo salta; que un exchange
con snapshot previo no traiga CSV hoy, no.

Subcomandos granulares (`metrics`, `detect`, `trend`, `rank`, `report`) en ese orden obligatorio:
`metrics` resetea flags y `trend_bonus`, así que un `rank` sin `detect` previo rankea sin flags.

## La data no está en el repo

Los dumps crudos de las APIs de Binance/Phemex **no se versionan** — no redistribuimos data de
terceros. Genera la tuya con `pipeline.py scrape`. Lo que sí está versionado son los agregados
del análisis (`data/SUMMARY.json`, `data/aggregate_*.json`) y los reportes de cada corrida.

Consecuencia: los 4 tests de `tests/test_regression.py` — los que verifican que el pipeline
reproduce el análisis auditado del 2026-08-25 — se **saltan** salvo que coloques un snapshot en
`data/snapshots/2026-08-25/`. Ese snapshot concreto ya no es re-obtenible: las APIs solo sirven
historial reciente.

## Las trampas de esta data

Seis formas documentadas de engañarse, cada una con casos reales en `SKILL.md`:

1. **Los loss-hiders.** Solo se ven posiciones **cerradas**. Quien nunca cierra una perdedora
   aparece con 98-100% de aciertos y encabeza cualquier ranking ingenuo. Un caso real del
   snapshot: **0 perdedoras en 174 cierres**, con un drawdown de portfolio del 63.7%.
2. **El ROI no mide habilidad.** Ver arriba.
3. **Rankear pares por rentabilidad es circular.** Desapalancando, 188/197 pares (95%) dan
   retorno mediano positivo: el universo son los top-600 por ROI, ganan en todo.
4. **Agregar en USD deja que decida el tamaño de cuenta.** SOL agrega −32,229 pero su mediana
   por trader es **+21.2**.
5. **`mdd` de Binance es porcentaje**, no fracción (mediana ~30). Y su `winRate` de portada no
   es comparable con el win rate de posiciones cerradas: mide otra ventana.
6. **Survivorship sin grupo de control.** El universo se selecciona por rendimiento reciente.

Y tres más, de método: una fila **no** es una operación atómica (13.4% son agregados de
scale-in/scale-out); nunca rankees a un trader por un solo par (la fiabilidad del estimador
dentro de un par es ~0.13, ruido); cualquier regla con expectancy < 0.10% del notional es
inoperable, se la comen las fees (~8 bps por round-trip).

## Límites conocidos

- **Un solo ciclo de régimen.** El snapshot auditado cubre ~5 meses: crash may-jun, pump
  jul-ago. No hay lateral ni bajista prolongado. Todo "esto es estable" significa, como mucho,
  "consistente dentro de un ciclo".
- **Winner's curse.** Con cientos de candidatos filtrados, espera ~la mitad del alpha mostrado.
- **v1 rankea solo Binance.** Phemex se scrapea e ingiere como archivo histórico, pero no entra
  a `metrics`/`rank`.
- **Falta el forward-test real** con datos nuevos, y una regla de salida validada.

## Licencia

MIT — ver [LICENSE](LICENSE).
