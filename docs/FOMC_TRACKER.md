# Minimal FOMC member tracker

This is a deliberately small, auditable addition to the existing Python repository.

## Historical coverage

- Builds a **full observed participant master** from the attendance sections of official FOMC minutes from January 2012 onward: 57 people and 2,130 meeting-person rows across 118 policy-vote dates. This includes voting members, alternate members, and nonvoting Reserve Bank presidents.
- Keeps `members.csv` as the narrower 45-person observed-voter table and writes the broader roster to `members_full.csv`; the two scopes are not mixed.
- Builds 1,208 per-person records for all 118 official named policy roll calls through July 2026, including 73 explicitly classified dissents.
- Uses the official June and July 2026 minutes to recover full named roll calls after the public statement format changed to aggregate totals.
- Tracks a 2,701-row speech/statement metadata catalog from official Board, FRASER, and documented Reserve Bank sources. All 45 observed voters have events; 10 alternate/nonvoting participants have no matching event in the selected official archives and are explicitly listed as zero rather than silently dropped.
- Keeps a small hand-labelled 2024-2025 speech subset for stance scoring. The remaining speech metadata is not automatically assigned a hawk/dove label.
- Freezes the voting cohort's stance at all 58 listed SEP dates from January 2012 through June 2026. Evidence dated after a SEP is excluded.
- Preserves official URLs, short source snippets, original HTML files, SHA-256 hashes, and transformation metadata.

`output/coverage.csv`, `output/participant_meeting_coverage.csv`, and `output/speech_catalog_coverage.csv` are the audit boundaries. First/last dates are observed-attendance bounds, not appointment-tenure claims. The build does **not** claim that the ten zero-event alternates never spoke publicly, or that an unlabeled speech implies a hawk/dove score.

The March 3, 2020 emergency action is a documented special case: the Fed points to the end of the March 15 minutes. Those minutes publish the ten voters for the March 2 videoconference/March 3 action, but no separate full attendance roster. It is marked `VOTE_LIST_ONLY_OFFICIAL_CROSS_REFERENCE`.

A concurring vote only proves support for that meeting's action. When there is no individual speech published within 180 days of the SEP date or a same-meeting dissent, the output labels the score as `VOTE_ACTION_PROXY`. This prevents a stale speech from years earlier from being presented as current.

## Rebuild from frozen sources

```bash
python3 tools/fomc_tracker.py --data-dir data/fomc_tracker
python3 tools/fomc_participant_master.py build --data-dir data/fomc_tracker
python3 tools/fomc_speech_catalog.py build --data-dir data/fomc_tracker
```

Outputs:

- `output/members.csv`
- `output/members_full.csv`
- `output/participants_by_meeting.csv`
- `output/participant_meeting_coverage.csv`
- `output/votes.csv`
- `output/events.csv`
- `output/speech_catalog.csv`
- `output/speech_catalog_coverage.csv`
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

Fetch new official statements/minutes and speech indexes, add any new explicit dissent mappings to `curated/dissent_overrides.csv`, and add SEP dates. Re-run the three build commands. The build and regression suite fail on unresolved dissents, missing SEP votes, participant parse failures, raw-snippet mismatches, source-hash mismatches, role text leaking into names, FRASER author-collapse, or look-ahead.
