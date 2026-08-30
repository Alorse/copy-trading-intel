# Combined ranking — Binance + OKX top picks (2026-08-29)

Both pipelines share the core metric: **alpha = de-leveraged price return − median of its
symbol×month×side cell** (OKX now leave-self-out). Both were adversarially audited. The
combined order below weighs: audited alpha + t, window length (the single biggest
differentiator post-audit), risk profile (leverage tail, ruin, concentration), and
copyability (real notional/copers/AUM).

⚠️ Binance numbers are self-inclusive-cell alpha (pre-dating the OKX correction); OKX
numbers are leave-self-out. Treat cross-exchange alpha comparison as indicative, not exact.

## The table

| Rank | Trader | Exchange | Weight | Alpha | t | Win rate | Leverage | PnL (visible) | Track record | Key risk |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Mine13** | OKX | 20% | +5.05% | 3.44 | 82% | 10x flat | $86.7k | ✅ ~3 meses | 1 celda 67% propia; 1 solo régimen |
| 2 | **Cooma** | Binance | 15% | +1.75% | 5.01 | 85% | 10x flat | — | ✅ 5 meses, ambos regímenes | Payoff 0.64; ruin −92% |
| 3 | **Algotoria** | OKX | 15% | +3.57% | 4.23 | 63% | 4x flat | $87.3k | ⚠️ 3 semanas | Snapshot, no track record |
| 4 | **秋高看山势** | Binance | 12% | +1.08% | 3.14 | 69% | 10x | — | ✅ mejora mes a mes | Notional $41 — no escalable |
| 5 | **重生之我在币圈捡垃圾-** | Binance | 12% | +0.60% | 3.36 | — | 6x | — | ✅ 5 meses | mdd 64%; duración 0.5h (latencia) |
| 6 | **梭哈到世界尽头** | Binance | 8% | +1.60%* | 6.11 | — | 5x | — | ⚠️ decay + borrarón pre-startTime | Top-3 = 59% del PnL; decay H1→H2 |
| 7 | **牛熊摆渡人** | Binance | 8% | +6.89% | 4.15 | 80% | 20x | — | ⚠️ 66 días | mdd 75%, ruin −1173% — el más peligroso |
| 8 | **BestMax** | OKX | 4% | +1.11% | 7.74 | 86% | 20x | $2.3k | ❌ 5 días, capped | Cross-check 0.20×; celda 95% propia |
| 9 | **Kunpeng Plan** | OKX | 3% | +0.66% | 5.03 | 78% | 3x | $1.4k | ❌ ~1 día, capped | Cross-check 0.003× ($490k invisible) |
| 10 | **對不起我騙了你...後山** | OKX | 3% | +0.68% | 2.93 | 67% | 10x | $2.1k | ❌ 1 día, leadDays=1 | Cuenta nueva; "no asignar peso real" |

*梭哈: alpha sobre la ventana visible post-borrado (+3.10% en 286 posiciones); el +1.60% es del análisis original.

## How to read it

- **Tier 1 — copy with confidence (ranks 1-2):** Mine13 and Cooma. Multi-month windows,
  audited, cross-checks close, survivable risk. Mine13 edges first on the corrected
  (leave-self-out) alpha and a clean OKX-native record; Cooma has the longest audited
  record and wins in both regimes.
- **Tier 2 — copy small, watch closely (3-5):** Algotoria's numbers are the best
  risk-adjusted in either pool (t=4.23, 4x flat, payoff 5.22) but 3 weeks is a snapshot.
  秋高看山势 improves every month but trades $41 notionals. 捡垃圾 has the best tail
  management on Binance but a demonstrated 64% mdd.
- **Tier 3 — structural doubts (6-7):** 梭哈's visible window is a decaying tail after
  Binance deleted his pre-startTime history (net −$5.6k deleted). 牛熊摆渡人 has elite
  alpha but mdd 75% / ruin −1173% — the same profile as OKX's rejected
  Powerful-Bubble-Rims.
- **Tier 4 — listed for transparency, not recommendations (8-10):** the three OKX
  survivors that passed the strict filters on razor-thin windows (1-6 days). The audited
  TOP5_OKX.md itself says do not allocate real weight to #10.

## Caveats that apply to the whole table

- Single regime cycle everywhere (May crash → Jul-Aug pump). Nobody here has been seen
  in a prolonged bear market.
- Winner's curse: expect ~half the alpha out of sample (Fable's rule).
- Binance alphas pre-date the leave-self-out correction; a full re-audit of the Binance
  side with the corrected methodology is future work.
- Weights above are my combined suggestion (sums to 100% across 10 traders); the
  per-exchange docs' own suggestions (Binance 30/25/20/15/10, OKX 45/30/15/7/3) remain
  the reference for within-exchange allocation.
