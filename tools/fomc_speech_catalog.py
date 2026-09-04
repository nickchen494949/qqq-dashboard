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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
MINNEAPOLIS_ROOT = "https://www.minneapolisfed.org"
DALLAS_ROOT = "https://www.dallasfed.org"
STLOUIS_ROOT = "https://www.stlouisfed.org"
KANSASCITY_ROOT = "https://www.kansascityfed.org"
DISTRICT_TENURE_START = {
    "Lorie K. Logan": "2022-08-22",
    "Neel Kashkari": "2016-01-01",
    "Alberto G. Musalem": "2024-04-02",
    "Jeffrey R. Schmid": "2023-08-21",
}
MINNEAPOLIS_LISTS = {
    "speeches": "{7E9951A8-3CA5-49E5-88D1-C0D7F5169713}",
    "essays": "{4714F800-1E0F-41C7-A4E0-84DC758E793A}",
}


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
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                break
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


def freeze_many(items: list[tuple[str, Path]], workers: int = 8) -> list[dict]:
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(freeze, url, path): (url, path) for url, path in items}
        for position, future in enumerate(as_completed(futures), start=1):
            url, path = futures[future]
            try:
                records.append(future.result())
            except (urllib.error.URLError, TimeoutError) as exc:
                records.append(
                    {
                        "url": url,
                        "path": path.as_posix(),
                        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                        "bytes": 0,
                        "sha256": "",
                        "last_modified": "",
                        "reused_existing": False,
                        "fetch_error": type(exc).__name__,
                        "http_status": getattr(exc, "code", ""),
                    }
                )
            if position % 50 == 0:
                print(f"  official district pages: {position}/{len(items)}", flush=True)
    return records


def safe_filename(url: str) -> str:
    path = urllib.parse.urlparse(url).path.strip("/") or "index"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", path) + ".htm"


def sitemap_entries(raw: bytes, prefix: str) -> list[tuple[str, str]]:
    root = ET.fromstring(raw)
    entries: list[tuple[str, str]] = []
    for node in root.iter():
        if not node.tag.endswith("url"):
            continue
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in node}
        url = values.get("loc", "")
        if url.startswith(prefix):
            entries.append((url, values.get("lastmod", "")))
    return entries


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def first_h1_and_date(raw: bytes) -> tuple[str, str]:
    text = raw.decode("utf-8", errors="replace")
    heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", text, re.I | re.S)
    if not heading:
        return "", "UNKNOWN"
    title = strip_tags(heading.group(1))
    after_heading = text[heading.end() :]
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b",
        strip_tags(after_heading),
    )
    return title, parse_date(match.group(0)) if match else "UNKNOWN"


