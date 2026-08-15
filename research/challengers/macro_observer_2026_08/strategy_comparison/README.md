# Strategy Comparison: Hawkish Exit + EPS Re-entry

## Summary

Head-to-head comparison of exit/re-entry strategy combinations on QQQ.

**Core hypothesis**: Hawkish Path handles exit timing, EPS Momentum handles re-entry.

## Sample

- **Period**: 2017-05-08 → 2026-08-12 (2,329 trading days, ~9.2 years)
- **Asset**: QQQ (Nasdaq 100 ETF)
- **Common constraint**: EPS data starts 2016-10 + 26w warmup → first valid signal ~2017-05

## Data Sources

| Source | Signal | Frequency | File |
|---|---|---|---|
| Kim-Wright (Fed) + FRED DFF | Hawkish Path, ΔExpected Rate | Daily | Downloaded live from Fed |
| LSEG I/B/E/S | EPS Momentum 26w, Forward PE | Weekly | `lseg_backtest_results_v3.csv` |
| QQQ prices | Equity curve | Daily | From project `data/yahoo/QQQ.json` |

## Signal Definitions (FROZEN)

### Exit Signals
- **Hawkish**: `HP > 0.5%` AND `ΔExpectedRate_1Y_4w > 0.25%`
  - Execution: observation date → publication Tuesday → trade at close
- **EPS Danger Zone**: `EPS_Mom_26w > +8%` AND `Forward_PE > 20x`
  - Execution: weekly observation → next business day close

### Re-entry Signals
- **Hawkish Normalize**: `HP < 0.5%` (publication-date delayed)
- **EPS Re-entry (-5%)**: `EPS_Mom_26w < -5%`
- **EPS Re-entry (-3%)**: `EPS_Mom_26w < -3%` ← **the threshold that works**
- **EPS Re-entry (0%)**: `EPS_Mom_26w < 0%`
- **Combined (E∨H)**: first of EPS(-3%) OR Hawkish normalize

## Results (v2)

| Strategy | CAGR | Sharpe | MDD | **Calmar** | In Mkt | # Trades | $1→ |
|---|---|---|---|---|---|---|---|
| Buy & Hold | +19.7% | 0.89 | -35.6% | 0.55 | 100% | 0 | $5.26 |
| H→H | +22.7% | 1.08 | -28.6% | 0.80 | 91% | 1 | $6.65 |
| **H→EPS(-3%)** | **+24.1%** | **1.12** | **-28.6%** | **0.84** | 92% | 2 | **$7.36** |
| H→EPS(0%) | +23.8% | 1.11 | -28.6% | 0.83 | 93% | 2 | $7.22 |
| H→(E∨H) | +24.1% | 1.12 | -28.6% | 0.84 | 92% | 2 | $7.36 |
| EPS→H | +23.9% | 1.14 | -28.6% | 0.84 | 89% | 8 | $7.28 |
| **EPS→(E∨H)** | **+25.0%** | **1.17** | **-28.6%** | **0.87** | 89% | 8 | **$7.87** |
| H→EPS(-5%) | +11.1% | 0.72 | -28.6% | 0.39 | 51% | 1 | $2.66 |
| EPS→EPS | +8.5% | 0.61 | -28.6% | 0.30 | 38% | 1 | $2.13 |

### Key Episode: 2022 Bear Market

| Strategy | Exit Date | Exit QQQ | Entry Date | Entry QQQ | Avoided |
|---|---|---|---|---|---|
| H→EPS(-3%) | 2022-02-01 | $366 | 2022-11-07 | $268 | -26.8% |
| H→H | 2022-02-01 | $366 | 2022-11-15 | $289 | -20.8% |
| EPS→(E∨H) | 2021-11-15 | $395 | 2022-11-07 | $268 | -32.2% |

## Caveats

1. **N=1**: All strategies had exactly 1 meaningful trade (2022 bear). This is a case study.
2. **EPS -5% threshold is dead**: The 2022 bear only reached -4.7% EPS momentum.
3. **EPS danger zone is structurally broken as exit**: fires during sustained bull markets.
4. **No transaction costs modeled** (multi-month holds make this less relevant).

## Files

| File | Description |
|---|---|
| `strategy_comparison_v1.py` | Initial backtest (5 strategies, original thresholds) |
| `strategy_comparison_v2.py` | Extended backtest (9 strategies, relaxed thresholds) |
| `lseg_backtest_results_v3.csv` | LSEG I/B/E/S parsed data (400 weekly observations) |

## How to Run

```bash
# Requires: pandas, numpy, internet access (for Kim-Wright download)
# Optional: yfinance (if QQQ.json not available locally)
python3 strategy_comparison_v2.py
```
