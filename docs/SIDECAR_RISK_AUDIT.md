# Sidecar Risk Audit — v2 Sealed Strategy

> **Purpose: Test what v2 still misses. Do NOT change production rules.**
> **Date: 2026-06-07 | Baseline: v2 sealed (Sharpe 1.53, MDD -37.4%)**

---

## Executive Summary

| Test | Verdict | Action |
|---|---|---|
| **1. Valuation** | ⭐ **Promising** — Val>1.25 has 93% 20d loss rate | Future v3 candidate |
| **2. Earnings** | ⚠️ Weak standalone signal | Dashboard explanation only |
| **3. Concentration** | ❌ NOT a sell signal (high conc → market UP) | Dashboard monitor only |
| **4. Liquidity** | ⭐ **Promising** — net liq contraction leads weakness | Future v3 candidate |
| **5. TQQQ Product** | ✅ Healthy (-2.13 bps/day drag, expected) | Dashboard health monitor |
| **6. Failure Audit** | 🔴 #2 worst DD (-36.4%) had NO signal fired | Key blind spot identified |

---

## Test 1: Valuation ⭐

### Data
- **Real Yield** (DGS10 − T10YIE): daily from 2003, current 2.11%
- **Valuation proxy**: QQQ / SMA200 ratio, current 1.136

### Findings

#### Valuation alone predicts weakness

| Threshold | Days | Fwd 20d | % Negative | Normal |
|---|---|---|---|---|
| Val > 1.10 | 1,396 | +0.91% | 37% | +1.99%, 29% |
| Val > 1.15 | 397 | +0.36% | 42% | +1.72%, 31% |
| Val > 1.20 | 133 | +0.63% | 38% | +1.61%, 32% |
| **Val > 1.25** | **15** | **-5.13%** | **93%** | +1.60%, 32% |

> [!IMPORTANT]
> Val > 1.25 is extremely rare (15 days) but has 93% negative forward return. Small sample but striking.

#### Valuation × Real Yield interaction

| Condition | Days | Fwd 20d | Fwd 60d | % Neg 60d |
|---|---|---|---|---|
| Val > 1.10 + RY↑ > 0.0 | 645 | +0.90% | +2.82% | 30% |
| **Val > 1.15 + RY↑ > 0.3** | **53** | **+0.16%** | **-0.48%** | **51%** |
| Val > 1.10 + RY↑ > 0.5 | 49 | +0.88% | +3.67% | 31% |

**Expensive + real yield rising → negative 60d return with 51% probability.** This is the interaction that might add edge beyond TIP/TLT.

### Verdict
Dashboard worthy + future v3 trading rule candidate. The Val > 1.15 + RY↑ > 0.3 combo deserves a proper backtest as a 5th layer.

---

## Test 2: Earnings ⚠️

### Data
- **Corporate Profits (FRED CP)**: quarterly from 1946, current YoY +2.8%
- **SOXX/QQQ ratio**: daily from 2005, current Z = 3.35

### Findings

#### Earnings × Real Yield interaction

| Condition | Days | Fwd 20d | % Neg |
|---|---|---|---|
| RY high + earnings weak | 421 | +2.07% | 29% |
| RY high + earnings strong | 378 | +2.51% | 27% |
| RY low + earnings weak | 1,800 | +1.22% | 35% |
| RY low + earnings strong | 1,013 | +1.67% | 29% |

> [!NOTE]
> Earnings strength doesn't meaningfully differentiate — RY high periods actually have HIGHER returns regardless of earnings. This is likely because high real yield = post-crisis recovery.

#### Corporate profit contraction

| Condition | Fwd 20d | Fwd 60d |
|---|---|---|
| CP growth < 0% | +1.36% | +4.86% |
| CP growth < -5% | +1.88% | +5.99% |
| **CP growth < -10%** | **-0.93%** | **-6.05%** |

Only severe profit collapse (< -10% YoY) predicts weakness, but it's quarterly and lagging.

