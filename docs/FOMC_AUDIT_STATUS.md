# FOMC tracker — external audit status

Verdict: **AUDIT READY AT GLOBAL C2; NOT C5 COMPLETE**

Release boundary: **2012-01-01 through 2026-09-05**  
Source check completed: **2026-09-05T04:27:48Z**  
Governing contract: `docs/FOMC_COMPLETENESS_SPEC.md` (v1.0, frozen)  
Branch: `audit/fomc-speech-history-wip`

Plain language: this release enumerates and reconciles the registered official Federal Reserve source universe and preserves the evidence needed to audit every accepted row. It does **not** claim that every public appearance ever made is discoverable online. Open archive and artifact gaps remain visible, so the database-wide level is C2, not C3/C5.

## What is in the release

| Layer | Verified result |
|---|---:|
| Official source registry | Board + 12 Reserve Banks + FRASER = 14 sources |
| FOMC policy dates | 118 from 2012 onward |
| Named vote rows | 1,208 |
| Named dissents | 73 across 50 meetings |
| Vote universe | 45 people, rule-derived |
| Deliberation universe | 57 people, rule-derived from official attendance |
| SEP universe | 1,050 person-date rows across 58 SEP dates |
| Deduplicated public communication events | 3,488 |
| Preserved source observations | 4,313 |
| Frozen artifact rows | 4,799 |
| Concrete audio/video/transcript links | 411 |
| Participants with at least one accepted communication | 49 of 57 |
| Coverage matrix | 68,796 applicable tenure/year/event/source/artifact cells |
| Automated tests | 37 passed |

The 73 dissents are directionally classified as 46 `TIGHTER`, 21 `EASIER`, four `TIGHTER_GUIDANCE`, one `EASIER_GUIDANCE`, and one `TIGHTER_BALANCE_SHEET`.

## What “full history” means here

The release covers the complete requested **time window** and exhausts the frozen **registered source universe** through the release date. It collects all discoverable official public communications during a qualifying policymaker tenure before topic classification. Counts are results, not targets.

It does not mean universal historical closure. Eight attendance-derived participants have no accepted communication in the registered archives:

- Cheryl L. Venable
- Helen E. Mucciolo
- Kathleen O'Neill Paese
- Kelly J. Dubbert
- Marie Gooding
- Meredith Black
- Naureen Hassan
- Sushmita Shukla

Most are interim presidents or designated alternates. A zero remains `UNKNOWN`; it is never translated into “this person never spoke.” Kevin Warsh now has an official 2026-08-28 event, which is why coverage increased from 48 to 49 people when the release boundary was extended through 2026-09-05.

## Open gaps that prevent C3/C5

- 10 known in-scope legacy Kansas City URLs remain dead.
- One additional in-scope source fetch remains unresolved.
- 10 St. Louis Fed prepared-text PDF URLs timed out; because some link to more than one reconciled source row, they produce 19 `KNOWN_GAP` artifact rows. Their official HTML event pages are preserved.
- 195 rejected candidate pages do not expose an auditable event date.
- 277 dead archive URLs do not expose enough evidence to attribute an author. These are `UNKNOWN`, not silently discarded accepted events.
- Exact speech/posting times are not generally published. Every event retains its dated official basis; date-only events use end-of-day as a conservative analytical upper bound, and same-day communications are excluded from SEP snapshots.
- C4 requires documented archive/library investigation. C5 additionally requires zero unresolved discrepancies and zero known gaps inside the frozen source universe. Neither claim is made here.

## Point-in-time stance output

The latest available SEP is 2026-06-17 and contains 20 eligible participants:

- 9 have classified named personal evidence.
- 7 use an explicitly labelled `VOTE_ACTION_PROXY`.
- 4 remain `UNKNOWN`: Austan D. Goolsbee, Cheryl L. Venable, Mary C. Daly, and Sushmita Shukla.

`member_latest_stance.csv` means “latest classified evidence available by the cutoff.” It is not necessarily a classification of the person's most recent communication, and it is never presented as an individual SEP dot. `evidence_date`, `evidence_age_days`, the raw snippet, and the official URL show exactly how stale or direct each label is.

## Audit entry points

- Frozen definition: `docs/FOMC_COMPLETENESS_SPEC.md`
- Frozen source universe: `data/fomc_tracker/spec/source_registry_v1.0.json`
- Participant and tenure evidence: `data/fomc_tracker/output/members_full.csv`, `policy_tenures.csv`, `universe_memberships.csv`
- Votes and dissent direction: `data/fomc_tracker/output/votes.csv`
- Deduplicated events: `data/fomc_tracker/output/communication_events.csv`
- Every source URL, snippet, raw path, hash, and date basis: `data/fomc_tracker/output/event_sources.csv`
- Artifact versions and hashes: `data/fomc_tracker/output/artifacts.csv`
- Rejections and unresolved items: `data/fomc_tracker/output/communication_rejections.csv`
- Smallest measured coverage cells: `data/fomc_tracker/output/communication_coverage_cells.csv`
- SEP snapshots and latest table: `data/fomc_tracker/output/member_stance_by_sep.csv`, `member_latest_stance.csv`, `member_latest_stance.md`
- Release binding and aggregate hashes: `data/fomc_tracker/output/release_manifest.json`

## Reproduce and verify

```bash
python3 tools/fomc_tracker.py --data-dir data/fomc_tracker
python3 tools/fomc_participant_master.py build --data-dir data/fomc_tracker
python3 tools/fomc_speech_catalog.py build --data-dir data/fomc_tracker
python3 tools/fomc_public_communications.py fetch --data-dir data/fomc_tracker --workers 12
python3 tools/fomc_public_communications.py build --data-dir data/fomc_tracker
python3 tools/fomc_public_communications.py fetch-artifacts --data-dir data/fomc_tracker --workers 12
python3 tools/fomc_public_communications.py build --data-dir data/fomc_tracker
python3 tools/fomc_stance_snapshots.py --data-dir data/fomc_tracker
python3 tools/fomc_release_manifest.py verify --data-dir data/fomc_tracker
python3 -m pytest tests/ -q
```

The `fetch` commands require internet access. The published frozen raw files let an auditor verify the released outputs without silently substituting today's webpages.

## Data flow

```text
Board + 12 Reserve Banks + FRASER
  -> frozen raw pages/files + URLs + timestamps + SHA-256
  -> participant / vote / event / source / artifact tables
  -> conservative deduplication + explicit UNKNOWN and KNOWN_GAP rows
  -> SEP cutoff with same-day unknown-time communications excluded
  -> member stance and change versus immediately prior SEP
  -> release manifest + clean-tree tests + public GitHub audit link
```
