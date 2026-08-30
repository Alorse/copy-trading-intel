# Exchange integration checklist — lessons paid for in Phemex, Binance and OKX

Purpose: before trusting data from a new exchange (or re-trusting an existing one after an
API change), run this checklist end to end. Every item below exists because we got it
wrong — or discovered it late — on a previous exchange. The 2026-08-29 OKX adversarial
audit (2 independent reviewers) found that most of the defects were **repeats of lessons
already learned elsewhere**, not novel failures. This doc exists to break that cycle.

Rule of thumb: **an exchange's API is guilty until proven innocent.** Every assumption
below was false somewhere.

---

## Phase 0 — Before writing any scraper

- [ ] **Enumerate the public surface first.** Don't guess endpoint paths. Three sources,
  in order: (1) official API docs (often the copy-trading leaderboard is NOT documented —
  it wasn't for OKX's web API, wasn't for Bybit's beehive), (2) load the exchange's
  copy-trading web page in a real browser and capture the XHR/fetch calls it makes
  (performance.getEntriesByType("resource") or a fetch interceptor injected before page
  scripts — see the Bybit/Bitget captures of 2026-08-29), (3) third-party sites that
  already track the exchange (e.g. arenafi.org indexes 28 exchanges and sometimes reveals
  the id scheme).
- [ ] **Check WAF/TLS fingerprinting from the VPS early.** Plain curl 403s on Akamai-fronted
  exchanges (Bybit) even with browser headers. curl_cffi with `impersonate='chrome'` passes
  for some endpoints; same-origin fetch from a real browser tab passes for the rest. Decide
  the access path BEFORE building the scraper — it changes the architecture (OKX: plain
  HTTP; Bybit: curl_cffi + prefetch fallback; Bitget: web-session tokens that expire).
- [ ] **Determine the trader identifier scheme and whether third parties can be cross-
  referenced.** OKX: `uniqueCode` (works on arenafi.org too). Binance: numeric portfolio
  id. Knowing this unlocks external cross-checks later.
- [ ] **Understand what "universe" means here.** OKX ranking = 261 SWAP lead traders,
  capped and re-sorted by the exchange. Binance = top ~600 by 90D ROI (~8,520 portfolios
  exist). The universe is ALWAYS a curated subset chosen by the exchange — survivorship
  bias is built in before we scrape anything (Trap 6).

## Phase 1 — Trust the data less than you want to

Each of these burned us at least once:

- [ ] **Where does the history truncate?** Every exchange truncates; find the mechanism
  before trusting any window:
  - Phemex: paginates fully (good).
  - Binance: nothing before the portfolio's `startTime` (Trap 7 — and 86% of portfolios
    with visible pre-start history were net-negative before going public; the deleted
    history is systematically bad).
  - OKX: silent **100-row cap** on position history — no page/limit/cursor param gets
    past it, and the cap counts closed + still-open rows combined (our first flag counted
    only closed rows and miscounted one survivor; caught by audit, not by us).
  - ⚠️ Probe with the BUSIEST trader you can find. If they return exactly N rows (58, 100,
    whatever), that's a cap, not a coincidence. Then check whether N includes open/partial
    rows.
- [ ] **Is the PnL field net or gross of fees?** Verify empirically, don't trust docs:
  reconstruct gross from prices × size and diff. Binance `closingPnl`: NET (−7.85 bps
  residual over 96,994 closes). OKX `pnl`: NET (6.5 bps median residual over 558 rows).
  Phemex: `closedPnl` gross, `realizedPnl` net — TWO fields, both exist, mixing them
  silently corrupts every sum.
- [ ] **Do the math on weird field encodings.** OKX ships leverage as "1E+1" scientific
  notation strings; empty `closeTime` on history rows means still-open (they must be
  folded into the open file, not dropped — 8 rows nearly got lost this way).
- [ ] **Which traders are invisible?** OKX: 79/261 (30%) ranked traders return
  "Trader doesn't exist" on position endpoints — the top list and the history API
  disagree. Whatever the cause, record it per-trader in the manifest; never let a failed
  fetch masquerade as "zero positions".
- [ ] **Are there OTHER endpoints with their own caps?** OKX's open-positions endpoint is
  ALSO capped at 100 — which blinded our only mdd-proxy guard exactly for the 10 traders
  with the biggest open books. Cap every endpoint separately.
- [ ] **Cross-check headline numbers against computed sums — for EVERY candidate,
  uniformly.** `ranking.pnn` vs `sum(closed pnl)`. OKX audit found we quoted the
  favorable cross-checks (Mine13: 0.99×) and skipped the damning one (01014588: $5,019
  lifetime vs $89,364 visible = a hidden −34.5% drawdown behind a 5-week window; Kunpeng
  Plan: 0.003×). A cross-check applied selectively is worse than none — it manufactures
  confidence. Print the ratio for every survivor in every report.
