#!/usr/bin/env python3
"""Build a 2012-present FOMC participant master from official meeting minutes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


FED_ROOT = "https://www.federalreserve.gov"
USER_AGENT = "fomc-audit-participant-master/1.0"
MINUTES_ALIASES = {"2020-03-03": "2020-03-15"}
PERSON_ALIASES = {
    "Ben Bernanke": "Ben S. Bernanke",
    "Elizabeth Duke": "Elizabeth A. Duke",
    "Eric Rosengren": "Eric S. Rosengren",
    "Kathleen O'Neill": "Kathleen O'Neill Paese",
}

BOARD_MEMBERS = {
    "Adriana D. Kugler", "Ben S. Bernanke", "Christopher J. Waller",
    "Daniel K. Tarullo", "Elizabeth A. Duke", "Janet L. Yellen",
    "Jeremy C. Stein", "Jerome H. Powell", "Kevin Warsh", "Lael Brainard",
    "Lisa D. Cook", "Michael S. Barr", "Michelle W. Bowman",
    "Philip N. Jefferson", "Randal K. Quarles", "Richard H. Clarida",
    "Sarah Bloom Raskin", "Stanley Fischer", "Stephen I. Miran",
}

# Institution is stable and auditable even when an exact appointment day is not
# exposed by the FOMC minutes.  Exact tenure dates are deliberately not inferred
# from first/last attendance; the output labels those dates as observation bounds.
RESERVE_BANK_BY_PERSON = {
    "Alberto G. Musalem": "Federal Reserve Bank of St. Louis",
    "Anna Paulson": "Federal Reserve Bank of Philadelphia",
    "Austan D. Goolsbee": "Federal Reserve Bank of Chicago",
    "Beth M. Hammack": "Federal Reserve Bank of Cleveland",
    "Charles I. Plosser": "Federal Reserve Bank of Philadelphia",
    "Charles L. Evans": "Federal Reserve Bank of Chicago",
    "Cheryl L. Venable": "Federal Reserve Bank of Atlanta",
    "Dennis P. Lockhart": "Federal Reserve Bank of Atlanta",
    "Eric S. Rosengren": "Federal Reserve Bank of Boston",
    "Esther L. George": "Federal Reserve Bank of Kansas City",
    "James Bullard": "Federal Reserve Bank of St. Louis",
    "Jeffrey M. Lacker": "Federal Reserve Bank of Richmond",
    "Jeffrey R. Schmid": "Federal Reserve Bank of Kansas City",
    "John C. Williams": "Federal Reserve Bank of San Francisco;Federal Reserve Bank of New York",
    "Kathleen O'Neill Paese": "Federal Reserve Bank of St. Louis",
    "Kelly J. Dubbert": "Federal Reserve Bank of Kansas City",
    "Kenneth C. Montgomery": "Federal Reserve Bank of Boston",
    "Lorie K. Logan": "Federal Reserve Bank of Dallas",
    "Loretta J. Mester": "Federal Reserve Bank of Cleveland",
    "Marie Gooding": "Federal Reserve Bank of Atlanta",
    "Mark L. Mullinix": "Federal Reserve Bank of Richmond",
    "Mary C. Daly": "Federal Reserve Bank of San Francisco",
    "Meredith Black": "Federal Reserve Bank of Dallas",
    "Narayana Kocherlakota": "Federal Reserve Bank of Minneapolis",
    "Neel Kashkari": "Federal Reserve Bank of Minneapolis",
    "Patrick Harker": "Federal Reserve Bank of Philadelphia",
    "Raphael W. Bostic": "Federal Reserve Bank of Atlanta",
    "Richard W. Fisher": "Federal Reserve Bank of Dallas",
    "Robert S. Kaplan": "Federal Reserve Bank of Dallas",
    "Sandra Pianalto": "Federal Reserve Bank of Cleveland",
    "Susan M. Collins": "Federal Reserve Bank of Boston",
    "Thomas I. Barkin": "Federal Reserve Bank of Richmond",
    "William C. Dudley": "Federal Reserve Bank of New York",
}

NY_ALTERNATES = {
    "Christine Cumming", "Helen E. Mucciolo", "Michael Strine",
    "Naureen Hassan", "Sushmita Shukla",
}
INTERIM_PRESIDENTS = {
    "Cheryl L. Venable", "Kathleen O'Neill Paese", "Kelly J. Dubbert",
    "Kenneth C. Montgomery", "Marie Gooding", "Mark L. Mullinix",
    "Meredith Black",
}
FED_HISTORY_ROOT = "https://www.federalreservehistory.org"
FED_HISTORY_INTERIM = FED_HISTORY_ROOT + "/interim"
BOARD_MEMBERSHIP_URL = FED_ROOT + "/aboutthefed/bios/board/boardmembership.htm"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def minutes_url(meeting_date: str) -> str:
    return FED_ROOT + "/monetarypolicy/fomcminutes" + meeting_date.replace("-", "") + ".htm"


def fetch_one(url: str, path: Path) -> dict:
    if path.exists():
        return {"url": url, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path), "status": "OK_REUSED"}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return {"url": url, "path": path.as_posix(), "bytes": 0, "sha256": "", "status": f"HTTP_{exc.code}"}
    except urllib.error.URLError as exc:
        return {"url": url, "path": path.as_posix(), "bytes": 0, "sha256": "", "status": f"URL_ERROR:{exc.reason}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"url": url, "path": path.as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "status": "OK"}


def fetch(data_dir: Path) -> dict:
    dates = sorted({row["meeting_date"] for row in read_csv(data_dir / "output" / "votes.csv")})
    raw_dir = data_dir / "raw" / "minutes_history"
    source_dates = sorted({MINUTES_ALIASES.get(day, day) for day in dates})
    items = [(minutes_url(day), raw_dir / f"fomcminutes{day.replace('-', '')}.htm") for day in source_dates]
    source_records = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, url, path): (url, path) for url, path in items}
        for position, future in enumerate(as_completed(futures), start=1):
            source_records.append(future.result())
            if position % 25 == 0:
                print(f"minutes {position}/{len(items)}", flush=True)
    by_url = {row["url"]: row for row in source_records}
    records = []
    for day in dates:
        source_day = MINUTES_ALIASES.get(day, day)
        source = dict(by_url[minutes_url(source_day)])
        source["requested_meeting_date"] = day
        source["source_meeting_date"] = source_day
        if day in MINUTES_ALIASES and source["status"].startswith("OK"):
            source["status"] = "OK_OFFICIAL_CROSS_REFERENCE"
        records.append(source)
    for row in records:
        row["path"] = Path(row["path"]).relative_to(data_dir).as_posix()
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_meetings": len(dates),
        "unique_minutes_documents": len(items),
        "successful_minutes": sum(row["status"].startswith("OK") for row in records),
        "failed_minutes": sum(not row["status"].startswith("OK") for row in records),
        "files": records,
    }
    (raw_dir / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<sup\b[^>]*>.*?</sup>", "", value, flags=re.I | re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", value)).replace("’", "'").strip()


def clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ,.;:")
    value = re.sub(r"^(?:Messrs\.|Mses\.|Ms\.|Mr\.)\s+", "", value)
    value = re.sub(r",\s*(?:Chair|Vice Chair).*$", "", value)
    return value.strip()


def plausible_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z.'-]+)){1,5}", value))


def list_names(value: str) -> list[str]:
    value = value.replace(" and ", ", ")
    names = [clean_name(part) for part in value.split(",")]
    return [name for name in names if plausible_name(name)]


def parse_attendance(path: Path, meeting_date: str) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    all_paragraphs = re.findall(r"<p\b[^>]*>.*?</p>", raw, re.I | re.S)
    marker_index = next(
        (
            index
            for index, paragraph in enumerate(all_paragraphs)
            if re.match(r"^(?:Attendance|PRESENT:?)\s*(?:\n|$)", strip_tags(paragraph), re.I)
        ),
        None,
    )
    if marker_index is None:
        raise ValueError(f"No attendance section: {path.name}")
    paragraphs = all_paragraphs[marker_index:]
    first_plain = re.sub(r"^(?:Attendance|PRESENT:?)\s*", "", strip_tags(paragraphs[0]), flags=re.I)
    policy_blocks: list[str] = []
    if first_plain:
        policy_blocks.append(first_plain)
    policy_blocks.extend(strip_tags(paragraph) for paragraph in paragraphs[1:])
    rows: list[dict] = []
    source_url = minutes_url(meeting_date)
    for position, plain in enumerate(policy_blocks):
        if position and re.search(r"\b(?:Secretary|General Counsel|Economist)\b", plain):
            break
        if position == 0:
            names = []
            for line in plain.splitlines():
                candidate = clean_name(line.split(",", 1)[0])
                if plausible_name(candidate):
                    names.append(candidate)
            category = "MEMBER_OR_VOTING_BANK_PRESIDENT"
        elif re.search(r"Alternate Members of (?:the )?(?:Federal Open Market )?Committee", plain, re.I):
            names = list_names(re.split(r", Alternate Members", plain, maxsplit=1, flags=re.I)[0])
            category = "ALTERNATE_MEMBER"
        elif re.search(r"(?:Interim )?Presidents of the Federal Reserve Banks", plain, re.I):
            names = list_names(re.split(r", (?:Interim )?Presidents of", plain, maxsplit=1, flags=re.I)[0])
            category = "NONVOTING_BANK_PRESIDENT"
        else:
            continue
        snippet = re.sub(r"\s+", " ", plain).strip()
        for name in names:
            rows.append(
                {
                    "meeting_date": meeting_date,
                    "member_name": PERSON_ALIASES.get(name, name),
                    "raw_member_name": name,
                    "attendance_category": category,
                    "source_url": source_url,
                    "raw_file": path.as_posix(),
                    "raw_snippet": snippet,
                }
            )
    if len(rows) < 12:
        raise ValueError(f"Only {len(rows)} policymakers parsed: {path.name}")
    return rows


def parse_cross_referenced_vote(path: Path, meeting_date: str) -> list[dict]:
    """Extract voters when an official minutes document has no separate attendance roster."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    section = re.search(r"Videoconference meeting of March 2.*", raw, re.I | re.S)
    if not section:
        raise ValueError(f"No March 2 cross-reference section: {path.name}")
    paragraphs = re.findall(r"<p\b[^>]*>.*?</p>", section.group(0), re.I | re.S)
    voting = next((strip_tags(p) for p in paragraphs if re.match(r"^Voting for this action:", strip_tags(p), re.I)), None)
    if not voting:
        raise ValueError(f"No cross-referenced voting list: {path.name}")
    names = list_names(re.sub(r"^Voting for this action:\s*", "", voting, flags=re.I))
    if len(names) < 8:
        raise ValueError(f"Only {len(names)} cross-referenced voters parsed: {path.name}")
    return [
        {
            "meeting_date": meeting_date,
            "member_name": PERSON_ALIASES.get(name, name),
            "raw_member_name": name,
            "attendance_category": "VOTE_LIST_ONLY",
            "source_url": minutes_url(MINUTES_ALIASES[meeting_date]),
            "raw_file": path.as_posix(),
            "raw_snippet": voting,
        }
        for name in names
    ]


