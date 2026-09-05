# FOMC communication validation specification v1.0

Status: **FROZEN BEFORE TARGET EXTRACTION**

Frozen at: **2026-09-05T05:02:53Z**

Machine-readable contract: `data/fomc_validation/spec/validation_spec_v1.0.json`

## 1. The three questions are separate

This project may answer three different questions:

1. `TEXT_TRUTH`: did a blinded reader and the classifier interpret the communication in the same way?
2. `SEP_VALUE`: did information from official communications improve a forecast of a participant's next individual SEP policy-rate path?
3. `MARKET_VALUE`: did a prediction frozen before prices move anticipate the policy surprise and market reaction?

A pass on one question is not evidence for either of the others. `HAWKISH` is not synonymous with `QQQ_BEARISH`, and a later vote is not text ground truth.

## 2. Official answer-key universe

The answer key is limited to official Federal Reserve historical materials that contain both:

- the compilation of individual projections with randomized participant numbers; and
- the official participant key linking those numbers to names.

The frozen enumeration contains all 36 SEP compilation/key pairs linked on the official 2012-2020 historical pages: five in 2012, four in each year 2013-2019, and three in 2020. Later years are excluded until the official participant key becomes public. The Fed states that 2007-2015 keys are released after ten years and keys beginning March 2016 after five years.

The later key is answer-key evidence only. It is never a feature that a historical forecast could see.

## 3. Unit of analysis and eligibility

The primary unit is:

```text
participant x target SEP date x shared finite calendar-year policy-rate horizon
```

An example is eligible only when:

- the official key identifies the participant at both the immediately previous and target SEP;
- both compilations contain a federal-funds-rate projection for the same finite calendar year;
- the participant had a qualifying policy role during the communication window; and
- all feature evidence satisfies the target cutoff.

`Longer run` is excluded from the primary result because it is not a dated policy-path endpoint. It may be reported separately. A participant entering at the target SEP without a previous personal projection is excluded from B0/B5/B6 paired comparisons, not imputed.

## 4. Historical information boundary

For each target SEP, the communication window opens immediately after the prior SEP public release and closes at the frozen analytical cutoff.

The analytical cutoff is **00:00 America/New_York ten calendar days before the first day of the target meeting**. This deliberately conservative rule is applied to every year, even when the contemporaneous formal blackout began later. Date-only communications are treated as available at end of day and must be strictly earlier than the cutoff. Unknown dates or irreconcilable publication timing are excluded.

Allowed features must have public availability supported on or before the cutoff. `first_seen_at` in the 2026 database is not treated as historical availability; the official event/publication date must independently support earlier availability.

Forbidden inputs include target or later SEP materials, later participant keys as features, later votes, later speeches, revised macro observations without vintage proof, current biographies, market moves after the cutoff, and any label created after viewing the target.

## 5. Prediction targets

For every eligible example, score:

- `DIRECTION`: lower, unchanged, or higher than that participant's previous projection for the same horizon;
- `RELATIVE_TO_TARGET_MEDIAN`: below, at, or above the target SEP median for that horizon;
- `EXACT_DOT`: the target projection in basis points.

Primary metrics are exact-dot mean absolute error in basis points and three-class direction balanced accuracy. Secondary metrics are exact-dot root mean squared error, relative-to-median balanced accuracy, and probabilistic log loss/Brier score when probabilities exist.

All uncertainty intervals use a meeting-cluster bootstrap so multiple participants and horizons from one meeting are not treated as independent events. The fixed bootstrap seed is `20260905` and the planned replicate count is `10000`.

## 6. Frozen chronological partitions

- `DEVELOPMENT`: targets from 2012-04-25 through 2016-12-14. Parser repair, feature construction, and model fitting may use these targets.
- `VALIDATION`: targets from 2017-03-15 through 2018-12-19. It may be opened once to reject the frozen model or confirm readiness; no feature or hyperparameter selection may follow from its results.
- `FINAL_HOLDOUT`: targets from 2019-03-20 through 2020-12-16. It is opened once only after code, tests, feature schema, and model parameters are frozen.

Fixing a mechanical parser defect discovered after a partition opens is allowed only with a preserved counterexample and without changing model features, parameters, or the pass gate. The affected partition is then reported as touched and cannot be called untouched.

## 7. Frozen baselines and candidate

- `B0_PREVIOUS_DOT`: copy the participant's previous dot for the same horizon.
- `B1_PREVIOUS_MEDIAN`: copy the previous SEP median for the same horizon.
- `B2_MARKET`: target-horizon market-implied rate frozen at the cutoff. It is `NOT_RUN_NO_FROZEN_SOURCE` unless a timestamped, auditable futures/OIS source is added before the final holdout opens.
- `B3_MACRO`: point-in-time public macro information without identity or speech features. Initial implementation may use only vintage-safe official inputs; absent vintage proof, a variable is omitted rather than silently revised.
- `B4_MEMBER`: expanding-window member fixed effect plus horizon and seasonality, estimated only from earlier targets.
- `B5_MACRO_PREVIOUS`: B3 plus previous personal dot and previous SEP information.
- `B6_PLUS_SPEECH`: B5 plus text derived only from eligible official communications in the window.

