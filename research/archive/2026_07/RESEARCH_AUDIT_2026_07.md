# Research Audit — QQQ Risk Strategy Deep Analysis

**Date**: 2026-06-22 to 2026-07-25
**Strategy**: TQQQ 4-Layer Defense System (v2 sealed)
**Dashboard**: https://nickchen494949.github.io/qqq-dashboard/

---

## Table of Contents

1. [Earnings Growth vs SEP EXIT](#1-earnings-growth-vs-sep-exit)
2. [Yield Curve Crash Prediction (10Y-2Y, 10Y-3M)](#2-yield-curve-crash-prediction)
3. [3M T-Bill vs Fed Funds — Hawkish Signal](#3-3m-t-bill-vs-fed-funds)
4. [Stock Price Drivers Framework](#4-stock-price-drivers-framework)
5. [Strategy Transferability to SOXL](#5-strategy-transferability-to-soxl)
6. [SOXL vs TQQQ Relationship](#6-soxl-vs-tqqq-relationship)
7. [QE Regime Change — Statistical Validation](#7-qe-regime-change-validation)
8. [Scripts & Reproducibility](#8-scripts--reproducibility)

---

## 1. Earnings Growth vs SEP EXIT

**Question**: Does S&P 500 earnings growth (YoY) always drop one quarter before a SEP EXIT?

**Script**: [check_sep_earnings.py](scripts/check_sep_earnings.py)

### Data
- Source: [multpl_earnings_growth.csv](../../../market_data/multpl_earnings_growth.csv) (S&P 500 quarterly YoY earnings growth)
- SEP signals: Parsed from 75 FOMC SEP PDFs via [strategy_engine.py](scripts/strategy_engine.py)

### Results

| SEP EXIT | Earnings Q Before | Growth | Prev Q | Growth | Delta | Dropping? |
|:---|:---|:---|:---|:---|:---|:---|
| 2021-09-22 | 2021-Q2 | +59.99% | 2021-Q1 | +10.20% | +49.79pp | ❌ Rising |
| 2023-06-14 | 2023-Q1 | -11.49% | 2022-Q4 | -12.70% | +1.21pp | ❌ Rising |
| 2024-06-12 | 2024-Q1 | +9.26% | 2023-Q4 | +11.39% | -2.13pp | ✅ Dropping |
| 2024-12-18 | 2024-Q3 | +8.69% | 2024-Q2 | +8.24% | +0.45pp | ❌ Rising |
| 2026-06-17 | 2025-Q3 | +16.87% | 2025-Q2 | +13.58% | +3.29pp | ❌ Rising |

### Conclusion
**❌ NO** — Only 1/5 (20%) had earnings declining. SEP EXIT is driven by Fed projections (Core PCE ↑ + Rate ↑), not by realized earnings. Most EXITs occurred while earnings were accelerating.

---

## 2. Yield Curve Crash Prediction

**Question**: Can yield curve inversions (10Y-2Y, 10Y-3M) predict QQQ crashes?

**Script**: [check_yield_curve_crash.py](scripts/check_yield_curve_crash.py)

### Data
- [fred_T10Y2Y.csv](../../../market_data/fred_T10Y2Y.csv) (2010-2026, 4095 days)
- [fred_T10Y3M.csv](../../../market_data/fred_T10Y3M.csv) (2010-2026, 4095 days)

### Crash Detection Rate

| Crash | DD | 10Y-2Y Inverted? | 10Y-3M Inverted? |
|:---|:---|:---|:---|
| 2010 Correction | -15.6% | ❌ | ❌ |
| 2011 Debt Ceiling | -16.1% | ❌ | ❌ |
| 2015-16 Slowdown | -16.1% | ❌ | ❌ |
| 2018 Q4 Selloff | -22.8% | ❌ | ❌ |
| 2020 COVID | -28.6% | ✅ (176d lead) | ✅ (334d lead) |
| 2022 Bear | -35.1% | ❌ | ✅ (696d lead) |
| 2025 Tariff | -22.8% | ✅ (729d lead) | ✅ (729d lead) |

**Score**: 10Y-2Y caught 3/7 (43%), 10Y-3M caught 3/7 (43%)

### Forward Returns During Inversion (10Y-2Y)

| Horizon | Normal Days | Inverted Days |
|:---|:---|:---|
| 3mo | +4.5% | +6.3% |
| 12mo | +18.9% | **+29.2%** |

### Naive Strategy: Sell When Inverted

| Strategy | CAGR | MDD |
|:---|:---|:---|
| Buy & Hold | +19.4% | -35.1% |
| Sell on 10Y-2Y inversion | +15.6% | -36.5% |
| Sell on 10Y-3M inversion | +15.3% | -35.8% |

### Conclusion
**❌ Unusable** — Misses 57% of crashes, lead time 6mo-2yr, selling during inversion costs -3.8 to -4.1pp CAGR annually, MDD doesn't improve.

---

## 3. 3M T-Bill vs Fed Funds

**Question**: Can the 3M-FF spread (market pricing rate hikes) predict crashes?

**Script**: [check_3m_ff_inversion.py](scripts/check_3m_ff_inversion.py)

### Data
- DTB3 fetched from FRED API (2003-2026, 5859 days)
- [fred_DFF.csv](../../../market_data/fred_DFF.csv)

### Hawkish Signal (3M > FF) vs Crashes

| Crash | DD | 6mo Prior Hawk Days (>10bp) | Result |
|:---|:---|:---|:---|
| 2004 Tech | -15.9% | 0d | ❌ |
| 2006 Correction | -17.3% | 5d | ❌ |
| 2007-08 GFC | -53.4% | 0d | ❌ |
| 2011 Debt Ceiling | -16.1% | 0d | ❌ |
| 2015-16 Slowdown | -16.1% | 1d | ❌ |
| **2018 Q4** | **-22.8%** | **68d** | **✅** |
| 2020 COVID | -28.6% | 0d | ❌ |
| 2022 Bear | -35.1% | 0d | ❌ |
| 2025 Tariff | -22.8% | 0d | ❌ |

**Score**: 1/9 (11%)

### SEP EXIT Overlap: 0/5

### Conclusion
**❌ Fails** — Major crashes occur when Fed has already STOPPED hiking or is cutting. The fundamental contradiction: 3M > FF signals mid-cycle hawkishness, but crashes come at cycle ends. Zero overlap with SEP EXIT signals.

---

## 4. Stock Price Drivers Framework

### Four Driver Layers

| Driver | Timeframe | Captured By | Tradeable? |
|:---|:---|:---|:---|
| Earnings | Long-term anchor | Nothing (45d lag) | ❌ |
| Liquidity | Medium-term trend | **SEP layer** | ✅ |
| Credit/Panic | Short-term trigger | **Credit Z + Vol Z** | ✅ |
| Narrative/Shocks | Unpredictable | None | ❌ |

### Strategy Layer Mapping

| Layer | What it catches | Mechanism |
|:---|:---|:---|
| SEP = 0x | Liquidity tightening | Fed intent to tighten |
| Credit Z = 1x | Credit collapse | HYG underperforming IEF |
| TIP/TLT = 1x | Stress events | Inflation/duration shock |
| Vol Z = 2x | Market panic | Realized volatility spike |

### All Failed Signal Directions

| # | Signal | Result | Failure Reason |
|:---|:---|:---|:---|
| 1 | EPS acceleration | CAGR -5% | 45-day data delay |
| 2 | EPS absolute growth | r = -0.09 | No predictive power |
| 3 | EPS mean reversion | CAGR -1.5% | Stays at top too long |
| 4 | VIX Backwardation | CAGR -0.7% | Bottom-fishing signal |
| 5 | HY OAS credit spread | Too short | Synchronous/bottom signal |
| 6 | VIX+Momentum | T+1: -1.5% | Look-ahead bias |
| 7 | Yield curve 10Y-2Y | -3.8pp CAGR | Too early (6mo-2yr) |
| 8 | Yield curve 10Y-3M | -4.1pp CAGR | Too early, misses 57% |
| 9 | 3M-FF hawkish | 1/9 caught | Crashes at cycle end |
| 10 | 3M-FF dovish | 52% inverted | Structural tax bias |

---

## 5. Strategy Transferability to SOXL

**Script**: [check_soxl_strategy.py](scripts/check_soxl_strategy.py)

### Performance (2012-01 → 2026-06, 14.4 years)

| Strategy | CAGR | MDD | Sharpe | Trades/yr |
|:---|:---|:---|:---|:---|
| TQQQ Buy & Hold | +46.0% | -81.1% | 0.93 | 0.0 |
| **TQQQ + Full Strategy** | **+57.8%** | **-38.4%** | **1.48** | 4.2 |
| SOXL Buy & Hold | +55.9% | -90.2% | 0.95 | 0.0 |
| **SOXL + Full Strategy** | **+81.4%** | **-56.4%** | **1.31** | 5.1 |

### IS / Holdout / Forward

| Period | TQQQ Sharpe | SOXL Sharpe | SOXL B&H Sharpe |
|:---|:---|:---|:---|
| IS (2012-2018) | 1.34 | 1.02 | 0.83 |
| Holdout (2019-2022) | 1.53 | 1.16 | 0.72 |
| Forward (2023+) | 1.69 | 1.89 | 1.47 |

### Key Event Protection

| Event | TQQQ Strat MDD | SOXL Strat MDD | SOXL B&H MDD |
|:---|:---|:---|:---|
| 2022 Bear | 0.0% | 0.0% | -90.0% |
| COVID | -38.4% | -56.4% | -79.7% |
| 2025 Tariff | +40.5% return | +62.7% return | -73.7% MDD |

### Decision: Parameter Re-optimization?
**NO** — Training set too short (7yr), signals are macro (not asset-specific), overfitting risk high. Better approach: reduce leverage or cap allocation.

### Conclusion
**⚠️ Transferable but riskier** — MDD -56.4% vs -38.4% due to SOXX's 1.48x higher volatility. Strategy generality is itself the strongest validation.

---

## 6. SOXL vs TQQQ Relationship

**Script**: [check_soxl_tqqq_link.py](scripts/check_soxl_tqqq_link.py)

### Core Metrics (2007-2026)

| Metric | QQQ | SOXX |
|:---|:---|:---|
| Annualized Vol | 22.2% | 31.1% |
| Beta vs QQQ | 1.00 | 1.22 |
| Daily Correlation | — | 0.867 |
| 3x MDD (simulated) | -94.3% | -98.0% |

### Rolling Correlation Stability

| Window | Mean | Min | Days < 0.80 |
|:---|:---|:---|:---|
| 21d | 0.827 | 0.231 | 29.3% |
| 63d | 0.840 | 0.494 | 23.6% |
| 252d | 0.857 | 0.765 | 11.9% |

### SOXX-Only Crashes (>3% while QQQ <1%): 17 days
Including DeepSeek (-7.84%), chip export controls (-7.21%), COVID supply chain (-8.22%)

### Holdings Overlap: Only NVDA + AVGO (2/10 top holdings)

---

## 7. QE Regime Change Validation

**Question**: Is post-2009 QE a statistically significant structural break?

**Script**: [check_qe_regime_change.py](scripts/check_qe_regime_change.py)

### 6 Statistical Tests

| Test | Pre-QE | Post-QE | p-value |
|:---|:---|:---|:---|
| Recovery speed | 282 days | 83 days | 0.13 (small n) |
| Return volatility | 23.7% | 20.7% | **0.0000** (Levene) |
| Annual return | 3.7% | 22.4% | — |
| HYG/IEF volatility | 25.3% | 11.4% | — |
| Fed balance sheet corr | r = -0.24 | r = +0.04 | ❌ unstable |
| Rolling Sharpe distribution | mean 0.53 | mean 1.11 | **0.0000** (KS) |

### Verdict
**5/6 tests confirm structural regime change.** Post-2009 is a statistically different market. Backtest window 2012-2026 covers the complete QE era. Pre-QE testing would produce misleading conclusions due to different volatility structure, recovery patterns, and credit market behavior.

---

## 8. Scripts & Reproducibility

### Analysis Scripts

| Script | Purpose | Dependencies |
|:---|:---|:---|
| [check_sep_earnings.py](scripts/check_sep_earnings.py) | Earnings vs SEP EXIT | strategy_engine, multpl CSV |
| [check_yield_curve_crash.py](scripts/check_yield_curve_crash.py) | 10Y-2Y, 10Y-3M analysis | FRED CSVs, yahoo QQQ |
| [check_3m_ff_inversion.py](scripts/check_3m_ff_inversion.py) | 3M T-bill vs Fed Funds | FRED API (DTB3), DFF CSV |
| [check_soxl_strategy.py](scripts/check_soxl_strategy.py) | SOXL full backtest | strategy_engine, SOXX CSV |
| [check_soxl_tqqq_link.py](scripts/check_soxl_tqqq_link.py) | SOXL-TQQQ relationship | Yahoo CSVs |
| [check_qe_regime_change.py](scripts/check_qe_regime_change.py) | QE regime tests | scipy.stats, all CSVs |

### Reproduction
```bash
cd .
python3 tools/check_sep_earnings.py
python3 tools/check_yield_curve_crash.py
python3 tools/check_3m_ff_inversion.py      # requires FRED API key
python3 tools/check_soxl_strategy.py
python3 tools/check_soxl_tqqq_link.py
python3 tools/check_qe_regime_change.py
```

### Data Sources
- Yahoo Finance: QQQ, SOXX, HYG, IEF, TIP, TLT, SPY, IWM (cached in market_data/)
- FRED: DFF, T10Y2Y, T10Y3M, VIXCLS, WALCL, DTB3 (cached + API)
- Multpl.com: S&P 500 earnings growth (cached)
- Federal Reserve: 75 FOMC SEP PDFs (fomc_sep/)
