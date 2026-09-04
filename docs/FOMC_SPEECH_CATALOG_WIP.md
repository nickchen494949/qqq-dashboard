# FOMC speech catalog — external audit work in progress

Status: **NOT COMPLETE**

This branch is a public, auditable snapshot of the full-history build. It is not a completion claim.

## Snapshot scope

- Federal Reserve Board annual speech indexes: 2012–2026 downloaded from official Board pages.
- Board index rows parsed in this snapshot: 952.
- Partial combined catalog rows after creator-validation: 1,000 (952 Board + 48 FRASER).
- FRASER author harvesting was paused during member 14 of 40 to create this consistent Git snapshot.
- Five voters in the existing vote-derived member list do not have a matched FRASER participant collection and require their Reserve Bank/Board official archives.

## Audit entry points

- Downloader/builder: `tools/fomc_speech_catalog.py`
- Partial normalized output: `data/fomc_tracker/output/speech_catalog.csv`
- Output summary and hash: `data/fomc_tracker/output/speech_catalog_summary.json`
- Frozen Board indexes: `data/fomc_tracker/raw/speech_catalog/board_indexes/`
- Frozen FRASER metadata: `data/fomc_tracker/raw/speech_catalog/fraser_fomc_participants.json` and `fraser_oai/`

## Timing rules

- `event_date` is the actual dated speech/event date exposed by the official archive.
- `published_date` is separate and remains `UNKNOWN` unless the official source exposes it.
- Exact event/publication time and timezone remain `UNKNOWN` unless explicitly published.
- A same-day record with unknown publication time must not be treated as available before a point-in-time cutoff.

## Known gaps at this snapshot

- FRASER download is partial and has per-record HTTP failures; final manifest will list every failed identifier.
- FRASER's OAI resumption token was observed returning unrelated global records on later pages. The builder therefore requires each MODS record's embedded creator to match the member; unrelated frozen responses are excluded from normalized output.
- Official district-bank archive supplementation and member-by-member gap checks are pending.
- The existing `members.csv` is a master of observed named voters, not every nonvoting FOMC participant. That label will be corrected or expanded before final acceptance.
- Stance classification remains the small manually labeled subset until catalog completeness is proven. Metadata rows are not silently assigned hawk/dove labels.
