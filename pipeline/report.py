"""Generates the human-readable TOP_YYYY-MM.md report."""
import json, os

CAVEATS = """## Standing caveats
- **Single regime window**: the data covers few months and one cycle only; \
consistency within the cycle, not universal stability.
- **Survivorship**: the Binance universe is the top-600 by 90D ROI; there is no \
control group of blown-up traders.
- **Winner's curse**: with hundreds of candidates filtered down, expect ~half the \
alpha shown.
- **Only closed positions** are visible (barring open-position data): a \
loss-hider's latent losses may never show up.
- **i.i.d. t-stat**: alphas correlated by (symbol, month, side) inflate the t by \
~10-15%; clustered, no roster case falls below 2.5.

> **Not financial advice.** Automated output of a statistical analysis over public \
data; the flags describe the shape of a track record, not a person's conduct. \
See DISCLAIMER.md.
"""


def _scraped(snap_dir, exchange):
    """How many portfolios the scrape listing returned, or None if absent."""
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
    """Universe funnel: scraped -> with positions -> with metrics.
    Each step loses traders (no closed positions, no computable alpha) and
    without this line the report gives no way to audit how many."""
    row = con.execute(
        "SELECT n_traders FROM snapshots WHERE snapshot_date=? AND exchange=?",
        (snapshot_date, exchange)).fetchone()
    n_met = con.execute(
        "SELECT COUNT(DISTINCT trader_id) FROM trader_metrics "
        "WHERE snapshot_date=? AND exchange=?", (snapshot_date, exchange)).fetchone()[0]
    steps = []
    scraped = _scraped(snap_dir, exchange)
    if scraped:
        steps.append(f"{scraped} portfolios scraped")
    if row and row["n_traders"]:
        steps.append(f"{row['n_traders']} with positions")
    steps.append(f"{n_met} with metrics")
    return "**Universe**: " + " → ".join(steps)


def write(con, snapshot_date, exchange, roster, diff, out_dir, snap_dir=None):
    month = snapshot_date[:7]
    path = os.path.join(str(out_dir), f"TOP_{month}.md")
    L = [f"# Copy-trading roster — {snapshot_date} ({exchange})", ""]
    L += ["| nick | tier | weight | score | roi% | alpha% | t | payoff | lev | mdd "
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
        L.append(f"\n**Unallocated weight: {roster['unallocated']:.0%}** "
                 f"(roster is all tier B — 10% cap per trader)")
    L += ["", "## Changes vs previous run"]
    if diff.get("prev") is None:
        L.append("First run — no previous run.")
    else:
        L.append(f"Compared with {diff['prev']}.")
        for n in diff["added_a"]:
            L.append(f"- ▲ **{n}** enters tier A")
        for n in diff["removed_a"]:
            L.append(f"- ▼ **{n}** leaves tier A")
        for w in diff["weight_moves"]:
            L.append(f"- ⚖ **{w['nick']}**: {w['prev']:.0%} → {w['now']:.0%}")
        for d in diff["new_disqualified_incumbents"]:
            L.append(f"- ✖ **{d['nick']}** disqualified: {', '.join(d['flags'])}")
        if len(L[-1]) and L[-1].startswith("Compared"):
            L.append("No material changes.")
    for r in roster.get("removed", []):
        L.append(f"- ✖ **{r['nick']}** out of the roster: {r['reason']}")
    L += ["", "## Notable exclusions"]
    rows = con.execute(
        "SELECT tm.nick, ts.roi, tm.flags FROM trader_metrics tm "
        "LEFT JOIN trader_snapshot ts ON ts.snapshot_date=tm.snapshot_date "
        "AND ts.exchange=tm.exchange AND ts.trader_id=tm.trader_id "
        "WHERE tm.snapshot_date=? AND tm.exchange=? AND tm.tier='X' "
        "ORDER BY ts.roi DESC LIMIT 10", (snapshot_date, exchange)).fetchall()
    for r in rows:
        roi = f"{r['roi']:.0f}%" if r['roi'] is not None else "—"
        L.append(f"- **{r['nick']}** (headline ROI {roi}): "
                 f"{', '.join(json.loads(r['flags'] or '[]'))}")
    L += ["", CAVEATS]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return path
