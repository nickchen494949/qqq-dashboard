# QQQ Dashboard & Risk Strategy

A production-grade, 4-layer defensive state machine for managing risk in a leveraged Nasdaq-100 (TQQQ) portfolio.

## Architecture (v2-Sealed)
The system operates as a hierarchical leverage state machine. It evaluates macroeconomic and market signals in strict priority to scale exposure appropriately:

1. **Macro Environment (SEP)**: Uses Federal Reserve Summary of Economic Projections to establish the baseline market regime.
2. **Credit Risk (HYG/IEF)**: Monitors corporate credit stress versus Treasury safe havens.
3. **Inflation Risk (TIP/TLT)**: Monitors inflation expectations via bond markets.
4. **Volatility Risk (QQQ Intraday)**: Monitors tactical equity market shock via intraday price action.

Priority: `SEP > Credit > TIP/TLT > Vol > Normal`

**Note for AI Agents**: Read `AI_READ_FIRST.md` before proceeding. This repository acts as the sealed production environment and historical research archive.
