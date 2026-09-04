#!/usr/bin/env python3
"""Fetch and build a 2012-present FOMC speech metadata catalog from official sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


START_DATE = "2012-01-01"
CURRENT_YEAR = 2026
BOARD_ROOT = "https://www.federalreserve.gov"
FRASER_ROOT = "https://fraser.stlouisfed.org"
FRASER_SERIES_URL = (
    FRASER_ROOT
    + "/series/statements-speeches-federal-open-market-committee-participants-3761?listRecords=true"
)
OAI_URL = FRASER_ROOT + "/oai/"
NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "mods": "http://www.loc.gov/mods/v3"}
USER_AGENT = "fomc-audit-catalog/1.0 (official metadata research)"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def member_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def person_key(name: str) -> tuple[str, str]:
    words = re.findall(r"[a-z]+", name.lower().replace(",", " "))
    words = [word for word in words if word not in {"statements", "speeches", "and", "of"}]
    if not words:
        return "", ""
    if "," in name:
        return words[1] if len(words) > 1 else "", words[0]
    return words[0], words[-1]


def fetch_bytes(url: str, attempts: int = 3, timeout: int = 60) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers.items())
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)
    assert error
    raise error


def freeze(url: str, path: Path, attempts: int = 3, timeout: int = 60) -> dict:
    if path.exists():
        raw = path.read_bytes()
        return {
            "url": url,
            "path": path.as_posix(),
            "retrieved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "last_modified": "",
            "reused_existing": True,
        }
    raw, headers = fetch_bytes(url, attempts=attempts, timeout=timeout)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "url": url,
        "path": path.as_posix(),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "last_modified": headers.get("Last-Modified", ""),
        "reused_existing": False,
    }


def oai_url(params: dict[str, str]) -> str:
    return OAI_URL + "?" + urllib.parse.urlencode(params)


def xml_token(raw: bytes) -> str:
    root = ET.fromstring(raw)
    node = root.find(".//oai:resumptionToken", NS)
    return (node.text or "").strip() if node is not None else ""


def xml_identifiers(raw: bytes) -> list[str]:
    root = ET.fromstring(raw)
    return [
        node.text.strip()
        for header in root.findall(".//oai:header", NS)
        for node in [header.find("oai:identifier", NS)]
        if header.get("status") != "deleted" and node is not None and node.text and ":item:" in node.text
    ]


def fetch_oai_pages(params: dict[str, str], output_dir: Path, prefix: str) -> list[dict]:
    pages: list[dict] = []
    page = 1
    current = params
    while True:
        url = oai_url(current)
        path = output_dir / f"{prefix}-{page:04d}.xml"
        record = freeze(url, path)
        pages.append(record)
        token = xml_token(path.read_bytes())
        if not token:
            break
        current = {"verb": params["verb"], "resumptionToken": token}
        page += 1
        time.sleep(0.15)
    return pages


def fetch_oai_author(author_id: str, output_dir: Path) -> tuple[list[dict], str, list[dict]]:
    params = {"verb": "ListRecords", "metadataPrefix": "mods", "set": f"author:{author_id}"}
    try:
        return fetch_oai_pages(params, output_dir, "records"), "LIST_RECORDS", []
    except urllib.error.HTTPError as exc:
        if exc.code != 500:
            raise
    identifier_pages = fetch_oai_pages(
        {"verb": "ListIdentifiers", "metadataPrefix": "mods", "set": f"author:{author_id}"},
        output_dir,
        "identifiers",
    )
    identifiers: list[str] = []
    for page in identifier_pages:
        identifiers.extend(xml_identifiers(Path(page["path"]).read_bytes()))
    records = list(identifier_pages)
    failures: list[dict] = []
    record_dir = output_dir / "records"
    for position, identifier in enumerate(sorted(set(identifiers)), start=1):
        item_id = identifier.rsplit(":", 1)[-1]
        url = oai_url({"verb": "GetRecord", "metadataPrefix": "mods", "identifier": identifier})
        try:
            records.append(
                freeze(url, record_dir / f"item-{item_id}.xml", attempts=1, timeout=15)
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            failures.append(
                {
                    "identifier": identifier,
                    "url": url,
                    "error": type(exc).__name__,
                    "http_status": getattr(exc, "code", ""),
                }
            )
        if position % 20 == 0:
            time.sleep(0.25)
    return records, "IDENTIFIERS_GET_RECORD", failures


def creator_info(record: dict) -> tuple[str, str]:
    for name in record.get("metadata", {}).get("name", []):
        if name.get("role") != "creator":
            continue
        parts = name.get("namePart", [])
        creator = " ".join(value for value in parts if isinstance(value, str)).strip()
        ids = name.get("recordInfo", {}).get("recordIdentifier", [])
        return creator, str(ids[0]) if ids else ""
    return "", ""


def contributor(record: dict) -> str:
    for name in record.get("metadata", {}).get("name", []):
        if name.get("role") != "contributor":
            continue
        parts = name.get("namePart", [])
        return " ".join(value for value in parts if isinstance(value, str)).strip()
    return ""


def match_participants(members: list[str], records: list[dict]) -> tuple[dict[str, dict], list[str]]:
    matched: dict[str, dict] = {}
    for member in members:
        first, last = person_key(member)
        candidates = []
        for record in records:
            creator, author_id = creator_info(record)
            c_first, c_last = person_key(creator)
            if first and last and first == c_first and last == c_last and author_id:
                candidates.append(record)
        if len(candidates) == 1:
            matched[member] = candidates[0]
    return matched, sorted(set(members) - set(matched))


class BoardIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self.row: dict[str, str] | None = None
        self.eventlist_depth = 0
        self.capture = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "div" and "eventlist" in classes and self.eventlist_depth == 0:
            self.eventlist_depth = 1
            return
        if self.eventlist_depth and tag == "div":
            self.eventlist_depth += 1
        if not self.eventlist_depth:
            return
        if tag == "time":
            if self.row and self.row.get("url"):
                self.rows.append(self.row)
            self.row = {}
            self.capture, self.parts = "date", []
        elif self.row is not None and tag == "a" and re.search(r"/newsevents/speech/[a-z]+20\d{6}[a-z]?\.htm$", values.get("href") or ""):
            self.row["url"] = urllib.parse.urljoin(BOARD_ROOT, values["href"] or "")
            self.capture, self.parts = "title", []
        elif self.row is not None and tag == "p" and "news__speaker" in classes:
            self.capture, self.parts = "speaker", []

    def handle_endtag(self, tag: str) -> None:
        if self.row is not None and self.capture and tag in {"time", "a", "p"}:
            self.row[self.capture] = re.sub(r"\s+", " ", html.unescape("".join(self.parts))).strip()
            self.capture, self.parts = "", []
        if self.eventlist_depth and tag == "div":
            self.eventlist_depth -= 1
            if self.eventlist_depth == 0:
                if self.row and self.row.get("url"):
                    self.rows.append(self.row)
                self.row = None

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)


def canonical_board_speaker(label: str, members: list[str]) -> str:
    cleaned = re.sub(r"^(Chairman|Chair|Vice Chair|Vice Chairman|Governor)\s+", "", label).strip()
    first, last = person_key(cleaned)
    candidates = [member for member in members if person_key(member) == (first, last)]
    return candidates[0] if len(candidates) == 1 else cleaned


def parse_date(value: str) -> str:
    for pattern in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    return "UNKNOWN"


def build_board_rows(raw_dir: Path, members: list[str]) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((raw_dir / "board_indexes").glob("*.htm")):
        parser = BoardIndexParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        for item in parser.rows:
            event_date = parse_date(item.get("date", ""))
            if event_date < START_DATE:
                continue
            member = canonical_board_speaker(item.get("speaker", ""), members)
            rows.append(
                {
                    "member_name": member,
                    "event_date": event_date,
                    "event_time_local": "UNKNOWN",
                    "event_timezone": "UNKNOWN",
                    "published_date": "UNKNOWN",
                    "published_time_local": "UNKNOWN",
                    "published_timezone": "UNKNOWN",
                    "archive_record_updated_at_utc": "",
                    "title": item.get("title", ""),
                    "venue_or_subtitle": "",
                    "source_institution": "Board of Governors of the Federal Reserve System",
                    "source_archive": "FEDERAL_RESERVE_BOARD_ANNUAL_INDEX",
                    "source_url": item["url"],
                    "secondary_source_url": "",
                    "raw_metadata_file": path.relative_to(raw_dir.parent.parent).as_posix(),
                    "publication_status": "PUBLICATION_DATE_TIME_NOT_EXPOSED_IN_ANNUAL_INDEX",
                    "record_type": "SPEECH",
                }
            )
    return rows


def node_text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def mods_creator_matches(mods: ET.Element, member: str) -> bool:
    target = person_key(member)
    for name in mods.findall("mods:name", NS):
        roles = [node_text(node).lower() for node in name.findall("mods:role/mods:roleTerm", NS)]
        if "creator" not in roles:
            continue
        parts = [node_text(node) for node in name.findall("mods:namePart", NS)]
        if person_key(" ".join(part for part in parts if part)) == target:
            return True
    return False


def build_fraser_rows(raw_dir: Path, member_map: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for member, record in member_map.items():
        institution = contributor(record) or "Federal Reserve System"
        directory = raw_dir / "fraser_oai" / member_id(member)
        for path in sorted(directory.rglob("*.xml")):
            try:
                root = ET.fromstring(path.read_bytes())
            except ET.ParseError:
                continue
            for oai_record in root.findall(".//oai:record", NS):
                identifier = node_text(oai_record.find("oai:header/oai:identifier", NS))
                if ":item:" not in identifier:
                    continue
                mods = oai_record.find("oai:metadata/mods:mods", NS)
                if mods is None or node_text(mods.find("mods:genre", NS)).lower() != "speech":
                    continue
                if not mods_creator_matches(mods, member):
                    continue
                event_date = node_text(mods.find("mods:originInfo/mods:sortDate", NS))
                if not event_date or event_date < START_DATE:
                    continue
                title = node_text(mods.find("mods:titleInfo/mods:title", NS))
                subtitle = node_text(mods.find("mods:titleInfo/mods:subTitle", NS))
                urls = [node_text(node) for node in mods.findall("mods:location/mods:url", NS)]
                urls = [url for url in urls if url]
                rows.append(
                    {
                        "member_name": member,
                        "event_date": event_date,
                        "event_time_local": "UNKNOWN",
                        "event_timezone": "UNKNOWN",
                        "published_date": "UNKNOWN",
                        "published_time_local": "UNKNOWN",
                        "published_timezone": "UNKNOWN",
                        "archive_record_updated_at_utc": node_text(oai_record.find("oai:header/oai:datestamp", NS)),
                        "title": title,
                        "venue_or_subtitle": subtitle,
                        "source_institution": institution,
                        "source_archive": "FRASER_OAI_PMH",
                        "source_url": urls[0] if urls else "",
                        "secondary_source_url": urls[1] if len(urls) > 1 else "",
                        "raw_metadata_file": path.relative_to(raw_dir.parent.parent).as_posix(),
                        "publication_status": "ORIGINAL_PUBLICATION_DATE_TIME_NOT_IN_FRASER_METADATA",
                        "record_type": "SPEECH",
                    }
                )
    return rows


def title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def deduplicate(rows: list[dict]) -> list[dict]:
    chosen: dict[tuple[str, str, str], dict] = {}
    priority = {"FEDERAL_RESERVE_BOARD_ANNUAL_INDEX": 2, "FRASER_OAI_PMH": 1}
    for row in rows:
        key = (row["member_name"], row["event_date"], title_key(row["title"]))
        current = chosen.get(key)
        if current is None or priority.get(row["source_archive"], 0) > priority.get(current["source_archive"], 0):
            if current and not row["secondary_source_url"]:
                row["secondary_source_url"] = current["source_url"]
            chosen[key] = row
        elif not current["secondary_source_url"]:
            current["secondary_source_url"] = row["source_url"]
    result = sorted(chosen.values(), key=lambda row: (row["event_date"], row["member_name"], row["title"]))
    for row in result:
        raw = "\0".join((row["member_name"], row["event_date"], row["title"], row["source_url"]))
        row["event_id"] = hashlib.sha256(raw.encode()).hexdigest()[:20]
    return result


def fetch(data_dir: Path) -> None:
    raw_dir = data_dir / "raw" / "speech_catalog"
    manifest: list[dict] = []
    for year in range(2012, CURRENT_YEAR + 1):
        url = f"{BOARD_ROOT}/newsevents/speech/{year}-speeches.htm"
        manifest.append(freeze(url, raw_dir / "board_indexes" / f"{year}-speeches.htm"))
    participants_path = raw_dir / "fraser_fomc_participants.json"
    manifest.append(freeze(FRASER_SERIES_URL, participants_path))
    members = [row["member_name"] for row in read_csv(data_dir / "output" / "members.csv")]
    records = json.loads(participants_path.read_text(encoding="utf-8"))["records"]
    matched, unmatched = match_participants(members, records)
    methods: dict[str, str] = {}
    oai_failures: dict[str, list[dict]] = {}
    for position, (member, record) in enumerate(sorted(matched.items()), start=1):
        _, author_id = creator_info(record)
        files, method, failures = fetch_oai_author(
            author_id, raw_dir / "fraser_oai" / member_id(member)
        )
        manifest.extend(files)
        methods[member] = method
        if failures:
            oai_failures[member] = failures
        print(
            f"FRASER {position}/{len(matched)} {member}: {len(files)} response file(s), "
            f"{len(failures)} failure(s)",
            flush=True,
        )
    metadata = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "matched_members": sorted(matched),
        "unmatched_members": unmatched,
        "oai_methods": methods,
        "oai_failures": oai_failures,
        "files": [
            {
                **record,
                "path": Path(record["path"]).relative_to(data_dir).as_posix(),
            }
            for record in manifest
        ],
    }
    (raw_dir / "fetch_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def build(data_dir: Path) -> dict:
    raw_dir = data_dir / "raw" / "speech_catalog"
    members = [row["member_name"] for row in read_csv(data_dir / "output" / "members.csv")]
    records = json.loads((raw_dir / "fraser_fomc_participants.json").read_text(encoding="utf-8"))["records"]
    matched, unmatched = match_participants(members, records)
    rows = deduplicate(build_board_rows(raw_dir, members) + build_fraser_rows(raw_dir, matched))
    fields = [
        "event_id", "member_name", "event_date", "event_time_local", "event_timezone",
        "published_date", "published_time_local", "published_timezone",
        "archive_record_updated_at_utc", "title", "venue_or_subtitle", "record_type",
        "source_institution", "source_archive", "source_url", "secondary_source_url",
        "raw_metadata_file", "publication_status",
    ]
    output = data_dir / "output" / "speech_catalog.csv"
    write_csv(output, rows, fields)
    summary = {
        "schema_version": 1,
        "history_start": START_DATE,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "member_count": len({row["member_name"] for row in rows}),
        "event_date_min": min(row["event_date"] for row in rows),
        "event_date_max": max(row["event_date"] for row in rows),
        "board_rows": sum(row["source_archive"] == "FEDERAL_RESERVE_BOARD_ANNUAL_INDEX" for row in rows),
        "fraser_rows": sum(row["source_archive"] == "FRASER_OAI_PMH" for row in rows),
        "unmatched_fraser_members": unmatched,
        "publication_datetime_known_rows": sum(row["published_date"] != "UNKNOWN" for row in rows),
        "output_sha256": sha256_bytes(output.read_bytes()),
    }
    (data_dir / "output" / "speech_catalog_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.data_dir.resolve())
    else:
        build(args.data_dir.resolve())


if __name__ == "__main__":
    main()
