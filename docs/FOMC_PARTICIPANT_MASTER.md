# FOMC participant master audit note

Status: audit candidate on the WIP branch; not merged to `main`.

## What is included

- 118 official policy-vote dates from 2012-01-25 through 2026-07-29.
- 117 unique official FOMC minutes documents with frozen HTML and SHA-256 hashes.
- 2,130 meeting-person rows and 57 normalized people.
- Separate attendance categories for committee/voting-bank members, alternate members, nonvoting Reserve Bank presidents, and the single vote-list-only cross-reference.
- Original name text, full attendance snippet, official URL, and local raw-file path on every row.

`first_observed_attendance_date` and `last_observed_attendance_date` are bounds from the downloaded minutes. They are not appointment or employment tenure dates.

## March 2020 exception

The official 2020 historical page says the March 2 unscheduled meeting's minutes are at the end of the March 15 minutes. The March 15 document records the March 2 videoconference and the vote completed for the March 3 statement. It publishes ten voters but does not publish a separate full attendance roster for that call.

The output therefore covers 118/118 vote dates, but labels 2020-03-03 `VOTE_LIST_ONLY_OFFICIAL_CROSS_REFERENCE`. It does not copy the March 15 nonvoting attendance roster backward.

## Audit files

- Parser/downloader: `tools/fomc_participant_master.py`
- Full person master: `data/fomc_tracker/output/members_full.csv`
- Per-meeting observations: `data/fomc_tracker/output/participants_by_meeting.csv`
- Meeting coverage: `data/fomc_tracker/output/participant_meeting_coverage.csv`
- Summary and output hashes: `data/fomc_tracker/output/participant_master_summary.json`
- Frozen minutes and fetch manifest: `data/fomc_tracker/raw/minutes_history/`
- Regression tests: `tests/test_fomc_participant_master.py`

## Acceptance checks

- Every observed voter is present in the full participant master.
- No staff secretary is parsed as a policy participant.
- Name aliases retain the original printed name in `raw_member_name`.
- Every normalized row's snippet is found in its frozen official page.
- Every frozen file's SHA-256 matches the fetch manifest.
