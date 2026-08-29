# Top 5 traders to copy — the consensus of 4 independent analyses

Sources: Fable, Kimi, GLM and my own ranking, each with a different criterion.
**Every number below was re-derived by me**; no agent's figure is reported unverified.
Core metric: **alpha = de-leveraged price return − the median of its own symbol×month×side.**
It neutralises all three unfairnesses: account size, leverage and regime beta. Going long in the
August pump scores zero by construction: only beating those who did the same counts.

`closing_pnl` is NET of fees (verified: −7.85 bps of residual over 96,994 complete closes).

## The consensus

| # | trader | votes | n | med alpha | t | payoff | lev | ruin | top3 | mdd | notional |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Cooma** | GLM#1 + mine | 127 | +1.75% | **5.01** | 0.64 | 10x | **−92%** | 37% | 32 | $1,999 |
| 2 | **梭哈到世界尽头** | GLM#5 + mine | 527 → **286**† | +1.60% | **6.11** | 1.04 | **5x** | −398% | 59% | 20 | $506 |
| 3 | **秋高看山势** | Fable#1 + Kimi#4 | 270 | +1.08%* | 3.14 | **1.55** | 10x | −231% | 33% | **15** | $41 |
| 4 | **牛熊摆渡人** | GLM#2 + mine | 90 | **+6.89%** | 4.15 | **1.40** | 20x | −1173% | 49% | 75 | $627 |
| 5 | **重生之我在币圈捡垃圾-** | Fable#5 + mine | 298 | +0.60%* | 3.36 | 0.82 | 6x | **−75%** | **9%** | 64 | $6,030 |

*mean alpha. "ruin" = worst price loss × median leverage, as a % of margin.
†his sample **shrank to 286** three days after this table was built — see the correction below.

**None appeared on 3 of the 4 lists.** That alone says something: with 5 months of data the
ranking depends heavily on the criterion. Treat it as a portfolio of correlated bets, not as five
certainties.

### Why each one

**1. Cooma** — the most balanced. The only one whose worst loss (−92% of margin) is survivable on
isolated margin, with flat 10x leverage (does not scale aggression when winning), a $2k notional
(genuinely copyable) and t=5.01. GLM verified they win in both regimes: +1.23% in the crash,
+2.22% in the pump.
*Risk:* payoff 0.64 — their mean loss is 1.6× their mean gain. They live off an 85% hit rate.

**2. 梭哈到世界尽头** — the largest sample in the consensus at the time (527 positions), with
t=6.11 and the most conservative leverage (5x). mdd 20%.
*Risk:* their 3 best trades are **59% of the PnL** — the highest concentration in the Top 5. And
their alpha decays gently (H1 +1.95% → H2 +1.37%): the only one trending down.

> ### ⚠️ Correction, 2026-08-29 — this entry no longer describes what is visible
>
> On the 2026-08-28 scrape his history is **286 positions, not 527**. Binance now serves nothing
> opened before a portfolio's `startTime`, and his is **2026-06-07 23:34** (Trap 7 in `SKILL.md`).
> 249 positions were deleted, 8 new ones appeared. The cut is exact: 249/249 deleted were opened
> before `startTime`, 286/286 survivors after it.
>
> **What the deleted history contained is worse than the deletion.** Those 249 positions were net
> **−$5,589**, and the last week before the portfolio opened was **−$8,292** over 114 closes —
> including a single LABUSDT short at **−$7,754**. His last pre-portfolio close is 2026-06-07
> **23:30**; the lead portfolio starts **23:34**; his $40k ETH core long opens 23:42. The +139%
> headline ROI is measured from a starting point chosen four minutes after that week was
> liquidated.
>
> **His decay is steeper than either snapshot alone shows.** Recomputed with the engine's own
> formula:
>
> | | on the 527-position data | on the 286 visible today |
> |---|---|---|
> | alpha | **+4.21%** | +3.10% |
> | months active | 6 | **3** |
> | monthly alpha | +7.73% → +4.32% → +3.23% → **+2.96%** | +3.53% → +3.18% → +2.62% |
> | May 2026 PnL | **−$6,943** | *invisible* |
>
> The engine now sees only the flat tail of a decaying series, and `months_active=3` sits exactly
> on the `insufficient` threshold in `pipeline/detect.py`.
>
> **This is not specific to him.** Of the 177 portfolios whose pre-`startTime` history was still
> visible on 2026-08-25, **86% were net negative before going public** (binomial p = 4.4e-20,
> aggregate −$859,606). He is an extreme case of a population-wide selection effect, not an
> outlier in kind. The `fresh_start` warning flags portfolios young enough that none of this is
> checkable.
>
> Verified independently by two adversarial reviewers (Fable, GLM) and re-derived first-hand;
> the reviewers disagreed on the mechanism and the `startTime` filter is what the data supports.