def build(data_dir: Path) -> dict:
    raw_dir = data_dir / "raw" / "minutes_history"
    observations: list[dict] = []
    failures: list[dict] = []
    for path in sorted(raw_dir.glob("fomcminutes*.htm")):
        day = datetime.strptime(re.search(r"(20\d{6})", path.name).group(1), "%Y%m%d").date().isoformat()
        try:
            rows = parse_attendance(path, day)
        except ValueError as exc:
            failures.append({"meeting_date": day, "raw_file": path.relative_to(data_dir).as_posix(), "error": str(exc)})
            continue
        for row in rows:
            row["raw_file"] = path.relative_to(data_dir).as_posix()
        observations.extend(rows)
    for meeting_date, source_date in MINUTES_ALIASES.items():
        path = raw_dir / f"fomcminutes{source_date.replace('-', '')}.htm"
        try:
            rows = parse_cross_referenced_vote(path, meeting_date)
        except ValueError as exc:
            failures.append({"meeting_date": meeting_date, "raw_file": path.relative_to(data_dir).as_posix(), "error": str(exc)})
            continue
        for row in rows:
            row["raw_file"] = path.relative_to(data_dir).as_posix()
        observations.extend(rows)
    observations.sort(key=lambda row: (row["meeting_date"], row["member_name"], row["attendance_category"]))
    write_csv(
        data_dir / "output" / "participants_by_meeting.csv",
        observations,
        ["meeting_date", "member_name", "raw_member_name", "attendance_category", "source_url", "raw_file", "raw_snippet"],
    )
    parsed_dates = {row["meeting_date"] for row in observations}
    requested_dates = sorted({row["meeting_date"] for row in read_csv(data_dir / "output" / "votes.csv")})
    coverage = []
    for day in requested_dates:
        if day in MINUTES_ALIASES and day in parsed_dates:
            status = "VOTE_LIST_ONLY_OFFICIAL_CROSS_REFERENCE"
            note = "Vote completed March 3 after the March 2 videoconference; official March 15 minutes publish the voter list but no separate attendance roster"
        elif day in parsed_dates:
            status = "FULL_ATTENDANCE"
            note = "Official minutes attendance section parsed"
        else:
            status = "MISSING"
            note = "No official participant record parsed"
        coverage.append(
            {
                "meeting_date": day,
                "coverage_status": status,
                "source_url": minutes_url(MINUTES_ALIASES.get(day, day)),
                "note": note,
            }
        )
    write_csv(data_dir / "output" / "participant_meeting_coverage.csv", coverage, ["meeting_date", "coverage_status", "source_url", "note"])
    by_name: dict[str, list[dict]] = defaultdict(list)
    for row in observations:
        by_name[row["member_name"]].append(row)
    members = []
    for name, seen in sorted(by_name.items()):
        members.append(
            {
                "member_id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                "member_name": name,
                "first_observed_attendance_date": min(row["meeting_date"] for row in seen),
                "last_observed_attendance_date": max(row["meeting_date"] for row in seen),
                "meetings_observed": len({row["meeting_date"] for row in seen}),
                "attendance_categories": ";".join(sorted({row["attendance_category"] for row in seen})),
                "first_source_url": min(seen, key=lambda row: row["meeting_date"])["source_url"],
                "last_source_url": max(seen, key=lambda row: row["meeting_date"])["source_url"],
                "coverage_note": "Observed in official FOMC minutes; dates are attendance bounds, not appointment tenure",
            }
        )
    write_csv(
        data_dir / "output" / "members_full.csv",
        members,
        ["member_id", "member_name", "first_observed_attendance_date", "last_observed_attendance_date", "meetings_observed", "attendance_categories", "first_source_url", "last_source_url", "coverage_note"],
    )

    # Universe membership is derived from evidence, never from a target count.
    vote_rows = read_csv(data_dir / "output" / "votes.csv")
    vote_evidence: dict[str, dict] = {}
    for row in vote_rows:
        vote_evidence.setdefault(row["member_name"], row)
    attendance_evidence: dict[str, dict] = {}
    for row in observations:
        attendance_evidence.setdefault(row["member_name"], row)
    universe_rows: list[dict] = []
    for name, row in sorted(vote_evidence.items()):
        universe_rows.append({
            "universe": "VOTE_UNIVERSE",
            "member_id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "member_name": name,
            "effective_from": min(r["meeting_date"] for r in vote_rows if r["member_name"] == name),
            "effective_to": max(r["meeting_date"] for r in vote_rows if r["member_name"] == name),
            "evidence_url": row["source_url"],
            "evidence_type": "NAMED_OFFICIAL_POLICY_VOTE",
            "status": "VERIFIED_PRESENT",
        })
    for name, seen in sorted(by_name.items()):
        first = min(seen, key=lambda r: r["meeting_date"])
        universe_rows.append({
            "universe": "DELIBERATION_UNIVERSE",
            "member_id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "member_name": name,
            "effective_from": min(r["meeting_date"] for r in seen),
            "effective_to": max(r["meeting_date"] for r in seen),
            "evidence_url": first["source_url"],
            "evidence_type": "OFFICIAL_FOMC_POLICYMAKER_ATTENDANCE",
            "status": "VERIFIED_PRESENT",
        })
    write_csv(
        data_dir / "output" / "universe_memberships.csv", universe_rows,
        ["universe", "member_id", "member_name", "effective_from", "effective_to", "evidence_url", "evidence_type", "status"],
    )

    # Role/tenure table keeps observed bounds distinct from appointment tenure.
    tenure_rows: list[dict] = []
    for member in members:
        name = member["member_name"]
        if name in BOARD_MEMBERS:
            role = "BOARD_GOVERNOR"
            institution = "Board of Governors of the Federal Reserve System"
            role_url = BOARD_MEMBERSHIP_URL
        elif name in NY_ALTERNATES:
            role = "OFFICIALLY_DESIGNATED_FOMC_ALTERNATE"
            institution = "Federal Reserve Bank of New York"
            role_url = member["first_source_url"]
        elif name in INTERIM_PRESIDENTS:
            role = "ACTING_OR_INTERIM_RESERVE_BANK_PRESIDENT"
            institution = RESERVE_BANK_BY_PERSON[name]
            role_url = FED_HISTORY_INTERIM
        else:
            role = "RESERVE_BANK_PRESIDENT"
            institution = RESERVE_BANK_BY_PERSON.get(name, "UNKNOWN")
            role_url = FED_HISTORY_ROOT + "/people/" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        tenure_rows.append({
            "tenure_id": hashlib.sha256((name + "|" + role + "|" + institution).encode()).hexdigest()[:20],
            "member_id": member["member_id"],
            "member_name": name,
            "role": role,
            "institution": institution,
            "effective_from": member["first_observed_attendance_date"],
            "effective_to": member["last_observed_attendance_date"],
            "date_basis": "OBSERVED_FOMC_PARTICIPATION_BOUNDS_NOT_APPOINTMENT_TENURE",
            "role_basis_url": role_url,
            "participation_basis_url": member["first_source_url"],
            "evidence_status": "VERIFIED_PRESENT",
        })
    write_csv(
        data_dir / "output" / "policy_tenures.csv", tenure_rows,
        ["tenure_id", "member_id", "member_name", "role", "institution", "effective_from", "effective_to", "date_basis", "role_basis_url", "participation_basis_url", "evidence_status"],
    )

    # Public SEP material does not name individual dots.  Eligibility is based on
    # official participation at that meeting; submission/identity remain UNKNOWN.
    sep_dates = {row["sep_date"] for row in read_csv(data_dir / "curated" / "sep_dates.csv")}
    sep_rows: list[dict] = []
    for row in observations:
        if row["meeting_date"] not in sep_dates or row["attendance_category"] == "VOTE_LIST_ONLY":
            continue
        sep_rows.append({
            "sep_date": row["meeting_date"],
            "member_id": re.sub(r"[^a-z0-9]+", "-", row["member_name"].lower()).strip("-"),
            "member_name": row["member_name"],
            "sep_eligible": "YES",
            "sep_submitted": "UNKNOWN",
            "sep_identity_public": "NO",
            "individual_projection_known": "NO",
            "evidence_url": row["source_url"],
            "evidence_status": "VERIFIED_PRESENT",
            "note": "Eligibility inferred from named policymaker participation; no public individual SEP key",
        })
    sep_rows.sort(key=lambda r: (r["sep_date"], r["member_name"]))
    write_csv(
        data_dir / "output" / "sep_universe.csv", sep_rows,
        ["sep_date", "member_id", "member_name", "sep_eligible", "sep_submitted", "sep_identity_public", "individual_projection_known", "evidence_url", "evidence_status", "note"],
    )
    summary = {
        "requested_vote_dates": len(requested_dates),
        "full_attendance_meetings": sum(row["coverage_status"] == "FULL_ATTENDANCE" for row in coverage),
        "vote_list_only_meetings": sum(row["coverage_status"].startswith("VOTE_LIST_ONLY") for row in coverage),
        "missing_meetings": sum(row["coverage_status"] == "MISSING" for row in coverage),
        "participant_rows": len(observations),
        "unique_policy_participants": len(members),
        "vote_universe_count": len(vote_evidence),
        "deliberation_universe_count": len(by_name),
        "sep_universe_rows": len(sep_rows),
        "parse_failures": failures,
        "members_full_sha256": sha256(data_dir / "output" / "members_full.csv"),
        "participants_by_meeting_sha256": sha256(data_dir / "output" / "participants_by_meeting.csv"),
        "participant_meeting_coverage_sha256": sha256(data_dir / "output" / "participant_meeting_coverage.csv"),
        "universe_memberships_sha256": sha256(data_dir / "output" / "universe_memberships.csv"),
        "policy_tenures_sha256": sha256(data_dir / "output" / "policy_tenures.csv"),
        "sep_universe_sha256": sha256(data_dir / "output" / "sep_universe.csv"),
    }
    (data_dir / "output" / "participant_master_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        print(json.dumps(fetch(args.data_dir.resolve()), indent=2))
    else:
        build(args.data_dir.resolve())


if __name__ == "__main__":
    main()
