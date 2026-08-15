# Research Archive & History

This directory contains the entire research history for the `qqq-dashboard` production system. **Research on the v2-sealed architecture is officially CLOSED as of 2026-08-13.**

## Research Chronology

1. **Original Strategy Development (v1/v2)**: Explorations into building a 3-layer and then 4-layer defensive system for leveraged equity.
2. **SEP Validation**: Deep dive into the Summary of Economic Projections to prove its efficacy as a primary macro filter.
3. **Component Audits**: Individual audits of Credit, TIP/TLT, and Volatility layers.
4. **Joint Robustness**: Checking combinations and intersections of different defensive triggers.
5. **Final Ablation/Parsimony Audit (The "Final Seal")**:
   - A rigorous 10,000 iteration block bootstrap test was run.
   - Evaluated the value of removing each layer.
   - Proved that the system does not primarily predict crashes (95% CI for crash lift crosses zero), but instead provides undeniable, statistically significant **portfolio synergy** (ΔSharpe > 0 for Credit and TIP/TLT with >98% confidence).
6. **Frozen Data Reproducibility**: The exact data snapshot used to authorize the v2-sealed architecture was frozen in `data/frozen/ablation_2026-08-13/`.

## Final Verdict (KEEP/CUT)
- **SEP**: KEEP (Master regime filter).
- **Credit**: KEEP (High Confidence).
- **TIP/TLT**: KEEP (High Confidence).
- **Vol**: KEEP (Marked as OOS validation ongoing).

The four-layer architecture is locked. No layers were cut.

## Organization
- `challengers/`: Promising strategies (like Hawkish Path, v6) that were thoroughly investigated but ultimately rejected or deferred in favor of the v2-sealed system. These are kept for reference so future agents do not repeat the work.
- `rejected/`: Ideas that failed validation entirely.
- `archive/`: Older audits and intermediate scripts.
- `pending/`: Research ideas that were proposed but never fully tested.
