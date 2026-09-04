# Minimal FOMC member tracker

This is a deliberately small, auditable addition to the existing Python repository.

## Historical coverage

- Builds an **observed voting-member master** from official FOMC roll calls from January 2012 onward. First and last dates are observed votes, not appointment-tenure claims.
- Builds 1,208 per-person records for all 118 official named policy roll calls through July 2026, including 73 explicitly classified dissents.
- Uses the official June and July 2026 minutes to recover full named roll calls after the public statement format changed to aggregate totals.
- Tracks a complete 2012-present stream of official statement/minutes events, plus a small hand-labelled 2024-2025 individual-speech sample from official Board and Reserve Bank pages.
- Freezes the voting cohort's stance at all 58 listed SEP dates from January 2012 through June 2026. Evidence dated after a SEP is excluded.
- Preserves official URLs, short source snippets, original HTML files, SHA-256 hashes, and transformation metadata.

`output/coverage.csv` is the audit boundary. The vote and SEP histories are complete for the stated scope. The member master is an observed-voter master, not a tenure roster, and the individual-speech corpus is explicitly `SAMPLE_ONLY`. The build does **not** claim a complete census of every speech across the Board and 12 Reserve Banks, or a definitive ideological hawk/dove score.

A concurring vote only proves support for that meeting's action. When there is no individual speech published within 180 days of the SEP date or a same-meeting dissent, the output labels the score as `VOTE_ACTION_PROXY`. This prevents a stale speech from years earlier from being presented as current.

## One command

```bash
python3 tools/fomc_tracker.py --data-dir data/fomc_tracker
```

Outputs:

- `output/members.csv`
- `output/votes.csv`
- `output/events.csv`
- `output/sep_snapshots.csv`
- `output/latest_stance.csv`
- `output/latest_stance.md` (human-readable audit table)
- `output/coverage.csv`
- `output/sources_manifest.json`
- `output/transformation.json`

## Stance scale

```text
-2 = explicit easier-policy dissent
-1 = explicit easing/cut bias
 0 = hold/wait/current action neutral
+1 = hold longer / tighter bias
+2 = explicit tighter-policy dissent
```

The score is an auditable annotation, not a statistical estimate. `evidence_basis` says whether it came from an individual speech, a dissent, or only the committee action proxy.

## Extending the history

Add official index/statement HTML files to `raw/`, add any new explicit dissent mappings to `curated/dissent_overrides.csv`, add SEP dates, and optionally add individual speech events. Re-run the same command. The build fails on missing raw pages, unmatched snippets, unresolved dissents, missing SEP votes, or look-ahead.
