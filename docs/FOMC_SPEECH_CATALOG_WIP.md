# FOMC speech catalog — external audit work in progress

Status: **NOT COMPLETE**

This branch is a public, auditable snapshot of the full-history build. It is not a completion claim.

## Snapshot scope

- Federal Reserve Board annual speech indexes: 2012–2026 downloaded from official Board pages.
- Board index rows parsed in this snapshot: 952.
- Current local catalog rows after creator-validation: 2,696 (952 Board + 1,415 FRASER + 329 official district-bank rows).
- FRASER rows cover 22 regional-bank members; Board governors are covered by the Board annual indexes instead of FRASER.
- All 45 people in the existing vote-derived member list now have official events. The four district supplements add Alberto Musalem (22), Jeffrey Schmid (21), Lorie Logan (31), and Neel Kashkari (255).

## Audit entry points

- Downloader/builder: `tools/fomc_speech_catalog.py`
- Partial normalized output: `data/fomc_tracker/output/speech_catalog.csv`
- Output summary and hash: `data/fomc_tracker/output/speech_catalog_summary.json`
- Frozen Board indexes: `data/fomc_tracker/raw/speech_catalog/board_indexes/`
- Frozen FRASER metadata: `data/fomc_tracker/raw/speech_catalog/fraser_fomc_participants.json` and `fraser_oai/`
- Frozen district-bank pages and APIs: `data/fomc_tracker/raw/speech_catalog/district_supplements/`
- Member-by-member counts: `data/fomc_tracker/output/speech_catalog_coverage.csv`

## Timing rules

- `event_date` is the actual dated speech/event date exposed by the official archive.
- `published_date` is separate and remains `UNKNOWN` unless the official source exposes it.
- Exact event/publication time and timezone remain `UNKNOWN` unless explicitly published.
- A same-day record with unknown publication time must not be treated as available before a point-in-time cutoff.

## Known gaps at this snapshot

- FRASER has per-record HTTP failures; the fetch manifest lists every failed identifier.
- FRASER's OAI resumption token was observed returning unrelated global records on later pages. The builder now accepts records only when the item belongs to that member's official FRASER collection or its embedded creator matches. Unrelated frozen responses are excluded from normalized output.
- The Kansas City sitemap contains many stale URLs. The district fetch manifest preserves 185 HTTP failures instead of silently dropping them; 21 usable Schmid events are included, beginning with his Nov. 7, 2023 opening remarks.
- The existing `members.csv` is a master of observed named voters, not every nonvoting FOMC participant. That label will be corrected or expanded before final acceptance.
- Stance classification remains the small manually labeled subset until catalog completeness is proven. Metadata rows are not silently assigned hawk/dove labels.
