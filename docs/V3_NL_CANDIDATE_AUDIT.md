# V3-NL Candidate Audit

> **Net Liquidity as 5th layer in production engine**
> **Date: 2026-06-08 | Run via `strategy_engine.py` with T+1, gap/intra, NSL, costs**
> **Status: CANDIDATE — not sealed**

---

## Baseline Comparison

| Metric | v2 Sealed | v3 +NL | Δ |
|---|---|---|---|
| Sharpe | 1.53 | **1.56** | +0.03 |
| CAGR | 58.3% | **58.8%** | +0.5pp |
| MDD | -37.4% | **-33.9%** | **+3.5pp** |
| Trades | 62 | 70 | +8 |
| Trades/yr | 4.3 | 4.9 | +0.6 |

### IS / OOS / Forward Sharpe

| Period | v2 | v3 |
|---|---|---|
| IS (2012-2018) | 1.36 | 1.35 |
| Holdout (2019-2022) | 1.58 | **1.74** |
| Forward (2023-2026) | 1.81 | 1.81 |

> [!NOTE]
> IS is flat (NL data starts mid-2016, limited IS impact). Holdout improves significantly (+0.16). Forward unchanged.

---

## TC Stress

| TC (bps) | v2 | v3 |
|---|---|---|
| 0 | 1.57 | 1.61 |
| 25 | 1.53 | 1.56 |
| 50 | 1.47 | 1.50 |
| 100 | 1.35 | 1.37 |
| **200** | **1.14** | **1.13** |

> [!WARNING]
> TC200 is essentially flat (1.14 → 1.13). v3 does NOT improve TC robustness. The 8 extra trades at TC200 eat the small Sharpe gain.

---

## Hill Tests

### NL Trigger (recover=-0.5, lev=2x)

| NLT | Sharpe | CAGR | MDD |
|---|---|---|---|
| -0.5 | 1.57 | +57.6% | -33.9% |
| -1.0 | 1.57 | +58.5% | -33.9% |
| **-1.5** | **1.56** | **+58.8%** | **-33.9%** ◀ |
| -2.0 | 1.55 | +58.5% | -37.4% |
| -2.5 | 1.56 | +58.9% | -37.4% |

**Plateau: -0.5 to -1.5.** MDD step at -2.0 (loses the improvement).

### NL Recover (trigger=-1.5, lev=2x)

| NLR | Sharpe | MDD |
|---|---|---|
| -1.0 | 1.56 | -34.4% |
| **-0.5** | **1.56** | **-33.9%** ◀ |
| 0.0 | 1.56 | -34.6% |
| 0.5 | 1.56 | -34.5% |
| 1.0 | 1.57 | -33.9% |

**Completely flat.** Recover doesn't matter much.

### NL Leverage

| Target | Sharpe | MDD |
|---|---|---|
| 0x | 1.37 | -64.3% |
| **1x** | **1.59** | **-33.3%** |
| 2x | 1.56 | -33.9% ◀ |

> [!IMPORTANT]
> 0x is catastrophic (MDD -64.3%) because NL misfires during recoveries. 1x is slightly better than 2x but the difference is marginal. **2x is the safer choice** — less risk of selling too aggressively on a false signal.

---

## 2D Grid (NL Trigger × Recover)

```
         R=-1.0  R=-0.5  R=0.0  R=+0.5
T=-0.5     —      —     1.57   1.50
T=-1.0     —     1.57   1.57   1.52
T=-1.5   1.56   1.56   1.56   1.56
T=-2.0   1.55   1.55   1.55   1.55
T=-2.5   1.55   1.56   1.56   1.56
```

**Entire grid is a flat plateau (1.55–1.57).** Candidate is NOT on a peak.

---

## Ablation

| Config | Sharpe | CAGR | MDD |
|---|---|---|---|
| **Full v3 (all 5)** | **1.56** | +58.8% | **-33.9%** |
| No SEP | 1.17 | +51.4% | -60.5% |
| No overlays | 1.12 | +56.3% | -69.7% |
| **No NL (= v2)** | **1.53** | +58.3% | **-37.4%** |
| No Vol | 1.42 | +56.5% | -42.1% |
| No TIP/TLT | 1.33 | +55.4% | -41.2% |
| No Credit | 1.34 | +56.5% | -52.1% |

**Layer importance ranking:**
1. SEP (most important — removes → Sharpe 1.17)
2. Credit (removes → MDD -52.1%)
3. TIP/TLT (removes → MDD -41.2%)
4. Vol (removes → MDD -42.1%)
5. **NL (removes → MDD -37.4% vs -33.9% = +3.5pp)**

NL is the weakest layer but still contributes meaningful MDD improvement.

---

## NL Trade Log

Only **4 NL trades in 14 years**:

| Signal Date | Exec Date | Action | Equity | Context |
|---|---|---|---|---|
| 2016-10-12 | 2016-10-13 | 3x→2x | 5.68 | Fed balance sheet tightening |
| 2019-05-01 | 2019-05-02 | 3x→2x | 24.02 | QT + trade war |
| 2020-02-19 | 2020-02-20 | 3x→2x | 38.78 | Pre-COVID liquidity freeze |
| **2025-08-20** | **2025-08-21** | **3x→2x** | **476.61** | **Pre-blind-spot!** |

> [!TIP]
> The 2025-08-20 trade is exactly what we wanted — NL triggered 2 months BEFORE the worst drawdown, reducing exposure from 3x to 2x.

---

## 2025-2026 Blind Spot

| Period | v2 DD | v3 DD | NL Active | Improvement |
|---|---|---|---|---|
| Oct 25 → Mar 26 | -36.4% | **-33.9%** | 40 days | **+2.5pp** |
| Full 2025-2026 | -36.4% | **-33.9%** | 69 days | **+2.5pp** |

NL was active for 40-69 days during the blind spot period. It didn't fully prevent the drawdown but reduced it by 2.5pp.

---

## Verdict

### ✅ What NL does well
- MDD improvement: -37.4% → -33.9% (+3.5pp)
- Fixes part of the 2025-2026 blind spot (-36.4% → -33.9%)
- Hills are flat — robust to parameter changes
- Only 4 trades in 14 years — minimal disruption
- OOS Sharpe improves (1.58 → 1.74)
- Pre-COVID signal was perfectly timed

### ⚠️ Concerns
- TC200 is flat (1.14 → 1.13) — no improvement under heavy TC
- IS Sharpe slightly worse (1.36 → 1.35) — NL data too short for IS validation
- Forward standalone predictor failed (2024-2026: NL contraction → QQQ went UP)
- Only 10 years of data (vs 14 for other layers)
- Sharpe gain is small (+0.03)

### Recommendation

```
v2 sealed:    KEEP as production strategy
v3-NL:        SERIOUS CANDIDATE but NOT ready to seal
```

**Reasons to wait:**
1. TC200 not improving — means under heavy friction, NL adds no value
2. Data history too short (10 years) for confident IS/OOS
3. Forward period standalone signal reversed

**What would change the verdict:**
1. 2-3 more years of data (making IS/OOS more reliable)
2. TC200 improving to > 1.20
3. Another successful NL trigger in live market

### Current architecture (if approved)

```
SEP > Credit > TIP/TLT > Vol > NL > Default
                                 ↑
                         Only when all others = 3x
                         NL Z < -1.5 → 2x
                         NL Z > -0.5 → recover
```

### Parameters (candidate, not sealed)

```
NL_TRIGGER  = -1.5
NL_RECOVER  = -0.5
NL_LEV      = 2.0
NL_CHG_WINDOW = 63
NL_Z_WINDOW = 252
```