### Verdict
Not actionable as a trading signal. Useful for dashboard narrative ("why is QQQ still up despite rate pressure? → earnings are strong"). SOXX/QQQ ratio is an interesting watchlist item.

---

## Test 3: Concentration ❌

### Data
- **QQQ/QQQE ratio**: daily from 2012, current 1.76x (normalized)
- **Concentration Z**: 63d change / 252d z-score, current 0.14

### Findings

| Concentration | Days | Fwd 20d | % Neg | Normal |
|---|---|---|---|---|
| Conc Z > 1.0 | 706 | +1.02% | 35% | +1.80%, 31% |
| Conc Z > 1.5 | 361 | +1.83% | 30% | +1.60%, 32% |
| **Conc Z > 2.0** | **158** | **+3.07%** | **28%** | +1.55%, 32% |

> [!WARNING]
> **High concentration is BULLISH, not bearish.** When a few stocks dominate, they tend to keep dominating. Concentration is NOT a risk signal — it's a momentum signal.

### Verdict
Dashboard monitor only. Do NOT use as sell trigger. Shows market structure context.

---

## Test 4: Liquidity ⭐

### Data Available (FRED)

| Series | Description | From | Frequency |
|---|---|---|---|
| WALCL | Fed Balance Sheet | 2002 | Weekly |
| RRPONTSYD | Reverse Repo | 2003 | Daily |
| WTREGEN | Treasury General Account | 2015 | Weekly |
| NFCI | National Financial Conditions | 1971 | Weekly |
| WM2NS | M2 Money Supply | 1981 | Weekly |
| SOFR | Secured Overnight Rate | 2018 | Daily |

### Key Finding: NFCI/STLFSI are redundant with Credit Z

```
NFCI vs Credit Z correlation:  +0.680 (concurrent)
STLFSI vs Credit Z correlation: +0.671 (concurrent)
```

These stress indices track the SAME thing as Credit Z. Not useful as additional signal.

### Key Finding: Net Liquidity contraction IS a leading indicator

**Net Liquidity = WALCL − RRPONTSYD − WTREGEN**

| Condition | Days | Fwd 20d | % Neg | Normal |
|---|---|---|---|---|
| NL Z < -1.0 | 487 | +0.28% | 40% | +1.78%, 31% |
| NL Z < -1.5 | 256 | -0.48% | 44% | +1.73%, 31% |
| **NL Z < -2.0** | **107** | **-1.09%** | **47%** | +1.66%, 31% |

Net liquidity contraction (NL Z < -1.5) predicts negative QQQ returns. And it's only weakly correlated with Credit Z (+0.164) — meaning it captures a **different risk dimension**.

> [!TIP]
> Net Liquidity is the most promising new sidecar indicator. It's low-correlation with Credit Z and has predictive power. However, data only from 2015 — insufficient for proper IS/OOS/FWD testing.

### Verdict
Net liquidity is a future v3 candidate, but needs longer data. Dashboard monitor now, trading rule test when data matures.

---

## Test 5: TQQQ Product ✅

### Tracking Quality

| Metric | Value |
|---|---|
| Daily tracking error | 0.186% |
| Annualized tracking error | 3.0% |
| Mean daily drag | -2.13 bps |
| Cumulative drift (2010-2026) | -54.7% |
| Current rolling 1yr TE | 0.86% (best ever) |

### Tracking by period

| Period | Daily TE | Mean Drag | Drift |
|---|---|---|---|
| 2012-2015 | 0.119% | -0.62 bps | -6.2% |
| 2016-2019 | 0.129% | -1.83 bps | -16.9% |
| 2020-2022 | 0.299% | -2.22 bps | -15.8% |
| 2023-2026 | 0.088% | -4.81 bps | -33.9% |

> [!NOTE]
> Tracking error improved dramatically (0.088% in 2023-2026, down from 0.299% in COVID era). But mean drag increased to -4.81 bps, likely due to higher financing costs. The strategy engine already models this via EXPENSE_RATIO and borrowing cost.

