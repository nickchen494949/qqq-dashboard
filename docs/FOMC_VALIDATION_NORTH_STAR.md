# FOMC validation north star

NORTH STAR
- Final claim: determine whether pre-blackout official public communications add honest out-of-sample information about each participant's next individual SEP policy-rate path beyond simple point-in-time baselines.
- Separate claims: text interpretation accuracy, next-SEP predictive value, and market-reaction value are never merged.
- Explicit non-goals: no change to the sealed TQQQ strategy, no trading rule, no retrospective narrative score, and no claim that behavior is text ground truth.
- Untouched: production strategy files and the released `data/fomc_tracker/` evidence package.

MILESTONES
1. [IN PROGRESS] Freeze the validation contract before inspecting target values.
2. [PENDING] Preserve and parse every publicly released 2012-2020 SEP compilation and participant key.
3. [PENDING] Build point-in-time examples and run frozen B0-B6 comparisons.
4. [PENDING] Produce a blinded human-label packet and score completed reviews.
5. [PENDING] Audit lineage, time boundaries, results, and publish an external-audit branch.

CURRENT GATE
- Stage: official truth feasibility and contract freeze.
- Evidence required: all 36 released SEP compilation/key pairs enumerated from official historical pages, immutable raw hashes, explicit development/validation/final-holdout dates, and frozen scoring/stopping rules.
- Current status: IN PROGRESS.
- Why this task closes the gate: no model result is admissible until its permitted inputs and later-released answer key are mechanically separated.

ACTIVE TASK
- Small bounded action: write and hash validation specification v1.0, then download the enumerated official SEP files without parsing their target values.
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
- If PASS: parse participant keys and individual projections on development years first.
- If FAIL: preserve the failing file/example and reject or repair only the parser; do not change the predictive hypothesis.
