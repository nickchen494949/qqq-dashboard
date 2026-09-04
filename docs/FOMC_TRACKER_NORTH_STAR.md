# FOMC tracker north star

- Outcome: an auditable FOMC member/vote/event tracker with point-in-time SEP snapshots.
- Current gate: verified official named policy roll calls and every SEP snapshot from 2012 through the latest available 2026 meeting.
- Non-goals: no strategy changes, NLP classifier, database, service, dashboard framework, or automatic hawk/dove inference.
- Owned paths: `tools/fomc_tracker.py`, `tests/test_fomc_tracker.py`, and `data/fomc_tracker/` after installation.
- Pass evidence: every raw file hashes, every parsed dissent has an explicit direction, every listed SEP date has a named voting cohort, every speech snippet exists in its frozen source, and every snapshot uses evidence dated on or before its SEP date.
