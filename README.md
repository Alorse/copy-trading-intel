# copy-trading-intel

**We audited 6 crypto copy-trading exchanges. Only 1 produced traders worth copying.**

Every exchange publishes "top trader" leaderboards. We scraped the actual position
history behind those leaderboards — ~200,000 closed positions across Binance, OKX,
Phemex, Bybit, Bitget and KuCoin — and measured who has *skill* instead of *luck,
leverage and hidden losses*.

The result: 4 of 6 exchanges have **zero** traders who survive honest scrutiny.
The "top traders" you see are mostly survivors of selection bias, not skill.

> ⚠️ Not financial advice — see [DISCLAIMER.md](DISCLAIMER.md).

## The one metric

```
alpha = de-leveraged price return − median of its cell (symbol × month × side)
```

ROI rewards leverage, account size and regime luck. This doesn't. Going long in a
pump scores zero — the only thing that counts is beating everyone who traded the
same pair, the same month, the same direction.

**The 3 highest-ROI traders on Binance, measured this way:** alpha −0.72%, −1.23%,
and one whose "profit" is 96.9% a single trade at 145x.

## What the audits found

| exchange | traders scraped | survivors | report |
|---|---|---|---|
| Binance | ~600 → **951** (2026-09-23) | **5** | [TOP5.md](analysis/TOP5.md) |
| OKX | 261 → **287** (2026-09-23) | 5 (2 recommended) → **0** | [TOP5_OKX.md](analysis/TOP5_OKX.md) |
| Phemex | 192 | 0 | [TOP5_PHEMEX.md](analysis/TOP5_PHEMEX.md) |
| Bybit | 295 | 0 | [TOP5_BYBIT.md](analysis/TOP5_BYBIT.md) |
| Bitget | 400 | 0 | [TOP5_BITGET.md](analysis/TOP5_BITGET.md) |
| KuCoin | 165 | 0 | [TOP5_KUCOIN.md](analysis/TOP5_KUCOIN.md) |

Cross-exchange ranking: [COMBINED_RANKING.md](analysis/COMBINED_RANKING.md).

## The 2026-09-23 re-run: a different regime, a different answer

The table above was measured in one market regime (August). Re-scraped from scratch on
2026-09-23 — 951 Binance portfolios and 150,165 closed positions, 287 OKX lead traders —
the same unchanged pipelines say something else:

- **OKX drops from 5 survivors to 0**, both recommended picks included.
- **Four of six audited leads come off**, and no replacement clears the bar. "No
  replacement" is the finding, not a failure to search.
- The most instructive case is a lead whose alpha *held*: +617% headline ROI, alpha
  +0.60% at t=3.85 — and **1,862 copiers collectively down $322,314**. Binance publishes
  realized copier PnL per lead, and across the 120 highest-scoring portfolios, **51% of
  the leads with ≥5 lifetime copiers have lost money for them.** Skill on the lead's own
  fills and skill you can buy are not the same quantity.
- A new trap on OKX: its 100-row history cap is a *rolling* window, so a past month's
  benchmark shrinks and keeps only the traders who have since traded little. **Alpha is
  not comparable across two OKX snapshots.**
- **The pipeline now enforces both lessons.** Realized lifetime copier PnL is scraped
  per lead and disqualifies the ones whose copiers lost real money (`copiers_losing`),
  and no single trader may hold more than **20%** of the book — the +617% lead above was
  removed by the first rule, and a trader with 84 trades and a $2,001 account that had
  been handed **70%** of the roster was removed by both.

See [COMBINED_RANKING.md](analysis/COMBINED_RANKING.md) for the verdicts and the numbers.

## Versus the public rankings