- [ ] **Does the exchange disclose a PnL/ROI time series the positions API doesn't give
  you?** OKX ships weekly `pnlRatios[]` in the ranking metadata — it revealed 01014588's
  hidden drawdown that NO position-based filter could see (our visible window started
  mid-drawdown). Screen it: reject drawdowns deeper than −20% that the visible window
  doesn't cover. Binance has no equivalent — check what exists, use what exists.

## Phase 2 — Analysis methodology (non-negotiable, all exchanges)

Ported from SKILL.md; these are the traps that survive every migration:

- [ ] **Alpha = de-leveraged price return − cell median (symbol × month × side), with
  LEAVE-SELF-OUT medians.** Self-inclusive medians inflate or deflate alpha when a trader
  dominates a cell (Mine13 was 6/9 rows of its CRCL cell; the fix moved alpha +4.22%→
  +5.05% — and would have moved others the other way). Report both figures. Drop cells
  with no other trader's rows. Flag >40% max cell-share. ⚠️ The Binance TOP5 was built on
  self-inclusive medians (re-audit in progress 2026-08-30) — when thick cells make the
  effect small, SAY so, don't skip the check.
- [ ] **Never rank by ROI or PnL** (Trap 2). The three best by ROI on Binance had alpha
  between −1.23% and +1.21%; one had 96.9% of PnL in a single trade at 145x.
- [ ] **Trampa 1 filter: win rate ≤92% + payoff ≥0.5 + check open/unrealized losses.**
  On OKX: 21 of 110 traders with ≥15 closes had wr >92%, six at exactly 100%. A spotless
  close record is the strongest don't-copy signal that exists. On exchanges without
  portfolio mdd (OKX), net open `upl` is the best available proxy — and it only sees
  positions open RIGHT NOW.
- [ ] **Full Binance filter set, no silent drops** (this was an audit finding): t≥2.5,
  alpha H2>0, leverage p90 ≤25x, median margin ≥$50, median duration ≥30min, multi-pair
  only, min 15 closed + min 8 alpha rows, concentration top-1 <30%. If a small universe
  forces relaxing one, document the deviation IN the deliverable — the original OKX doc
  claimed to "mirror" the Binance filters while silently dropping four of them; two of
  the five picks failed the dropped ones.
- [ ] **Rejection buckets must mean what they say.** OKX shipped with a `conc=999`
  sentinel that filed 18 net-losing traders under "concentration" — half the bucket was
  mislabeled. Separate buckets; assert buckets sum to universe.
- [ ] **Concentration guard on every winner** (top-1 trade <30% of net PnL): DugEFresh
  (Binance), KingoftheWORLD and liyuan-luo (OKX) — same 64.7% concentration, same lesson.
- [ ] **Declare net vs gross on every published number**, and which column produced it.
- [ ] **Expectancy floor**: anything <0.10–0.15% of notional is eaten by fees (≈8 bps
  round-trip). Scalps under 1h were +0.04% — inoperable.
- [ ] **Single regime caveat is universal.** Phemex/Binance/OKX datasets all turned out
  to be one regime cycle (crash May–Jun, pump Jul–Aug). "Stable across months" inside
  one cycle is NOT stability. Walk-forward against long price history (analysis/RULES.md)
  is the only fix.

## Phase 3 — Scraper engineering

- [ ] **Resumable via manifest, one line per trader, with per-endpoint status** (history
  OK / not_found / error recorded separately — a single 'ok' hides half-failures).
- [ ] **Flush order matters**: write position rows BEFORE the manifest 'done' line, and
  dedup on read by the natural key (OKX: `uniqueCode`+`subPosId`; Binance: portfolio id +
  orderId) — a kill between flush and manifest must not duplicate rows on resume. (Audit
  finding; the OKX scraper had the gap, data got lucky.)
- [ ] **Record cap flags computed the right way** (total response rows, not a subset) and
  store `n_hist` in the manifest so caps can be recomputed offline without re-scraping.
- [ ] **Polite pacing** (0.3–0.5s), retry with backoff on 429/5xx, terminal handling for
  per-trader errors (OKX 60004) so one bad trader doesn't loop the run.
- [ ] **Print universe size + ETA + progress every ~25 traders.** The OKX run was 261
  traders/7 min; Binance is 594 portfolios/hours. Knowing which one you're in changes
  whether you background it.

## Phase 4 — Verification before publishing any TOP-N

- [ ] **Adversarial audit before the deliverable is trusted** (the ventura/adversarial-
  review pattern: 2+ independent reviewers with a refute mandate). It caught, on OKX:
  the cap miscount, the selective cross-checks, the hidden drawdown, the self-inclusive
  alpha, the dropped filters, the sentinel bucket, the thin-window false positives. Cost:
  ~40–60 agent-turns. It pays for itself.