### Verdict
Product is healthy. Current TE at historic lows. Drag is expected and modeled. Dashboard health monitor only — no action needed.

---

## Test 6: Failure Case Audit 🔴

### Top 5 Worst Drawdowns

| # | Peak → Trough | DD | Lev | SEP | Credit | TIP/TLT | Vol | Blind? |
|---|---|---|---|---|---|---|---|---|
| 1 | 2020-02-19 → 03-16 | **-37.4%** | 1x | IN | ✅ YES | NO | ✅ YES | No — captured |
| **2** | **2025-10-29 → 2026-03-30** | **-36.4%** | **3x** | IN | NO | NO | NO | **YES — BLIND** |
| 3 | 2012-04-02 → 06-01 | -30.1% | 3x | IN | YES | NO | NO | Partial |
| 4 | 2015-07-20 → 2016-06-27 | -24.3% | 3x | IN | NO | NO | NO | YES |
| 5 | 2019-04-29 → 06-03 | -23.6% | 1x | IN | ✅ YES | NO | NO | No — captured |

> [!CAUTION]
> **The #2 worst drawdown (-36.4%, Oct 2025 → Mar 2026) was completely uncaptured.** System held 3x the entire time. All z-scores were near zero. This is the primary blind spot.

### Worst Months at 3x

| Month | Return | All signals safe? | What was missing? |
|---|---|---|---|
| 2012-05 | -20.4% | ⚪ all safe | Credit Z rising but below trigger |
| 2026-03 | -15.5% | ⚪ all safe | Unknown — possible valuation? |
| 2016-04 | -12.1% | ⚪ all safe | Low vol, low credit stress |
| 2026-06 | -13.8% | Vol danger only | Vol just triggered |

### What v2 already captured well

The 2022 bear market: QQQ -35%, 3x synth -80%, **v2 was only -8.5%** (SEP had system at 0x). This saved **72 percentage points** — the single biggest win.

### Blind spot diagnosis

The 2025-2026 drawdown shows:
- Credit spreads didn't widen significantly
- TIP/TLT didn't spike
- Vol didn't spike
- SEP was still dovish

This suggests the missing dimension may be **valuation** (QQQ was extended) or **liquidity** (net liquidity may have contracted), not credit/vol.

---

## Recommendations

### 1. Future v3 Trading Rule Candidates

| Indicator | Why | Data From | Risk |
|---|---|---|---|
| **Valuation (QQQ/SMA200 + Real Yield)** | Val>1.15+RY↑ predicts 60d weakness | 2003 | Small sample at extreme |
| **Net Liquidity (WALCL-RRP-TGA)** | NL Z<-1.5 predicts weakness, low correlation with Credit Z | 2015 | Short history, weekly data |

> [!IMPORTANT]
> Both candidates need proper backtesting with IS/OOS/FWD split, TC stress, and parameter plateau before consideration. Do NOT add to v2 without full testing protocol.

### 2. Dashboard Additions (no trading impact)

| Indicator | Purpose |
|---|---|
| QQQ/SMA200 ratio | Valuation context |
| Real Yield | Rate pressure context |
| SOXX/QQQ ratio | Tech earnings momentum |
| QQQ/QQQE ratio | Concentration context |
| TQQQ tracking error | Product health |
| Net Liquidity | Liquidity regime context |

### 3. Redundant / Do Not Add

| Indicator | Why |
|---|---|
| NFCI | Correlation 0.68 with Credit Z — same signal |
| STLFSI | Correlation 0.67 with Credit Z — same signal |
| Corporate profits | Quarterly, lagging, weak predictive power |
| Concentration as sell signal | High concentration is BULLISH |

### 4. Final Verdict

```
v2 sealed:     KEEP UNCHANGED
Dashboard:     ADD valuation + liquidity + concentration monitors
v3 candidate:  Valuation layer (Val > 1.15 + RY↑) needs full test
v3 candidate:  Net Liquidity layer needs longer data (2015 start too short)
Primary blind spot: 2025-2026 drawdown at 3x — not captured by any layer
```
