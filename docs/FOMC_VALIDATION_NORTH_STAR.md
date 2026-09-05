# FOMC validation north star

NORTH STAR
- Final claim: determine whether pre-blackout official public communications add honest out-of-sample information about each participant's next individual SEP policy-rate path beyond simple point-in-time baselines.
- Separate claims: text interpretation accuracy, next-SEP predictive value, and market-reaction value are never merged.
- Explicit non-goals: no change to the sealed TQQQ strategy, no trading rule, no retrospective narrative score, and no claim that behavior is text ground truth.
- Untouched: production strategy files and the released `data/fomc_tracker/` evidence package.

MILESTONES
1. [COMPLETE] Freeze the validation contract before inspecting prediction metrics.
2. [COMPLETE] Preserve and parse every publicly released 2012-2020 SEP compilation and participant key.
3. [COMPLETE] Build point-in-time examples and run frozen B0-B6 comparisons: `SEP_VALUE_FAIL`.
4. [PARTIAL] Produce a blinded 120-passage packet: complete; two independent human reviews remain `PENDING_HUMAN_REVIEW`.
5. [COMPLETE] Audit lineage, time boundaries, results, and publish the external-audit branch.

CURRENT GATE
- Stage: release audit and external publication.
- Evidence required: deterministic rebuild, tests, raw-manifest verification, secret scan, clean git state, and public commit link.
- Current status: COMPLETE WITH EXPLICIT PENDING/BLOCKED SUBCLAIMS.
- Why this task closes the gate: the negative model result is useful only if an outsider can reproduce it and see every limitation.

ACTIVE TASK
- Small bounded action: none. v1.0 is sealed and published; do not tune it after the negative holdout result.
- Owned paths: `docs/FOMC_VALIDATION_*`, `data/fomc_validation/`, `tools/fomc_validation.py`, and `tests/test_fomc_validation.py`.
- Budget: standard library plus existing NumPy/pandas/pypdf only; one frozen final-holdout opening; no paid data.
- Stop rule: proceed only if official files provide a mechanically attributable participant-level policy-rate path; otherwise issue BLOCK.

BLOCKER ROUTE
- Current blocker: none.
- Data fallback: missing official files remain `UNKNOWN`/`BLOCK`; anonymous dots, votes, or press reports are never substituted for named SEP truth.
- What must not be weakened: B6 must beat B5 out of sample; an attractive in-sample fit is not a pass.

PARKING LOT
- Intraday 2-year yield/futures/QQQ reaction testing until a timestamped market-data source is frozen.
- Production dashboard integration until the validation verdict is known.

NEXT
- Publish the negative v1 result without tuning it.
- Obtain two independent human reviewer files before any `TEXT_TRUTH` claim.
- Add market validation only if a timestamped, auditable 2Y and futures/OIS source is frozen first.
