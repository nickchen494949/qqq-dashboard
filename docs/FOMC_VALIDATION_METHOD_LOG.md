# FOMC validation method log

This log exists so the release cannot describe v1.0 as cleaner than it was.

## Frozen before target extraction

- `2026-09-05T05:02:53Z`: validation contract v1.0 was frozen in commit `629a9ae`.
- The model family, B0-B6 definitions, chronological partitions, 10-day cutoff, text vocabulary rules, ridge alpha, bootstrap seed/replicates, and final pass gate were fixed before prediction metrics were calculated.

## Mechanical parser work after freeze

The official 2012-2020 SEP PDFs do not use one stable table layout. Full structural parsing exposed these mechanical cases:

- Appendix pages also contain the words `Table 2`; they are excluded so duplicate appendix values cannot replace the individual projections table.
- Some extracted decimals contain spaces around the decimal point, such as `3. 6`; the parser joins only digit-decimal-digit patterns.
- 2020 uses the heading `Individual Projections Table` instead of the earlier `Table 2` wording.
- Four official participant keys include submitters outside the attendance-derived tracker master. They remain explicitly labelled `OFFICIAL_KEY_ONLY_NOT_TRACKER_MASTER`; they are not silently mapped to somebody else.

These repairs affected structural parsing in the validation and final-holdout years. No prediction metric was inspected and no model feature, hyperparameter, partition, or pass condition changed as a result. Nevertheless, the affected partitions are truthfully labelled `TOUCHED_PARSER_ONLY` and v1.0 must not be called a strictly untouched holdout.

## Scoring implementation fixed before first model run

- A model may score a target only after at least four earlier target SEP dates and 100 earlier eligible examples exist.
- Continuous dot forecasts are used for MAE/RMSE. Direction is obtained by snapping the forecast to the official 12.5-basis-point dot grid and comparing it with the prior personal dot.
- Relative-to-median predictions compare each participant forecast with the median of that model's participant forecasts for the same target date and horizon. The observed target median is used only to score the true class, never as a feature or prediction threshold.
- Missing text is represented by zero text counts. Vocabulary document frequency is calculated once per participant-window, not once per repeated horizon row.
- Numeric imputation, scaling, member columns, vocabulary, and coefficients are fitted using earlier target dates only.
- B2 remains `NOT_RUN_NO_FROZEN_SOURCE`; no daily market proxy is substituted.

This implementation note was committed before the first `run-model` command and before any validation or final-holdout metric was seen.
