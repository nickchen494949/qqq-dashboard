# Federal Reserve public communications completeness specification v1.0

Status: **FROZEN**

Frozen at: **2026-09-05T02:55:27Z**

Coverage start: **2012-01-01**

Machine-readable contract: `data/fomc_tracker/spec/completeness_spec_v1.0.json`

## 1. Claim this specification permits

This project may claim only that it has measured coverage of Federal Reserve policymakers' public communications within a named, versioned source universe. It must report unresolved gaps and the highest completeness level actually passed.

It must not claim that a row count proves completeness, that a missing record means a person never spoke, or that a closed registered-source search proves that no historical material exists elsewhere.

Counts such as 45 voters, 57 observed participants, or 2,701 catalog rows are outputs of a particular run. They are not requirements written into this specification.

## 2. Time boundary and versions

Every release must freeze all of the following:

- `coverage_start`: earliest event date allowed; v1.0 uses 2012-01-01.
- `coverage_end`: latest event date allowed for that release.
- `snapshot_created_at`: immutable time at which the release was created.
- `source_checked_through`: latest completed source-check time represented by the release.
- `spec_version`, `source_registry_version`, `code_commit`, raw aggregate hash, and output aggregate hash.

Historical releases are immutable. A later backfill creates a new database vintage; it does not rewrite an older release.

## 3. Person universes are rules, not fixed counts

### `VOTE_UNIVERSE`

A person enters when an official FOMC policy record names that person as casting a policy vote on or after `coverage_start`. Concurring and dissenting voters are included. Notation votes unrelated to a monetary-policy action are excluded.

### `DELIBERATION_UNIVERSE`

A person enters for an interval only when both conditions hold:

1. The person held an eligible policy office: Board governor, Reserve Bank president, officially designated acting/interim Reserve Bank president, or officially designated FOMC alternate such as the New York Fed first vice president.
2. An official FOMC roster or minutes identifies the person in a policymaker, alternate-member, or Reserve Bank president attendance category.

Staff, economists, advisers, managers, invited presenters, and other attendees do not enter solely because their names appear in the attendance section.

Each qualifying interval must retain `role`, `institution`, `effective_from`, `effective_to`, `role_basis_url`, and `participation_basis_url`. Observed attendance dates are not silently converted into appointment tenure.

### `SEP_UNIVERSE`

For each SEP date, the project records separately:

- `sep_eligible`: official role made the person eligible to participate.
- `sep_submitted`: an official source confirms that the person submitted projections.
- `sep_identity_public`: an official public key permits attribution of an anonymous projection package to the person.
- `individual_projection_known`: an official released key and projection package permit a specific projection to be attributed.

Absence of a named public key is `UNKNOWN`, not evidence that a person did or did not submit. Public dot plots and ranges are not assigned to named individuals before official attribution becomes available.

The number of people in each universe is recomputed from evidence for every release.

## 4. Communication scope

The ingestion layer collects all discoverable official public communications issued during a qualifying tenure before deciding whether they are relevant to monetary policy. Topic relevance belongs to a later classification layer.

Included event types are:

- speech
- remarks
- opening remarks
- testimony
- interview
- panel or moderated discussion
- question and answer session
- press conference
- personal public statement, including a dissent explanation
- article, essay, or official publication by the person
- public letter expressing the person's policy view
- other official public communication, with a required explanation

Biographies, event announcements with no communication, third-party reporting, staff-only work, and anonymous committee material are excluded from the personal-communication table. Committee statements, minutes, implementation notes, and SEP releases are stored as separate committee events and linked where relevant.

## 5. Event, artifact, source, and version model

One real-world communication is one `communication_event`, even when several websites or file formats describe it.

```text
person -> tenure -> policy participation
                         |
                         v
communication_event -> event_source -> source observation
          |
          v
       artifact -> artifact_version -> frozen raw bytes
```

Event format and delivery mode are separate, multi-valued dimensions. One panel may contain prepared opening remarks and an extemporaneous question-and-answer segment.

Artifact types include event listing, HTML prepared text, PDF prepared text, full transcript, Q&A transcript, audio, video, captions, and official summary. A verified artifact proves that artifact exists and was captured; it does not prove that an unlisted Q&A or transcript never existed.

Revised files create new `artifact_version` rows. Raw bytes are never overwritten or normalized in place.

## 6. Two time axes and point-in-time rules

Required event/source fields:

- `event_date` and, when published, `event_time` plus timezone
- `public_available_at`: earliest time supported by evidence that the public could access the item
- `source_last_modified_at`: publisher-reported modification time, if available
- `first_seen_at`: first time this database observed the item
- `last_checked_at`: latest source verification time
- `retrieved_at`: time the frozen artifact bytes were fetched

The database maintains two distinct views:

1. `MARKET_TIME_SNAPSHOT`: what can be supported as publicly available by the analytical cutoff. Include only evidence with `public_available_at <= analytical_cutoff`.
2. `DATABASE_VINTAGE`: what this database had actually captured by a release. Include only evidence with `first_seen_at <= snapshot_created_at`.

A later discovery may improve a new reconstructed market-time snapshot if earlier public availability can be proved, but it must not alter an old frozen database vintage.

If an event and SEP occur on the same date and exact public availability time is unknown, the event is excluded from that SEP's market-time stance snapshot. Dates and times are never invented.

## 7. SEP-aligned stance is not a personal SEP-dot claim