The candidate question is strictly the incremental comparison `B6 - B5`. Results for B0-B4 are context, not substitutes for this comparison.

The first frozen text implementation is deliberately simple: lowercase English word tokens; names and boilerplate navigation removed; unigram and bigram counts; vocabulary learned only from the training window; document-frequency floor 3; maximum 500 text columns chosen by training-window document frequency; log-count scaling; fixed ridge penalty `alpha=10`; no embeddings, external language model, sentiment API, or holdout-driven tuning.

All learned models use an expanding chronological window. No observation from the target meeting or a later date may enter fitting, scaling, vocabulary selection, imputation, or feature selection.

## 8. Pass, fail, and stopping rules

`SEP_VALUE_PASS` requires all of the following on the final holdout:

1. B6 exact-dot MAE is lower than B5 MAE.
2. The meeting-cluster bootstrap 95% confidence interval for `MAE(B6) - MAE(B5)` is entirely below zero.
3. B6 direction balanced accuracy is not lower than B5.
4. B6 beats B5 on exact-dot MAE in both 2019 and 2020 separately.
5. At least 70% of eligible participant-window examples have one or more preserved official communication artifacts containing usable text; otherwise the result is `COVERAGE_BLOCK`, not a negative speech finding.

If any condition fails, the honest verdict is `SEP_VALUE_FAIL` or `COVERAGE_BLOCK`. There is one frozen B6 specification and one final-holdout opening. No post-holdout model search is permitted under v1.0.

## 9. Text-truth audit

The system creates a deterministic blinded packet of 120 passages, stratified across years, event types, members, and preliminary classifier confidence. Names, titles that reveal identity, votes, later SEP values, and market reactions are hidden. Each passage includes enough surrounding original context to interpret conditional statements.

At least two independent human reviewers assign one label:

```text
HAWKISH / DOVISH / NEUTRAL / MIXED / CONDITIONAL / UNCLEAR
```

They also record confidence and the exact supporting span. Reviewers cannot see each other's labels. Disagreements are adjudicated only after both files are frozen. Report raw agreement, Cohen's kappa for each pair, consensus coverage, per-class precision/recall, and confusion matrices.

Until two completed human files exist, `TEXT_TRUTH` is `PENDING_HUMAN_REVIEW`. LLM or agent labels may be exploratory but may not be described as human validation.

## 10. Behavioral corroboration

Next vote, next attributed SEP, and subsequent public statements are recorded as separate outcomes. They can corroborate or contradict a text interpretation, but disagreement is triaged as:

- interpretation error;
- intervening information changed;
- original statement was conditional or mixed; or
- unresolved.

Behavior is not relabelled as text truth and is never used to rewrite the blinded answer after results are visible.

## 11. Market validation

Market validation requires a prediction timestamp frozen before the event and pre-event state plus `+5m`, `+30m`, `+2h`, close, and next-close observations. The primary instruments are 2-year Treasury yield and federal-funds futures/OIS. QQQ/NQ, DXY, and gold are secondary because concurrent news can dominate.

The schema keeps `POLICY_STANCE`, `POLICY_SURPRISE`, and asset-specific `MARKET_SIGNAL` separate. Without auditable intraday timestamps and a concurrent-event control log, this branch is `NOT_RUN_NO_FROZEN_INTRADAY_SOURCE`; daily QQQ movement is not accepted as a substitute.

## 12. Provenance and release evidence

Preserve four separate layers:

```text
official raw bytes -> parsed individual SEP/text tables -> model features -> sealed results
```

Every arrow records the validation-spec hash, raw aggregate hash, exact code commit and dirty-state note, command and parameters, timestamps, output hashes, row/coverage assertions, and QA report hashes. Raw official bytes are immutable. Superseded or failed runs remain labelled and are not overwritten.

The release must include source URLs, retrieval timestamps/status, per-file SHA-256, deterministic aggregate hashes, schemas, exclusions, coverage by partition, predictions for every eligible example, paired B5/B6 errors, bootstrap draws or sufficient recomputation inputs, blinded review templates, focused tests, and one clean end-to-end rebuild.

## 13. Completion language

The validation layer is complete only when every branch is explicitly `PASS`, `FAIL`, `BLOCK`, `PENDING_HUMAN_REVIEW`, or `NOT_RUN` with evidence. A negative result is a completed result. A pending human audit or unavailable intraday source is not silently promoted to success.

## Official sources frozen into the rationale

- Historical SEP description and release lags: https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm
- Historical materials by year: https://www.federalreserve.gov/monetarypolicy/fomc_historical_year.htm
- 2012-2020 year pages linked from the historical archive
- External-communications blackout rule: https://www.federalreserve.gov/monetarypolicy/files/FOMC_RulesAuthPamphlet_201701.pdf
- Current blackout explanation/calendar: https://www.federalreserve.gov/monetarypolicy/files/fomc-blackout-period-calendar.pdf
