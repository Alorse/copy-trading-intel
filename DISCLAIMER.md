# Disclaimer

## This is not financial advice

This repository is a **data analysis project**. Nothing in it — the `TOP_YYYY-MM.md` reports, the
`roster.json`, the allocation weights, the findings in `analysis/` — is an investment
recommendation, an offer, or an invitation to trade or to copy anyone.

Copy-trading leveraged futures can lose you **more than you deposit**. The metrics here describe
the past of a short and particular window; they predict nothing. If you act on this information
you do so at your own exclusive risk, and you would do well to consult a licensed financial
adviser.

The software is provided "as is", with no warranty of any kind (see [LICENSE](LICENSE)).

## About the traders named

The nicknames appearing in the analysis are the ones **the platforms themselves publish** on
their copy-trading pages, alongside the metrics they themselves expose.

The detector's labels — `loss_hider`, `lottery`, `roi_artifact`, `ruin_risk`, `no_alpha` and the
rest — are **automated statistical classifications**, produced by deterministic rules over that
public data and documented in `pipeline/detect.py`. They describe the *shape* of a track record
of closed positions, not a person's conduct or intent.

In particular, `loss_hider` marks the numerical signature of a track record with a very high
close win rate alongside a high portfolio drawdown. That signature is **consistent with** not
closing losing positions, but also with other explanations this data cannot tell apart: the
public record shows **closed** positions only. The label does not assert that anyone is hiding
anything or acting in bad faith.

Reading these labels as an accusation of fraud or misconduct is a misreading.

## About the data

The data comes from **public, unauthenticated** HTTP endpoints of Binance and Phemex, queried
with rate limiting (~0.4-0.5 s between calls). This repository does **not redistribute** the raw
dumps: anyone wanting to reproduce the analysis generates their own snapshot. Review each
platform's terms of service before running the scrapers; what you do with them is your
responsibility.

If you are one of the traders analysed and want your nickname removed from the published
analysis, open an issue.

## No affiliation

This project is not affiliated with, endorsed by, or sponsored by Binance, Phemex or any other
platform. All trademarks belong to their respective owners.
