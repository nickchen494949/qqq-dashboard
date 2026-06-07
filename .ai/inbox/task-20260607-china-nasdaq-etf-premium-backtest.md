target: qqq-dashboard

# Task
Backtest whether China-listed Nasdaq/QDII ETF premium is a useful predictor for QQQ/TQQQ risk or return.

## Background
User asked: "help me check china nasdaq etf premium is that a good predictor" and then "backtest it".

This is a research task only. Do not change the sealed production strategy unless the signal passes the full testing protocol.

Current sealed production strategy must remain unchanged:
- Fed SEP > Credit Z > Vol Z > Normal priority
- NSL must remain on
- T+1 next-open execution
- Transaction cost protocol must remain intact

## Main Question
Does China-listed Nasdaq/QDII ETF premium predict future QQQ/TQQQ returns, drawdowns, or overheat risk better than existing signals?

## One-Sentence Hypothesis
China Nasdaq ETF premium is more likely a China retail/QDII quota stress indicator than a direct Nasdaq return predictor; it may only be useful as an extreme-overheat warning or dashboard sentiment thermometer.

## Instruments to Test
Use at least these China-listed Nasdaq/QDII ETFs if data is available:
- 513100.SH / 513100: Guotai Nasdaq-100 ETF
- 159941.SZ / 159941: GF Nasdaq-100 ETF
- Add other liquid China Nasdaq/QDII ETFs only if historical price + NAV are available and clean.

## Required Data
For each ETF, collect daily history:
- China ETF close price
- China ETF adjusted close if available
- official daily NAV / IOPV / unit NAV
- premium = close / NAV - 1
- trading status / suspended subscription flags if available
- QQQ daily OHLC
- TQQQ daily OHLC
- USD/CNY or USD/CNH if available
- existing dashboard risk signals: SEP, Credit Z, Vol Z

Preferred Python data sources, in order:
1. Existing repo cache if already present
2. akshare if available in environment
3. yfinance for QQQ/TQQQ/USD proxies
4. Eastmoney/Sina/Netease endpoints only if stable and documented in code comments

## Core Test Design
Do not test only same-day correlation.

For each ETF premium series, test forward windows:
- 1 trading day
- 5 trading days
- 20 trading days
- 60 trading days

Target outcomes:
- forward QQQ return
- forward TQQQ return
- forward max drawdown over the window
- probability of negative return
- probability of >5%, >10%, >20% drawdown depending on window

Premium regimes:
- premium percentile >= 90th percentile
- premium percentile >= 95th percentile
- premium percentile >= 99th percentile
- premium z-score >= 1.5
- premium z-score >= 2.0
- absolute premium > 2%, >5%, >10% if enough samples

Also test low/negative premium regimes if available.

## Conditional Tests
Separate results into at least these groups:

A. Nasdaq/QQQ already in uptrend
- QQQ above 200DMA
- QQQ 20D return positive

B. Nasdaq/QQQ after selloff
- QQQ below 50DMA or 20D return negative
- premium high after decline may mean China investors are buying dip, not chasing top

C. RMB pressure regime
- USD/CNY or USD/CNH 20D return positive / RMB weakening
- Test whether premium predicts China capital pressure more than Nasdaq return

D. Existing dashboard states
- Normal
- Vol danger
- Credit danger
- Fed out if SEP history overlaps

## Backtest Rules
Must avoid look-ahead bias:
- Signal available after China market close
- US execution must be next tradable US session open or next close, clearly specified
- No same-day US close execution unless justified by timestamp availability

Transaction cost assumptions:
- Use existing repo cost protocol where applicable
- If testing as overlay, include 25 bps per switch baseline and 200 bps stress

## Strategy Variants to Test
Do not directly add to production. Test as separate research variants:

1. Dashboard-only predictive study
- No trading, just event study after high premium events.

2. Overheat de-risk overlay
- If premium extreme and existing state is Normal, reduce TQQQ exposure from 100% to 66%.
- Must obey NSL unless explicitly testing diagnostic-only scenario.

3. No-buy filter
- If premium extreme, block adding/re-risking for N days.
- This may be more realistic than forced sell.

4. China-capital-pressure indicator
- Test against CNH/CNY depreciation, China equity underperformance, and QDII premium persistence if data exists.

## Required Statistical Outputs
Create a research output markdown file under docs/research/ or .ai/outbox/ with:
- data coverage by ETF
- missing data summary
- premium distribution summary
- event count by threshold
- mean/median forward return by window
- win rate by window
- forward max drawdown stats
- t-stat or bootstrap confidence where sample size allows
- baseline comparison vs unconditional QQQ/TQQQ returns
- separate IS / holdout / forward periods if enough data exists

Use repo's existing testing protocol where possible:
- IS: 2012-2018 if data exists
- Holdout: 2019-2022
- Forward: 2023-present
If ETF/NAV data starts later, use the maximum clean sample and clearly say coverage is too short for production if applicable.

## Production Acceptance Rules
The signal can only be considered for production if all are true:
- It improves holdout and forward results, not just full-sample
- It survives threshold variants / parameter plateau
- It does not increase trades beyond acceptable limits
- It works under T+1 execution
- It survives 200 bps cost stress if used as a trading overlay
- It adds value beyond existing Credit Z and Vol Z states

If it fails these tests, recommend dashboard-only display:
- China QDII Premium: normal / hot / extreme
- Label explicitly: sentiment/quota-stress indicator, not Nasdaq predictor

## Failure Checks
Reject the signal if:
- effect only appears with same-day execution
- sample size is tiny at high premium thresholds
- premium is driven by subscription suspension only and not market timing
- results disappear in 2023-present forward period
- it mostly duplicates Vol Z or QQQ momentum
- forced selling underperforms while no-buy filter works better

## Deliverables
1. Python script, preferably tools/research_china_nasdaq_premium.py
2. Cached raw/clean data if repo conventions allow
3. Markdown report with charts/tables
4. Clear conclusion:
   - Useful as predictor? yes/no
   - Useful as overheat warning? yes/no
   - Useful as dashboard sentiment indicator? yes/no
   - Should it modify sealed TQQQ system? yes/no

## Do Not Do
- Do not modify sealed production parameters.
- Do not update dashboard production UI unless the research report is generated first.
- Do not claim predictive power without holdout/forward evidence.
- Do not use same-day US close if timestamp would create look-ahead bias.
