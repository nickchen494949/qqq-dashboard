# File Manifest

This document categorizes all files in the repository.

## 1. Production Code (`tools/`)
The core `v2-sealed` production files.
- `strategy_engine.py`: The production engine running the 4-layer state machine.
- `build_dashboard.py`: Renders the output for the static HTML dashboard.
- `server.py`: Serves the dashboard locally.
- `auto_update_sep.py`: Fetches SEP PDFs to maintain macro state.

## 2. Production Audits (`tools/`)
Scripts used to verify the v2-sealed system.
- `audit_backtest.py`: Full production test asserting logic against the frozen data.
- `ablation_audit.py`: The final block bootstrap script ensuring portfolio synergy.

## 3. Diagnostics (`tools/diagnostics/`)
Helper scripts to check data availability.
- `check_trigger_timeline.py`: Visualizes entry/exit triggers.
- `test_data_avail.py`: Tests API health for live data.

## 4. Documentation (`docs/`)
Current production documentation.
- `STRATEGY.md`: The definition of the v2-sealed layers.
- `ABLATION_AUDIT.md`: The report from `ablation_audit.py`.
- `V2_SEALED_REPORT.md`: The main report on the final state.
- `JOINT_ROBUSTNESS_AUDIT.md`: Checks for intersection logic.

## 5. Research Archive (`research/`)
The complete historical archive.
- `challengers/`: Robust strategies that were ultimately deferred.
- `rejected/`: Dead ends (see `FAILED_STRATEGIES.md`).
- `archive/`: Old audits, deprecated versions, and old `.py` exploration scripts.
- `pending/`: Unfinished concepts.

## 6. Root Context
- `AI_READ_FIRST.md`: The only entrypoint a future agent should read.
- `PROJECT_CONTEXT.md`: System truth.
- `README.md`: The Github landing page.
