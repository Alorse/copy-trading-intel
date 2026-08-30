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
| Binance | ~600 | **5** | `analysis/TOP5.md` |
| OKX | 261 | 5 (2 recommended) | `analysis/TOP5_OKX.md` |
| Phemex | 192 | 0 | `analysis/TOP5_PHEMEX.md` |
| Bybit | 295 | 0 | `analysis/TOP5_BYBIT.md` |
| Bitget | 400 | 0 | `analysis/TOP5_BITGET.md` |
| KuCoin | 165 | 0 | `analysis/TOP5_KUCOIN.md` |

Cross-exchange ranking: `analysis/COMBINED_RANKING.md`.

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

Full checklist for auditing a new exchange: `docs/exchange-integration-checklist.md`.

## Run it

```bash
pip install -r requirements-dev.txt && pytest   # 405 tests

python3 scripts/scrape_okx_positions.py         # any exchange's scraper (resumable)
python3 analysis/okx_flatten.py && python3 analysis/okx_top5.py
```

Scrapers exist for all 6 exchanges (see `scripts/`); each documents its endpoint
quirks — WAF bypasses, silent caps, lying pagination fields. Raw data is not
versioned; scrapes are cheap and resumable.

## Repo layout

- `analysis/` — flatten + ranking per exchange, the TOP5 reports, combined ranking
- `scripts/` — one scraper per exchange + the repair/utility scripts
- `pipeline/` — the permanent Binance/Phemex pipeline (scrape → SQLite → roster)
- `docs/exchange-integration-checklist.md` — every lesson we paid for
- `SKILL.md` — the living endpoint reference

MIT — see [LICENSE](LICENSE).
