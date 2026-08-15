# AI_READ_FIRST: QQQ-Dashboard Production & Research Archive

## 1. Repository Purpose
This repository houses the **v2-sealed TQQQ Risk Strategy**, a production-grade 4-layer defensive system designed to manage risk in leveraged Nasdaq-100 exposure.

It serves as both the active production environment and the permanent research archive for all experiments leading up to the final strategy seal.

## 2. Production System: v2-Sealed Architecture
The production strategy is a hierarchical leverage state machine, not a collection of independent crash predictors. It consists of 4 distinct layers:

1. **Macro Environment (SEP Layer)**: Federal Reserve Summary of Economic Projections. Acts as the master regime filter.
2. **Credit Risk (HYG vs IEF)**: Evaluates high-yield corporate credit stress vs Treasury safe havens.
3. **Inflation Risk (TIP vs TLT)**: Evaluates bond-market / duration / inflation repricing stress.
4. **Volatility Risk**: 20D realized volatility Z-score based on QQQ daily returns. Acts as the fastest tactical airbag.

**Priority Order:** `SEP > Credit > TIP/TLT > Vol > Normal`

## 3. Sealed Parameters (v2)
- **Credit:** Trigger 1.2, Recover 0.5 → 1x
- **TIP/TLT:** Trigger 2.5, Recover 0.3, Window 63 → 1x
- **Vol:** Trigger 1.5, Recover 0.5 → 2x
- **TC (Transaction Cost):** 25 bps
- **NSL:** ON

## 4. Sealed Behavior & Rules
**v2-sealed production architecture selection and parameter-tuning research is CLOSED as of the frozen 2026-08-13 snapshot.**

Future research is allowed as separate challenger research and true OOS evaluation, but **must not silently modify or refit v2-sealed.** 

**Ironclad Rules:**
- **No Parameter Tuning:** You may not tweak parameters or thresholds using post-2026-08-13 data.
- **T+1 Execution:** All strategy actions assume execution on the *next day's open*.
- **NSL (Anti-whipsaw Re-entry Gate):** Originally "Never Sell in Loss". Profit allows tactical scaling back up, but loss restricts it to prevent whipsawing. SEP may optionally force 0x, but NSL critically prevents the system from prematurely exiting a danger state just because of a small bounce.
- **Testing Protocol:** Any proposed architectural modifications must pass the complete block-bootstrap ablation test against frozen data.
- **Auditable Changes:** Every strategy change must leave an auditable Git trail.

## 5. Current Research Status
- **Credit & TIP/TLT:** Retained with High Confidence. Historical block-bootstrap strongly supports their portfolio synergy.
- **Vol:** Retained, but marked as *OOS validation ongoing*.
- **Macro-Observer:** The `macro-observer` repository is completely independent. It is a separate active Macro Dashboard. Artifacts copied into this repository (`research/challengers/macro_observer_2026_08`) are for historical reference only.

## 6. Dashboard Data-Integrity Rule
**Never silently deploy stale QQQ/TQQQ market data.**
If the source data exceeds the allowed freshness window, the build should fail loudly rather than silently fall back to stale prices.

## 7. Recommended Reading Order
For any future AI agents modifying or studying this repository, read these files in order:
1. `AI_READ_FIRST.md` (You are here)
2. `PROJECT_CONTEXT.md` (Current system context)
3. `docs/STRATEGY.md` (Strategy definitions)
4. `docs/ABLATION_AUDIT.md` (Final 10,000-iteration bootstrap proof)
5. `research/README.md` (Chronological history of the research)
6. `tools/strategy_engine.py` (The production code - read only after understanding the above).
