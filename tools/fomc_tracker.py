#!/usr/bin/env python3
"""Build an auditable 2012-present FOMC member tracker from frozen official HTML."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin


FED_ROOT = "https://www.federalreserve.gov"
HISTORY_START = "2012-01-01"
ACTION_SCORE = {"CUT": -1, "HOLD": 0, "HIKE": 1}
SPEECH_MAX_AGE_DAYS = 180
ROLE_SUFFIXES = ("Chairman", "Vice Chairman", "Chair", "Vice Chair")
NAME_ALIASES = {
    "Eric Rosengren": "Eric S. Rosengren",
    "Beth Hammack": "Beth M. Hammack",
}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        elif not self.skip_depth and tag in {"p", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in {"p", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and re.search(r"/newsevents/pressreleases/monetary20\d{6}a\.htm$", href):
            self.links.append(urljoin(FED_ROOT, href))


def normalized_text(raw: str) -> str:
    parser = TextExtractor()
    parser.feed(raw)
    text = html.unescape("".join(parser.parts))
    text = text.replace("’", "'").replace("“", '"').replace("”", '"').replace("‑", "-")
    return re.sub(r"\s+", " ", text).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_latest_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        f"# Latest FOMC stance at SEP ({rows[0]['sep_date']})",
        "",
        "Scores are evidence labels, not estimated ideology. Change is versus the prior SEP for the same voter; blank means no directly comparable prior-row score.",
        "",
        "| Member | Stance | Score | Change vs prior SEP | Evidence | Date | Source |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for row in rows:
        member = row["member_name"].replace("|", "\\|")
        stance = row["stance_label"].replace("|", "\\|")
        lines.append(
            f"| {member} | {stance} | {row['stance_score']} | {row['change_vs_prior_sep']} | "
            f"{row['evidence_basis']} | {row['evidence_date']} | [official]({row['source_url']}) |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def statement_urls(index_dir: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(index_dir.glob("*.htm")):
        parser = LinkExtractor()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        for url in parser.links:
            found[url.rsplit("/", 1)[-1]] = url
    if len(found) < 100:
        raise ValueError(f"Only {len(found)} official statement links found; expected at least 100")
    return dict(sorted(found.items()))


def meeting_date(filename: str) -> str:
    match = re.search(r"monetary(20\d{6})a\.htm", filename)
    if not match:
        raise ValueError(f"Cannot read meeting date from {filename}")
    return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()


def voting_block(text: str, filename: str) -> str:
    start = text.find("Voting for")
    if start < 0:
        raise ValueError(f"No 'Voting for' record in {filename}")
    tail = text[start:]
    stops = [tail.find(marker) for marker in ("For media inquiries", "Last Update:")]
    stops = [pos for pos in stops if pos > 0]
    block = tail[: min(stops)] if stops else tail[:5000]
    return re.sub(r"\s+", " ", block).strip()


def aggregate_voting_block(text: str, filename: str) -> str:
    marker = "The Federal Open Market Committee approved the following statement for release by"
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"No aggregate vote record in {filename}")
    tail = text[start:]
    stops = [tail.find(value) for value in ("For media inquiries", "Last Update:")]
    stops = [pos for pos in stops if pos > 0]
    block = tail[: min(stops)] if stops else tail[:5000]
    return re.sub(r"\s+", " ", block).strip()


def canonical_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip(" .,:;")
    return NAME_ALIASES.get(cleaned, cleaned)


def affirmative_names(block: str) -> list[str]:
    end_positions = [
        pos
        for pos in (
            block.find("Voting against"),
            block.find("Absent and not voting"),
            block.find(" Statement Regarding"),
        )
        if pos >= 0
    ]
    section = block[: min(end_positions)] if end_positions else block
    section = re.sub(
        r"^Voting for (?:(?:the )?(?:FOMC )?monetary policy action were|this action):?\s*",
        "",
        section,
        flags=re.IGNORECASE,
    )
    section = section.rstrip(" .")
    for role in ROLE_SUFFIXES:
        section = re.sub(rf",\s*{re.escape(role)},", f", {role};", section)
    parts = re.split(r";|,\s*|\band\s+(?=[A-Z])", section)
    names: list[str] = []
    for part in parts:
        part = part.strip(" .,:;")
        if part in ROLE_SUFFIXES:
            continue
        part = re.sub(r",\s*(?:Chairman|Vice Chairman|Chair|Vice Chair).*$", "", part)
        part = canonical_name(part)
        if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z.'-]+)){1,4}", part):
            names.append(part)
    if len(names) < 5:
        raise ValueError(f"Parsed only {len(names)} affirmative voters from: {block[:240]}")
    return names


def infer_action(text: str) -> str:
    policy_text = text[: text.find("Voting for")]
    matches = list(
        re.finditer(
            r"Committee (?:decided|voted)(?: today)? to (lower|reduce|raise|increase|maintain|keep)[^.]{0,450}(?:federal funds|target range)",
            policy_text,
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return "UNKNOWN"
    verb = matches[-1].group(1).lower()
    if verb in {"lower", "reduce"}:
        return "CUT"
    if verb in {"raise", "increase"}:
        return "HIKE"
    return "HOLD"


def dissent_names(block: str, known_names: set[str]) -> list[str]:
    start = block.find("Voting against")
    if start < 0:
        return []
    section = block[start:]
    if re.match(r"Voting against(?: this action)?\s*:\s*None\b", section, flags=re.IGNORECASE):
        return []
    stops = [section.find(marker) for marker in ("Consistent with", "The Committee also voted", "The Board of Governors")]
    stops = [pos for pos in stops if pos > 0]
    if stops:
        section = section[: min(stops)]
    absent = section.find("Absent and not voting")
    if absent >= 0:
        section = section[:absent]
    # Some releases append a separate sentence saying that a Reserve Bank
    # president voted as an alternate. That person supported the action and
    # must not be pulled into the preceding dissent list.
    alternate = re.search(r"[A-Z][^.]{0,120}voted as an alternate member", section)
    if alternate:
        sentence_start = section.rfind(".", 0, alternate.start())
        section = section[: sentence_start + 1]
    found: list[tuple[int, str]] = []
    for name in known_names:
        variants = {name}
        if name == "Eric S. Rosengren":
            variants.add("Eric Rosengren")
        if name == "Beth M. Hammack":
            variants.add("Beth Hammack")
        positions = [section.find(v) for v in variants if section.find(v) >= 0]
        if positions:
            found.append((min(positions), name))
    return [name for _, name in sorted(found)]


def load_statements(data_dir: Path) -> tuple[list[dict], dict[str, str], list[str], list[str]]:
    urls = statement_urls(data_dir / "raw" / "index")
    staged: list[dict] = []
    known_names: set[str] = set()
    non_vote_releases: list[str] = []
    aggregate_vote_releases: list[str] = []
    for filename, url in urls.items():
        path = data_dir / "raw" / "statements" / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing frozen official statement: {path}")
        text = normalized_text(path.read_text(encoding="utf-8", errors="replace"))
        if "Voting for" in text:
            block = voting_block(text, filename)
            for_names = affirmative_names(block)
        elif "approved the following statement for release by" in text:
            block = aggregate_voting_block(text, filename)
            for_names = []
            aggregate_vote_releases.append(filename)
        else:
            non_vote_releases.append(filename)
            continue
        known_names.update(for_names)
        staged.append(
            {
                "meeting_date": meeting_date(filename),
                "source_url": url,
                "raw_file": f"raw/statements/{filename}",
                "raw_snippet": block,
                "action": infer_action(text),
                "for_names": for_names,
            }
        )
    # A member can appear only as a dissenter inside the working slice. The
    # curated direction table is also the explicit identity check for that case.
    for override in read_csv(data_dir / "curated" / "dissent_overrides.csv"):
        known_names.add(canonical_name(override["member_name"]))
    for row in staged:
        row["against_names"] = dissent_names(row["raw_snippet"], known_names)
    action_path = data_dir / "curated" / "action_overrides.csv"
    if action_path.exists():
        staged_by_date = {row["meeting_date"]: row for row in staged}
        for override in read_csv(action_path):
            row = staged_by_date.get(override["meeting_date"])
            if not row:
                raise ValueError(f"Action override has no statement: {override['meeting_date']}")
            if override["committee_action"] not in ACTION_SCORE:
                raise ValueError(f"Invalid action override: {override}")
            row["action"] = override["committee_action"]
    rollcall_path = data_dir / "curated" / "rollcall_overrides.csv"
    if rollcall_path.exists():
        staged_by_date = {row["meeting_date"]: row for row in staged}
        for override in read_csv(rollcall_path):
            row = staged_by_date.get(override["meeting_date"])
            if not row:
                raise ValueError(f"Roll-call override has no statement: {override['meeting_date']}")
            raw_path = data_dir / override["raw_file"]
            if not raw_path.exists():
                raise FileNotFoundError(f"Missing roll-call source: {raw_path}")
            text = normalized_text(raw_path.read_text(encoding="utf-8", errors="replace"))
            block = voting_block(text, raw_path.name)
            parsed_for = affirmative_names(block)
            expected_for = [canonical_name(name) for name in override["for_names"].split("|")]
            if parsed_for != expected_for:
                raise ValueError(f"Roll-call affirmative mismatch on {override['meeting_date']}")
            parsed_against = dissent_names(block, known_names | set(expected_for))
            expected_against = [canonical_name(name) for name in override["against_names"].split("|") if name]
            if parsed_against != expected_against:
                raise ValueError(f"Roll-call dissent mismatch on {override['meeting_date']}")
            row.update(
                {
                    "for_names": parsed_for,
                    "against_names": parsed_against,
                    "source_url": override["source_url"],
                    "raw_file": override["raw_file"],
                    "raw_snippet": block,
                }
            )
    return staged, urls, non_vote_releases, aggregate_vote_releases


def build_member_master(statements: list[dict]) -> list[dict]:
    observations: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for statement in statements:
        for name in statement["for_names"] + statement["against_names"]:
            observations[name].append((statement["meeting_date"], statement["source_url"]))
    rows = []
    for name, seen in sorted(observations.items()):
        seen.sort()
        rows.append(
            {
                "member_id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
                "member_name": name,
                "first_observed_vote_date": seen[0][0],
                "last_observed_vote_date": seen[-1][0],
                "meetings_observed": len({date for date, _ in seen}),
                "observed_voting_years": "|".join(sorted({date[:4] for date, _ in seen})),
                "first_source_url": seen[0][1],
                "last_source_url": seen[-1][1],
                "coverage_note": "Observed FOMC votes; not appointment tenure",
            }
        )
    return rows


def build_votes(data_dir: Path, statements: list[dict]) -> list[dict]:
    overrides = read_csv(data_dir / "curated" / "dissent_overrides.csv")
    override_map = {(row["meeting_date"], canonical_name(row["member_name"])): row for row in overrides}
    rows: list[dict] = []
    seen_overrides: set[tuple[str, str]] = set()
    for statement in statements:
        date = statement["meeting_date"]
        if date < HISTORY_START:
            continue
        action = statement["action"]
        if action not in ACTION_SCORE:
            raise ValueError(f"Unresolved committee action on {date}")
        for name in statement["for_names"]:
            rows.append(
                {
                    "meeting_date": date,
                    "member_name": name,
                    "vote": "FOR",
                    "committee_action": action,
                    "dissent_direction": "CONCUR",
                    "policy_preference": action,
                    "stance_score": ACTION_SCORE[action],
                    "evidence_basis": "VOTE_ACTION_PROXY",
                    "source_url": statement["source_url"],
                    "raw_file": statement["raw_file"],
                    "raw_snippet": statement["raw_snippet"],
                    "annotation_note": "Concurrence proves support for the action, not ideology",
                }
            )
        for name in statement["against_names"]:
            key = (date, name)
            override = override_map.get(key)
            if not override:
                raise ValueError(f"Missing explicit dissent direction for {date} {name}")
            seen_overrides.add(key)
            rows.append(
                {
                    "meeting_date": date,
                    "member_name": name,
                    "vote": "AGAINST",
                    "committee_action": action,
                    "dissent_direction": override["dissent_direction"],
                    "policy_preference": override["policy_preference"],
                    "stance_score": int(override["stance_score"]),
                    "evidence_basis": "VOTE_DISSENT",
                    "source_url": statement["source_url"],
                    "raw_file": statement["raw_file"],
                    "raw_snippet": statement["raw_snippet"],
                    "annotation_note": override["annotation_note"],
                }
            )
    unused = set(override_map) - seen_overrides
    if unused:
        raise ValueError(f"Dissent overrides did not match official records: {sorted(unused)}")
    return sorted(rows, key=lambda row: (row["meeting_date"], row["member_name"]))


def load_speech_events(data_dir: Path) -> list[dict]:
    rows = read_csv(data_dir / "curated" / "speech_events.csv")
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (canonical_name(row["member_name"]), row["event_date"], row["source_url"])
        if key in seen:
            raise ValueError(f"Duplicate speech event: {key}")
        seen.add(key)
        row["member_name"] = key[0]
        row["stance_score"] = int(row["stance_score"])
        if row["publication_date"] < row["event_date"]:
            raise ValueError(f"Publication predates event: {key}")
        raw_path = data_dir / "raw" / "speeches" / row["raw_file"]
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing frozen speech source: {raw_path}")
        source_text = normalized_text(raw_path.read_text(encoding="utf-8", errors="replace"))
        needle = re.sub(r"\s+", " ", row["raw_snippet"]).casefold()
        if needle not in source_text.casefold():
            raise ValueError(f"Speech snippet not found in {row['raw_file']}: {row['raw_snippet']}")
        row["raw_file"] = f"raw/speeches/{row['raw_file']}"
        row["evidence_basis"] = "INDIVIDUAL_SPEECH"
    return sorted(rows, key=lambda row: (row["publication_date"], row["member_name"]))


def build_events(votes: list[dict], speeches: list[dict]) -> list[dict]:
    """Combine complete meeting statement events with optional speech enrichment."""
    events: list[dict] = []
    for vote in votes:
        events.append(
            {
                "member_name": vote["member_name"],
                "event_date": vote["meeting_date"],
                "publication_date": vote["meeting_date"],
                "source_type": "FOMC_STATEMENT_OR_MINUTES",
                "stance_label": vote["dissent_direction"] if vote["vote"] == "AGAINST" else f"COMMITTEE_{vote['committee_action']}",
                "stance_score": vote["stance_score"],
                "confidence": "HIGH" if vote["vote"] == "AGAINST" else "ACTION_PROXY",
                "evidence_basis": vote["evidence_basis"],
                "source_url": vote["source_url"],
                "raw_file": vote["raw_file"],
                "raw_snippet": vote["raw_snippet"],
                "annotation_note": vote["annotation_note"],
            }
        )
    events.extend(speeches)
    return sorted(events, key=lambda row: (row["publication_date"], row["member_name"], row["source_type"]))


def build_snapshots(data_dir: Path, votes: list[dict], speeches: list[dict]) -> list[dict]:
    sep_dates = [row["sep_date"] for row in read_csv(data_dir / "curated" / "sep_dates.csv")]
    vote_by_date: dict[str, list[dict]] = defaultdict(list)
    speech_by_member: dict[str, list[dict]] = defaultdict(list)
    for row in votes:
        vote_by_date[row["meeting_date"]].append(row)
    for row in speeches:
        speech_by_member[row["member_name"]].append(row)
    snapshots: list[dict] = []
    prior_scores: dict[str, int] = {}
    for sep_date in sep_dates:
        meeting_votes = vote_by_date.get(sep_date, [])
        if not meeting_votes:
            raise ValueError(f"SEP date has no vote record: {sep_date}")
        current_scores: dict[str, int] = {}
        for vote in meeting_votes:
            name = vote["member_name"]
            snapshot_day = date.fromisoformat(sep_date)
            # The archived pages do not expose a trustworthy publication time.
            # Conservatively exclude same-day speeches from a SEP cutoff.
            eligible_speeches = [
                row for row in speech_by_member.get(name, [])
                if row["publication_date"] < sep_date
                and (snapshot_day - date.fromisoformat(row["publication_date"])).days <= SPEECH_MAX_AGE_DAYS
            ]
            latest_speech = eligible_speeches[-1] if eligible_speeches else None
            if vote["vote"] == "AGAINST":
                chosen = {
                    "stance_label": vote["dissent_direction"],
                    "stance_score": int(vote["stance_score"]),
                    "evidence_basis": vote["evidence_basis"],
                    "evidence_date": vote["meeting_date"],
                    "source_url": vote["source_url"],
                    "raw_snippet": vote["raw_snippet"],
                }
            elif latest_speech:
                chosen = {
                    "stance_label": latest_speech["stance_label"],
                    "stance_score": int(latest_speech["stance_score"]),
                    "evidence_basis": latest_speech["evidence_basis"],
                    "evidence_date": latest_speech["publication_date"],
                    "source_url": latest_speech["source_url"],
                    "raw_snippet": latest_speech["raw_snippet"],
                }
            else:
                chosen = {
                    "stance_label": f"COMMITTEE_{vote['committee_action']}",
                    "stance_score": int(vote["stance_score"]),
                    "evidence_basis": "VOTE_ACTION_PROXY",
                    "evidence_date": vote["meeting_date"],
                    "source_url": vote["source_url"],
                    "raw_snippet": vote["raw_snippet"],
                }
            if chosen["evidence_date"] > sep_date:
                raise AssertionError(f"Look-ahead for {name} at {sep_date}: {chosen['evidence_date']}")
            score = chosen["stance_score"]
            current_scores[name] = score
            prior = prior_scores.get(name)
            snapshots.append(
                {
                    "sep_date": sep_date,
                    "member_name": name,
                    "voted": vote["vote"],
                    "committee_action": vote["committee_action"],
                    "policy_preference": vote["policy_preference"],
                    "stance_label": chosen["stance_label"],
                    "stance_score": score,
                    "change_vs_prior_sep": "" if prior is None else score - prior,
                    "evidence_basis": chosen["evidence_basis"],
                    "evidence_date": chosen["evidence_date"],
                    "source_url": chosen["source_url"],
                    "raw_snippet": chosen["raw_snippet"],
                }
            )
        prior_scores = current_scores
    return snapshots


def raw_manifest(data_dir: Path, statement_source_urls: dict[str, str], speeches: list[dict]) -> dict:
    url_by_path = {f"raw/statements/{name}": url for name, url in statement_source_urls.items()}
    for row in speeches:
        url_by_path[row["raw_file"]] = row["source_url"]
    rollcall_path = data_dir / "curated" / "rollcall_overrides.csv"
    if rollcall_path.exists():
        for row in read_csv(rollcall_path):
            url_by_path[row["raw_file"]] = row["source_url"]
    for path in (data_dir / "raw" / "index").glob("*.htm"):
        year = re.search(r"(20\d{2})", path.name)
        url_by_path[f"raw/index/{path.name}"] = (
            f"{FED_ROOT}/monetarypolicy/fomchistorical{year.group(1)}.htm"
            if year
            else f"{FED_ROOT}/monetarypolicy/fomccalendars.htm"
        )
    for path in (data_dir / "raw" / "minutes_history").glob("fomcminutes*.htm"):
        url_by_path[f"raw/minutes_history/{path.name}"] = (
            f"{FED_ROOT}/monetarypolicy/{path.stem}.htm"
        )
    files = []
    aggregate = hashlib.sha256()
    for path in sorted((data_dir / "raw").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir).as_posix()
        if relative == "raw/minutes_history/fetch_manifest.json":
            # Generated provenance sidecar; it hashes the minute files below.
            continue
        if relative.startswith("raw/speech_catalog/"):
            # The full catalog has its own URL-aware fetch manifest.
            continue
        digest = sha256(path)
        size = path.stat().st_size
        files.append({"path": relative, "bytes": size, "sha256": digest, "source_url": url_by_path.get(relative, "")})
        aggregate.update(f"{relative}\0{size}\0{digest}\n".encode())
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "root_label": "fomc_tracker_official_raw_html",
        "source": {
            "label": "Federal Reserve Board and Federal Reserve Bank official web pages",
            "url": f"{FED_ROOT}/monetarypolicy/fomccalendars.htm",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "license_terms_note": "Public official pages; verify applicable site terms before redistribution",
        },
        "hash_algorithm": "sha256",
        "file_count": len(files),
        "total_bytes": sum(row["bytes"] for row in files),
        "aggregate_sha256": aggregate.hexdigest(),
        "files": files,
    }


def git_state(project_root: Path) -> tuple[str, bool | None]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=project_root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return "NOT_A_GIT_CHECKOUT", None


def build(data_dir: Path) -> dict:
    output_dir = data_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    statements, urls, non_vote_releases, aggregate_vote_releases = load_statements(data_dir)
    members = build_member_master(statements)
    votes = build_votes(data_dir, statements)
    speeches = load_speech_events(data_dir)
    events = build_events(votes, speeches)
    snapshots = build_snapshots(data_dir, votes, speeches)
    latest_date = max(row["sep_date"] for row in snapshots)
    latest = [row for row in snapshots if row["sep_date"] == latest_date]

    member_fields = [
        "member_id", "member_name", "first_observed_vote_date", "last_observed_vote_date",
        "meetings_observed", "observed_voting_years", "first_source_url", "last_source_url", "coverage_note",
    ]
    vote_fields = [
        "meeting_date", "member_name", "vote", "committee_action", "dissent_direction",
        "policy_preference", "stance_score", "evidence_basis", "source_url", "raw_file",
        "raw_snippet", "annotation_note",
    ]
    event_fields = [
        "member_name", "event_date", "publication_date", "source_type", "stance_label",
        "stance_score", "confidence", "evidence_basis", "source_url", "raw_file", "raw_snippet", "annotation_note",
    ]
    snapshot_fields = [
        "sep_date", "member_name", "voted", "committee_action", "policy_preference", "stance_label",
        "stance_score", "change_vs_prior_sep", "evidence_basis", "evidence_date", "source_url", "raw_snippet",
    ]
    coverage_fields = ["component", "coverage_start", "coverage_end", "status", "row_count", "limitation"]
    coverage = [
        {
            "component": "named_policy_votes",
            "coverage_start": min(row["meeting_date"] for row in votes),
            "coverage_end": max(row["meeting_date"] for row in votes),
            "status": "COMPLETE_OFFICIAL_ROLLCALLS",
            "row_count": len(votes),
            "limitation": "Policy decisions without a named roll call are excluded",
        },
        {
            "component": "observed_voting_member_master",
            "coverage_start": min(row["first_observed_vote_date"] for row in members),
            "coverage_end": max(row["last_observed_vote_date"] for row in members),
            "status": "COMPLETE_FOR_OBSERVED_VOTERS",
            "row_count": len(members),
            "limitation": "Observed voting history is not an appointment-tenure roster",
        },
        {
            "component": "sep_snapshots",
            "coverage_start": min(row["sep_date"] for row in snapshots),
            "coverage_end": max(row["sep_date"] for row in snapshots),
            "status": "COMPLETE_FOR_LISTED_SEP_DATES",
            "row_count": len(snapshots),
            "limitation": "Covers the voting cohort at each SEP meeting",
        },
        {
            "component": "individual_speeches",
            "coverage_start": min(row["event_date"] for row in speeches),
            "coverage_end": max(row["event_date"] for row in speeches),
            "status": "SAMPLE_ONLY",
            "row_count": len(speeches),
            "limitation": "Not a complete census of Board and Reserve Bank speeches",
        },
    ]
    write_csv(output_dir / "members.csv", members, member_fields)
    write_csv(output_dir / "votes.csv", votes, vote_fields)
    write_csv(output_dir / "events.csv", events, event_fields)
    write_csv(output_dir / "sep_snapshots.csv", snapshots, snapshot_fields)
    write_csv(output_dir / "latest_stance.csv", latest, snapshot_fields)
    write_csv(output_dir / "coverage.csv", coverage, coverage_fields)
    write_latest_markdown(output_dir / "latest_stance.md", latest)

    manifest = raw_manifest(data_dir, urls, speeches)
    (output_dir / "sources_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    contract_path = project_root / "docs" / "FOMC_TRACKER.md"
    if not contract_path.exists():
        contract_path = project_root / "README.md"
    commit, dirty = git_state(project_root)
    output_hashes = {
        path.name: sha256(path)
        for path in sorted(output_dir.iterdir())
        if path.suffix in {".csv", ".md"}
    }
    transformation = {
        "schema_version": 1,
        "started_and_finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_input_aggregate_sha256": manifest["aggregate_sha256"],
        "contract_file": contract_path.relative_to(project_root).as_posix(),
        "contract_sha256": sha256(contract_path),
        "code_sha256": sha256(script_path),
        "git_commit": commit,
        "git_dirty": dirty,
        "command": "python3 tools/fomc_tracker.py --data-dir data/fomc_tracker",
        "parameters": {
            "history_start": HISTORY_START,
            "speech_max_age_days": SPEECH_MAX_AGE_DAYS,
        },
        "exit_status": 0,
        "row_counts": {
            "official_links_downloaded": len(urls),
            "official_statements": len(statements),
            "aggregate_vote_only_statements": len(aggregate_vote_releases),
            "non_vote_releases_excluded": len(non_vote_releases),
            "observed_members": len(members),
            "vote_rows": len(votes),
            "policy_statement_events": len(votes),
            "speech_events": len(speeches),
            "all_events": len(events),
            "sep_snapshot_rows": len(snapshots),
            "latest_stance_rows": len(latest),
        },
        "assertions": {
            "all_dissents_resolved": True,
            "all_speech_snippets_found_in_raw": True,
            "no_snapshot_lookahead": True,
            "full_statement_event_history_from_2012": True,
            "full_speech_corpus": False,
        },
        "non_vote_releases_excluded": non_vote_releases,
        "aggregate_vote_only_statements": aggregate_vote_releases,
        "output_sha256": output_hashes,
    }
    (output_dir / "transformation.json").write_text(json.dumps(transformation, indent=2) + "\n", encoding="utf-8")
    return transformation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.data_dir.resolve())
    print(json.dumps(result["row_counts"], indent=2))


if __name__ == "__main__":
    main()