**3. 秋高看山势** — the one who **improves month over month without exception**:
+0.2 → +1.5 → +1.7 → +1.8. The only one in the group with payoff >1.5 and a moderate win rate
(69%), meaning they win by capture, not by piling up micro-wins. mdd 15%, the lowest.
*Risk:* median notional **$41**. They trade micro-caps on a $679 account. Their edge could
evaporate into slippage when scaled — which is why my own filter excluded them.

**4. 牛熊摆渡人** — the highest alpha in the consensus (+6.89%) **with payoff 1.40**, a rare
combination: right 80% of the time *and* their gains exceed their losses. Flips side with the
regime. Responsible sizing: $627 per trade on a $56k account.
*Risk:* the most dangerous of the five. mdd **74.9%**, worst loss = **−1173% of margin**, only 90
positions, and their first closes on 19 June: **66 days of history**. Minimum weight.

**5. 重生之我在币圈捡垃圾-** — the best tail management in the group: worst loss −75% of margin and
**top-3 = only 9% of the PnL** (nobody depends less on lucky trades). 298 positions, sustained
improvement (+0.0 → +0.4 → +0.5 → +1.3), $6k notional.
*Risk:* mdd **63.8%** — at some point in these 5 months you would have watched two thirds of the
account disappear. And they trade at a 0.5h median duration: sensitive to copy latency.

## Rejects — as important as the Top 5

**The three best by ROI are the worst by skill:**

| trader | ROI | real alpha | what kills it |
|---|---|---|---|
| VickyKaushal | **+5,436%** | **−0.72%** (t=−2.88) | payoff 0.13; the ROI is a tiny margin, not skill |
| Omofun | **+4,844%** | **−1.23%** (t=−2.44) | payoff 0.07 |
| 龟兔赛跑985 | +2,382% | +1.21% | **96.9% of the PnL is ONE trade**, at 145x |

**By absolute PnL:**
- **道亦有道 1994** — $551k of PnL, 309 copiers. alpha +0.11% with **t=0.46**: no measurable skill.
  **15% of their 486 positions consumed >80% of margin**, leverage p90 75x.
- **风雪哥** — $207k. Median alpha **−0.16%**, and their top-3 explains **93.2%** of the PnL.
- **geddong** — $228k over 2,000 trades. alpha **−1.50% with t=−12.11**: they lose per trade before
  leverage. That is volume with a negative edge.

**The ones hiding their losses** (detected independently by Fable, GLM and by me):
**GGbond哦** (98.5% hit rate, mdd 50.5%), **无人在稻** (98.9%, payoff 0.39), **Una躺平记_**
(0 losers in 174 closes, mdd 63.7%), **NepNeptune** (0 in 43, mdd 42.4%).
The record shows **closed** positions only. A trader who never closes a loser looks perfect while
accumulating unrealised loss. A high mdd alongside a spotless close record is the signature.
**These are the ones topping any naive ranking.**

**The best alpha in the dataset, not copyable:** **The Scalper King** — median alpha **+8.96%**,
t=9.50, payoff 1.55, mdd 16.6%. But a median notional of **$50** and a worst loss of −715% of
margin. GLM and I reached the same conclusion separately: if their sizing were copyable they
would be #1.

## Confidence: low-to-moderate

- **5 months, a single regime cycle.** None has been observed sideways or in a prolonged bear
  market. Demeaning by symbol×month×side removes the beta, but it cannot invent absent regimes.
- **Winner's curse.** Hundreds of traders were filtered; with ~300 candidates, roughly 4-6 would
  clear t≈2.5 by pure chance. Fable's rule of thumb, which I share: **expect half the alpha** in
  these tables and count it a success if it stays positive.
- **Survivorship**: top-600 by 90D ROI, with no control group.
- **Only closed positions are visible**: any latent loss in positions open today is invisible. The
  win-rate filter mitigates, it does not eliminate.
- **The most fragile: 牛熊摆渡人** (66 days of history, mdd 75%). **The most severe if it fails:
  重生之我在币圈捡垃圾-** (mdd 64% already demonstrated).

**Suggested operation:** weights 30/25/20/15/10 in the given order, not spread evenly. Review the
monthly alpha against the cell (reproducible with `top5_final.py`) and stop copying anyone with
two consecutive months of negative alpha.
