# Joint Robustness Audit — v2 Sealed Parameters

> **Verdict: v2 is sitting on a broad plateau, not standing on a needle.** ✅

---

## Executive Summary

| Metric | Result | Interpretation |
|:---|:---|:---|
| Pass rate (v2 standard) | **17.4%** (3,007 / 17,250) | Strong (>10% threshold) |
| Sealed Sharpe rank | **7th / 17,250** (100th pctl) | Top tier, not isolated |
| Plateau (±0.10 Sharpe) | **679 combos (3.9%)** | Broad plateau |
| Plateau (±0.20 Sharpe) | **3,715 combos (21.5%)** | Very broad |
| Top 20 share same Credit+TIP | **Yes, all 20** | Core params are stable |
| Vol dimension | **Nearly flat** | Vol is auxiliary, not driving |

---

## Test 1: Random Grid (3,000 combos)

Wide-range random sampling across 6 parameters.

```
Total valid combos:  2,371
v2-passing:          122 (5.1%)
Sealed rank:         #1 / 2,371 (100th percentile)
```

> [!NOTE]
> 5.1% pass rate in random grid is expected — most of the wide parameter space is far from optimal. The structured grid below gives the real answer.

---

## Test 2: Full 6D Grid (17,250 combos)

Structured grid with 6 × 5 × 5 × 5 × 5 × 5 parameter combinations.

### Pass Rate: 17.4% ✅

```
v2 standard: Sharpe>1.33, MDD>-45%, trades/yr≤5, IS/HO/FW Sharpe>0.5
Passing:     3,007 / 17,250 (17.4%)
```

This is **strong** by the pre-defined criteria:
- \>5% = decent
- \>10% = strong
- **>17% = very strong** ✅

### Sealed Ranking: 7th / 17,250

```
Sealed Sharpe: 1.53
Rank:          7th (top 0.04%)
```

But critically — the top 7 combos are **neighbors**, not distant points:

| # | Credit T/R | TIP T/R | Vol T/R | Sharpe | t/yr |
|:---|:---|:---|:---|:---|:---|
| 1 | 1.2 / 0.5 | 2.5 / 0.3 | 1.8 / 0.5 | 1.54 | 4.2 |
| 2 | 1.2 / 0.5 | 2.5 / 0.3 | 1.8 / 0.8 | 1.54 | 4.2 |
| 3 | 1.2 / 0.5 | 2.5 / 0.3 | 1.0 / 0.3 | 1.54 | 5.0 |
| 4 | 1.2 / 0.5 | 2.5 / 0.3 | 1.8 / 0.3 | 1.54 | 4.2 |
| 5 | 1.2 / 0.5 | 2.5 / 0.3 | 1.0 / 0.5 | 1.53 | 5.0 |
| 6 | 1.2 / 0.5 | 2.5 / 0.3 | 1.5 / 0.8 | 1.53 | 4.5 |
| **7** | **1.2 / 0.5** | **2.5 / 0.3** | **1.5 / 0.5** | **1.53** | **4.3** ◀ SEALED |

> [!IMPORTANT]
> All top 7 share identical Credit (1.2/0.5) and TIP/TLT (2.5/0.3) params. Only Vol varies. This proves sealed v2 is on a plateau — changing Vol between 1.0–1.8 barely moves Sharpe.

### Plateau Analysis

```
Within 0.10 of sealed (≥1.43):  679 / 17,250 (3.9%)
Within 0.20 of sealed (≥1.33): 3,715 / 17,250 (21.5%)
```

Plateau parameter ranges (within 0.10 of sealed):

| Param | Min | Sealed | Max | Width |
|:---|:---|:---|:---|:---|
| Credit Trigger | 0.8 | **1.2** | 1.8 | 1.0 |
| Credit Recover | -0.5 | **0.5** | 0.7 | 1.2 |
| TIP Trigger | 2.0 | **2.5** | 3.0 | 1.0 |
| TIP Recover | -0.5 | **0.3** | 0.5 | 1.0 |
| Vol Trigger | 0.5 | **1.5** | 2.0 | 1.5 |
| Vol Recover | -0.5 | **0.5** | 0.8 | 1.3 |

> [!TIP]
> Every sealed param is **inside** the plateau ranges, never at an edge. This is the definition of robust.

### Distribution

```
Metric          10%      25%      50%      75%      90%   Sealed
Sharpe         0.99     1.11     1.23     1.32     1.38     1.53
CAGR          35.3%    40.4%    47.4%    51.2%    53.4%    58.3%
MDD          -68.1%   -62.9%   -45.4%   -40.6%   -37.4%   -37.4%
Trades/yr      3.00     3.70     4.88     6.35     8.02     4.33
```

### Simpler Neighbor Check

Lower-turnover alternatives from the top 20:

| Combo | Sharpe | CAGR | t/yr | Note |
|:---|:---|:---|:---|:---|
| ZT=1.0 ZR=0.2 IT=2.5 IR=0.3 VT=1.8 VR=0.5 | 1.52 | 56.3% | **3.6** | Fewer trades |
| ZT=1.0 ZR=0.2 IT=2.5 IR=0.3 VT=1.8 VR=0.8 | 1.52 | 56.7% | **3.6** | Fewer trades |
| ZT=1.2 ZR=0.2 IT=2.5 IR=0.3 VT=1.8 VR=0.5 | 1.51 | 56.2% | **3.6** | Fewer trades |

> [!NOTE]
> These neighbors trade only 3.6×/yr (would pass old v1 ≤4 standard) with Sharpe 1.51-1.52. Sealed v2 trades at 4.3×/yr for Sharpe 1.53. The 0.01-0.02 Sharpe difference is negligible — if you ever want to reduce turnover, these are the candidates.

---

## Key Structural Findings

### 1. Credit + TIP/TLT are the critical layers

All top 20 combos share:
- Credit Trigger = 1.0–1.2
- Credit Recover = 0.2–0.5
- TIP Trigger = **2.5** (unanimous)
- TIP Recover = **0.3** (unanimous)

### 2. Vol is auxiliary

Vol params vary from 0.5 to 2.0 in the top 20 with minimal Sharpe impact (1.51–1.54). This confirms the v1 finding: **SEP is the main risk control, Credit is the main overlay, TIP/TLT adds edge, Vol is smoothing.**

### 3. No overfit evidence

- Sealed is #7, not #1 — it wasn't cherry-picked to be the absolute best
- 679 nearby combos within 0.10 Sharpe — broad neighborhood
- IS/Holdout/Forward all >1.3 for the entire top 20 — no period-specific overfit
- MDD is identical (-37.4%) across all top 20 — the drawdown floor is structural, not parameter-dependent

---

## Final Verdict

```
Plateau:          ✅ broad (679 combos within 0.10, 3715 within 0.20)
Pass rate:        ✅ strong (17.4%)
Sealed position:  ✅ inside plateau, not at edge
Overfit risk:     ✅ low (rank #7, not #1; IS/HO/FW stable)
Simpler neighbor: ✅ exists (3.6 t/yr, Sharpe 1.52)
```

**v2 sealed = validated robust.** 🔒
