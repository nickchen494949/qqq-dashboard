# TQQQ Three-Layer Defense Strategy — Workspace Instructions

## Project Context
This is a production-grade TQQQ risk management strategy with a live dashboard at:
https://nickchen494949.github.io/qqq-dashboard/

## Key Documents (READ THESE FIRST)
- `docs/STRATEGY.md` — The sealed strategy rules (3-layer defense + NSL)
- `docs/RESEARCH_RULES.md` — 3 iron rules + complete testing protocol
- `docs/RESEARCH_PAPER.md` — Full research paper with data and methodology

## Three Iron Rules (ALWAYS FOLLOW)

### 1. Never Sell in Loss (NSL) is absolute
All strategy modifications MUST preserve NSL. If a trade is at a loss, Credit/Vol overlays do NOT force a sell. Only Fed SEP hawk signal can override NSL to force 0%.

### 2. Always push to Git
Every code change must be committed and pushed to `origin/main`. No uncommitted strategy code allowed.

### 3. Always run the full testing protocol
Any new signal, parameter change, or strategy modification must pass:
- T+1 execution (no T+0)
- Signal delay verification (exec_date > signal_date for every trade)
- In-Sample (2012-2018) → Holdout (2019-2022) → Forward (2023-2026), all Sharpe > 0.5
- Parameter plateau (≥ 5 combos within best Sharpe ± 0.05)
- TC stress test (0/25/50/100/200 bps)
- **5 Seal Checks**: MDD ≤ -40%, Sharpe ≥ Credit-only + 0.05, CAGR loss ≤ 2pp, TC 200bps Sharpe > 1.0, Avg trades ≤ 4/yr

## Sealed Parameters (DO NOT CHANGE without full protocol)
```
Credit:  Trigger = 1.2,  Recover = 0.2
Vol:     Trigger = 1.0,  Recover = -0.5,  Lev = 66%
TC:      25 bps per switch
```

## Current Performance (29/29 PASS)
```
CAGR: +54.5%, MDD: -38.7%, Sharpe: 1.36, Trades: 40 (2.8/yr)
```

## Key Files
- `tools/build_dashboard.py` — Main program (data fetch + backtest + HTML generation)
- `tools/audit_backtest.py` — Production audit (29 checks)
- `fomc_sep/` — 74 Fed SEP PDFs (primary data source)
- `.github/workflows/deploy-dashboard.yml` — Daily auto-deploy

## Portfolio Tracking
- Nick: 6326 units TQQQ
- SY: 416 units TQQQ
- Values shown in MYR (Malaysian Ringgit), auto-refreshed every 30 min

## Past Failures (DO NOT REPEAT)
6 secondary signals tested and ALL failed: EPS acceleration, EPS absolute growth, EPS mean reversion, VIX backwardation, HY OAS, VIX+Momentum. The VIX+Mom was the most dangerous — it passed all in-sample tests but collapsed completely under T+1 execution.