[Arena](https://www.arenafi.org/) aggregates ~30 exchange leaderboards into one score
over 13,433 traders — the closest thing to this project that exists. Its score is
`100 × Quality × Confidence`, and half of *Quality* is PnL and ROI; its
[methodology](https://www.arenafi.org/methodology) normalizes across exchanges but not
for leverage, symbol, month or side, and says nothing about survivorship, hidden losses
or truncated history. It answers *who earned the most*. This repo asks *who had skill*.
On the same traders, using the same exchange IDs, the two disagree hard:

| our rank | trader | our alpha | Arena rank |
|---|---|---|---|
| 1 | Mine13 (OKX) | +5.05% | #7 |
| 2 | Cooma (Binance) | +1.75% | #31 |
| 6 | 梭哈到世界尽头 (Binance) | +1.60% | #753 |
| 7 | 牛熊摆渡人 (Binance) | **+6.89%** | **#6,330** |

The last row is the argument in one line: the highest raw alpha we found sits six
thousand places down an ROI-driven board. Our own report also calls it the most fragile
of the seven (66 days of history, 75% max drawdown) — which is the point. The two
rankings are not competing answers to one question; they are answers to two.
The drawdown flag was right, too: on 2026-09-02 this portfolio closed 14 positions in
the same second for −15.3k USDT and has not traded since. It is retired from the
picks (see [the combined ranking](analysis/COMBINED_RANKING.md)). Alpha measures skill
on the trades you can see; it does not replace the risk screen.

Every pipeline went through adversarial review (two independent AI auditors with a
refute mandate) before its numbers were trusted — and the reviews found real bugs
every time: a drawdown screen that didn't measure drawdown, a cross-check that was
dead code, "survivors" whose entire edge lived outside the visible data window.

## The traps (all with real cases)

1. **Loss hiders** — 98-100% win rates from simply never closing a loser (0 losers in 174 closes, anyone?)
2. **ROI ≠ skill** — leverage arithmetic, not edge
3. **Survivorship everywhere** — the leaderboard IS the selection bias
4. **History truncation** — every exchange caps or prunes what you can see; some traders' "track record" is their last 50 trades
5. **Hidden drawdowns** — the pristine window you can see often hides the crash you can't
6. **Uncopyable sizing** — a real edge expressed in $12 positions is not a real edge for you
7. **The edge you can't buy** *(new, 2026-09-23)* — alpha is measured on the lead's fills, not yours. Across the 760 measured Binance portfolios, **45.5% have net-negative lifetime *copier* PnL** — including one at +617% ROI whose 1,862 copiers are down $322k. Now a disqualifier (`copiers_losing`), and careful: the leaderboard listing publishes a `copierPnl` of its own that is scoped to the query's time range, not lifetime, and reads *positive* for leads whose copiers are deeply under water
8. **Concentration by construction** *(new, 2026-09-23)* — a ranking that splits weight by score hands a thin-evidence winner the whole book. One lead, 84 trades, t=2.58, a $2,001 account: **70%** of the roster. Capped at 20%, with the excess left unallocated rather than pushed onto the next name

Full checklist for auditing a new exchange: [docs/exchange-integration-checklist.md](docs/exchange-integration-checklist.md).

## Run it

```bash
pip install -r requirements-dev.txt && pytest   # 455 tests

python3 scripts/scrape_okx_positions.py         # any exchange's scraper (resumable)
python3 analysis/okx_flatten.py && python3 analysis/okx_top5.py
```

Scrapers exist for all 6 exchanges (see `scripts/`); each documents its endpoint
quirks — WAF bypasses, silent caps, lying pagination fields. Raw data is not
versioned; scrapes are cheap and resumable.

## Repo layout

- `analysis/` — flatten + ranking per exchange, the TOP5 reports, combined ranking
- `scripts/` — one scraper per exchange + the repair/utility scripts
- `pipeline/` — the permanent Binance/Phemex pipeline (scrape → detail → SQLite → roster)
- [docs/exchange-integration-checklist.md](docs/exchange-integration-checklist.md) — every lesson we paid for
- `SKILL.md` — the living endpoint reference

MIT — see [LICENSE](LICENSE).
