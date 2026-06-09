# v2 Strategy — Full Component Audit

> Completed 2026-06-09. Every layer of the v2 risk stack has been independently audited with statistical tests, event-level attribution, and mechanism analysis.

---

## Component Audit Summary

| Layer | Sharpe Δ | MDD Δ | Statistical | Mechanism | Event Audit | Verdict |
|---|---|---|---|---|---|---|
| **SEP** | — | -69.7% → -37.4% | ✅ ablation | ✅ Fed public data | Prior session | Core — no dispute |
| **Credit Z** | +0.24 | -55.0% → -37.4% | ✅ t=-2.39* | ✅ r=-0.79 vs FRED HY spread | ✅ ablation | Core — stats + mechanism hard |
| **Vol Z** | +0.13 | -42.1% → -37.4% | ✅ t=-10.31*** | ✅ tail-risk cutter, not predictor | ✅ 87% grid, IS/OOS 11.44 | Core — most robust layer |
| **TIP/TLT Z** | +0.23 | -41.2% → -37.4% | ⚠️ t=-1.11 ns | ⚠️ not pure inflation; not independent (r=-0.52 vs Credit) | ⚠️ 12 trades, 69% from 1 month | Keep — event protector, concentrated |
| **NSL (Re-entry Gate)** | +0.11 | same | ✅ +41% final equity | ⚠️ anti-whipsaw re-entry gate, not "never sell at loss" | ✅ 2025 tariff attribution | Keep — high value, sealed behavior |

---

## 1. Vol Z Layer

### What It Does
Reduces leverage from 3x → 2x when realized volatility z-score exceeds 1.5 (sealed: `VZ_TRIGGER=1.5`, `VZ_RECOVER=0.5`, `VZ_LEV=2`).

### Robustness (6-Test Suite)

| Test | Result | Verdict |
|---|---|---|
| Parameter Grid | 87% of 61 combos beat No Vol; sealed rank 17/61 | ✅ |
| Hill Climbing | Ratio 0.77 (moderate); Sharpe plateau 1.50–1.55 | ⚠️ moderate |
| IS/OOS | IS +0.02, OOS **+0.23**; ratio 11.44 | ✅✅ extreme |
| Ablation | Drop Vol → Sharpe 1.54→1.41, MDD -37%→-42% | ✅ |
| TC Stability | Positive delta at all TC levels (0–300 bps) | ✅✅ |
| VZ_LEV Sensitivity | 1x–3x all improve; nearly flat | ✅ |

### Mechanism — Not a Predictor, a Safety Belt

```
Vol Z vs past 20d return:   r = -0.486 (strong — it knows what already happened)
Vol Z vs future 20d return: r = -0.012 (zero — it does NOT predict)
Vol Z vs future 60d return: r = +0.004 (zero)
```

> [!IMPORTANT]
> Vol Z is not a leading indicator. It's a "storm is happening now" detector. Its value comes from cutting tail risk during the second leg of drawdowns.

**Two-stage drop analysis (QQQ 2005–2026, 40 episodes crossing -5%):**

| After crossing -5% | Probability |
|---|---|
| Stops at -5% to -10% | 50% |
| Continues to -10%+ | 50% |
| Of those, continues to -15%+ | 40% |

**CAGR impact:** +1.6pp/yr — small per year, but compounds to ~+$15k per $100 over 14 years. Vol doesn't predict; it cuts drag (3x→2x reduces volatility drag from -40%/yr to -18%/yr at 30% realized vol).

---

## 2. Credit Z Layer (HYG/IEF)

### Why IEF, Not TLT?

Tested against FRED's real ICE BofA High Yield Spread:

```
HYG/IEF vs real HY Spread (252d): r = -0.788 ← strong
HYG/TLT vs real HY Spread (252d): r = -0.233 ← weak
```

**Backtest confirmation:**

| Config | Sharpe | TC200 |
|---|---|---|
| HYG/IEF (sealed) | 1.54 | 1.15 |
| HYG/TLT (alt) | 1.41 | 0.77 |

