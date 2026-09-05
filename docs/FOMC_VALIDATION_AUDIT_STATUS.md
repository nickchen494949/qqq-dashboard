# FOMC validation audit status

Last generated: 2026-09-05

## Plain-language verdict

The data pipeline is usable, but the frozen v1 speech model **failed** its predictive-value test. Adding official speech text made the next individual SEP-dot forecast worse than the same model without speech text. This negative result is preserved; it was not tuned away.

The three claims remain separate:

| Claim | Status | What it means |
|---|---|---|
| Next-SEP predictive value | `SEP_VALUE_FAIL` | B6 with speech failed to improve on B5 without speech. |
| Text stance interpretation | `PENDING_HUMAN_REVIEW` | A blinded 120-passage packet exists, but two independent humans have not completed it. |
| Market/trading value | `NOT_RUN_NO_FROZEN_INTRADAY_SOURCE` | No auditable timestamped 2Y/futures intraday source was available; daily QQQ was not substituted. |

## Frozen next-SEP result

Final holdout: 2019-03-20 through 2020-12-16, 391 participant-horizon examples.

| Model | Exact-dot MAE | Direction balanced accuracy |
|---|---:|---:|
| B0 previous personal dot | 40.66 bp | 0.333 |
| B1 previous SEP median | 43.29 bp | 0.503 |
| B3 point-in-time macro | 377.53 bp | 0.514 |
| B4 member fixed effect | 106.26 bp | 0.584 |
| B5 macro + previous SEP information | **71.11 bp** | **0.528** |
| B6 B5 + official speech text | **87.37 bp** | **0.365** |

Primary paired result: `MAE(B6) - MAE(B5) = +16.26 bp`. Positive is worse. The frozen meeting-cluster bootstrap 95% interval is `[-1.15, +44.99] bp`, so it does not show an improvement.

B6 also lost separately in both final years:

- 2019: B5 24.24 bp; B6 27.39 bp.
- 2020: B5 132.04 bp; B6 165.35 bp.

All predictive pass conditions failed except coverage. Final-holdout usable-text coverage was 88 of 119 participant windows, or 73.95%, above the frozen 70% gate.

## Evidence inventory

- Official SEP/key universe: all 36 compilation/key pairs currently published on the Fed historical pages for 2012-2020.
- Raw official SEP/key files: 72 PDFs, 76,594,825 bytes, aggregate SHA-256 `9e52912c90df3849d3559511c87de2d74245e9132e16e31f19e62fee2d73e9bf`.
- Parsed official truth: 612 participant-key rows and 2,143 finite-year projection rows.
- Paired validation examples: 1,875 total; 1,097 development, 387 validation, 391 final holdout.
- Vintage macro evidence: 175 ALFRED/FRED XML files for five frozen series across 35 target cutoffs, aggregate SHA-256 `f028216a19c2f9c73f1c15c2bfa522250bdb8fa541dfebbe8fe8baaf4200348c`.
- Communication windows: 575 participant-windows; 368 contain usable preserved official text.
- Frozen model predictions: 1,640 rows after the pre-declared minimum-history rule.
- Behavioral corroboration table: 503 participant-target rows; votes and later statements remain outcomes, not text labels.
- Human audit: two separate blank reviewer files plus a hidden provenance key; all identity tokens are redacted from reviewer passages.

## Important honesty note

The v1 model and gate were frozen before scoring, but this is not a perfectly untouched holdout. Mechanical PDF-parser repairs were needed for validation/final years before metrics were run. No metric was inspected and no model setting changed during those repairs. The affected partitions are therefore labelled `TOUCHED_PARSER_ONLY`, as documented in `FOMC_VALIDATION_METHOD_LOG.md`.

## Audit map

```text
Fed SEP PDFs + participant keys + official communications + ALFRED vintages
  -> hashed raw files
  -> parsed individual projections / text / vintage macro features
  -> chronological B0-B6 forecasts with a conservative pre-meeting cutoff
  -> sealed negative SEP verdict + blind human packet + explicit market-data block
```

## Where to inspect

- Contract: `docs/FOMC_VALIDATION_SPEC.md`
- Method chronology: `docs/FOMC_VALIDATION_METHOD_LOG.md`
- Machine result: `data/fomc_validation/results/sep_validation_results.json`
- Row-level predictions/errors: `data/fomc_validation/results/sep_predictions.csv`
- Bootstrap recomputation rows: `data/fomc_validation/results/bootstrap_b6_minus_b5.csv`
- Blind-review instructions/status: `data/fomc_validation/human_review/status.json`
- Reviewer files: `data/fomc_validation/human_review/reviewer_1.csv` and `reviewer_2.csv`
- Behavioral outcome table: `data/fomc_validation/results/behavior_corroboration.csv`
- Market block: `data/fomc_validation/results/market_validation_status.json`
- Raw manifests: `data/fomc_validation/manifests/`
- Minimal implementation: `tools/fomc_validation.py`
- Focused tests: `tests/test_fomc_validation.py`

## Official source scope

The Fed historical archive says the individual-projection keys are released with a lag. The public historical year index currently reaches 2020, so 2021-present individual named dots are not silently inferred from anonymous SEP charts. The broader tracker still preserves official votes and communications beyond 2020; the named-SEP validation layer stops where the official answer key stops.

## Verification status

- A clean temporary rebuild from the frozen raw files produced byte-identical feature tables, predictions, bootstrap draws, behavior table, and human-review packets. The result JSON was semantically identical after excluding its generation timestamp.
- All six raw/derived manifests verified with zero failures.
- `tests/` passed 49 tests. Unrestricted pytest collection across the entire repository still produces 22 pre-existing collection errors in archived/diagnostic scripts that require legacy import paths, unavailable private data, or an environment key. Those unrelated errors are not reported as passed.
- The configured independent-audit watcher was offline and did not allow this repository target. This release is ready for external audit, but is not described as independently approved.
