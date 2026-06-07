# V3 Quiet Bleed Layer — Audit Results

> **Candidate: Price Stretch > 1.20 + Net Liquidity Z < -1.5 → reduce to 1x**
> **Date: 2026-06-07**

---

## Executive Summary

| Metric | v2 Sealed | v3 Candidate | Change |
|---|---|---|---|
| Sharpe | 1.53 | **1.57** | +0.04 |
| CAGR | 58.3% | **60.1%** | +1.8pp |
| MDD | -37.4% | **-36.2%** | +1.2pp |
| TC200 Sharpe | 1.14 | **1.33** | +0.19 |
| Trades/yr | 4.3 | 4.5 | +0.2 |
| IS / HO / FW | 1.36/1.58/1.81 | 1.40/1.70/1.77 | All improved |

> [!WARNING]
> **The 2025-2026 blind spot (-36.4%) was NOT fixed.** During that drawdown, QQQ/SMA200 never exceeded 1.20 (max was 1.189), so the quiet bleed layer never triggered. The improvement comes from catching OTHER overextension episodes.

---

## Hill Tests

### Hill 1: Stretch Trigger (recover=1.10, NL=-1.5/-0.5)

| Value | Sharpe | CAGR | MDD |
|---|---|---|---|
| 1.05 | 1.56 | +58.7% | **-33.2%** |
| 1.10 | 1.56 | +58.5% | **-33.2%** |
| **1.15** | **1.59** | **+60.4%** | **-33.2%** |
| 1.20 | 1.57 | +60.1% | -36.2% ◀ |
| 1.25 | 1.54 | +58.8% | -38.2% |
| OFF | 1.54 | +58.8% | -38.2% |

**Plateau: 1.05–1.20.** Best MDD at 1.10–1.15 (-33.2%).

### Hill 2: Stretch Recover (trigger=1.20, NL=-1.5/-0.5)

| Value | Sharpe | MDD |
|---|---|---|
| 0.95 | 1.57 | -36.2% |
| 1.00 | 1.57 | -36.2% |
| 1.05 | 1.57 | -36.2% |
| **1.10** | **1.57** | **-36.2%** ◀ |
| 1.15 | 1.55 | -36.2% |

**Plateau: 0.95–1.15.** Extremely flat — recover threshold barely matters.

### Hill 3: NL Trigger (stretch=1.20/1.10, NL_R=-0.5)

| Value | Sharpe | MDD |
|---|---|---|
| -0.5 | 1.52 | -36.2% |
| -1.0 | 1.53 | -36.2% |
| **-1.5** | **1.57** | **-36.2%** ◀ |
| -2.0 | 1.54 | -38.2% |
| OFF | 1.54 | -38.2% |

**Plateau: -1.0 to -1.5.** NL trigger < -2.0 is too conservative (never fires enough).

### Hill 4: NL Recover (stretch=1.20/1.10, NL_T=-1.5)

| Value | Sharpe | MDD |
|---|---|---|
| -1.0 | 1.57 | -36.2% |
| -0.5 | 1.57 | -36.2% ◀ |
| 0.0 | 1.57 | -36.2% |
| 0.5 | 1.57 | -36.2% |
| 1.0 | 1.57 | -36.2% |

**Completely flat.** NL recover doesn't matter at all — the layer exits via stretch recovery.

### Hill 5: Target Leverage

| Value | Sharpe | MDD |
|---|---|---|
| 0x | 1.58 | -36.2% |
| **1x** | **1.57** | **-36.2%** ◀ |
| 2x | 1.55 | -36.2% |

All similar. 0x slightly better but more aggressive than needed.

---

## 4D Grid

```
Grid: 182 valid combos
v3-passing (beat v2): 52/182 (28.6%)
```

### Top 5

| ST | SR | NLT | NLR | Sharpe | CAGR | MDD | TC200 |
|---|---|---|---|---|---|---|---|
| 1.10 | 1.00 | -1.5 | 0.5 | **1.60** | +59.8% | **-33.2%** | 1.35 |
| 1.15 | 1.10 | -1.5 | -0.5 | 1.59 | +60.4% | **-33.2%** | 1.34 |
| 1.15 | 1.00 | -1.5 | -0.5 | 1.59 | +60.1% | **-33.2%** | 1.34 |
| 1.10 | 1.05 | -1.5 | -0.5 | 1.58 | +59.2% | **-33.2%** | 1.32 |
| 1.20 | 1.10 | -1.5 | -0.5 | 1.57 | +60.1% | -36.2% | 1.33 |

### Plateau

```
Within 0.10 of candidate: 182/182 (100%)
Within 0.20 of candidate: 182/182 (100%)
```

**Entire grid is one massive plateau.** Ranges:
- Stretch T: 1.10 – 1.30
- Stretch R: 1.00 – 1.10
- NL T: -2.0 – -0.5
- NL R: -1.0 – 0.5

---

## TC Stress

| TC (bps) | Sharpe | CAGR | MDD |
|---|---|---|---|
| 0 | 1.60 | +61.9% | -36.2% |
| 25 | 1.57 | +60.1% | -36.2% |
| 50 | 1.54 | +58.4% | -36.2% |
| 100 | 1.47 | +55.0% | -36.2% |
| 200 | 1.33 | +48.3% | -36.2% |

All TC levels pass Sharpe > 1.0. ✅

---

## 2025-2026 Blind Spot Check 🔴

```
v2 drawdown:  -36.4%
v3 drawdown:  -36.2%
Improvement:  +0.2pp (negligible)
QB triggered: NO
```

During Oct 2025 → Mar 2026:
- **Stretch range: 0.942 – 1.189** (never hit 1.20 trigger)
- **NL Z range: -2.03 – 1.58** (NL Z did go below -1.5 briefly)

**The stretch condition was not met** — QQQ was BELOW SMA200 for most of this drawdown. It was NOT an overextension selloff. It was a selloff FROM below-trend.

> [!CAUTION]
> This means the 2025-2026 drawdown is a different type of risk than "quiet bleed from overextension." It may be: tariff/policy shock, earnings disappointment, or rotation — none of which show up in price stretch or liquidity.

---

## Verdict

### ✅ What the quiet bleed layer does well
- Improves Sharpe, CAGR, MDD vs v2
- Massive plateau (100% of grid within 0.10)
- TC200 passes comfortably (1.33)
- IS/HO/FW all improve
- Catches overextension episodes where v2 holds 3x

### ❌ What it does NOT fix
- The specific 2025-2026 blind spot (QQQ was below SMA200)
- Any non-overextension drawdown

### Recommendation

```
v2 sealed:   KEEP
v3 QB layer: PROMISING but NOT ready to seal
```

Reasons to wait:
1. NL data only from 2015 — short IS period
2. Does not fix the primary identified blind spot
3. The best combo (ST=1.10, MDD=-33.2%) may be too aggressive for production

If adding to dashboard as monitor: **YES, immediately useful.**
If adding as production trading rule: **needs more history and a real OOS period.**