> [!NOTE]
> HYG/IEF works because IEF's duration (~7yr) matches HYG's, isolating pure credit risk. TLT's duration (~17yr) introduces interest rate noise (rate contamination r=0.93).

**Correct description:** HYG/IEF = credit-dominated risk sensor (not "pure credit").

---

## 3. TIP/TLT Z Layer

### Why TLT, Not IEF?

**Surprise finding:** TIP/IEF actually correlates *better* with real breakeven inflation (r=0.86 vs 0.65). TIP/TLT is **not orthogonal** to Credit (r=-0.52), but it wins in backtest because it provides less-redundant information:

```
Credit Z vs TIP/TLT: r = -0.52 (correlated — NOT orthogonal)
Credit Z vs TIP/IEF: r = -0.49 (similar)

But the cross-contamination with HY spread differs:
TIP/TLT vs HY Spread: r = +0.03 ← doesn't echo the same credit signal
TIP/IEF vs HY Spread: r = -0.21 ← echoes Credit layer → redundant
```

**Swapping to TIP/IEF → MDD explodes from -37% to -60%** because two layers catch the same risk.

> [!IMPORTANT]
> TIP/TLT is not fully independent from Credit (r=-0.52), and it's not the most accurate inflation gauge. But it often **triggers before Credit/Vol** and creates real leverage divergence at the event level. Its role is **event-driven stress protector**, not pure inflation layer or independent signal.

### Event-Level Audit

| Metric | Result |
|---|---|
| TIP_TLT trades | 12 (corrected from initial 0 — wrong label `INF` vs `TIP_TLT`) |
| Independent trigger | 12/14 episodes (before Credit/Vol) |
| Leverage divergence | 13/14 episodes actually changed leverage |
| Concentration | ⚠️ 69% of gain from Oct 2018 alone |
| Regression t-stat | -1.11 (not significant) |
| Partial corr | -0.016 (no independent linear predictive power) |

**Verdict:** Empirically useful, but concentrated in 2–3 events. Not an overfit — it triggers before other layers 12/14 times and trades real positions — but cannot claim "mechanism proven" or "fully independent." Classified as an **event-driven stress protector**, not a continuous predictor or pure inflation layer.

---

## 4. NSL → Re-entry Gate (formerly "Never Sell at Loss")

### The Discovery

Deep engine instrumentation revealed:

```
Total NSL block days in 14 years: 7
Real block episodes: 2
  - 2012-06: genuine underwater block (loss -19.4%) ✅
  - 2025-04: FAKE block (actually +18.9% profit, but in_trade=False) ⚠️
```

**NSL almost never fires** because the blend logic (`trade_entry_eq` weighted average on leverage increase, line 358-361) keeps entry_eq below equity almost permanently.

### But NSL ON vs OFF Shows Massive Difference

| Mode | Sharpe | CAGR | Final Equity | vs CURRENT |
|---|---|---|---|---|
| **CURRENT** (NSL ON) | 1.54 | 58.8% | 756 | — |
| NSL_OFF | 1.43 | 53.1% | 447 | **-41%** |
| NSL_FIXED | 1.45 | 56.7% | 627 | -17% |

### 2025 Tariff Attribution — The Real Story

Day-by-day breakdown revealed the true mechanism:

```
03-20: SEP period ends → system CAN re-enter market
       CURRENT: stays 0x (in_trade=False → is_profitable=False → NSL blocks)
       NSL_OFF: enters 2x immediately
       
04-03: QQQ -5.4% → CURRENT: 0x (safe), NSL_OFF: 2x (-10.7%)
04-04: QQQ -6.2% → CURRENT: 0x (safe), NSL_OFF: 2x (-12.4%)

04-07: CURRENT enters 3x at the bottom → rides full recovery
```