def catalog_row(
    *, member: str, event_date: str, title: str, source_url: str, raw_file: str,
    institution: str, archive: str, record_type: str = "SPEECH_OR_STATEMENT",
    venue: str = "", updated_at: str = "",
) -> dict[str, str]:
    return {
        "member_name": member,
        "event_date": event_date,
        "event_date_basis": "OFFICIAL_RESERVE_BANK_ARCHIVE_DATE",
        "event_time_local": "UNKNOWN",
        "event_timezone": "UNKNOWN",
        "published_date": "UNKNOWN",
        "published_time_local": "UNKNOWN",
        "published_timezone": "UNKNOWN",
        "archive_record_updated_at_utc": updated_at,
        "title": title,
        "venue_or_subtitle": venue,
        "source_institution": institution,
        "source_archive": archive,
        "source_url": source_url,
        "secondary_source_url": "",
        "raw_metadata_file": raw_file,
        "publication_status": "ORIGINAL_PUBLICATION_DATE_TIME_NOT_EXPOSED_BY_ARCHIVE",
        "record_type": record_type,
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


def browse_items(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    marker = "var browseByData = "
    start = text.index(marker) + len(marker)
    groups, _ = json.JSONDecoder().raw_decode(text[start:])
    return [
        item
        for group in groups.values()
        if isinstance(group, dict)
        for item in group.get("items", [])
    ]


def date_from_official_url(item: dict) -> str:
    urls = item.get("metadata", {}).get("location", {}).get("url", [])
    for url in urls:
        match = re.search(r"(?<!\d)((?:19|20)\d{6})(?!\d)", url)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    return "UNKNOWN"


def fetch_oai_author(record: dict, output_dir: Path) -> tuple[list[dict], str, list[dict]]:
    title_id = str(record["id"])
    title_url = f"{FRASER_ROOT}/title/{title_id}"
    title_path = output_dir / "title_page_v3.htm"
    page_record = freeze(title_url, title_path)
    files = [page_record]
    failures: list[dict] = []
    try:
        items = browse_items(title_path.read_bytes())
    except (ValueError, KeyError, json.JSONDecodeError, AttributeError) as exc:
        return files, "TITLE_PAGE_PLUS_GET_RECORD", [
            {"url": title_url, "error": f"BROWSE_DATA_{type(exc).__name__}"}
        ]
    candidates = [
        item
        for item in items
        if date_from_official_url(item) == "UNKNOWN"
        and (not item.get("decade") or str(item["decade"]) >= "2010")
    ]
    record_dir = output_dir / "records"
    for position, item in enumerate(candidates, start=1):
        identifier = f"oai:fraser.stlouisfed.org:item:{item['id']}"
        url = oai_url({"verb": "GetRecord", "metadataPrefix": "mods", "identifier": identifier})
        failure_path = record_dir / f"item-{item['id']}.failure.json"
        if failure_path.exists():
            failures.append(json.loads(failure_path.read_text(encoding="utf-8")))
            continue
        try:
            files.append(
                freeze(url, record_dir / f"item-{item['id']}.xml", attempts=1, timeout=2)
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            failure = {
                "identifier": identifier,
                "url": url,
                "error": type(exc).__name__,
                "http_status": getattr(exc, "code", ""),
            }
            failure_path.parent.mkdir(parents=True, exist_ok=True)
            failure_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            failures.append(failure)
        if position % 20 == 0:
            print(f"  {record['title']}: {position}/{len(candidates)} candidate records", flush=True)
            time.sleep(0.2)
    return files, "TITLE_PAGE_PLUS_GET_RECORD", failures


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
    label_words = set(re.findall(r"[a-z]+", label.lower()))
    token_matches = []
    for member in members:
        first, last = person_key(member)
        if first in label_words and last in label_words:
            token_matches.append(member)
    if len(token_matches) == 1:
        return token_matches[0]
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
                    "event_date_basis": "OFFICIAL_BOARD_INDEX_DATE",
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
    return re.sub(r"\s+", " ", node.text or "").strip() if node is not None else ""


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
        title_path = directory / "title_page_v3.htm"
        allowed_ids: set[str] = set()
        if title_path.exists():
            try:
                allowed_ids = {str(item["id"]) for item in browse_items(title_path.read_bytes())}
            except (ValueError, KeyError, json.JSONDecodeError, AttributeError):
                pass
        for path in sorted(directory.rglob("*.xml")):
            try:
                root = ET.fromstring(path.read_bytes())
            except ET.ParseError:
                continue
            for oai_record in root.findall(".//oai:record", NS):
                identifier = node_text(oai_record.find("oai:header/oai:identifier", NS))
                if ":item:" not in identifier:
                    continue
                item_id = identifier.rsplit(":", 1)[-1]
                mods = oai_record.find("oai:metadata/mods:mods", NS)
                if mods is None:
                    continue
                genre = node_text(mods.find("mods:genre", NS)).lower()
                if item_id not in allowed_ids and genre != "speech":
                    continue
                if item_id not in allowed_ids and not mods_creator_matches(mods, member):
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
                        "event_date_basis": "FRASER_MODS_SORT_DATE",
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


def build_fraser_title_rows(raw_dir: Path, member_map: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for member, record in member_map.items():
        institution = contributor(record) or "Federal Reserve System"
        if "Board of Governors" in institution:
            continue
        path = raw_dir / "fraser_oai" / member_id(member) / "title_page_v3.htm"
        if not path.exists():
            continue
        try:
            items = browse_items(path.read_bytes())
        except (ValueError, KeyError, json.JSONDecodeError, AttributeError):
            continue
        for item in items:
            event_date = date_from_official_url(item)
            if event_date == "UNKNOWN" or event_date < START_DATE:
                continue
            title = item.get("name", "")
            title_part, separator, venue = title.partition(" : ")
            source_url = urllib.parse.urljoin(FRASER_ROOT, item.get("url", ""))
            document_urls = item.get("metadata", {}).get("location", {}).get("url", [])
            rows.append(
                {
                    "member_name": member,
                    "event_date": event_date,
                    "event_date_basis": "DATE_IN_OFFICIAL_ARCHIVE_DOCUMENT_URL",
                    "event_time_local": "UNKNOWN",
                    "event_timezone": "UNKNOWN",
                    "published_date": "UNKNOWN",
                    "published_time_local": "UNKNOWN",
                    "published_timezone": "UNKNOWN",
                    "archive_record_updated_at_utc": "",
                    "title": title_part if separator else title,
                    "venue_or_subtitle": venue,
                    "source_institution": institution,
                    "source_archive": "FRASER_TITLE_COLLECTION",
                    "source_url": source_url,
                    "secondary_source_url": document_urls[0] if document_urls else "",
                    "raw_metadata_file": path.relative_to(raw_dir.parent.parent).as_posix(),
                    "publication_status": "PUBLICATION_DATE_TIME_NOT_EXPOSED_IN_COLLECTION_PAGE",
                    "record_type": "SPEECH_OR_STATEMENT",
                }
            )
    return rows


def title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def deduplicate(rows: list[dict]) -> list[dict]:
    chosen: dict[tuple[str, str, str], dict] = {}
    priority = {
        "DALLAS_FED_LOGAN_ARCHIVE": 4,
        "MINNEAPOLIS_FED_PERSON_CONTENT_API": 4,
        "ST_LOUIS_FED_PRESIDENT_REMARKS_SITEMAP": 4,
        "KANSAS_CITY_FED_SITEMAP_DISCOVERY": 4,
        "FEDERAL_RESERVE_BOARD_ANNUAL_INDEX": 3,
        "FRASER_OAI_PMH": 2,
        "FRASER_TITLE_COLLECTION": 1,
    }
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


def fetch_district_sources(raw_dir: Path) -> list[dict]:
    district = raw_dir / "district_supplements"
    manifest: list[dict] = []

    dallas_url = DALLAS_ROOT + "/news/speeches/logan"
    manifest.append(freeze(dallas_url, district / "dallas" / "logan.htm"))

    minneapolis_url = MINNEAPOLIS_ROOT + "/people/neel-kashkari"
    manifest.append(freeze(minneapolis_url, district / "minneapolis" / "kashkari.htm"))
    for label, item_id in MINNEAPOLIS_LISTS.items():
        url = MINNEAPOLIS_ROOT + "/api/ArticleList?" + urllib.parse.urlencode(
            {"itemId": item_id, "skip": "0", "take": "1000"}
        )
        manifest.append(freeze(url, district / "minneapolis" / f"kashkari_{label}.json"))

    stl_sitemap_url = STLOUIS_ROOT + "/sitemap.xml"
    stl_sitemap = district / "stlouis" / "sitemap.xml"
    manifest.append(freeze(stl_sitemap_url, stl_sitemap))
    stl_entries = sitemap_entries(
        stl_sitemap.read_bytes(), STLOUIS_ROOT + "/from-the-president/remarks/"
    )
    manifest.extend(
        freeze_many(
            [(url, district / "stlouis" / "pages" / safe_filename(url)) for url, _ in stl_entries]
        )
    )

    kc_sitemap_url = KANSASCITY_ROOT + "/sitemap.xml"
    kc_sitemap = district / "kansascity" / "sitemap.xml"
    manifest.append(freeze(kc_sitemap_url, kc_sitemap))
    kc_entries = sitemap_entries(kc_sitemap.read_bytes(), KANSASCITY_ROOT + "/speeches/")
    # A speech by Schmid cannot predate his 2023-08-21 tenure. Inspect all speech
    # URLs whose sitemap last-modified date is in his tenure, plus undated entries
    # in the newest 250 sitemap positions. Every inspected page is frozen.
    kc_candidates = [
        url
        for position, (url, lastmod) in enumerate(kc_entries)
        if lastmod >= DISTRICT_TENURE_START["Jeffrey R. Schmid"]
        or (not lastmod and position >= max(0, len(kc_entries) - 250))
    ]
    kc_special = (
        KANSASCITY_ROOT
        + "/energy/energy-conference/energy-and-the-economy-reshuffling-the-energy-deck/"
    )
    kc_candidates.append(kc_special)
    manifest.extend(
        freeze_many(
            [(url, district / "kansascity" / "pages" / safe_filename(url)) for url in kc_candidates]
        )
    )
    failures = [record for record in manifest if record.get("fetch_error")]
    (district / "discovery_summary.json").write_text(
        json.dumps(
            {
                "stlouis_remark_urls_in_sitemap": len(stl_entries),
                "kansascity_speech_urls_in_sitemap": len(kc_entries),
                "kansascity_candidate_pages_checked": len(kc_candidates),
                "kansascity_rule": "lastmod >= 2023-08-21, plus undated entries in newest 250 positions",
                "fetch_failures": len(failures),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (district / "fetch_manifest.json").write_text(
        json.dumps(
            {
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "files": [
                    {
                        **record,
                        "path": Path(record["path"]).relative_to(raw_dir.parent.parent).as_posix(),
                    }
                    for record in manifest
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def build_dallas_rows(raw_dir: Path) -> list[dict]:
    path = raw_dir / "district_supplements" / "dallas" / "logan.htm"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"<p>\s*<a\s+href=\"(?P<url>/news/speeches/logan/[^\"]+)\"[^>]*>\s*"
        r"<strong>(?P<title>.*?)</strong>\s*</a>\s*<br\s*/?>"
        r"(?P<venue>.*?)<br\s*/?>\s*(?P<date>[^<]+)</p>",
        re.I | re.S,
    )
    rows = []
    for match in pattern.finditer(text):
        event_date = parse_date(strip_tags(match.group("date")))
        if event_date == "UNKNOWN" or event_date < DISTRICT_TENURE_START["Lorie K. Logan"]:
            continue
        rows.append(
            catalog_row(
                member="Lorie K. Logan",
                event_date=event_date,
                title=strip_tags(match.group("title")),
                venue=strip_tags(match.group("venue")),
                source_url=urllib.parse.urljoin(DALLAS_ROOT, match.group("url")),
                raw_file=path.relative_to(raw_dir.parent.parent).as_posix(),
                institution="Federal Reserve Bank of Dallas",
                archive="DALLAS_FED_LOGAN_ARCHIVE",
            )
        )
    return rows


def build_minneapolis_rows(raw_dir: Path) -> list[dict]:
    directory = raw_dir / "district_supplements" / "minneapolis"
    rows: list[dict] = []
    for label in MINNEAPOLIS_LISTS:
        path = directory / f"kashkari_{label}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("Articles", []):
            event_date = parse_date(item.get("dateTimeText", ""))
            if event_date == "UNKNOWN" or event_date < DISTRICT_TENURE_START["Neel Kashkari"]:
                continue
            rows.append(
                catalog_row(
                    member="Neel Kashkari",
                    event_date=event_date,
                    title=item.get("title", "").strip(),
                    source_url=urllib.parse.urljoin(MINNEAPOLIS_ROOT, item.get("url", "")),
                    raw_file=path.relative_to(raw_dir.parent.parent).as_posix(),
                    institution="Federal Reserve Bank of Minneapolis",
                    archive="MINNEAPOLIS_FED_PERSON_CONTENT_API",
                    record_type=item.get("contentTypeName", "SPEECH").upper(),
                )
            )
    return rows


def build_stlouis_rows(raw_dir: Path) -> list[dict]:
    directory = raw_dir / "district_supplements" / "stlouis"
    sitemap = directory / "sitemap.xml"
    if not sitemap.exists():
        return []
    updated = dict(sitemap_entries(sitemap.read_bytes(), STLOUIS_ROOT + "/from-the-president/remarks/"))
    rows: list[dict] = []
    for url, lastmod in updated.items():
        path = directory / "pages" / safe_filename(url)
        if not path.exists():
            continue
        title, event_date = first_h1_and_date(path.read_bytes())
        if event_date == "UNKNOWN" or event_date < DISTRICT_TENURE_START["Alberto G. Musalem"]:
            continue
        rows.append(
            catalog_row(
                member="Alberto G. Musalem",
                event_date=event_date,
                title=title,
                source_url=url,
                raw_file=path.relative_to(raw_dir.parent.parent).as_posix(),
                institution="Federal Reserve Bank of St. Louis",
                archive="ST_LOUIS_FED_PRESIDENT_REMARKS_SITEMAP",
                updated_at=lastmod,
            )
        )
    return rows


def build_kansascity_rows(raw_dir: Path) -> list[dict]:
    directory = raw_dir / "district_supplements" / "kansascity"
    sitemap = directory / "sitemap.xml"
    if not sitemap.exists():
        return []
    updated = dict(sitemap_entries(sitemap.read_bytes(), KANSASCITY_ROOT + "/speeches/"))
    rows: list[dict] = []
    for path in sorted((directory / "pages").glob("*.htm")):
        raw = path.read_bytes()
        plain = strip_tags(raw.decode("utf-8", errors="replace"))
        special_event = "energy-energy-conference-energy-and-the-economy-reshuffling-the-energy-deck" in path.name
        if not special_event and not re.search(r"\bby:\s*Jeffrey Schmid\b", plain, re.I):
            continue
        if special_event:
            title, event_date = "Opening Remarks", "2023-11-07"
        else:
            title, event_date = first_h1_and_date(raw)
        if event_date == "UNKNOWN" or event_date < DISTRICT_TENURE_START["Jeffrey R. Schmid"]:
            continue
        canonical = re.search(
            r'<link\s+rel="canonical"\s+href="([^"]+)"',
            raw.decode("utf-8", errors="replace"),
            re.I,
        )
        url = canonical.group(1) if canonical else ""
        if special_event:
            url = (
                KANSASCITY_ROOT
                + "/energy/energy-conference/energy-and-the-economy-reshuffling-the-energy-deck/"
            )
        rows.append(
            catalog_row(
                member="Jeffrey R. Schmid",
                event_date=event_date,
                title=title,
                source_url=url,
                raw_file=path.relative_to(raw_dir.parent.parent).as_posix(),
                institution="Federal Reserve Bank of Kansas City",
                archive="KANSAS_CITY_FED_SITEMAP_DISCOVERY",
                updated_at=updated.get(url, ""),
            )
        )
    return rows


def build_district_rows(raw_dir: Path) -> list[dict]:
    return (
        build_dallas_rows(raw_dir)
        + build_minneapolis_rows(raw_dir)
        + build_stlouis_rows(raw_dir)
        + build_kansascity_rows(raw_dir)
    )


def fetch(data_dir: Path) -> None:
    raw_dir = data_dir / "raw" / "speech_catalog"
    progress_path = raw_dir / "live_progress.json"
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
    completed_members: list[str] = []
    progress_path.write_text(
        json.dumps(
            {
                "status": "RUNNING",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "completed_members": 0,
                "total_matched_members": len(matched),
                "current_member": "",
                "unmatched_members": unmatched,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for position, (member, record) in enumerate(sorted(matched.items()), start=1):
        progress_path.write_text(
            json.dumps(
                {
                    "status": "RUNNING",
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "completed_members": len(completed_members),
                    "total_matched_members": len(matched),
                    "current_member": member,
                    "unmatched_members": unmatched,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if "Board of Governors" in contributor(record):
            files, method, failures = [], "BOARD_ANNUAL_INDEX_PRIMARY", []
        else:
            files, method, failures = fetch_oai_author(
                record, raw_dir / "fraser_oai" / member_id(member)
            )
        manifest.extend(files)
        methods[member] = method
        if failures:
            oai_failures[member] = failures
        completed_members.append(member)
        progress_path.write_text(
            json.dumps(
                {
                    "status": "RUNNING",
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "completed_members": len(completed_members),
                    "total_matched_members": len(matched),
                    "current_member": "",
                    "last_completed_member": member,
                    "last_member_response_files": len(files),
                    "last_member_failures": len(failures),
                    "unmatched_members": unmatched,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"FRASER {position}/{len(matched)} {member}: {len(files)} response file(s), "
            f"{len(failures)} failure(s)",
            flush=True,
        )
    print("Fetching four official Reserve Bank supplements", flush=True)
    manifest.extend(fetch_district_sources(raw_dir))
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
    progress_path.write_text(
        json.dumps(
            {
                "status": "FETCH_COMPLETE",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "completed_members": len(completed_members),
                "total_matched_members": len(matched),
                "unmatched_members": unmatched,
                "members_with_oai_failures": sorted(oai_failures),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build(data_dir: Path) -> dict:
    raw_dir = data_dir / "raw" / "speech_catalog"
    members = [row["member_name"] for row in read_csv(data_dir / "output" / "members.csv")]
    records = json.loads((raw_dir / "fraser_fomc_participants.json").read_text(encoding="utf-8"))["records"]
    matched, unmatched = match_participants(members, records)
    rows = deduplicate(
        build_board_rows(raw_dir, members)
        + build_fraser_rows(raw_dir, matched)
        + build_fraser_title_rows(raw_dir, matched)
        + build_district_rows(raw_dir)
    )
    fields = [
        "event_id", "member_name", "event_date", "event_date_basis", "event_time_local", "event_timezone",
        "published_date", "published_time_local", "published_timezone",
        "archive_record_updated_at_utc", "title", "venue_or_subtitle", "record_type",
        "source_institution", "source_archive", "source_url", "secondary_source_url",
        "raw_metadata_file", "publication_status",
    ]
    output = data_dir / "output" / "speech_catalog.csv"
    write_csv(output, rows, fields)
    covered_members = {row["member_name"] for row in rows}
    source_counts = {
        source: sum(row["source_archive"] == source for row in rows)
        for source in sorted({row["source_archive"] for row in rows})
    }
    coverage_rows = []
    for member in sorted(members):
        member_rows = [row for row in rows if row["member_name"] == member]
        coverage_rows.append(
            {
                "member_name": member,
                "row_count": len(member_rows),
                "event_date_min": min((row["event_date"] for row in member_rows), default=""),
                "event_date_max": max((row["event_date"] for row in member_rows), default=""),
                "status": "HAS_OFFICIAL_EVENTS" if member_rows else "MISSING_OFFICIAL_EVENTS",
                "source_archives": ";".join(sorted({row["source_archive"] for row in member_rows})),
            }
        )
    write_csv(
        data_dir / "output" / "speech_catalog_coverage.csv",
        coverage_rows,
        ["member_name", "row_count", "event_date_min", "event_date_max", "status", "source_archives"],
    )
    summary = {
        "schema_version": 1,
        "history_start": START_DATE,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "member_count": len(covered_members),
        "event_date_min": min(row["event_date"] for row in rows),
        "event_date_max": max(row["event_date"] for row in rows),
        "board_rows": sum(row["source_archive"] == "FEDERAL_RESERVE_BOARD_ANNUAL_INDEX" for row in rows),
        "fraser_rows": sum(row["source_archive"] == "FRASER_OAI_PMH" for row in rows),
        "fraser_title_collection_rows": sum(
            row["source_archive"] == "FRASER_TITLE_COLLECTION" for row in rows
        ),
        "district_supplement_rows": sum("FED_" in row["source_archive"] and row["source_archive"] not in {"FEDERAL_RESERVE_BOARD_ANNUAL_INDEX", "FRASER_OAI_PMH"} for row in rows),
        "source_counts": source_counts,
        "unmatched_fraser_members": unmatched,
        "missing_catalog_members": sorted(set(members) - covered_members),
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
    parser.add_argument("command", choices=("fetch", "fetch-district", "build"))
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.data_dir.resolve())
    elif args.command == "fetch-district":
        fetch_district_sources(args.data_dir.resolve() / "raw" / "speech_catalog")
    else:
        build(args.data_dir.resolve())


if __name__ == "__main__":
    main()