The member stance table at an SEP date uses only named evidence publicly available by the cutoff: personal communications, named policy votes, and explicit dissent direction. It is a point-in-time stance estimate aligned to the SEP date.

It must not be described as the member's SEP dot or individual SEP forecast unless an official released key supports that attribution. Committee-action proxies remain labelled `VOTE_ACTION_PROXY`; they are not personal speech evidence.

## 8. Source universe and reconciliation

The mandatory primary institutional universe is the Board of Governors plus all twelve Reserve Banks. FRASER is the mandatory official archival source. Exact indexes, APIs, sitemaps, feeds, archive pages, pagination rules, and retrieval outcomes are recorded in a versioned source registry.

Official partner hosts such as another central bank or conference host may supply corroborating artifacts. Search engines, news reports, and aggregators may be used only for discovery unless the original official artifact is unavailable; their evidentiary role must be labelled.

Coverage is measured by the smallest applicable cell:

```text
person x qualifying tenure x institution x year x event type x source x artifact type
```

For every registered source the release preserves enumeration method, page/token exhaustion evidence, source-reported totals when available, HTTP failures, parser failures, first/last checked time, and discrepancy disposition.

## 9. Evidence and gap states

Every status is scoped to a named entity, source, artifact type, and check time.

- `VERIFIED_PRESENT`: the scoped item exists and the supporting evidence is preserved.
- `VERIFIED_ABSENT`: an authoritative source explicitly establishes absence within the stated scope.
- `KNOWN_GAP`: the event or artifact is known to exist but is missing, inaccessible, or unresolved.
- `UNKNOWN`: available evidence cannot determine presence or absence.
- `NOT_APPLICABLE`: the artifact or check does not apply, with a reason.

A missing link on one page is not `VERIFIED_ABSENT` globally. Zero event rows never imply that a person never spoke.

## 10. Completeness levels

- `C0_DISCOVERED`: records exist, but coverage has not been enumerated.
- `C1_PRIMARY_ENUMERATED`: applicable primary official indexes have been exhausted and the traversal proof is preserved.
- `C2_CROSS_SOURCE_RECONCILED`: applicable official institutions and FRASER have been compared; every discrepancy is resolved or explicitly open.
- `C3_ARTIFACT_VERIFIED`: each accepted event has verified source metadata and every claimed artifact is accessible or preserved, parsed where applicable, and hashed.
- `C4_ARCHIVAL_INVESTIGATED`: historical missing periods have received documented archive/library investigation, including replies or documented non-response.
- `C5_CLOSED_WITHIN_FROZEN_SOURCE_UNIVERSE`: the exact source registry is frozen, all applicable traversal is exhausted, and unresolved discrepancies and known gaps are zero within that registry.

C5 is never a claim of universal historical completeness outside the frozen source universe. The current automated project target is C3. It may report lower levels by person or coverage cell; it must not promote the whole database to the best-performing person's level.

## 11. Deduplication and revisions

Candidate records are merged only when evidence supports the same speaker, real-world event, event date, venue/context, and compatible title or content. Ambiguous candidates remain separate and receive a discrepancy record.

Every event retains all discovery paths and source URLs. Canonicalization never deletes source evidence. Content changes are preserved as artifact versions with hashes and retrieval times.

## 12. Frozen provenance and lineage

The required lineage is:

```text
raw source -> normalized event/artifact tables -> stance features -> SEP-aligned outputs
```

Each transformation records the specification version and hash, source-registry version, code commit, run parameters, input hashes, output hashes, and environment identifier. Raw official bytes, failures, and superseded runs are preserved. Secrets, cookies, tokens, and signed URLs are excluded from manifests.

## 13. Release acceptance gate

A release report must contain:

1. Universe counts produced by the rules, with inclusion evidence and unresolved identity/tenure cases.
2. Coverage level by person and coverage cell, not only a global row count.
3. Event, source, and artifact counts after deduplication.
4. All `KNOWN_GAP` and `UNKNOWN` rows and their effect on the claim.
5. Source traversal failures and discrepancies.
6. Market-time and database-vintage identifiers.
7. Manifest verification, focused tests, and one real end-to-end rebuild from frozen inputs.
8. A plain-language statement of what is complete, what is not, and what evidence would raise the level.

## 14. Status of the existing catalog

The existing 2,701-row catalog predates this frozen specification. It is a useful candidate corpus, but it has not passed the new source-registry, tenure, event/artifact, bitemporal, or coverage-cell gates. It remains `PRE_SPEC_WIP_UNASSESSED` and must not be called complete or C3.

The next implementation gate is to build the rule-derived person/tenure tables and versioned source registry, then measure the existing catalog against this contract before further crawling.

## 15. Change control

Any semantic change to universe eligibility, included communication types, time logic, source closure, status meaning, or completeness gates requires a new specification version and hash. A data refresh under unchanged rules creates a new database vintage, not a new specification version.

## Official references

- FOMC structure and nonvoting-president participation: https://www.federalreserve.gov/monetarypolicy/fomc.htm
- Example 2012 attendance categories: https://www.federalreserve.gov/monetarypolicy/fomcminutes20120620.htm
- SEP historical attribution and key-release lags: https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm
- Board speeches and testimony indexes: https://www.federalreserve.gov/newsevents/speeches-testimony.htm
- Example mixed speeches/publications archive: https://www.dallasfed.org/news/speeches/logan
- Evidence that older Bank speeches may require FRASER and library requests: https://fraser.stlouisfed.org/files/docs/historical/frbsf/workingpapers/frbsf_wp2019-02.pdf
