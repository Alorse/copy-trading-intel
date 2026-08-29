## Adversarial council — 2026-08-29

Convened because `diff.material == true` (first run against this universe).
Two independent reviewers, mandate to refute: **Fable** (subagent) and **GLM** (glm-5.3 via
`ask-glm`), same brief, no shared context. Every finding below was re-derived first-hand before
being recorded here; where the reviewers disagreed, the data decided.

### Verdict on the roster

| change | council | note |
|---|---|---|
| tier A promotions | — | none to review: the roster is all tier B |
| tier A demotions | — | none |
| weight moves | — | first run, no incumbents |
| **roster composition** | **objects in part** | see below |

No reviewer objected to a tier-A promotion, because there are none. The objection is to how
much confidence the table's numbers carry for **梭哈到世界尽头** (#1 by score).

### Objection — the #1 entry rests on a self-selected window

Binance serves nothing opened before a portfolio's `startTime`. His is **2026-06-07 23:34**, so
his entire visible record starts there. Three days before this snapshot the API still returned
**527** positions for him; it now returns **286**. The cut is exact: 249/249 deleted were opened
before `startTime`, 286/286 survivors after it.

What the deleted portion contained:

- net **−$5,589**, of which the last week before going public was **−$8,292** over 114 closes
- a single LABUSDT short at **−$7,754**
- his last pre-portfolio close is **23:30**; the lead portfolio opens **23:34**

Recomputed with this engine's own formula on the pre-filter data, he is **alpha +4.21% over 6
months, decaying +7.73% → +4.32% → +3.23% → +2.96%**. The engine sees **+3.10% over 3 months**
and only the flat tail of that decay. His `alpha_decay` warning is therefore understated, not
overstated.

This is a population-wide selection effect, not a claim about him alone: of the 177 portfolios
whose pre-`startTime` history was still visible on 2026-08-25, **86% were net negative before
going public** (binomial p = 4.4e-20, aggregate −$859,606). The `fresh_start` flag exists to
surface it; it fires on 447 of 589 traders here because the universe is young (median portfolio
age 49 days).

### Confirmed by both reviewers

- The hedging that prompted the review (simultaneous long/short on BTC/ETH) is **not** a red
  flag: 23 overlapping pairs against 6 distinct core longs, the short covering a median 9.8% of
  the long, always net long. Removing the hedge legs *improves* alpha (+3.10% → +3.39%) and
  leaves t essentially unchanged (6.7196 → 6.7222) — it is not inflating the ranking.
- Hedge mode is used by **158 of 584** traders (27%): common, not distinguishing.
- Its cost is immaterial: ~**$29** of fees against $13,440 of PnL. Funding does not double —
  the two legs accrue it with opposite sign and cancel.

### Where the reviewers disagreed

Fable attributed the vanished history to the `startTime` filter; GLM to a "keep the most recent
~N" rank cap. Settled against the data: a rank cap cannot produce **0 of 590** portfolios with a
pre-`startTime` position (it was 177 of 485 three days earlier), and the filter accounts for
**90.7%** of the 19,581 positions that vanished across the population. GLM's ~120-day
close-date ceiling is real but was present in *both* snapshots, so it is not what changed. 98%
of the unexplained residual sits in portfolios pinned at the 2000-row pagination cap.

Fable was right on the mechanism. Recorded as Trap 7 in `SKILL.md`.
