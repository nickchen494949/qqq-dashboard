#!/usr/bin/env python3
"""Build no-look-ahead, SEP-aligned member stance tables.

Only named dissents and the small manually reviewed communication set receive a
personal directional label.  A concurring vote is retained as an explicitly
labelled committee-action proxy.  Unclassified communications remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(data_dir: Path) -> dict:
    output = data_dir / "output"
    sep_universe = read_csv(output / "sep_universe.csv")
    votes = read_csv(output / "votes.csv")
    reviewed = read_csv(data_dir / "curated" / "speech_events.csv")
    supplemental_annotations = data_dir / "curated" / "stance_annotations.csv"
    if supplemental_annotations.exists():
        reviewed.extend(read_csv(supplemental_annotations))
    communications = read_csv(output / "communication_events.csv")
    sources = read_csv(output / "event_sources.csv")
    source_by_event: dict[str, dict] = {}
    for row in sources:
        source_by_event.setdefault(row["communication_event_id"], row)

    vote_by_person: dict[str, list[dict]] = defaultdict(list)
    for row in votes:
        vote_by_person[row["member_name"]].append(row)
    for rows in vote_by_person.values():
        rows.sort(key=lambda row: row["meeting_date"])

    reviewed_by_person: dict[str, list[dict]] = defaultdict(list)
    for row in reviewed:
        reviewed_by_person[row["member_name"]].append(row)
    for rows in reviewed_by_person.values():
        rows.sort(key=lambda row: row["publication_date"])

    communications_by_person: dict[str, list[dict]] = defaultdict(list)
    for row in communications:
        communications_by_person[row["member_name"]].append(row)
    for rows in communications_by_person.values():
        rows.sort(key=lambda row: (row["event_date"], row["communication_event_id"]))

    sep_people: dict[str, list[str]] = defaultdict(list)
    for row in sep_universe:
        sep_people[row["sep_date"]].append(row["member_name"])

    result: list[dict] = []
    prior_score: dict[str, tuple[str, int | None]] = {}
    ordered_sep_dates = sorted(sep_people)
    for sep_index, sep_date in enumerate(ordered_sep_dates):
        immediately_prior_sep = ordered_sep_dates[sep_index - 1] if sep_index else ""
        for member in sorted(set(sep_people[sep_date])):
            # The event table records a date-only conservative availability
            # bound.  Requiring that bound to precede 00:00 UTC on the SEP date
            # makes the no-look-ahead exclusion explicit and machine-checkable.
            sep_day_start = sep_date + "T00:00:00Z"
            eligible_comms = [
                row for row in communications_by_person.get(member, [])
                if row["public_available_at"] != "UNKNOWN" and row["public_available_at"] < sep_day_start
            ]
            latest_comm = eligible_comms[-1] if eligible_comms else None

            same_day_votes = [row for row in vote_by_person.get(member, []) if row["meeting_date"] == sep_date]
            latest_vote = same_day_votes[-1] if same_day_votes else None
            eligible_reviewed = [row for row in reviewed_by_person.get(member, []) if row["publication_date"] < sep_date]
            latest_reviewed = eligible_reviewed[-1] if eligible_reviewed else None

            if latest_vote and latest_vote["vote"] == "AGAINST":
                stance_label = latest_vote["dissent_direction"]
                score = int(latest_vote["stance_score"])
                evidence_basis = "NAMED_DISSENT"
                evidence_date = sep_date
                evidence_url = latest_vote["source_url"]
                evidence_snippet = latest_vote["raw_snippet"]
            elif latest_reviewed:
                stance_label = latest_reviewed["stance_label"]
                score = int(latest_reviewed["stance_score"])
                evidence_basis = latest_reviewed.get("evidence_basis") or "MANUALLY_REVIEWED_PERSONAL_COMMUNICATION"
                evidence_date = latest_reviewed["publication_date"]
                evidence_url = latest_reviewed["source_url"]
                evidence_snippet = latest_reviewed["raw_snippet"]
            elif latest_vote:
                stance_label = "COMMITTEE_" + latest_vote["committee_action"]
                score = int(latest_vote["stance_score"])
                evidence_basis = "VOTE_ACTION_PROXY"
                evidence_date = sep_date
                evidence_url = latest_vote["source_url"]
                evidence_snippet = latest_vote["raw_snippet"]
            else:
                stance_label = "UNKNOWN"
                score = None
                evidence_basis = "NO_DIRECTIONAL_PERSONAL_EVIDENCE_CLASSIFIED"
                evidence_date = ""
                evidence_url = ""
                evidence_snippet = ""

            previous_record = prior_score.get(member)
            previous = previous_record[1] if previous_record and previous_record[0] == immediately_prior_sep else None
            if score is None or previous is None:
                change = "UNKNOWN"
            elif score > previous:
                change = "MORE_HAWKISH"
            elif score < previous:
                change = "MORE_DOVISH"
            else:
                change = "UNCHANGED"
            # "Prior SEP" means the immediately preceding SEP row for this
            # person, not the last known score carried across UNKNOWN periods.
            prior_score[member] = (sep_date, score)

            latest_source = source_by_event.get(latest_comm["communication_event_id"], {}) if latest_comm else {}
            age = (date.fromisoformat(sep_date) - date.fromisoformat(evidence_date)).days if evidence_date else ""
            result.append({
                "sep_date": sep_date,
                "member_name": member,
                "stance_label": stance_label,
                "stance_score": "" if score is None else score,
                "change_vs_prior_sep": change,
                "evidence_basis": evidence_basis,
                "evidence_date": evidence_date,
                "evidence_age_days": age,
                "evidence_url": evidence_url,
                "evidence_snippet": evidence_snippet,
                "latest_communication_date": latest_comm["event_date"] if latest_comm else "",
                "latest_communication_title": latest_comm["title"] if latest_comm else "",
                "latest_communication_url": latest_source.get("source_url", ""),
                "cutoff_rule": "COMMUNICATION_EVENT_DATE_STRICTLY_BEFORE_SEP_WHEN_TIME_UNKNOWN",
                "analytical_cutoff": "SEP_RELEASE_DATE_AFTER_OFFICIAL_POLICY_STATEMENT; EXACT_RELEASE_TIME_NOT_STORED",
                "individual_sep_projection_known": "NO",
            })

    fields = [
        "sep_date", "member_name", "stance_label", "stance_score", "change_vs_prior_sep",
        "evidence_basis", "evidence_date", "evidence_age_days", "evidence_url", "evidence_snippet",
        "latest_communication_date", "latest_communication_title", "latest_communication_url",
        "cutoff_rule", "analytical_cutoff", "individual_sep_projection_known",
    ]
    write_csv(output / "member_stance_by_sep.csv", result, fields)
    latest_date = max(row["sep_date"] for row in result)
    latest = [row for row in result if row["sep_date"] == latest_date]
    write_csv(output / "member_latest_stance.csv", latest, fields)

    lines = [
        f"# FOMC participant stance at latest SEP ({latest_date})", "",
        "This is the latest classified named-evidence stance available by the cutoff, not a reconstruction of personal SEP dots and not necessarily a classification of the person's latest communication. UNKNOWN means the database has not classified directional personal evidence by the cutoff.", "",
        "| Member | Latest stance | Change | Basis | Evidence date | Latest official communication |", "|---|---|---|---|---|---|",
    ]
    for row in latest:
        latest_link = row["latest_communication_title"].replace("|", "\\|") or "none found"
        if row["latest_communication_url"]:
            latest_link = f"[{latest_link}]({row['latest_communication_url']})"
        lines.append(
            f"| {row['member_name']} | {row['stance_label']} | {row['change_vs_prior_sep']} | "
            f"{row['evidence_basis']} | {row['evidence_date'] or 'UNKNOWN'} | {latest_link} |"
        )
    (output / "member_latest_stance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "schema_version": 1,
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sep_dates": len(sep_people),
        "snapshot_rows": len(result),
        "latest_sep": latest_date,
        "latest_participants": len(latest),
        "latest_personal_directional_rows": sum(row["evidence_basis"] not in {"VOTE_ACTION_PROXY", "NO_DIRECTIONAL_PERSONAL_EVIDENCE_CLASSIFIED"} for row in latest),
        "latest_vote_action_proxy_rows": sum(row["evidence_basis"] == "VOTE_ACTION_PROXY" for row in latest),
        "latest_unknown_rows": sum(row["stance_label"] == "UNKNOWN" for row in latest),
        "no_lookahead_rule": "Same-day communications with unknown publication time are excluded; named same-day policy votes come from the official post-meeting statement.",
        "outputs": {
            "member_stance_by_sep.csv": sha256(output / "member_stance_by_sep.csv"),
            "member_latest_stance.csv": sha256(output / "member_latest_stance.csv"),
            "member_latest_stance.md": sha256(output / "member_latest_stance.md"),
        },
    }
    (output / "stance_snapshot_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    build(args.data_dir.resolve())


if __name__ == "__main__":
    main()
