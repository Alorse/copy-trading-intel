"""Genera el reporte humano TOP_YYYY-MM.md."""
import json, os

CAVEATS = """## Caveats fijos
- **Ventana de régimen única**: la data cubre pocos meses y un solo ciclo; \
consistencia dentro del ciclo, no estabilidad universal.
- **Survivorship**: el universo Binance es el top-600 por ROI-90D; no hay grupo \
de control de traders quebrados.
- **Winner's curse**: con cientos de candidatos filtrados, espera ~la mitad del \
alpha mostrado.
- **Solo posiciones cerradas** son visibles (salvo data de abiertas): las \
perdidas latentes de un loss-hider pueden no aparecer.
- **t-stat i.i.d.**: las alphas correlacionadas por (symbol, mes, lado) inflan \
el t ~10-15%; clusterizado, ningun caso del roster cae bajo 2.5.
"""


def _scraped(snap_dir, exchange):
    """Cuantos portfolios trajo el listado del scrape, o None si no esta."""
    if not snap_dir:
        return None
    path = os.path.join(str(snap_dir), f"{exchange}_list.json")
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path))
    except (ValueError, OSError):
        return None
    return len(data) if isinstance(data, list) else None


def _reconciliation(con, snapshot_date, exchange, snap_dir):
    """Embudo del universo: scrapeados -> con posiciones -> con metricas.
    Cada escalon se pierde traders (sin cerradas, sin alpha computable) y sin
    esta linea el reporte no deja auditar cuantos."""
    row = con.execute(
        "SELECT n_traders FROM snapshots WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange)).fetchone()
    n_met = con.execute(
        "SELECT COUNT(DISTINCT trader_id) FROM trader_metrics "
        "WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange)).fetchone()[0]
    steps = []
    scraped = _scraped(snap_dir, exchange)
    if scraped:
        steps.append(f"{scraped} portfolios scrapeados")
    if row and row["n_traders"]:
        steps.append(f"{row['n_traders']} con posiciones")
    steps.append(f"{n_met} con métricas")
    return "**Universo**: " + " → ".join(steps)


def write(con, snapshot_date, exchange, roster, diff, out_dir, snap_dir=None):
    month = snapshot_date[:7]
    path = os.path.join(str(out_dir), f"TOP_{month}.md")
    L = [f"# Roster copy-trading — {snapshot_date} ({exchange})", ""]
    L += ["| nick | tier | peso | score | roi% | alpha% | t | payoff | lev | mdd "
          "| n | n_alpha | warnings |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in roster["traders"]:
        m = t["metrics"]
        fmt = lambda x, k=2: f"{x:.{k}f}" if isinstance(x, (int, float)) else "—"
        L.append(f"| {t['nick']} | {t['tier']} | {t['weight']:.0%} | {t['score']:.2f} "
                 f"| {fmt(m.get('roi'), 1)} "
                 f"| {fmt((m['alpha'] or 0)*100)} | {fmt(m['t'])} | {fmt(m['payoff'])} "
                 f"| {fmt(m['lev_med'],0)} | {fmt(m['mdd'])} | {m['n']} "
                 f"| {m.get('n_alpha', '—')} "
                 f"| {', '.join(t['warnings']) or '—'} |")
    L += ["", _reconciliation(con, snapshot_date, exchange, snap_dir)]
    if roster.get("unallocated"):
        L.append(f"\n**Peso sin asignar: {roster['unallocated']:.0%}** "
                 f"(roster todo tier B — cap del 10% por trader)")
    L += ["", "## Cambios vs corrida anterior"]
    if diff.get("prev") is None:
        L.append("Primera corrida — sin corrida previa.")
    else:
        L.append(f"Comparado con {diff['prev']}.")
        for n in diff["added_a"]:
            L.append(f"- ▲ **{n}** entra a tier A")
        for n in diff["removed_a"]:
            L.append(f"- ▼ **{n}** sale de tier A")
        for w in diff["weight_moves"]:
            L.append(f"- ⚖ **{w['nick']}**: {w['prev']:.0%} → {w['now']:.0%}")
        for d in diff["new_disqualified_incumbents"]:
            L.append(f"- ✖ **{d['nick']}** descalificado: {', '.join(d['flags'])}")
        if len(L[-1]) and L[-1].startswith("Comparado"):
            L.append("Sin cambios materiales.")
    for r in roster.get("removed", []):
        L.append(f"- ✖ **{r['nick']}** fuera del roster: {r['reason']}")
    L += ["", "## Excluidos notables"]
    rows = con.execute(
        "SELECT tm.nick, ts.roi, tm.flags FROM trader_metrics tm "
        "LEFT JOIN trader_snapshot ts ON ts.snapshot_date=tm.snapshot_date "
        "AND ts.exchange=tm.exchange AND ts.trader_id=tm.trader_id "
        "WHERE tm.snapshot_date=? AND tm.exchange=? AND tm.tier='X' "
        "ORDER BY ts.roi DESC LIMIT 10", (snapshot_date, exchange)).fetchall()
    for r in rows:
        roi = f"{r['roi']:.0f}%" if r['roi'] is not None else "—"
        L.append(f"- **{r['nick']}** (ROI portada {roi}): "
                 f"{', '.join(json.loads(r['flags'] or '[]'))}")
    L += ["", CAVEATS]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
