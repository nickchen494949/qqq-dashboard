# Fed Hawkish Path Backtest

> Does market-implied hawkish repricing of the Fed path predict equity drawdowns?

## Signal Definition

```
ExpectedShortRate_1Y = THREEFF0100.B - THREEFFTP0100.B  (Kim-Wright model)
HawkishPath = ExpectedShortRate_1Y - DFF (FRED effective fed funds rate)

Danger Zone ("Strongly Hawkish"):
  HP > 0.50%  AND  ΔExpectedRate_1Y_4w > 0.25%
```

**Key correction (v2):** Uses ΔExpectedRate_1Y (change in the *expected* future rate itself), NOT ΔHP (change in the gap). This prevents false positives from crisis normalization — when the Fed emergency-cuts but the expected future rate stays flat, HP rises mechanically without any hawkish repricing.

## Data Sources

| Source | Series | Range | Notes |
|:---|:---|:---|:---|
| [Kim-Wright Model](https://www.federalreserve.gov/data/yield-curve-tables/feds200533.csv) | THREEFF0100.B, THREEFFTP0100.B | 1990-01-02 → present | Fed staff research, **current vintage** |
| [FRED DFF](https://fred.stlouisfed.org/series/DFF) | DFF | 1954 → present | Effective Federal Funds Rate |
| Yahoo Finance | SPY, QQQ | SPY: 1993-01-29+, QQQ: 1999-03-10+ | ETF inception dates enforced |

## Primary Results: Episode-Level (≥60-day gap)

Continuous signal days are collapsed into independent episodes.
Only the **first entry day** of each cluster counts.

### QQQ — 13 Independent Episodes

| Metric | Value |
|:---|:---|
| 3M mean return | **-0.86%** (vs +3.2% baseline) |
| 3M % negative | **62% (8/13)** (vs 31% baseline) |
| 6M mean return | **-4.77%** (vs +6.4% baseline) |
| 6M % negative | **69% (9/13)** (vs ~28% baseline) |

### SPY — 17 Independent Episodes

| Metric | Value |
|:---|:---|
| 3M mean return | +1.20% (vs +2.4% baseline) |
| 3M % negative | 53% (9/17) (vs 30% baseline) |
| 6M mean return | -0.51% (vs +4.9% baseline) |

### Permutation Test (100k block-bootstrap)

Random 13 dates drawn with ≥60-day spacing, repeated 100,000 times:

| QQQ Metric | Real Signal | Random Mean | Empirical p-value |
|:---|:---|:---|:---|
| 3M mean return | -0.86% | +3.06% | **p = 0.106** |
| 3M % negative | 62% | 32% | **p = 0.020** |
| 6M mean return | -4.77% | +6.39% | **p = 0.008** |

### Execution Lag Sensitivity

| Lag | QQQ 3M Mean | 3M %Neg | 6M Mean | 6M %Neg |
|:---|:---|:---|:---|:---|
| t+0 | -0.86% | 62% | -4.77% | 69% |
| t+1 | -0.83% | 62% | -4.34% | 69% |
| t+2 | -0.32% | 54% | -3.44% | 69% |

### Cooldown Sensitivity

| Cooldown | N | QQQ 3M Mean | 3M %Neg | 6M Mean | 6M %Neg |
|:---|:---|:---|:---|:---|:---|
| 20d | 18 | -0.54% | 56% | -3.21% | 67% |
| 40d | 15 | -0.88% | 60% | -4.07% | 67% |
| 60d | 13 | -0.86% | 62% | -4.77% | 69% |
| 90d | 11 | +0.10% | 64% | -2.93% | 73% |
| 120d | 10 | -1.73% | 70% | -5.64% | 80% |

## Caveats

1. **Current-vintage backtest.** Kim-Wright model parameters may differ from what was available in real time.
2. **Small sample.** N=13 episodes; 95% CI for hit rate is wide (~35%-85%).
3. **Overlapping forward windows.** 60-day cooldown < 3M horizon → some return overlap.
4. **Publication lag.** Kim-Wright updates approximately weekly; DFF publishes T+1. Signal tested at t+1 shows minimal degradation.

## Files

- `hawkish_path_backtest_v2.py` — Daily signal construction and regime-conditional returns
- `episode_robustness.py` — Episode clustering with configurable cooldown
- `final_validation.py` — Block permutation test, execution lag, cooldown sensitivity
- `hawkish_path_v2_results.csv` — Regime-conditional return statistics
- `hawkish_path_v2_signal.csv` — Daily signal timeseries (1990-2026)

## Running

```bash
python3 hawkish_path_backtest_v2.py    # daily signal
python3 episode_robustness.py          # episode clustering
python3 final_validation.py            # full validation suite (takes ~2min for 100k perms)
```

Requires: `pandas`, `numpy`, `scipy`, `yfinance`, network access for Kim-Wright download.
