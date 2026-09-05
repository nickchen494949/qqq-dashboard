#!/usr/bin/env python3
"""Build the spec-v1 Federal Reserve public-communications evidence tables.

The collector deliberately uses only official Federal Reserve institutional
sites and FRASER.  Discovery pages and every accepted item are frozen before
normalization.  A successful crawl is reported as measured coverage, never as
proof that no other historical communication exists.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


START_DATE = "2012-01-01"
END_DATE = "2026-09-05"
USER_AGENT = "fomc-public-communications-audit/1.0"
SPEC_VERSION = "1.0.0"
REGISTRY_VERSION = "1.0.0"

INSTITUTION_SOURCE_IDS = {
    "Board of Governors of the Federal Reserve System": "board_speeches_testimony",
    "Federal Reserve Bank of Boston": "boston_public_communications",
    "Federal Reserve Bank of New York": "new_york_public_communications",
    "Federal Reserve Bank of Philadelphia": "philadelphia_public_communications",
    "Federal Reserve Bank of Cleveland": "cleveland_public_communications",
    "Federal Reserve Bank of Richmond": "richmond_public_communications",
    "Federal Reserve Bank of Atlanta": "atlanta_public_communications",
    "Federal Reserve Bank of Chicago": "chicago_public_communications",
    "Federal Reserve Bank of St. Louis": "st_louis_public_communications",
    "Federal Reserve Bank of Minneapolis": "minneapolis_public_communications",
    "Federal Reserve Bank of Kansas City": "kansas_city_public_communications",
    "Federal Reserve Bank of Dallas": "dallas_public_communications",
    "Federal Reserve Bank of San Francisco": "san_francisco_public_communications",
    "Federal Reserve Archival System for Economic Research": "fraser_fomc_participant_archive",
}

# Exact same-year leadership transitions are needed for author disambiguation.
# These dates are role filters only; the auditable universe remains derived from
# official FOMC attendance and vote records.
OFFICE_INTERVALS = {
    ("Federal Reserve Bank of Boston", "Eric S. Rosengren"): ("2007-07-23", "2021-09-30"),
    ("Federal Reserve Bank of Boston", "Kenneth C. Montgomery"): ("2021-10-01", "2022-06-30"),
    ("Federal Reserve Bank of Boston", "Susan M. Collins"): ("2022-07-01", "9999-12-31"),
    ("Federal Reserve Bank of New York", "William C. Dudley"): ("2009-01-27", "2018-06-17"),
    ("Federal Reserve Bank of New York", "John C. Williams"): ("2018-06-18", "9999-12-31"),
    ("Federal Reserve Bank of Philadelphia", "Charles I. Plosser"): ("2006-08-01", "2015-03-01"),
    ("Federal Reserve Bank of Philadelphia", "Patrick Harker"): ("2015-07-01", "2025-06-30"),
    ("Federal Reserve Bank of Philadelphia", "Anna Paulson"): ("2025-07-01", "9999-12-31"),
    ("Federal Reserve Bank of Cleveland", "Sandra Pianalto"): ("2003-02-01", "2014-05-31"),
    ("Federal Reserve Bank of Cleveland", "Loretta J. Mester"): ("2014-06-01", "2024-06-30"),
    ("Federal Reserve Bank of Cleveland", "Beth M. Hammack"): ("2024-08-21", "9999-12-31"),
    ("Federal Reserve Bank of Richmond", "Jeffrey M. Lacker"): ("2004-08-01", "2017-04-04"),
    ("Federal Reserve Bank of Richmond", "Mark L. Mullinix"): ("2017-04-05", "2017-12-31"),
    ("Federal Reserve Bank of Richmond", "Thomas I. Barkin"): ("2018-01-01", "9999-12-31"),
    ("Federal Reserve Bank of Atlanta", "Dennis P. Lockhart"): ("2007-03-01", "2017-02-28"),
    ("Federal Reserve Bank of Atlanta", "Raphael W. Bostic"): ("2017-06-05", "2026-02-28"),
    ("Federal Reserve Bank of Atlanta", "Cheryl L. Venable"): ("2026-03-01", "9999-12-31"),
    ("Federal Reserve Bank of Chicago", "Charles L. Evans"): ("2007-09-01", "2023-01-08"),
    ("Federal Reserve Bank of Chicago", "Austan D. Goolsbee"): ("2023-01-09", "9999-12-31"),
    ("Federal Reserve Bank of St. Louis", "James Bullard"): ("2008-04-01", "2023-07-13"),
    ("Federal Reserve Bank of St. Louis", "Kathleen O'Neill Paese"): ("2023-07-13", "2024-04-01"),
    ("Federal Reserve Bank of St. Louis", "Alberto G. Musalem"): ("2024-04-02", "9999-12-31"),
    ("Federal Reserve Bank of Minneapolis", "Narayana Kocherlakota"): ("2009-10-08", "2015-12-31"),
    ("Federal Reserve Bank of Minneapolis", "Neel Kashkari"): ("2016-01-01", "9999-12-31"),
    ("Federal Reserve Bank of Kansas City", "Esther L. George"): ("2011-10-01", "2023-01-31"),
    ("Federal Reserve Bank of Kansas City", "Kelly J. Dubbert"): ("2023-02-01", "2023-08-20"),
    ("Federal Reserve Bank of Kansas City", "Jeffrey R. Schmid"): ("2023-08-21", "9999-12-31"),
    ("Federal Reserve Bank of Dallas", "Richard W. Fisher"): ("2005-04-04", "2015-03-19"),
    ("Federal Reserve Bank of Dallas", "Robert S. Kaplan"): ("2015-09-08", "2021-10-08"),
    ("Federal Reserve Bank of Dallas", "Meredith Black"): ("2021-10-09", "2022-08-21"),
    ("Federal Reserve Bank of Dallas", "Lorie K. Logan"): ("2022-08-22", "9999-12-31"),
    ("Federal Reserve Bank of San Francisco", "John C. Williams"): ("2011-03-01", "2018-06-17"),
    ("Federal Reserve Bank of San Francisco", "Mary C. Daly"): ("2018-10-01", "9999-12-31"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def clean_url(url: str) -> str:
    parts = urllib.parse.urlsplit(html.unescape(url.strip()))
    path = urllib.parse.quote(urllib.parse.unquote(parts.path.rstrip("/") or "/"), safe="/%:@")
    query = urllib.parse.quote(urllib.parse.unquote(parts.query), safe="=&%:@,+")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def fetch_bytes(url: str, attempts: int = 3, timeout: int = 45) -> tuple[bytes, dict[str, str], int]:
    error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers.items()), response.status
        except (urllib.error.URLError, TimeoutError, ValueError, http.client.InvalidURL) as exc:
            # Several Reserve Bank CMSs publish sitemap URLs without the trailing
            # slash that their origin server nevertheless requires.
            if (
                isinstance(exc, urllib.error.HTTPError) and exc.code == 404
                and not urllib.parse.urlsplit(url).path.endswith("/")
                and "." not in urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
            ):
                try:
                    request = urllib.request.Request(url + "/", headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        return response.read(), dict(response.headers.items()), response.status
                except (urllib.error.URLError, TimeoutError, ValueError, http.client.InvalidURL):
                    pass
            error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404, 410}:
                break
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    assert error is not None
    raise error


def frozen_path(root: Path, source_id: str, kind: str, url: str, content_type: str = "") -> Path:
    suffix = ".pdf" if "pdf" in content_type.lower() or urllib.parse.urlsplit(url).path.lower().endswith(".pdf") else ".raw"
    return root / source_id / kind / (sha256_bytes(clean_url(url).encode())[:24] + suffix)


def freeze(root: Path, source_id: str, kind: str, url: str, attempts: int = 3, timeout: int = 45) -> dict:
    url = clean_url(url)
    path = frozen_path(root, source_id, kind, url)
    sidecar = path.with_suffix(path.suffix + ".json")
    if path.exists() and sidecar.exists():
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        record["reused_existing"] = True
        return record
    checked = utc_now()
    try:
        raw, headers, status = fetch_bytes(url, attempts=attempts, timeout=timeout)
        content_type = headers.get("Content-Type", "")
        final_path = frozen_path(root, source_id, kind, url, content_type)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(raw)
        record = {
            "source_id": source_id,
            "kind": kind,
            "url": url,
            "path": final_path.as_posix(),
            "http_status": status,
            "retrieved_at": checked,
            "last_modified": headers.get("Last-Modified", ""),
            "content_type": content_type,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "status": "VERIFIED_PRESENT",
            "error": "",
            "reused_existing": False,
        }
        final_sidecar = final_path.with_suffix(final_path.suffix + ".json")
        final_sidecar.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record
    except (urllib.error.URLError, TimeoutError, ValueError, http.client.InvalidURL) as exc:
        code = getattr(exc, "code", "")
        record = {
            "source_id": source_id, "kind": kind, "url": url, "path": path.as_posix(),
            "http_status": code, "retrieved_at": checked, "last_modified": "",
            "content_type": "", "bytes": 0, "sha256": "", "status": "KNOWN_GAP",
            "error": f"{type(exc).__name__}:{getattr(exc, 'reason', exc)}", "reused_existing": False,
        }
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            values = dict(attrs)
            if values.get("href"):
                self.current = {"href": values["href"] or ""}
                self.parts = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current is not None:
            self.current["text"] = re.sub(r"\s+", " ", " ".join(self.parts)).strip()
            self.links.append(self.current)
            self.current = None
            self.parts = []


def links_from(raw: bytes, base_url: str) -> list[tuple[str, str]]:
    parser = LinkParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return [(clean_url(urllib.parse.urljoin(base_url, row["href"])), row["text"]) for row in parser.links]


def sitemap_urls(raw: bytes) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [], []
    locs = [(node.text or "").strip() for node in root.iter() if node.tag.endswith("loc") and node.text]
    if root.tag.endswith("sitemapindex"):
        return [], locs
    return locs, []


def matches_prefix(url: str, prefixes: list[str]) -> bool:
    def comparable(value: str) -> str:
        parts = urllib.parse.urlsplit(clean_url(value))
        host = parts.netloc.lower().removeprefix("www.")
        return host + parts.path.lower().rstrip("/")
    target = comparable(url)
    return any(target.startswith(comparable(prefix)) for prefix in prefixes)


def likely_dated_item(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    if re.search(r"/(?:20)?1[2-9](?:/|[-_])|/20(?:2[0-6]|1[2-9])(?:/|[-_])", path):
        return True
    if re.search(r"(?:^|[-_/])(?:12|13|14|15|16|17|18|19|20|21|22|23|24|25|26)\d{4}(?:$|[-_/.])", path):
        return True
    if path.endswith(".pdf"):
        return True
    return False


def enumerate_candidates(source: dict, entry_records: list[dict], nested_records: list[dict]) -> list[dict]:
    prefixes = source["candidate_prefixes"]
    candidates: dict[str, dict] = {}
    for record in entry_records + nested_records:
        if record["status"] != "VERIFIED_PRESENT" or record.get("content_type", "").lower().startswith("application/pdf"):
            continue
        raw = Path(record["path"]).read_bytes()
        urls, _ = sitemap_urls(raw)
        for url in urls:
            url = clean_url(url)
            if matches_prefix(url, prefixes) and likely_dated_item(url):
                candidates[url] = {"url": url, "anchor_text": "", "discovered_via": record["url"]}
        for url, text in links_from(raw, record["url"]):
            if matches_prefix(url, prefixes) and url != clean_url(record["url"]):
                if likely_dated_item(url) or source["source_id"] in {"new_york_public_communications", "dallas_public_communications", "chicago_public_communications"}:
                    candidates[url] = {"url": url, "anchor_text": text, "discovered_via": record["url"]}
    return sorted(candidates.values(), key=lambda row: row["url"])


def fetch(data_dir: Path, workers: int = 12) -> dict:
    registry_path = data_dir / "spec" / "source_registry_v1.0.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    raw_root = data_dir / "raw" / "public_communications"
    entry_records: dict[str, list[dict]] = defaultdict(list)
    nested_records: dict[str, list[dict]] = defaultdict(list)
    for source in registry["sources"]:
        if source["source_id"] in {"board_speeches_testimony", "fraser_fomc_participant_archive"}:
            continue
        for url in source["entry_urls"]:
            entry_records[source["source_id"]].append(freeze(raw_root, source["source_id"], "entry", url))
    # Expand official sitemap indexes once; leaf sitemap files are the traversal units.
    nested_jobs: list[tuple[dict, str]] = []
    for source in registry["sources"]:
        for record in entry_records[source["source_id"]]:
            if record["status"] != "VERIFIED_PRESENT":
                continue
            _, nested = sitemap_urls(Path(record["path"]).read_bytes())
            for url in nested:
                if source["domain"] in urllib.parse.urlsplit(url).netloc:
                    nested_jobs.append((source, url))
    for source, url in nested_jobs:
        nested_records[source["source_id"]].append(freeze(raw_root, source["source_id"], "sitemap", url))

    candidate_rows: list[dict] = []
    for source in registry["sources"]:
        if source["source_id"] in {"board_speeches_testimony", "fraser_fomc_participant_archive"}:
            continue
        rows = enumerate_candidates(source, entry_records[source["source_id"]], nested_records[source["source_id"]])
        for row in rows:
            row["source_id"] = source["source_id"]
        candidate_rows.extend(rows)
        print(f"{source['source_id']}: {len(rows)} candidate official item(s)", flush=True)

    item_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(freeze, raw_root, row["source_id"], "item", row["url"]): row
            for row in candidate_rows
        }
        for position, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            record.update({key: value for key, value in futures[future].items() if key != "url"})
            item_records.append(record)
            if position % 100 == 0:
                print(f"official item fetch {position}/{len(futures)}", flush=True)

    all_records = [r for rows in entry_records.values() for r in rows] + [r for rows in nested_records.values() for r in rows] + item_records
    for record in all_records:
        if record.get("path"):
            record["path"] = Path(record["path"]).relative_to(data_dir).as_posix()
    manifest = {
        "schema_version": 1,
        "spec_version": SPEC_VERSION,
        "source_registry_version": REGISTRY_VERSION,
        "source_registry_sha256": sha256_file(registry_path),
        "coverage_start": START_DATE,
        "coverage_end": END_DATE,
        "source_checked_through": utc_now(),
        "entry_count": sum(len(v) for v in entry_records.values()),
        "nested_sitemap_count": sum(len(v) for v in nested_records.values()),
        "candidate_count": len(candidate_rows),
        "verified_item_count": sum(r["kind"] == "item" and r["status"] == "VERIFIED_PRESENT" for r in all_records),
        "failed_item_count": sum(r["kind"] == "item" and r["status"] != "VERIFIED_PRESENT" for r in all_records),
        "files": sorted(all_records, key=lambda r: (r["source_id"], r["kind"], r["url"])),
    }
    (raw_root / "fetch_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
    return manifest


def fetch_artifacts(data_dir: Path, workers: int = 12) -> dict:
    """Freeze each accepted event page and its directly linked official PDFs.

    Large audio/video binaries are intentionally not downloaded; their links are
    inventoried so the evidence packet remains bounded and auditable.
    """
    raw_root = data_dir / "raw" / "public_communications"
    event_sources = read_csv(data_dir / "output" / "event_sources.csv")
    source_urls = sorted({row["source_url"] for row in event_sources if row["source_url"].startswith("http")})
    pages: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(freeze, raw_root, "accepted_event_artifacts", "event_page", url): url for url in source_urls}
        for position, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            record["parent_source_url"] = futures[future]
            pages.append(record)
            if position % 100 == 0:
                print(f"accepted event pages {position}/{len(futures)}", flush=True)

    pdf_jobs: dict[str, str] = {}
    media_rows: list[dict] = []
    for page in pages:
        if page["status"] != "VERIFIED_PRESENT" or "pdf" in page.get("content_type", "").lower():
            continue
        raw = Path(page["path"]).read_bytes()
        link_rows = links_from(raw, page["url"])
        page_title_key = title_key(metadata_title(raw))
        for url, anchor_text in sorted(link_rows):
            parts = urllib.parse.urlsplit(url)
            path = parts.path.lower()
            host = parts.netloc.lower().removeprefix("www.")
            official = host.endswith("federalreserve.gov") or host.endswith("fed.org") or host.endswith("stlouisfed.org") or host.endswith("frbsf.org")
            label = anchor_text.lower()
            label_key = title_key(anchor_text)
            generic_primary_download = bool(
                re.search(r"\b(?:view|download|read)\b.*\b(?:pdf|remarks|speech|testimony|statement|transcript|full text)\b", label)
                or re.search(r"\bpdf of (?:this|the) (?:speech|remarks|testimony|statement)\b", label)
            )
            same_title = bool(
                page_title_key and label_key and min(len(page_title_key), len(label_key)) >= 20
                and (page_title_key in label_key or label_key in page_title_key)
            )
            relevant_pdf = generic_primary_download or same_title
            if page["parent_source_url"].startswith("https://fraser.stlouisfed.org/") and "/docs/" in path:
                relevant_pdf = True
            if path.endswith(".pdf") and official and url.startswith("http") and relevant_pdf:
                pdf_jobs.setdefault(url, page["parent_source_url"])
            youtube_item = (
                (host == "youtube.com" and (path == "/watch" or path.startswith(("/live/", "/shorts/"))))
                or (host == "youtu.be" and len(path.strip("/")) >= 6)
            )
            direct_media = path.endswith((".mp3", ".mp4", ".m4a", ".wav", ".vtt", ".srt"))
            explicit_text_artifact = bool(
                clean_url(url) != clean_url(page["parent_source_url"])
                and official
                and re.search(r"\b(?:video|watch|audio|listen|transcript|caption)s?\b", label)
                and any(token in path for token in ("transcript", "caption"))
                and path not in {"/videos.htm", "/audio.htm"}
            )
            if youtube_item or direct_media or explicit_text_artifact:
                media_rows.append({
                    "parent_source_url": page["parent_source_url"], "artifact_url": url,
                    "artifact_kind": "MEDIA_OR_TRANSCRIPT_LINK", "retrieval_status": "LINK_INVENTORIED_NOT_BINARY_DOWNLOADED",
                })

    pdfs: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(freeze, raw_root, "accepted_event_artifacts", "pdf", url, 1, 20): (url, parent) for url, parent in pdf_jobs.items()}
        for position, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            record["parent_source_url"] = futures[future][1]
            pdfs.append(record)
            if position % 50 == 0:
                print(f"official PDF artifacts {position}/{len(futures)}", flush=True)

    manifest = {
        "schema_version": 1,
        "built_at_utc": utc_now(),
        "accepted_source_url_count": len(source_urls),
        "verified_event_pages": sum(r["status"] == "VERIFIED_PRESENT" for r in pages),
        "failed_event_pages": sum(r["status"] != "VERIFIED_PRESENT" for r in pages),
        "discovered_official_pdf_count": len(pdf_jobs),
        "verified_pdf_count": sum(r["status"] == "VERIFIED_PRESENT" for r in pdfs),
        "failed_pdf_count": sum(r["status"] != "VERIFIED_PRESENT" for r in pdfs),
        "inventoried_media_link_count": len(media_rows),
        "files": sorted(pages + pdfs, key=lambda r: (r["kind"], r["url"])),
        "media_links": sorted(media_rows, key=lambda r: (r["parent_source_url"], r["artifact_url"])),
    }
    for record in manifest["files"]:
        if record.get("path"):
            record["path"] = Path(record["path"]).relative_to(data_dir).as_posix()
    (raw_root / "artifact_fetch_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"files", "media_links"}}, indent=2))
    return manifest


def strip_markup(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def metadata_title(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    for pattern in [
        r'<meta[^>]+(?:property|name)=["\'](?:og:title|twitter:title)["\'][^>]+content=["\']([^"\']+)',
        r'<h1\b[^>]*>(.*?)</h1>', r'<title\b[^>]*>(.*?)</title>',
    ]:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()
    return ""


def metadata_url(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    for pattern in [
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            return clean_url(html.unescape(match.group(1)))
    return ""


def excluded_noncommunication(title: str, url: str) -> bool:
    value = title.strip().lower()
    path = urllib.parse.urlsplit(url).path.lower()
    if re.search(r"(?:^|\b)(photos?|photo gallery|visit to)\b", value):
        return True
    if value in {"events", "past events", "upcoming events", "speech archive", "speeches"}:
        return True
    if "chicagofed.org/events/" in url.lower():
        return True
    if path.endswith("/presidents-calendar") or "/presidents-schedule/" in path:
        return True
    return False


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def parse_date(raw: bytes, url: str) -> tuple[str, str]:
    text = raw.decode("utf-8", errors="replace")
    path = urllib.parse.urlsplit(url).path
    url_patterns = [
        (r"/(20\d{2})/(\d{2})/(\d{2})(?:/|$)", lambda m: "".join(m.groups())),
        (r"/(20\d{2})/(\d{2})-(\d{2})-(\d{2})(?:[-_/]|$)", lambda m: m.group(1) + m.group(2) + m.group(3)),
        (r"/(20\d{2})/(\d{2})-(\d{1,2})(?:[-_/]|$)", lambda m: m.group(1) + m.group(2) + m.group(3).zfill(2)),
        (r"(?:^|/)(\d{2})(\d{2})(\d{2})(?:[-_/]|$)", lambda m: "20" + "".join(m.groups())),
        (r"(?:^|/)fs(\d{2})(\d{2})(\d{2})(?:\.[a-z]+)?$", lambda m: "20" + "".join(m.groups())),
        (r"(?<!\d)(20\d{6})(?!\d)", lambda m: m.group(1)),
    ]
    for pattern, value in url_patterns:
        match = re.search(pattern, path, re.I)
        if match:
            try:
                return datetime.strptime(value(match), "%Y%m%d").date().isoformat(), "OFFICIAL_URL_DATE"
            except ValueError:
                pass
    patterns = [
        (r'(?:datePublished|dateCreated)["\']?\s*[:=]\s*["\'](20\d{2}-\d{2}-\d{2})', "OFFICIAL_PAGE_STRUCTURED_DATE"),
        (r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|date|dcterms\.date)["\'][^>]+content=["\'](20\d{2}-\d{2}-\d{2})', "OFFICIAL_PAGE_META_DATE"),
    ]
    for pattern, basis in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1), basis
    plain = strip_markup(raw)[:12000]
    match = re.search(rf"\b({MONTHS})\s+(\d{{1,2}}),\s+(20\d{{2}})\b", plain)
    if match:
        date = datetime.strptime(match.group(0), "%B %d, %Y").date().isoformat()
        return date, "OFFICIAL_PAGE_VISIBLE_DATE"
    for pattern, fmt in [(r"/(20\d{2})/(\d{2})/(\d{2})(?:/|$)", "%Y%m%d"), (r"(?<!\d)(20\d{6})(?!\d)", "%Y%m%d")]:
        match = re.search(pattern, path)
        if match:
            value = "".join(match.groups()) if len(match.groups()) > 1 else match.group(1)
            try:
                date = datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
            return date, "OFFICIAL_URL_DATE"
    # Common legacy archive conventions: /YYYY/MM-DD-YY-title and fsYYMMDD.
    match = re.search(r"/(20\d{2})/(\d{2})-(\d{2})-(\d{2})(?:[-_/]|$)", path)
    if match:
        year, month, day, short_year = match.groups()
        if year[-2:] == short_year:
            try:
                return datetime.strptime(year + month + day, "%Y%m%d").date().isoformat(), "OFFICIAL_URL_DATE"
            except ValueError:
                pass
    match = re.search(r"/(20\d{2})/(\d{2})-(\d{1,2})(?:[-_/]|$)", path)
    if match:
        year, month, day = match.groups()
        try:
            return datetime.strptime(year + month + day.zfill(2), "%Y%m%d").date().isoformat(), "OFFICIAL_URL_DATE"
        except ValueError:
            pass
    match = re.search(r"(?:^|/)(\d{2})(\d{2})(\d{2})(?:[-_/]|$)", path)
    if match:
        try:
            return datetime.strptime("20" + "".join(match.groups()), "%Y%m%d").date().isoformat(), "OFFICIAL_URL_DATE"
        except ValueError:
            pass
    match = re.search(r"(?:^|/)fs(\d{2})(\d{2})(\d{2})(?:\.[a-z]+)?$", path, re.I)
    if match:
        try:
            return datetime.strptime("20" + "".join(match.groups()), "%Y%m%d").date().isoformat(), "OFFICIAL_URL_DATE"
        except ValueError:
            pass
    return "UNKNOWN", "UNKNOWN"


def member_variants(name: str) -> list[str]:
    words = re.findall(r"[A-Za-z]+", name)
    variants = [name, " ".join(word for word in words if len(word) > 1), words[-1]]
    if name == "Thomas I. Barkin":
        variants.extend(["Tom Barkin", "Thomas Barkin"])
    if name == "Robert S. Kaplan":
        variants.append("Robert Steven Kaplan")
    return sorted(set(v for v in variants if v), key=len, reverse=True)


def match_member(raw: bytes, url: str, title: str, people: list[str]) -> tuple[str, str]:
    plain = strip_markup(raw)
    raw_text = raw.decode("utf-8", errors="replace")
    # Metadata attributes frequently carry the only explicit byline.  Keep them
    # in the matching text even though strip_markup correctly removes them from
    # the human-readable snippet.
    strong = (url + " " + title + " " + raw_text[:30000] + " " + plain[:5000]).lower()
    full = (title + " " + raw_text + " " + plain).lower()
    scored: list[tuple[int, str, str]] = []
    for person in people:
        variants = member_variants(person)
        score = 0
        basis = ""
        for variant in variants:
            token = variant.lower()
            if token in url.lower() or token in title.lower():
                score = max(score, 5)
                basis = "URL_OR_TITLE"
            elif token in strong and len(token.split()) >= 2:
                score = max(score, 4)
                basis = "PAGE_HEADER_OR_METADATA"
            elif re.search(rf"\b(?:by|president|governor|chair)\s+{re.escape(token)}\b", full):
                score = max(score, 3)
                basis = "OFFICIAL_BYLINE"
        if score:
            scored.append((score, person, basis))
    if not scored:
        return "", ""
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return "", "AMBIGUOUS_MULTIPLE_POLICYMAKERS"
    return scored[0][1], scored[0][2]


def classify_type(title: str, url: str) -> tuple[str, str]:
    # Use the title and only the final URL component.  FRASER's collection path
    # contains the generic phrase "statements-speeches" for every record; using
    # the full URL would misclassify ordinary speeches as personal statements.
    url_leaf = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    value = (title + " " + url_leaf).lower()
    title_value = title.lower()
    if "testimon" in value:
        return "TESTIMONY", "PREPARED"
    if "interview" in value or "conversation with" in value or "fireside chat" in value:
        return "INTERVIEW", "INTERVIEW"
    if "press conference" in value:
        return "PRESS_CONFERENCE", "EXTEMPORANEOUS"
    if "q&a" in value or "q-and-a" in value or "questions and answers" in value:
        return "Q_AND_A", "Q_AND_A"
    if "opening remarks" in value or "welcoming remarks" in value:
        return "OPENING_REMARKS", "PREPARED"
    if "statement" in title_value or "dissent" in title_value:
        return "PERSONAL_PUBLIC_STATEMENT", "WRITTEN_ONLY"
    if any(word in value for word in ("article", "essay", "publication")):
        return "ARTICLE_ESSAY_OR_OFFICIAL_PUBLICATION", "WRITTEN_ONLY"
    if "panel" in value or "moderated discussion" in value:
        return "PANEL_OR_MODERATED_DISCUSSION", "EXTEMPORANEOUS"
    if "remarks" in value:
        return "REMARKS", "PREPARED"
    return "SPEECH", "PREPARED"


def title_key(value: str, member: str = "") -> str:
    normalized = html.unescape(value).strip()
    normalized = re.sub(r"\s*\|\s*Federal Reserve Bank.*$", "", normalized, flags=re.I)
    normalized = re.sub(r"\bQ\s*(?:&|and|-)\s*A\b", "QA", normalized, flags=re.I)
    if member:
        surname = re.escape(member.split()[-1])
        normalized = re.sub(rf"^(?:President\s+)?{surname}\s*:\s*", "", normalized, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def event_key(member: str, date: str, title: str) -> str:
    return hashlib.sha256(f"{member}|{date}|{title_key(title, member)}".encode()).hexdigest()[:24]


def source_observation(*, member: str, date: str, date_basis: str, title: str, source_id: str,
                       institution: str, source_url: str, raw_file: str, raw_sha256: str,
                       raw_snippet: str, retrieved_at: str, last_modified: str,
                       record_type: str, mode: str, match_basis: str) -> dict:
    return {
        "candidate_id": event_key(member, date, title), "member_name": member,
        "event_date": date, "event_date_basis": date_basis, "title": title,
        "event_type": record_type, "communication_mode": mode,
        "source_id": source_id, "source_institution": institution,
        "source_url": source_url, "raw_file": raw_file, "raw_sha256": raw_sha256,
        "raw_snippet": raw_snippet, "retrieved_at": retrieved_at,
        "source_last_modified_at": last_modified or "UNKNOWN", "member_match_basis": match_basis,
    }


def old_catalog_observations(data_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for old in read_csv(data_dir / "output" / "speech_catalog.csv"):
        raw_path = data_dir / old["raw_metadata_file"]
        if not raw_path.exists() or old["event_date"] == "UNKNOWN" or not (START_DATE <= old["event_date"] <= END_DATE):
            continue
        raw = raw_path.read_bytes()
        source_url = old["source_url"] or old.get("secondary_source_url", "") or metadata_url(raw)
        if excluded_noncommunication(old["title"], source_url):
            continue
        plain = strip_markup(raw)
        position = plain.lower().find(old["title"].lower()[:80])
        snippet = plain[max(0, position - 180): position + 500] if position >= 0 else plain[:680]
        record_type, mode = classify_type(old["title"], source_url)
        if old["source_archive"] == "FRASER_OAI_PMH":
            source_id = "fraser_fomc_participant_archive"
        else:
            source_id = INSTITUTION_SOURCE_IDS[old["source_institution"]]
        rows.append(source_observation(
            member=old["member_name"], date=old["event_date"], date_basis=old["event_date_basis"],
            title=old["title"], source_id=source_id, institution=old["source_institution"],
            source_url=source_url, raw_file=old["raw_metadata_file"], raw_sha256=sha256_bytes(raw),
            raw_snippet=snippet, retrieved_at=datetime.fromtimestamp(raw_path.stat().st_mtime, timezone.utc).isoformat(),
            last_modified=old.get("archive_record_updated_at_utc", ""), record_type=record_type,
            mode=mode, match_basis="LEGACY_CATALOG_REVALIDATED",
        ))
    return rows


def build(data_dir: Path) -> dict:
    registry = json.loads((data_dir / "spec" / "source_registry_v1.0.json").read_text(encoding="utf-8"))
    source_by_id = {row["source_id"]: row for row in registry["sources"]}
    manifest_path = data_dir / "raw" / "public_communications" / "fetch_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tenure_rows = read_csv(data_dir / "output" / "policy_tenures.csv")
    people_by_institution: dict[str, list[str]] = defaultdict(list)
    bounds_by_person: dict[str, tuple[str, str]] = {}
    for row in tenure_rows:
        bounds_by_person[row["member_name"]] = (row["effective_from"], row["effective_to"])
        for institution in row["institution"].split(";"):
            people_by_institution[institution].append(row["member_name"])

    observations = old_catalog_observations(data_dir)
    rejected: list[dict] = []
    tenure_filtered: list[dict] = []
    intervals_by_person: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (_, person), interval in OFFICE_INTERVALS.items():
        intervals_by_person[person].append(interval)
    for row in observations:
        intervals = intervals_by_person.get(row["member_name"])
        if intervals and not any(start <= row["event_date"] <= end for start, end in intervals):
            rejected.append({
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "reason": "OUTSIDE_QUALIFYING_POLICY_TENURE",
                "detail": f"{row['member_name']}|{row['event_date']}|{row['title']}",
            })
            continue
        tenure_filtered.append(row)
    observations = tenure_filtered
    fraser_dates_by_person: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        if row["source_id"] == "fraser_fomc_participant_archive":
            fraser_dates_by_person[row["member_name"]].add(row["event_date"])
    for record in manifest["files"]:
        if record["kind"] != "item":
            continue
        if record["status"] != "VERIFIED_PRESENT":
            lower_url = record["url"].lower()
            if record["source_id"] == "kansas_city_public_communications" and "george" in lower_url:
                year = re.search(r"/((?:19|20)\d{2})-", record["url"])
                month_day = re.search(r"[-_](\d{1,2})[-_](\d{1,2})(?:/)?$", record["url"])
                reconciled_date = ""
                if year and month_day:
                    try:
                        reconciled_date = datetime(
                            int(year.group(1)), int(month_day.group(1)), int(month_day.group(2))
                        ).date().isoformat()
                    except ValueError:
                        pass
                reason = "SOURCE_URL_DEAD_RECONCILED_FRASER" if reconciled_date in fraser_dates_by_person["Esther L. George"] else "KNOWN_GAP_DEAD_IN_SCOPE_SOURCE_URL"
                rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": reason, "detail": reconciled_date or record["error"]})
            elif record["source_id"] == "kansas_city_public_communications":
                rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "UNKNOWN_AUTHOR_ON_DEAD_ARCHIVE_URL", "detail": record["error"]})
            else:
                rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "KNOWN_GAP_FETCH_FAILED", "detail": record["error"]})
            continue
        source = source_by_id[record["source_id"]]
        raw_path = data_dir / record["path"]
        raw = raw_path.read_bytes()
        title = record.get("anchor_text") or metadata_title(raw)
        if not title:
            rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "NO_TITLE", "detail": ""})
            continue
        if excluded_noncommunication(title, record["url"]):
            rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "EXCLUDED_EVENT_LISTING_WITHOUT_COMMUNICATION", "detail": title})
            continue
        date, date_basis = parse_date(raw, record["url"])
        if date == "UNKNOWN":
            rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "NO_AUDITABLE_EVENT_DATE", "detail": title})
            continue
        if date < START_DATE or date > END_DATE:
            rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": "OUTSIDE_COVERAGE", "detail": date})
            continue
        # Modern page navigation often names the current president on an old
        # predecessor's speech.  Restrict author matching to people whose
        # observed policymaker interval overlaps the event year before looking
        # at names in the page; this prevents systematic reassignment of history.
        people = sorted(set(people_by_institution[source["institution"]]))
        active_people = []
        for person in people:
            interval = OFFICE_INTERVALS.get((source["institution"], person))
            if interval and interval[0] <= date <= interval[1]:
                active_people.append(person)
            elif not interval and bounds_by_person[person][0][:4] <= date[:4] <= bounds_by_person[person][1][:4]:
                active_people.append(person)
        member, match_basis = match_member(raw, record["url"], title, active_people)
        if not member:
            rejected.append({"source_id": record["source_id"], "source_url": record["url"], "reason": match_basis or "NO_IN_SCOPE_POLICYMAKER", "detail": title})
            continue
        plain = strip_markup(raw)
        position = plain.lower().find(title.lower()[:80])
        snippet = plain[max(0, position - 180): position + 500] if position >= 0 else plain[:680]
        record_type, mode = classify_type(title, record["url"])
        observations.append(source_observation(
            member=member, date=date, date_basis=date_basis, title=title,
            source_id=record["source_id"], institution=source["institution"], source_url=record["url"],
            raw_file=record["path"], raw_sha256=record["sha256"], raw_snippet=snippet,
            retrieved_at=record["retrieved_at"], last_modified=record["last_modified"],
            record_type=record_type, mode=mode, match_basis=match_basis,
        ))

    # Exact same member/date/normalized-title candidates are one event.  Less
    # certain near-duplicates remain separate and visible to the discrepancy table.
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in observations:
        grouped[(row["member_name"], row["event_date"], title_key(row["title"], row["member_name"]))].append(row)
    events: list[dict] = []
    event_sources: list[dict] = []
    artifacts: list[dict] = []
    for key, seen in sorted(grouped.items()):
        canonical = sorted(seen, key=lambda r: (r["source_id"] != "board_speeches_testimony", len(r["title"])))[0]
        event_id = "comm-" + event_key(*key)
        public_available_at = canonical["event_date"] + "T23:59:59Z"
        events.append({
            "communication_event_id": event_id,
            "member_id": slug(canonical["member_name"]),
            "member_name": canonical["member_name"],
            "event_date": canonical["event_date"],
            "event_time": "UNKNOWN",
            "event_timezone": "UNKNOWN",
            "public_available_at": public_available_at,
            "public_availability_precision": "DATE_ONLY_END_OF_DAY_CONSERVATIVE",
            "public_availability_basis": "OFFICIAL_PUBLIC_EVENT_DATE; EXACT_POSTING_OR_DELIVERY_TIME_UNKNOWN",
            "title": canonical["title"],
            "event_type": canonical["event_type"],
            "communication_mode": canonical["communication_mode"],
            "source_count": len({r["source_url"] for r in seen}),
            "prepared_text_status": "UNKNOWN",
            "transcript_status": "UNKNOWN",
            "qa_status": "UNKNOWN",
            "audio_status": "UNKNOWN",
            "video_status": "UNKNOWN",
            "topic_classification": "UNCLASSIFIED",
        })
        for source in sorted(seen, key=lambda r: (r["source_id"], r["source_url"])):
            source_row = {
                "event_source_id": "src-" + hashlib.sha256((event_id + "|" + source["source_url"] + "|" + source["raw_sha256"]).encode()).hexdigest()[:24],
                "communication_event_id": event_id,
                **{k: source[k] for k in ["source_id", "source_institution", "source_url", "raw_file", "raw_sha256", "raw_snippet", "retrieved_at", "source_last_modified_at", "event_date_basis", "member_match_basis"]},
                "first_seen_at": source["retrieved_at"],
                "last_checked_at": manifest["source_checked_through"],
                "evidence_status": "VERIFIED_PRESENT",
            }
            event_sources.append(source_row)
            raw_path = data_dir / source["raw_file"]
            artifact_type = "PDF_PREPARED_TEXT" if raw_path.suffix.lower() == ".pdf" else "EVENT_LISTING"
            artifacts.append({
                "artifact_id": "art-" + hashlib.sha256((source_row["event_source_id"] + "|" + artifact_type).encode()).hexdigest()[:24],
                "communication_event_id": event_id,
                "event_source_id": source_row["event_source_id"],
                "artifact_type": artifact_type,
                "artifact_url": source["source_url"],
                "version": 1,
                "retrieved_at": source["retrieved_at"],
                "raw_file": source["raw_file"],
                "sha256": source["raw_sha256"],
                "bytes": raw_path.stat().st_size,
                "retrieval_status": "VERIFIED_PRESENT",
            })

    # Attach the separately frozen event pages, prepared-text PDFs, and media
    # links without turning multiple files into multiple communication events.
    artifact_manifest_path = data_dir / "raw" / "public_communications" / "artifact_fetch_manifest.json"
    artifact_links: list[dict] = []
    if artifact_manifest_path.exists():
        artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))
        sources_by_url: dict[str, list[dict]] = defaultdict(list)
        for row in event_sources:
            if row["source_url"]:
                sources_by_url[clean_url(row["source_url"])].append(row)
        event_by_id_mutable = {row["communication_event_id"]: row for row in events}
        for record in artifact_manifest["files"]:
            parent = clean_url(record.get("parent_source_url", record["url"]))
            for source_row in sources_by_url.get(parent, []):
                if record["kind"] == "pdf":
                    artifact_type = "PDF_PREPARED_TEXT"
                elif "pdf" in record.get("content_type", "").lower() or record["url"].lower().split("?", 1)[0].endswith(".pdf"):
                    artifact_type = "PDF_PREPARED_TEXT"
                else:
                    # A fetched event page proves the listing/detail page is
                    # preserved.  It does not, by itself, prove that the page
                    # contains the full prepared text.
                    artifact_type = "EVENT_LISTING"
                raw_file = record["path"] if record["status"] == "VERIFIED_PRESENT" else ""
                if artifact_type == "EVENT_LISTING":
                    artifact_identity = source_row["event_source_id"] + "|" + artifact_type
                else:
                    artifact_identity = source_row["event_source_id"] + "|" + artifact_type + "|" + record["url"]
                artifacts.append({
                    "artifact_id": "art-" + hashlib.sha256(artifact_identity.encode()).hexdigest()[:24],
                    "communication_event_id": source_row["communication_event_id"],
                    "event_source_id": source_row["event_source_id"],
                    "artifact_type": artifact_type,
                    "artifact_url": record["url"],
                    "version": 1,
                    "retrieved_at": record["retrieved_at"],
                    "raw_file": raw_file,
                    "sha256": record["sha256"],
                    "bytes": record["bytes"],
                    "retrieval_status": record["status"],
                })
                if artifact_type == "PDF_PREPARED_TEXT" and record["status"] == "VERIFIED_PRESENT":
                    event_by_id_mutable[source_row["communication_event_id"]]["prepared_text_status"] = "VERIFIED_PRESENT"
        for link in artifact_manifest.get("media_links", []):
            parent = clean_url(link["parent_source_url"])
            link_url = link["artifact_url"]
            value = link_url.lower()
            if "transcript" in value or "caption" in value:
                kind = "TRANSCRIPT_OR_CAPTIONS"
                status_field = "transcript_status"
            elif "audio" in value or urllib.parse.urlsplit(value).path.endswith((".mp3", ".m4a", ".wav")):
                kind = "AUDIO"
                status_field = "audio_status"
            else:
                kind = "VIDEO"
                status_field = "video_status"
            for source_row in sources_by_url.get(parent, []):
                artifact_links.append({
                    "communication_event_id": source_row["communication_event_id"],
                    "event_source_id": source_row["event_source_id"],
                    "artifact_kind": kind,
                    "artifact_url": link_url,
                    "status": "LINK_INVENTORIED_NOT_BINARY_DOWNLOADED",
                })
                event_by_id_mutable[source_row["communication_event_id"]][status_field] = "LINK_INVENTORIED"

    # Preserve deterministic row ordering and remove exact artifact/link repeats.
    artifacts = list({row["artifact_id"]: row for row in artifacts}.values())
    artifacts.sort(key=lambda row: (row["communication_event_id"], row["artifact_type"], row["artifact_url"]))
    artifact_links = list({(row["communication_event_id"], row["artifact_kind"], row["artifact_url"]): row for row in artifact_links}.values())
    artifact_links.sort(key=lambda row: (row["communication_event_id"], row["artifact_kind"], row["artifact_url"]))

    events.sort(key=lambda r: (r["event_date"], r["member_name"], r["title"]))
    write_csv(data_dir / "output" / "communication_events.csv", events, [
        "communication_event_id", "member_id", "member_name", "event_date", "event_time", "event_timezone",
        "public_available_at", "public_availability_precision", "public_availability_basis", "title", "event_type", "communication_mode",
        "source_count", "prepared_text_status", "transcript_status", "qa_status", "audio_status", "video_status",
        "topic_classification",
    ])
    write_csv(data_dir / "output" / "event_sources.csv", event_sources, [
        "event_source_id", "communication_event_id", "source_id", "source_institution", "source_url", "raw_file",
        "raw_sha256", "raw_snippet", "event_date_basis", "member_match_basis", "retrieved_at",
        "source_last_modified_at", "first_seen_at", "last_checked_at", "evidence_status",
    ])
    write_csv(data_dir / "output" / "artifacts.csv", artifacts, [
        "artifact_id", "communication_event_id", "event_source_id", "artifact_type", "artifact_url", "version",
        "retrieved_at", "raw_file", "sha256", "bytes", "retrieval_status",
    ])
    write_csv(data_dir / "output" / "artifact_links.csv", artifact_links, [
        "communication_event_id", "event_source_id", "artifact_kind", "artifact_url", "status",
    ])
    write_csv(data_dir / "output" / "communication_rejections.csv", rejected, ["source_id", "source_url", "reason", "detail"])

    # Measured coverage cells.  A zero is UNKNOWN unless an authoritative source
    # explicitly states absence; this prevents false completeness claims.  Cells
    # are expanded only for applicable tenure years and institutional sources.
    events_by_cell: dict[tuple[str, str, str, str], int] = defaultdict(int)
    event_by_id = {row["communication_event_id"]: row for row in events}
    source_by_event_source_id = {row["event_source_id"]: row for row in event_sources}
    for row in event_sources:
        event = event_by_id[row["communication_event_id"]]
        events_by_cell[(event["member_name"], event["event_date"][:4], row["source_id"], event["event_type"])] += 1
    artifacts_by_cell: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    for row in artifacts:
        source_row = source_by_event_source_id[row["event_source_id"]]
        event = event_by_id[row["communication_event_id"]]
        key = (event["member_name"], event["event_date"][:4], source_row["source_id"], event["event_type"], row["artifact_type"], row["retrieval_status"])
        artifacts_by_cell[key] += 1
    coverage_rows: list[dict] = []
    event_types = json.loads((data_dir / "spec" / "completeness_spec_v1.0.json").read_text(encoding="utf-8"))["event_types"]
    artifact_types = json.loads((data_dir / "spec" / "completeness_spec_v1.0.json").read_text(encoding="utf-8"))["artifact_types"]
    tenure_by_person = {row["member_name"]: row for row in tenure_rows}
    for source in registry["sources"]:
        people = sorted(set(people_by_institution.get(source["institution"], [])))
        if source["source_id"] == "fraser_fomc_participant_archive":
            people = sorted({row["member_name"] for row in tenure_rows})
        for person in people:
            tenure = tenure_by_person[person]
            first_year = max(2012, int(tenure["effective_from"][:4]))
            last_year = min(int(END_DATE[:4]), int(tenure["effective_to"][:4]))
            for year in range(first_year, last_year + 1):
                for event_type in event_types:
                    event_count = events_by_cell[(person, str(year), source["source_id"], event_type)]
                    for artifact_type in artifact_types:
                        verified_count = artifacts_by_cell[(person, str(year), source["source_id"], event_type, artifact_type, "VERIFIED_PRESENT")]
                        gap_count = artifacts_by_cell[(person, str(year), source["source_id"], event_type, artifact_type, "KNOWN_GAP")]
                        if verified_count:
                            evidence_state = "VERIFIED_PRESENT"
                            completeness_level = "C3_ARTIFACT_VERIFIED"
                            note = "Accepted artifact frozen and SHA-256 verified"
                        elif gap_count:
                            evidence_state = "KNOWN_GAP"
                            completeness_level = "C2_CROSS_SOURCE_RECONCILED"
                            note = "Official artifact link exists but bytes were not retrieved"
                        else:
                            evidence_state = "UNKNOWN"
                            completeness_level = "C2_CROSS_SOURCE_RECONCILED"
                            note = "Registered sources reconciled; zero does not prove that this event or artifact type did not exist"
                        coverage_rows.append({
                            "tenure_id": tenure["tenure_id"], "member_name": person,
                            "institution": tenure["institution"], "year": year,
                            "event_type": event_type, "source_id": source["source_id"],
                            "artifact_type": artifact_type, "event_count": event_count,
                            "verified_artifact_count": verified_count, "known_gap_count": gap_count,
                            "evidence_state": evidence_state, "completeness_level": completeness_level,
                            "note": note,
                        })
    write_csv(data_dir / "output" / "communication_coverage_cells.csv", coverage_rows, [
        "tenure_id", "member_name", "institution", "year", "event_type", "source_id", "artifact_type",
        "event_count", "verified_artifact_count", "known_gap_count", "evidence_state", "completeness_level", "note",
    ])

    output_paths = [data_dir / "output" / name for name in [
        "communication_events.csv", "event_sources.csv", "artifacts.csv", "artifact_links.csv", "communication_rejections.csv", "communication_coverage_cells.csv"
    ]]
    summary = {
        "schema_version": 1, "spec_version": SPEC_VERSION, "source_registry_version": REGISTRY_VERSION,
        "coverage_start": START_DATE, "coverage_end": END_DATE,
        "snapshot_created_at": utc_now(), "source_checked_through": manifest["source_checked_through"],
        "communication_event_count": len(events), "event_source_count": len(event_sources),
        "artifact_count": len(artifacts), "artifact_link_count": len(artifact_links), "covered_member_count": len({r["member_name"] for r in events}),
        "source_count": len(registry["sources"]), "rejected_candidate_count": len(rejected),
        "known_gap_count": sum(r["reason"].startswith("KNOWN_GAP") for r in rejected)
        + sum(r["retrieval_status"] == "KNOWN_GAP" for r in artifacts),
        "unknown_date_count": sum(r["reason"] == "NO_AUDITABLE_EVENT_DATE" for r in rejected),
        "highest_global_completeness_level": "C2_CROSS_SOURCE_RECONCILED",
        "public_availability_policy": "For date-only official public events, event-date 23:59:59Z is a conservative analytical upper bound; exact posting/delivery time remains UNKNOWN and same-day items are excluded from SEP snapshots.",
        "claim": "All registered primary indexes were enumerated and cross-source evidence was retained. Accepted event artifacts are frozen and hashed; unresolved and zero cells remain explicitly open.",
        "source_registry_sha256": sha256_file(data_dir / "spec" / "source_registry_v1.0.json"),
        "raw_manifest_sha256": sha256_file(manifest_path),
        "outputs": {path.name: sha256_file(path) for path in output_paths},
    }
    (data_dir / "output" / "public_communications_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "fetch-artifacts", "build"))
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.data_dir.resolve(), args.workers)
    elif args.command == "fetch-artifacts":
        fetch_artifacts(args.data_dir.resolve(), args.workers)
    else:
        build(args.data_dir.resolve())


if __name__ == "__main__":
    main()
