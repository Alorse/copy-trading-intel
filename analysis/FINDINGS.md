# Audit of `copy-trading-intel` SKILL.md vs the data — 2026-08-25

Local snapshot: the root of this repo.
Reproducible: `flatten.py` → `phemex_positions.csv` (7,467 rows) / `binance_positions.csv` (108,616 rows).
Then `pair_select.py`, `pair_select2.py`, `btc_behavior.py`, `persistence.py`, `style_vs_skill.py`.
Nothing was re-scraped.

**The user's goal**: concrete entry/exit rules for ONE pair, copying *patterns* (not trades) from
traders who already win. Soft rules, not hard rules.

## What the SKILL gets right

| Claim | Verdict |
|---|---|
| 7,467 Phemex pos / 196 traders | ✅ exact |
| 108,616 Binance pos / 594 portfolios | ✅ exact (600 lines, 6 with no positions) |
| Without DugEFresh, XRP-Phemex is not tradeable | ✅ DugEFresh = 91.3% of the PnL, median/trader −1.5, 27/64 win |
| BTC is the least concentrated pair | ✅ top1 = 15.8%, 437 traders, median/trader +128 |
| Aggregate XRP-Binance PnL is negative | ✅ −3,966 USD over 771 pos |

## What is refuted

**R1 — Internal contradiction about XRP.** "Phemex findings" claims *"XRP the exception: 64
traders, +38k distributed"*. It is not distributed: DugEFresh is 91.3%, the median per trader is
−1.5 and only 27/64 win. A later section corrects it but the original bullet is still published.

**R2 — "12-24h ALWAYS loses (every table: XRP, BTC, ETH)".** False.
12-24h is the BEST bucket on Phemex-XRP (+40.1k) and on Binance-XRP too (+5.0k). It only loses on
BTC. The skill overcorrected its own "12-24h sweet spot": neither version is true.

**R3 — Aggregating PnL in USD lets account size decide the conclusion.**
SOL and XRP have NEGATIVE aggregate PnL but a POSITIVE median per trader (+21 and +3.0): the
typical trader won, and a few enormous accounts sank the aggregate. For copying *patterns* that
is the inverted reading.

**R4 — Picking a pair by profitability within this dataset is circular.**
De-leveraged (signed price return, not ROI-on-margin), **188 of 197 pairs (95%) have a POSITIVE
median return per trader**. The dataset is the top-600 by 90D ROI: they win at everything. The
pair ranking measures survival, not the pair's edge.

**R5 — The ROI ranking is contaminated by leverage.** ROI is on margin, so ranking by ROI rewards
high leverage arithmetically. Median leverage: BTC/ETH 30x, altcoins 5x. BTC dominates in USD with
only a 0.33% median price move. This also clashes with the skill's claim that "6-20x concentrates
the PnL; >50x is neutral to negative".

**R6 — MOST IMPORTANT: skill does not persist.** An out-of-sample test, ranking each trader on the
first half of their history and measuring the second (price return, de-leveraged):

| metric | rho H1→H2 (BTC, n=59 with ≥30 pos) |
|---|---|
| win rate | **+0.805** |
| payoff | +0.186 |
| **expectancy** | **+0.136** |

What persists is the win rate; what pays (expectancy) does not. And `corr(winrate, payoff)`
Spearman = **−0.497**: win rate and payoff are a STYLE trade-off (partial closing / taking profit
early), not levels of skill. Confirmed by the quartile split: the top quartile has an 81.9% win
rate but a payoff of 1.08, against 37.9% and 1.15 for the bottom quartile — median gain and loss
almost identical (0.49%/0.41% vs 0.45%/0.39%), duration almost identical (4.9h vs 4.7h), %long
almost identical (52.5% vs 56.4%).

**Implication for the goal**: "identify traders who win and copy their patterns" has no support in
this data. Winning does not persist. What persists is a style parameter which on its own is not
profitable.

## Limitations I declare myself (attack here)

- **L1** The persistence test splits EACH trader's history at their own median, not by calendar.
  Different traders land in different regimes → regime confound.
- **L2** n=59 traders. Spearman's standard error is ~1/√58 ≈ 0.13, so rho=+0.136 is ~1 SE:
  **absence of evidence of persistence, not evidence of absence**. The test is underpowered.
- **L3** 10.9% of BTC rows show a partial close (|closedVolume − maxOpenInterest| > 2%).
  `avgCost`/`avgClosePrice` are averages over scale-ins/scale-outs → the per-row win rate may be
  an aggregation artefact, not a real trade.
- **L4** There is no OHLC in the data. Only positions (entry, exit, timestamps, leverage).
  Technical entry rules cannot be derived without downloading candles.
- **L5** The whole set is survivors (top-600 by 90D ROI). There is no control group of failed
  Binance traders. Phemex does have the losing crowd and could serve as a control, but it is
  another exchange, another period and another pair mix.
- **L6** Is `closingPnl` net or gross of fees/funding? Not verified. If it is gross, every
  expectancy is overstated.

## Questions for the reviewers

1. Does R6 (skill does not persist) survive? Or do L1/L2/L3 knock it down?
2. Is there a better persistence test with this data (calendar-aligned, with more power)?
3. If the edge does not persist, what IS copyable? Structural parameters (duration, leverage,
   sizing, cross/isolated, adapting side to the regime)?
4. Is BTCUSDT the right pair choice, given that choosing by profitability is circular (R4)?
5. Which soft entry/exit rules hold, and which would be overfitting to this snapshot?