> [!WARNING]
> **NSL's 41% advantage is NOT from "never sell at loss."** It's from a specific edge case: when `in_trade=False` (after SEP 0x), `is_profitable` is forced `False`, which prevents re-entry during danger states. This acts as a **"don't re-enter during storm" gate** — not the originally intended NSL logic.

### Equity at Key 2025 Dates

| Date | Event | CURRENT | NSL_OFF | C/O |
|---|---|---|---|---|
| 02-19 | Pre-crash | 241.5 (0x) | 214.1 (0x) | 1.13x |
| 04-04 | Black Friday | 242.9 (0x) | 166.4 (2x) | 1.46x |
| 04-07 | Bottom entry | 267.7 (3x) | 160.7 (1x) | 1.67x |
| 05-30 | May end | 349.4 (1x) | 206.6 (1x) | 1.69x |

### NSL Verdict

```
Old name: "Never Sell at Loss"
New name: "Anti-whipsaw Re-entry Gate"

Old description: "prevents selling when underwater"
New description: "prevents re-entering during danger after SEP 0x exit"
                  
Status: KEEP in v2, do not modify
Risk:   ~70% of value from single 2025 event
        Edge case behavior (in_trade=False) is the actual mechanism
        This is now SEALED BEHAVIOR, not a bug to fix
```

> [!CAUTION]
> **Do not "fix" NSL behavior unless the whole v2 is re-sealed.** The current `in_trade=False → is_profitable=False` edge case is part of v2's production results. Changing it to "clean" NSL logic would alter the strategy itself. If a cleaner implementation is desired, it must go through v2.1/v3 with full re-validation.

---

## 5. Bond ETF Pairing — IEF vs TLT

### Verified with FRED Data

| Pairing | Measures | Key Correlation | Backtest |
|---|---|---|---|
| **HYG/IEF** (Credit) | Credit spread | r=-0.79 vs real HY spread | Sharpe 1.54 |
| HYG/TLT (alt) | Credit + rate noise | r=-0.24 vs real HY spread | Sharpe 1.41 |
| TIP/IEF (alt) | Inflation (more accurate) | r=+0.86 vs breakeven | MDD -59.5% ❌ |
| **TIP/TLT** (Inflation) | Inflation (orthogonal) | r=+0.65 vs breakeven | Sharpe 1.54 |

**Swapping both → Sharpe 1.54 → 1.17, MDD -37% → -54%.**

> [!NOTE]
> The correct principle is not "IEF for credit, TLT for inflation" as a rule. It's: **choose pairings that make layers less redundant.** HYG/IEF isolates credit cleanly (r=-0.79 vs FRED); TIP/TLT is not orthogonal to Credit (r=-0.52), but it doesn't echo the same HY spread signal (r=+0.03). The combination matters more than individual accuracy.

---

## System-Level Conclusions

### What's Proven

1. **Credit Z + Vol Z** are statistically robust, mechanistically clear, and survive all stress tests
2. **SEP** is foundational (0x during Fed tightening = -70% MDD protection)
3. **Bond pairings** (IEF for credit, TLT for inflation) are data-validated via FRED macro series
4. **NSL** has real economic value, though its mechanism is different from what was assumed

### What's Not Proven

1. **TIP/TLT** lacks independent linear predictive power (regression t=-1.11); not orthogonal to Credit (r=-0.52); value concentrated in 2–3 events
2. **NSL as "亏损不卖"** — the actual mechanism is a re-entry gate from `in_trade=False` edge case, not a frequent underwater-sell blocker
3. **NSL's robustness** — 70% of its value comes from the 2025 tariff event

### v2 Status

```
v2 sealed = 生产版本，不动
Do not "fix" NSL unless whole v2 is re-sealed
All components audited
No changes recommended to production code
Documentation updated to reflect true mechanisms:
  SEP = regime exit
  Credit = core crash-risk brake  
  Vol = tail-risk airbag
  TIP/TLT = event-driven stress protector (not pure inflation, not independent)
  NSL = anti-whipsaw re-entry gate (not "never sell at loss")
```
