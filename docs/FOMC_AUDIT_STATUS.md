# FOMC tracker audit status

Branch status: **AUDIT CANDIDATE — DO NOT MERGE BEFORE INDEPENDENT REVIEW**

## Current frozen result

| Component | Result | Boundary |
|---|---:|---|
| Full observed participant master | 57 people | Official minutes attendance; observed bounds, not appointment tenure |
| Per-meeting participant rows | 2,130 | 118 vote dates; 117 full attendance rosters + one official vote-list-only cross-reference |
| Named vote rows | 1,208 | 118 policy dates, including 73 explicit dissents |
| Speech/statement metadata | 2,701 | 952 Board + 1,420 FRASER + 329 Reserve Bank supplement rows |
| Speech members with events | 47 of 57 | All 45 observed voters plus two alternates/nonvoters |
| SEP snapshots | 599 rows / 58 SEP dates | No speech look-ahead; unknown same-day publication times are excluded |
| Latest stance table | 12 current SEP voters | Stance label plus change versus prior SEP |

## Previously reported failures and disposition

1. Board role prefix leaked into 113 member names: fixed; regression test rejects role-prefix leakage and out-of-master names.
2. FRASER collapsed to one author/48 rows: fixed; current creator-validated result is 1,420 rows across 24 people, including the two full-master additions.
3. FRASER page two returned global-library noise: fixed; records must belong to the member's official collection or have matching embedded creator metadata.
4. Publication time: not invented. All 2,701 rows remain `UNKNOWN` because the selected official archive indexes do not expose a trustworthy original publication timestamp. Event date and publication date are separate fields.
5. Old `members.csv` was only voters: retained with that narrow label; `members_full.csv` now contains all official policy participants observed in the minutes.

## Explicit limitations

- Ten people who appeared only as alternate/nonvoting participants have no event in the selected official Board/FRASER/district archives. They remain as zero rows in `speech_catalog_coverage.csv`.
- A zero means “not found in these documented archives,” not “this person never spoke.”
- Metadata-only speeches are not automatically classified hawk/dove. The stance table uses explicit dissents, a small manually reviewed speech subset, or a clearly labeled committee-action proxy.
- March 3, 2020 has no separate published attendance roster. The official March 15 minutes contain its voter list, so the row is marked vote-list-only.

## Reproduction

```bash
python3 tools/fomc_tracker.py --data-dir data/fomc_tracker
python3 tools/fomc_participant_master.py build --data-dir data/fomc_tracker
python3 tools/fomc_speech_catalog.py build --data-dir data/fomc_tracker
python3 -m unittest discover -s tests -v
```

Expected result: 21 tests pass.