- [ ] **Independent recomputation of every published number from the raw JSONL** — not
  from the flatten CSV, not from the ranking script's own output. The orchestrator's
  first audit of the OKX TOP5 found the win-rate definition mismatch (44.4% vs 47.5%:
  price-return wins vs net-pnl wins) by recomputing from raw.
- [ ] **Tests at production thresholds.** Every OKX ranking test initially overrode
  min_cell/min_alpha_n to 1 — passing green while never exercising the shipped code
  paths. One full-rank test with default params + boundary tests per filter.
- [ ] **Fixtures must be REAL payload shapes**, not hand-written approximations. The
  Bybit fixture shipped with `metricColumns` as plain strings; the live API returns
  dicts — the parser crashed on first contact with real data and tests stayed green.
- [ ] **State window coverage per pick, honestly**: "3 months, not capped" vs "5 days,
  capped" vs "1 day". Fewer than 5 survivors is a valid outcome — never relax filters to
  fill slots (OKX post-audit: picks #3–5 are listed as transparency, not recommendations).

## Appendix — known per-exchange quirks (as of 2026-08-30)

| Exchange | History truncation | PnL fields | Access quirks | Universe |
|---|---|---|---|---|
| Phemex | none (paginates) | `closedPnl` GROSS, `realizedPnl` NET | api.phemex.com (api10 403s), browser headers | top-N recommend list |
| Binance | portfolio `startTime` (pre-history deleted, 86% of it was negative) | `closingPnl` NET | bapi POST endpoints, no auth | top-600 by 90D ROI (~8,520 exist) |
| OKX | **100-row silent cap** (closed+open combined); open endpoint also capped at 100 | `pnl` NET; weekly `pnlRatios[]` in ranking metadata (use the drawdown screen!) | plain HTTP works; 30% of ranked traders 60004 on history | 261 SWAP lead traders |
| Bybit | unknown (list endpoint blocked for curl) | n/a (list has pre-formatted metric strings) | Akamai TLS-fingerprint: curl_cffi for Hall of Fame; same-origin fetch for the full list; 7,462 traders listed | 7,462 (enumerable) |
| Bitget | **none found via the API itself** — busiest trader probed (734 closed rows) paginated cleanly to 734/734; `pageSize` capped at 20/page server-side regardless of requested value. ⚠️ A **2,000-row cap** DOES apply to hand-fetched pulls done outside `paginate_history` (observed on all 4 traders repaired by `scripts/bitget_repair_raw_rows.py` after a transport-timeout outage — one sits at exactly 2,000). **0/399 (0%)** show a protection flag on `historyList` at full-universe scale (`data/bitget_manifest.jsonl`, 2026-08-30) | `netProfit` NET by field name; price-derived de-leveraged return disagrees in SIGN with it on **10.1%** of a 455-row live sample (one row per order/fill, not per position — a scaled position's multi-fill close doesn't split PnL proportional to each fill's price delta); `returnRate/openLevel` is the adopted fallback (median 0.8pp / p90 6.0pp deviation from `netProfit/margin`, weaker than Bybit's 0.02%/0.16% but far tighter than the 10% price-basis sign-flip rate). ⚠️ **`returnRate` percent-encoding trap**: raw (hand-fetched) `historyList` rows ship it as a bare PERCENT number (`"558"` == 558%, not 5.58) — a naive `/100` skip inflates it 100x; caught by reusing `row_from_history`'s own division rather than reimplementing it. **MDD exists on ≥4 disconnected bases/windows** and none reduce to each other: leaderboard `mdd` (unknown window), 90d `cycleData.roiRows` computed peak-to-trough, 90d `cycleData.statisticsDTO.maxRetracement` (native, undisclosed formula), and `traderDetailPageV2`'s lifetime `max_retracement` (`detail_mdd`) — empirically checked against a 180d `cycleData` peak-to-trough for 36 traders and found to differ by 1-2 orders of magnitude (hundreds-to-thousands of pp vs tens-to-low-hundreds of %), not just a window difference. The drawdown screen was originally `min()` of the raw cumulative curve (a level, not a drawdown) — corrected post-audit to true peak-to-trough + all 3 disclosed MDD bases as separate hard filters (see `analysis/TOP5_BITGET.md`) | plain `curl_cffi` (`impersonate='chrome'`) works with NO auth on every endpoint (leaderboard, history, current, detail, cycleData) — supersedes the 2026-08-29 finding that the v1 web endpoints needed expiring session tokens; leaderboard's `totals` field lies (echoes page size, 50) — use `maxShowSizes`; `currentList` (open positions) is protected (code `30066`) for **24.8%** (99/399) of the full scraped universe (2026-08-30), independently of closed-history visibility, which stayed open for all of them; no verified unrealized-PnL field exists on `currentList` | 1,488 traders (live `maxShowSizes`) |
