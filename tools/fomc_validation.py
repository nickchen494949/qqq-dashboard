#!/usr/bin/env python3
"""Minimal, auditable FOMC communication validation pipeline.

The later-released SEP participant keys are answer keys, never historical
features.  Commands keep raw files, parsed tables, examples, and results in
separate directories under ``data/fomc_validation``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from pypdf import PdfReader


FED_BASE = "https://www.federalreserve.gov"
HISTORICAL_URL = FED_BASE + "/monetarypolicy/fomc_historical.htm"
SPEC_VERSION = "1.0"
YEAR_START = 2012
YEAR_END = 2020
EXPECTED_PAIR_COUNT = 36
USER_AGENT = "qqq-dashboard-fomc-validation/1.0 (+public audit research)"
FRED_API_ROOT = "https://api.stlouisfed.org/fred/series/observations"
MACRO_SERIES = {
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
    "PCEPILFE": "Personal Consumption Expenditures Excluding Food and Energy (Chain-Type Price Index)",
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "All Employees, Total Nonfarm",
    "GDPC1": "Real Gross Domestic Product",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.current_href = dict(attrs).get("href")
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.current_href is not None:
            text = " ".join("".join(self.current_text).split())
            self.anchors.append((text, self.current_href))
            self.current_href = None
            self.current_text = []


class VisibleTextParser(HTMLParser):
    """Extract likely article text without website navigation or scripts."""

    CAPTURE_HINTS = (
        "main-content", "article-body", "content-body", "post-content", "entry-content",
        "page-content", "rich-text", "speech-content", "article-content",
    )
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer"}
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.capture_depth = 0
        self.main_text: list[str] = []
        self.all_text: list[str] = []
        self.stack: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        skips = tag in self.SKIP_TAGS
        if skips:
            self.skip_depth += 1
        values = " ".join(value or "" for key, value in attrs if key in {"class", "id"}).lower()
        captures = tag in {"main", "article"} or any(hint in values for hint in self.CAPTURE_HINTS)
        if captures:
            self.capture_depth += 1
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, skips, captures))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        match = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index][0] == tag), None)
        if match is None:
            return
        closing = self.stack[match:]
        del self.stack[match:]
        self.skip_depth -= sum(1 for _, skips, _ in closing if skips)
        self.capture_depth -= sum(1 for _, _, captures in closing if captures)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.all_text.append(data)
        if self.capture_depth:
            self.main_text.append(data)


def normalize_visible_text(parts: Iterable[str]) -> str:
    return " ".join(" ".join(parts).replace("\u00a0", " ").split())


def trim_html_fallback(text: str, title: str) -> str:
    trimmed = text
    normalized_title = " ".join(title.split())
    if normalized_title:
        positions: list[int] = []
        start = 0
        lower_text = text.lower()
        needle = normalized_title.lower()
        while True:
            position = lower_text.find(needle, start)
            if position < 0:
                break
            positions.append(position)
            start = position + len(needle)
        if positions:
            candidate = text[positions[-1] + len(normalized_title):].strip()
            if len(candidate.split()) >= 200:
                trimmed = candidate
    for marker in (" Back to Top ", " SUBSCRIBE TO ", " About the Fed ", " Follow Us "):
        position = trimmed.find(marker)
        if position >= 0 and len(trimmed[:position].split()) >= 200:
            trimmed = trimmed[:position].strip()
    return trimmed


def extract_artifact_text(path: Path, title: str = "") -> tuple[str, str]:
    body = path.read_bytes()
    if body.startswith(b"%PDF-"):
        text = normalize_visible_text([pdf_text(path)])
        return text, "PDF_PYPDF"
    decoded = body.decode("utf-8", errors="replace")
    if "<html" in decoded[:2000].lower() or "<!doctype" in decoded[:2000].lower():
        parser = VisibleTextParser()
        parser.feed(decoded)
        main = normalize_visible_text(parser.main_text)
        if len(main.split()) >= 200:
            return main, "HTML_MAIN"
        all_text = normalize_visible_text(parser.all_text)
        if len(all_text.split()) >= 500:
            trimmed = trim_html_fallback(all_text, title)
            return trimmed, "HTML_ALL_TITLE_TRIMMED" if trimmed != all_text else "HTML_ALL_FALLBACK"
        return main or all_text, "HTML_METADATA_ONLY"
    return normalize_visible_text([decoded]), "PLAIN_TEXT"


SEP_URL_RE = re.compile(r"FOMC(\d{8})SEP(compilation|key)\.pdf$", re.IGNORECASE)


def enumerate_sep_sources(tracker_dir: Path) -> list[dict[str, object]]:
    by_date: dict[str, dict[str, object]] = {}
    for year in range(YEAR_START, YEAR_END + 1):
        index = tracker_dir / "raw" / "index" / f"fomchistorical{year}.htm"
        if not index.is_file():
            raise ValueError(f"missing frozen historical index: {index}")
        parser = AnchorParser()
        parser.feed(index.read_text(encoding="utf-8", errors="replace"))
        for label, href in parser.anchors:
            url = urljoin(FED_BASE, href)
            match = SEP_URL_RE.search(url)
            if not match:
                continue
            raw_date, kind = match.groups()
            decision_date = datetime.strptime(raw_date, "%Y%m%d").date()
            if decision_date.year != year:
                raise ValueError(f"year mismatch in {url}")
            meeting = by_date.setdefault(
                decision_date.isoformat(),
                {
                    "sep_date": decision_date.isoformat(),
                    "meeting_first_day": (decision_date - timedelta(days=1)).isoformat(),
                    "analytical_cutoff_date": (decision_date - timedelta(days=11)).isoformat(),
                    "historical_index_url": f"{FED_BASE}/monetarypolicy/fomchistorical{year}.htm",
                    "historical_index_raw_file": str(index.relative_to(tracker_dir.parent.parent)),
                    "historical_index_sha256": sha256(index),
                },
            )
            field = "compilation_url" if kind.lower() == "compilation" else "participant_key_url"
            if field in meeting and meeting[field] != url:
                raise ValueError(f"duplicate conflicting {field} for {decision_date}")
            meeting[field] = url
            meeting[field.replace("_url", "_link_label")] = label
    records = [by_date[key] for key in sorted(by_date)]
    if len(records) != EXPECTED_PAIR_COUNT:
        raise ValueError(f"expected {EXPECTED_PAIR_COUNT} SEP pairs, found {len(records)}")
    for record in records:
        missing = {"compilation_url", "participant_key_url"} - record.keys()
        if missing:
            raise ValueError(f"incomplete SEP pair {record['sep_date']}: {sorted(missing)}")
    return records


def command_enumerate(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    tracker_dir = Path(args.tracker_dir).resolve()
    records = enumerate_sep_sources(tracker_dir)
    payload = {
        "schema_version": "fomc-validation-sep-sources/v1",
        "validation_spec_version": SPEC_VERSION,
        "created_at_utc": utc_now(),
        "source": {"label": "Federal Reserve FOMC historical materials", "url": HISTORICAL_URL},
        "pair_count": len(records),
        "records": records,
    }
    write_json(data_dir / "spec" / "sep_source_registry_v1.0.json", payload)
    print(json.dumps({"ok": True, "pair_count": len(records)}))
    return 0


def download_pdf(url: str, destination: Path, attempts: int = 3) -> dict[str, object]:
    if destination.exists():
        if not destination.read_bytes()[:5] == b"%PDF-":
            raise ValueError(f"existing file is not a PDF: {destination}")
        return {
            "status": "EXISTING_VERIFIED",
            "retrieved_at_utc": "UNKNOWN_PREEXISTING",
            "http_status": "NOT_REQUESTED",
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=60) as response:
                body = response.read()
                status = getattr(response, "status", 200)
            if status != 200 or not body.startswith(b"%PDF-"):
                raise ValueError(f"unexpected response status/content: {status}")
            destination.write_bytes(body)
            return {
                "status": "VERIFIED_PRESENT",
                "retrieved_at_utc": utc_now(),
                "http_status": status,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            error = exc
            if attempt < attempts:
                time.sleep(attempt)
    raise ValueError(f"failed to fetch {url}: {error}")


def read_secret_from_env_file(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise ValueError(f"{name} not found in {path}")


def download_xml(url: str, destination: Path, attempts: int = 3) -> dict[str, object]:
    if destination.exists():
        try:
            ET.fromstring(destination.read_bytes())
        except ET.ParseError as error:
            raise ValueError(f"existing file is not valid XML: {destination}: {error}") from error
        return {
            "status": "EXISTING_VERIFIED",
            "retrieved_at_utc": "UNKNOWN_PREEXISTING",
            "http_status": "NOT_REQUESTED",
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=60) as response:
                body = response.read()
                status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(f"unexpected response status: {status}")
            root = ET.fromstring(body)
            if root.tag != "observations":
                message = root.attrib.get("message", root.tag)
                raise ValueError(f"unexpected FRED response: {message}")
            destination.write_bytes(body)
            return {
                "status": "VERIFIED_PRESENT",
                "retrieved_at_utc": utc_now(),
                "http_status": status,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        except (HTTPError, URLError, TimeoutError, ValueError, OSError, ET.ParseError) as exc:
            error = exc
            if attempt < attempts:
                time.sleep(attempt)
    raise ValueError(f"failed to fetch FRED XML: {error}")


def command_fetch(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    registry_path = data_dir / "spec" / "sep_source_registry_v1.0.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    raw_root = data_dir / "raw" / "sep_answer_keys"
    log: list[dict[str, object]] = []
    for record in registry["records"]:
        sep_date = str(record["sep_date"])
        compact = sep_date.replace("-", "")
        for kind, url_field in (("compilation", "compilation_url"), ("participant_key", "participant_key_url")):
            destination = raw_root / sep_date / f"FOMC{compact}SEP{'compilation' if kind == 'compilation' else 'key'}.pdf"
            result = download_pdf(str(record[url_field]), destination)
            log.append(
                {
                    "sep_date": sep_date,
                    "kind": kind,
                    "url": record[url_field],
                    "raw_file": destination.relative_to(data_dir).as_posix(),
                    **result,
                }
            )
            print(json.dumps({"sep_date": sep_date, "kind": kind, "status": result["status"]}))
    if len(log) != EXPECTED_PAIR_COUNT * 2:
        raise ValueError(f"expected {EXPECTED_PAIR_COUNT * 2} downloads, got {len(log)}")
    write_json(
        data_dir / "raw" / "sep_download_log.json",
        {
            "schema_version": "fomc-validation-download-log/v1",
            "validation_spec_version": SPEC_VERSION,
            "completed_at_utc": utc_now(),
            "file_count": len(log),
            "records": log,
        },
    )
    return 0


def command_fetch_macro(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    env_path = Path(args.fred_env_file).expanduser().resolve()
    api_key = read_secret_from_env_file(env_path, "FRED_API_KEY")
    if not re.fullmatch(r"[a-z0-9]{32}", api_key):
        raise ValueError("FRED_API_KEY has unexpected format")
    registry = json.loads((data_dir / "spec" / "sep_source_registry_v1.0.json").read_text(encoding="utf-8"))
    log: list[dict[str, object]] = []
    for source in registry["records"][1:]:
        target_date = str(source["sep_date"])
        cutoff_date = date.fromisoformat(str(source["analytical_cutoff_date"]))
        # Cutoff is midnight ET.  FRED vintages have dates but no publication
        # time, so use the previous day to exclude same-day releases.
        vintage_date = cutoff_date - timedelta(days=1)
        observation_start = cutoff_date - timedelta(days=800)
        for series_id, title in MACRO_SERIES.items():
            public_params = {
                "series_id": series_id,
                "realtime_start": vintage_date.isoformat(),
                "realtime_end": vintage_date.isoformat(),
                "observation_start": observation_start.isoformat(),
                "observation_end": vintage_date.isoformat(),
                "file_type": "xml",
            }
            request_params = {**public_params, "api_key": api_key}
            request_url = FRED_API_ROOT + "?" + urlencode(request_params)
            canonical_url = FRED_API_ROOT + "?" + urlencode(public_params)
            destination = data_dir / "raw" / "alfred" / target_date / f"{series_id}.xml"
            result = download_xml(request_url, destination)
            log.append(
                {
                    "target_sep_date": target_date,
                    "analytical_cutoff_date": cutoff_date.isoformat(),
                    "vintage_date": vintage_date.isoformat(),
                    "series_id": series_id,
                    "series_title": title,
                    "canonical_url_without_api_key": canonical_url,
                    "raw_file": destination.relative_to(data_dir).as_posix(),
                    **result,
                }
            )
            print(json.dumps({"target_sep_date": target_date, "series_id": series_id, "status": result["status"]}))
    write_json(
        data_dir / "raw" / "alfred_download_log.json",
        {
            "schema_version": "fomc-validation-alfred-download-log/v1",
            "validation_spec_version": SPEC_VERSION,
            "completed_at_utc": utc_now(),
            "source": {"label": "ALFRED/FRED real-time observations", "url": "https://alfred.stlouisfed.org/"},
            "secret_policy": "FRED_API_KEY used for retrieval and omitted from every stored URL/file",
            "file_count": len(log),
            "records": log,
        },
    )
    return 0


def parse_fred_xml(path: Path) -> list[dict[str, object]]:
    root = ET.fromstring(path.read_bytes())
    rows: list[dict[str, object]] = []
    for child in root.findall("observation"):
        value = child.attrib.get("value", ".")
        if value == ".":
            continue
        rows.append(
            {
                "observation_date": child.attrib["date"],
                "value": float(value),
                "realtime_start": child.attrib.get("realtime_start", root.attrib.get("realtime_start", "UNKNOWN")),
                "realtime_end": child.attrib.get("realtime_end", root.attrib.get("realtime_end", "UNKNOWN")),
            }
        )
    return rows


def months_before(value: date, months: int) -> tuple[int, int]:
    index = value.year * 12 + value.month - 1 - months
    return index // 12, index % 12 + 1


def observation_month(rows: list[dict[str, object]], year: int, month: int) -> float:
    matching = [
        float(row["value"])
        for row in rows
        if date.fromisoformat(str(row["observation_date"])).year == year
        and date.fromisoformat(str(row["observation_date"])).month == month
    ]
    if not matching:
        raise ValueError(f"missing observation for {year}-{month:02d}")
    return matching[-1]


def command_build_macro(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    registry = json.loads((data_dir / "spec" / "sep_source_registry_v1.0.json").read_text(encoding="utf-8"))
    observations: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    for source in registry["records"][1:]:
        target_date = str(source["sep_date"])
        series_rows: dict[str, list[dict[str, object]]] = {}
        for series_id in MACRO_SERIES:
            path = data_dir / "raw" / "alfred" / target_date / f"{series_id}.xml"
            rows = parse_fred_xml(path)
            if not rows:
                raise ValueError(f"no observations for {series_id} at {target_date}")
            series_rows[series_id] = rows
            for row in rows:
                observations.append(
                    {
                        "target_sep_date": target_date,
                        "series_id": series_id,
                        **row,
                        "raw_file": path.relative_to(data_dir).as_posix(),
                        "raw_sha256": sha256(path),
                    }
                )
        latest = {series_id: rows[-1] for series_id, rows in series_rows.items()}
        cpi_date = date.fromisoformat(str(latest["CPIAUCSL"]["observation_date"]))
        cpi_year, cpi_month = months_before(cpi_date, 12)
        pce_date = date.fromisoformat(str(latest["PCEPILFE"]["observation_date"]))
        pce_year, pce_month = months_before(pce_date, 12)
        payroll_date = date.fromisoformat(str(latest["PAYEMS"]["observation_date"]))
        payroll_year, payroll_month = months_before(payroll_date, 3)
        gdp_rows = series_rows["GDPC1"]
        if len(gdp_rows) < 2:
            raise ValueError(f"insufficient GDP history at {target_date}")
        features.append(
            {
                "target_sep_date": target_date,
                "analytical_cutoff_date": source["analytical_cutoff_date"],
                "alfred_vintage_date": (date.fromisoformat(str(source["analytical_cutoff_date"])) - timedelta(days=1)).isoformat(),
                "unemployment_rate": latest["UNRATE"]["value"],
                "unemployment_observation_date": latest["UNRATE"]["observation_date"],
                "cpi_yoy": (float(latest["CPIAUCSL"]["value"]) / observation_month(series_rows["CPIAUCSL"], cpi_year, cpi_month) - 1) * 100,
                "cpi_observation_date": cpi_date.isoformat(),
                "core_pce_yoy": (float(latest["PCEPILFE"]["value"]) / observation_month(series_rows["PCEPILFE"], pce_year, pce_month) - 1) * 100,
                "core_pce_observation_date": pce_date.isoformat(),
                "payroll_change_3m_thousands": float(latest["PAYEMS"]["value"]) - observation_month(series_rows["PAYEMS"], payroll_year, payroll_month),
                "payroll_observation_date": payroll_date.isoformat(),
                "real_gdp_qoq_annualized": ((float(gdp_rows[-1]["value"]) / float(gdp_rows[-2]["value"])) ** 4 - 1) * 100,
                "real_gdp_observation_date": latest["GDPC1"]["observation_date"],
            }
        )
    write_csv(
        data_dir / "parsed" / "macro_vintage_observations.csv",
        observations,
        ["target_sep_date", "series_id", "observation_date", "value", "realtime_start", "realtime_end", "raw_file", "raw_sha256"],
    )
    write_csv(
        data_dir / "features" / "macro_features.csv",
        features,
        [
            "target_sep_date", "analytical_cutoff_date", "alfred_vintage_date", "unemployment_rate",
            "unemployment_observation_date", "cpi_yoy", "cpi_observation_date", "core_pce_yoy",
            "core_pce_observation_date", "payroll_change_3m_thousands", "payroll_observation_date",
            "real_gdp_qoq_annualized", "real_gdp_observation_date",
        ],
    )
    print(json.dumps({"ok": True, "target_dates": len(features), "observation_rows": len(observations)}))
    return 0


AFFILIATION_RE = re.compile(
    r"\s+(?:Office of Board Members|Board of Governors|"
    r"(?:Atlanta|Boston|Chicago|Cleveland|Dallas|Kansas City|Minneapolis|New York|Philadelphia|Richmond|San Francisco|St[.]? Louis)"
    r"\s+(?:Federal Reserve Bank|Reserve Bank|FRB))\b.*$",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"^(?:chairman|chair|vice chairman|vice chair)\s+", re.IGNORECASE)


def clean_key_name(value: str) -> str:
    value = AFFILIATION_RE.sub("", " ".join(value.split())).strip()
    value = TITLE_RE.sub("", value).strip()
    return value


def parse_key_text(text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in text.splitlines():
        compact = " ".join(line.split())
        match = re.match(r"^(\d{1,2})\s+(.+)$", compact)
        if not match:
            continue
        participant = int(match.group(1))
        name = clean_key_name(match.group(2))
        if not name or re.search(r"\b(?:Page|Participant|Authorized)\b", name, re.IGNORECASE):
            continue
        if not re.search(r"[A-Za-z]", name):
            continue
        if participant in result and result[participant] != name:
            raise ValueError(f"conflicting participant {participant}: {result[participant]} vs {name}")
        result[participant] = name
    if len(result) < 10:
        raise ValueError(f"implausibly small participant key: {len(result)}")
    return result


def pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    return "\f".join(page.extract_text() or "" for page in reader.pages)


def parse_projection_text(text: str) -> list[dict[str, object]]:
    rows: dict[tuple[int, int], dict[str, object]] = {}
    for page in text.split("\f"):
        compact_page = " ".join(page.split())
        is_projection_table = "Table 2" in compact_page or "Individual Projections Table" in compact_page
        if not is_projection_table or re.search(r"Table 2[.]?\s+Appendix", compact_page, re.IGNORECASE):
            continue
        for line in page.splitlines():
            compact = " ".join(line.replace("−", "-").split())
            compact = re.sub(r"(\d)(?:\s+[.]\s*|\s*[.]\s+)(\d)", r"\1.\2", compact)
            compact = re.sub(r"(?<!\w)-\s+(?=\d)", "-", compact)
            match = re.match(r"^(\d{1,2})\s+(20\d{2}|LR)\s+(.+)$", compact)
            if not match or match.group(2) == "LR":
                continue
            participant = int(match.group(1))
            horizon_year = int(match.group(2))
            values = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", match.group(3))
            if len(values) != 5:
                continue
            gdp, unemployment, pce, core_pce, funds = map(float, values)
            funds_rate_bp = round(round(funds * 8) / 8 * 100, 1)
            key = (participant, horizon_year)
            row = {
                "participant_number": participant,
                "horizon_year": horizon_year,
                "gdp": gdp,
                "unemployment": unemployment,
                "pce_inflation": pce,
                "core_pce_inflation": core_pce,
                "federal_funds_rate_published": funds,
                "federal_funds_rate_bp": funds_rate_bp,
            }
            if key in rows and rows[key] != row:
                raise ValueError(f"conflicting projection row {key}")
            rows[key] = row
    if not rows:
        raise ValueError("no finite-year individual projection rows parsed")
    return [rows[key] for key in sorted(rows)]


def normalize_person(value: str) -> list[str]:
    value = TITLE_RE.sub("", value)
    value = re.sub(r"[^A-Za-z ]", " ", value).lower()
    tokens = [token for token in value.split() if len(token) > 1 or token in {"c", "d", "j", "k", "m", "s"}]
    return tokens


def person_slug(value: str) -> str:
    return "-".join(normalize_person(value))


@dataclass(frozen=True)
class Member:
    member_id: str
    member_name: str
    tokens: tuple[str, ...]


def load_members(path: Path) -> list[Member]:
    return [Member(row["member_id"], row["member_name"], tuple(normalize_person(row["member_name"]))) for row in read_csv(path)]


def match_member(raw_name: str, members: list[Member]) -> tuple[Member, str]:
    tokens = normalize_person(raw_name)
    if not tokens:
        raise ValueError(f"empty normalized participant name: {raw_name}")
    last = tokens[-1]
    surname = [member for member in members if member.tokens and member.tokens[-1] == last]
    if len(tokens) == 1 and len(surname) == 1:
        return surname[0], "UNIQUE_SURNAME"
    first = tokens[0]
    first_last = [member for member in surname if member.tokens[0] == first]
    if len(first_last) == 1:
        return first_last[0], "FIRST_AND_SURNAME"
    raise ValueError(f"could not uniquely map participant name {raw_name!r}; candidates={[m.member_name for m in surname]}")


def partition_for(target_date: str) -> str:
    if target_date <= "2016-12-14":
        return "DEVELOPMENT"
    if target_date <= "2018-12-19":
        return "VALIDATION"
    return "FINAL_HOLDOUT"


def command_parse(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    tracker_dir = Path(args.tracker_dir).resolve()
    registry = json.loads((data_dir / "spec" / "sep_source_registry_v1.0.json").read_text(encoding="utf-8"))
    members = load_members(tracker_dir / "output" / "members_full.csv")
    key_rows: list[dict[str, object]] = []
    projection_rows: list[dict[str, object]] = []
    qa: list[dict[str, object]] = []
    for source in registry["records"]:
        sep_date = str(source["sep_date"])
        compact = sep_date.replace("-", "")
        raw_dir = data_dir / "raw" / "sep_answer_keys" / sep_date
        key_path = raw_dir / f"FOMC{compact}SEPkey.pdf"
        compilation_path = raw_dir / f"FOMC{compact}SEPcompilation.pdf"
        key = parse_key_text(pdf_text(key_path))
        projections = parse_projection_text(pdf_text(compilation_path))
        mapped: dict[int, Member] = {}
        key_only_names: list[str] = []
        for participant, raw_name in sorted(key.items()):
            try:
                member, basis = match_member(raw_name, members)
            except ValueError:
                # A few officially keyed submitters were acting/first vice presidents
                # outside the tracker attendance-derived master.  Preserve them as
                # official SEP participants; do not force-map them to another person.
                canonical = " ".join(clean_key_name(raw_name).split())
                member = Member(person_slug(canonical), canonical, tuple(normalize_person(canonical)))
                basis = "OFFICIAL_KEY_ONLY_NOT_TRACKER_MASTER"
                key_only_names.append(canonical)
            mapped[participant] = member
            key_rows.append(
                {
                    "sep_date": sep_date,
                    "participant_number": participant,
                    "participant_key_name": raw_name,
                    "member_id": member.member_id,
                    "member_name": member.member_name,
                    "match_basis": basis,
                    "participant_key_url": source["participant_key_url"],
                    "participant_key_raw_file": key_path.relative_to(data_dir).as_posix(),
                    "participant_key_sha256": sha256(key_path),
                    "answer_key_release_lag_years": 10 if int(sep_date[:4]) <= 2015 else 5,
                }
            )
        unknown_numbers = sorted({int(row["participant_number"]) for row in projections} - mapped.keys())
        if unknown_numbers:
            raise ValueError(f"projection participant numbers missing from key for {sep_date}: {unknown_numbers}")
        for row in projections:
            member = mapped[int(row["participant_number"])]
            projection_rows.append(
                {
                    "sep_date": sep_date,
                    "partition": partition_for(sep_date),
                    "member_id": member.member_id,
                    "member_name": member.member_name,
                    **row,
                    "compilation_url": source["compilation_url"],
                    "compilation_raw_file": compilation_path.relative_to(data_dir).as_posix(),
                    "compilation_sha256": sha256(compilation_path),
                }
            )
        horizons = sorted({int(row["horizon_year"]) for row in projections})
        qa.append(
            {
                "sep_date": sep_date,
                "participant_key_count": len(key),
                "projection_participant_count": len({row["participant_number"] for row in projections}),
                "finite_projection_rows": len(projections),
                "horizon_years": horizons,
                "official_key_only_names": sorted(key_only_names),
                "status": "PASS" if len(key) == len({row["participant_number"] for row in projections}) else "FAIL",
            }
        )
    if len(qa) != EXPECTED_PAIR_COUNT or any(row["status"] != "PASS" for row in qa):
        raise ValueError("SEP parse QA failed")
    output = data_dir / "parsed"
    write_csv(
        output / "sep_participant_keys.csv",
        key_rows,
        [
            "sep_date", "participant_number", "participant_key_name", "member_id", "member_name", "match_basis",
            "participant_key_url", "participant_key_raw_file", "participant_key_sha256", "answer_key_release_lag_years",
        ],
    )
    write_csv(
        output / "individual_sep_projections.csv",
        projection_rows,
        [
            "sep_date", "partition", "member_id", "member_name", "participant_number", "horizon_year", "gdp",
            "unemployment", "pce_inflation", "core_pce_inflation", "federal_funds_rate_published",
            "federal_funds_rate_bp", "compilation_url", "compilation_raw_file", "compilation_sha256",
        ],
    )
    write_json(
        output / "sep_parse_qa.json",
        {
            "schema_version": "fomc-validation-sep-parse-qa/v1",
            "validation_spec_version": SPEC_VERSION,
            "created_at_utc": utc_now(),
            "meetings": qa,
            "status": "PASS",
        },
    )
    print(json.dumps({"ok": True, "meetings": len(qa), "keys": len(key_rows), "projection_rows": len(projection_rows)}))
    return 0


def command_build_examples(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    parsed = read_csv(data_dir / "parsed" / "individual_sep_projections.csv")
    registry = json.loads((data_dir / "spec" / "sep_source_registry_v1.0.json").read_text(encoding="utf-8"))
    source_by_date = {str(row["sep_date"]): row for row in registry["records"]}
    by_date: dict[str, dict[tuple[str, int], dict[str, str]]] = {}
    for row in parsed:
        by_date.setdefault(row["sep_date"], {})[(row["member_id"], int(row["horizon_year"]))] = row
    dates = sorted(by_date)
    examples: list[dict[str, object]] = []
    for previous_date, target_date in zip(dates, dates[1:]):
        previous = by_date[previous_date]
        target = by_date[target_date]
        medians: dict[int, list[float]] = {}
        previous_medians: dict[int, list[float]] = {}
        for (_, horizon), row in target.items():
            medians.setdefault(horizon, []).append(float(row["federal_funds_rate_bp"]))
        for (_, horizon), row in previous.items():
            previous_medians.setdefault(horizon, []).append(float(row["federal_funds_rate_bp"]))
        median_values: dict[int, float] = {}
        previous_median_values: dict[int, float] = {}
        for horizon, values in medians.items():
            ordered = sorted(values)
            mid = len(ordered) // 2
            median_values[horizon] = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        for horizon, values in previous_medians.items():
            ordered = sorted(values)
            mid = len(ordered) // 2
            previous_median_values[horizon] = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        for key in sorted(previous.keys() & target.keys()):
            member_id, horizon = key
            prev = previous[key]
            actual = target[key]
            previous_bp = float(prev["federal_funds_rate_bp"])
            target_bp = float(actual["federal_funds_rate_bp"])
            delta = target_bp - previous_bp
            direction = "HIGHER" if delta > 0 else "LOWER" if delta < 0 else "UNCHANGED"
            median_bp = median_values[horizon]
            relative = "ABOVE" if target_bp > median_bp else "BELOW" if target_bp < median_bp else "AT"
            examples.append(
                {
                    "example_id": hashlib.sha256(f"{member_id}|{target_date}|{horizon}".encode()).hexdigest()[:24],
                    "partition": partition_for(target_date),
                    "previous_sep_date": previous_date,
                    "target_sep_date": target_date,
                    "meeting_first_day": source_by_date[target_date]["meeting_first_day"],
                    "analytical_cutoff_date": source_by_date[target_date]["analytical_cutoff_date"],
                    "member_id": member_id,
                    "member_name": actual["member_name"],
                    "horizon_year": horizon,
                    "horizon_offset": horizon - int(target_date[:4]),
                    "previous_dot_bp": previous_bp,
                    "previous_median_bp": previous_median_values[horizon],
                    "previous_gdp": prev["gdp"],
                    "previous_unemployment": prev["unemployment"],
                    "previous_pce_inflation": prev["pce_inflation"],
                    "previous_core_pce_inflation": prev["core_pce_inflation"],
                    "target_dot_bp": target_bp,
                    "target_minus_previous_bp": delta,
                    "direction": direction,
                    "target_median_bp": median_bp,
                    "relative_to_target_median": relative,
                    "answer_key_compilation_url": actual["compilation_url"],
                    "answer_key_participant_key_url": source_by_date[target_date]["participant_key_url"],
                }
            )
    fields = [
        "example_id", "partition", "previous_sep_date", "target_sep_date", "meeting_first_day", "analytical_cutoff_date",
        "member_id", "member_name", "horizon_year", "horizon_offset", "previous_dot_bp", "previous_median_bp",
        "previous_gdp", "previous_unemployment", "previous_pce_inflation", "previous_core_pce_inflation",
        "target_dot_bp", "target_minus_previous_bp",
        "direction", "target_median_bp", "relative_to_target_median", "answer_key_compilation_url",
        "answer_key_participant_key_url",
    ]
    write_csv(data_dir / "features" / "sep_validation_examples.csv", examples, fields)
    counts: dict[str, int] = {}
    for row in examples:
        counts[str(row["partition"])] = counts.get(str(row["partition"]), 0) + 1
    write_json(
        data_dir / "features" / "example_build_summary.json",
        {
            "schema_version": "fomc-validation-examples/v1",
            "validation_spec_version": SPEC_VERSION,
            "created_at_utc": utc_now(),
            "row_count": len(examples),
            "partition_counts": counts,
            "status": "PASS",
        },
    )
    print(json.dumps({"ok": True, "examples": len(examples), "partition_counts": counts}, sort_keys=True))
    return 0


def command_build_text(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    tracker_dir = Path(args.tracker_dir).resolve()
    registry = json.loads((data_dir / "spec" / "sep_source_registry_v1.0.json").read_text(encoding="utf-8"))
    source_by_date = {str(row["sep_date"]): row for row in registry["records"]}
    key_rows = read_csv(data_dir / "parsed" / "sep_participant_keys.csv")
    members_by_date: dict[str, dict[str, str]] = {}
    for row in key_rows:
        members_by_date.setdefault(row["sep_date"], {})[row["member_id"]] = row["member_name"]
    dates = sorted(members_by_date)

    events_by_member: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(tracker_dir / "output" / "communication_events.csv"):
        events_by_member.setdefault(row["member_id"], []).append(row)
    artifacts_by_event: dict[str, list[dict[str, str]]] = {}
    for row in read_csv(tracker_dir / "output" / "artifacts.csv"):
        if row["retrieval_status"] == "VERIFIED_PRESENT":
            artifacts_by_event.setdefault(row["communication_event_id"], []).append(row)

    extracted_dir = data_dir / "parsed" / "communication_text"
    window_dir = data_dir / "features" / "speech_windows"
    map_rows: list[dict[str, object]] = []
    windows: list[dict[str, object]] = []
    extraction_cache: dict[str, tuple[str, str, str]] = {}
    for previous_date, target_date in zip(dates, dates[1:]):
        target_source = source_by_date[target_date]
        cutoff_date = str(target_source["analytical_cutoff_date"])
        common_members = sorted(set(members_by_date[previous_date]) & set(members_by_date[target_date]))
        for member_id in common_members:
            member_name = members_by_date[target_date][member_id]
            selected_events = [
                event for event in events_by_member.get(member_id, [])
                if previous_date < event["event_date"] < cutoff_date
            ]
            selected_events.sort(key=lambda event: (event["event_date"], event["communication_event_id"]))
            usable_texts: list[str] = []
            usable_events = 0
            for event in selected_events:
                event_id = event["communication_event_id"]
                candidates = sorted(
                    artifacts_by_event.get(event_id, []),
                    key=lambda item: (0 if item["artifact_type"] == "PDF_PREPARED_TEXT" else 1, -int(item["bytes"] or 0), item["raw_file"]),
                )
                seen_hashes: set[str] = set()
                best: tuple[int, int, str, str, dict[str, str]] | None = None
                errors: list[str] = []
                for artifact in candidates:
                    artifact_hash = artifact["sha256"]
                    if artifact_hash in seen_hashes:
                        continue
                    seen_hashes.add(artifact_hash)
                    raw_path = tracker_dir / artifact["raw_file"]
                    if not raw_path.is_file() or sha256(raw_path) != artifact_hash:
                        errors.append(f"missing_or_hash_mismatch:{artifact['raw_file']}")
                        continue
                    cache_key = artifact_hash + "|" + event["title"]
                    try:
                        if cache_key not in extraction_cache:
                            text, method = extract_artifact_text(raw_path, event["title"])
                            extraction_cache[cache_key] = (text, method, hashlib.sha256(text.encode("utf-8")).hexdigest())
                        text, method, text_hash = extraction_cache[cache_key]
                    except Exception as error:  # pypdf exposes several parser-specific exception types
                        errors.append(f"extract_error:{artifact['raw_file']}:{type(error).__name__}")
                        continue
                    word_count = len(re.findall(r"[A-Za-z]+", text))
                    priority = 0 if artifact["artifact_type"] == "PDF_PREPARED_TEXT" else 1
                    candidate = (priority, -word_count, text, method, artifact)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
                if best is None:
                    map_rows.append(
                        {
                            "communication_event_id": event_id,
                            "member_id": member_id,
                            "event_date": event["event_date"],
                            "title": event["title"],
                            "status": "NO_VERIFIED_ARTIFACT",
                            "errors": ";".join(errors),
                        }
                    )
                    continue
                _, negative_words, text, method, artifact = best
                word_count = -negative_words
                usable = word_count >= 200 and method != "HTML_METADATA_ONLY"
                text_file = ""
                text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if usable:
                    text_path = extracted_dir / f"{event_id}.txt"
                    text_path.parent.mkdir(parents=True, exist_ok=True)
                    text_path.write_text(text + "\n", encoding="utf-8")
                    text_file = text_path.relative_to(data_dir).as_posix()
                    usable_texts.append(text)
                    usable_events += 1
                map_rows.append(
                    {
                        "communication_event_id": event_id,
                        "member_id": member_id,
                        "member_name": member_name,
                        "event_date": event["event_date"],
                        "public_available_at": event["public_available_at"],
                        "title": event["title"],
                        "artifact_type": artifact["artifact_type"],
                        "artifact_url": artifact["artifact_url"],
                        "raw_file": (tracker_dir / artifact["raw_file"]).relative_to(tracker_dir.parent.parent).as_posix(),
                        "raw_sha256": artifact["sha256"],
                        "extraction_method": method,
                        "word_count": word_count,
                        "status": "USABLE" if usable else "NO_USABLE_TEXT",
                        "text_file": text_file,
                        "text_sha256": text_sha,
                        "errors": ";".join(errors),
                    }
                )
            window_id = hashlib.sha256(f"{member_id}|{target_date}".encode()).hexdigest()[:24]
            aggregate = "\n\n".join(usable_texts)
            aggregate_file = ""
            aggregate_hash = ""
            if aggregate:
                aggregate_path = window_dir / f"{window_id}.txt"
                aggregate_path.parent.mkdir(parents=True, exist_ok=True)
                aggregate_path.write_text(aggregate + "\n", encoding="utf-8")
                aggregate_file = aggregate_path.relative_to(data_dir).as_posix()
                aggregate_hash = sha256(aggregate_path)
            windows.append(
                {
                    "window_id": window_id,
                    "partition": partition_for(target_date),
                    "previous_sep_date": previous_date,
                    "target_sep_date": target_date,
                    "analytical_cutoff_date": cutoff_date,
                    "member_id": member_id,
                    "member_name": member_name,
                    "event_count": len(selected_events),
                    "usable_event_count": usable_events,
                    "usable_word_count": len(re.findall(r"[A-Za-z]+", aggregate)),
                    "has_usable_text": "YES" if aggregate else "NO",
                    "aggregate_text_file": aggregate_file,
                    "aggregate_text_sha256": aggregate_hash,
                }
            )

    write_csv(
        data_dir / "parsed" / "communication_text_artifacts.csv",
        map_rows,
        [
            "communication_event_id", "member_id", "member_name", "event_date", "public_available_at", "title",
            "artifact_type", "artifact_url", "raw_file", "raw_sha256", "extraction_method", "word_count", "status",
            "text_file", "text_sha256", "errors",
        ],
    )
    write_csv(
        data_dir / "features" / "speech_windows.csv",
        windows,
        [
            "window_id", "partition", "previous_sep_date", "target_sep_date", "analytical_cutoff_date", "member_id",
            "member_name", "event_count", "usable_event_count", "usable_word_count", "has_usable_text",
            "aggregate_text_file", "aggregate_text_sha256",
        ],
    )
    coverage: dict[str, dict[str, object]] = {}
    for partition in ("DEVELOPMENT", "VALIDATION", "FINAL_HOLDOUT"):
        subset = [row for row in windows if row["partition"] == partition]
        usable = sum(row["has_usable_text"] == "YES" for row in subset)
        coverage[partition] = {
            "participant_windows": len(subset),
            "windows_with_usable_text": usable,
            "coverage": usable / len(subset) if subset else 0,
        }
    total_usable = sum(row["has_usable_text"] == "YES" for row in windows)
    total_coverage = total_usable / len(windows) if windows else 0
    write_json(
        data_dir / "features" / "speech_text_coverage.json",
        {
            "schema_version": "fomc-validation-speech-text-coverage/v1",
            "validation_spec_version": SPEC_VERSION,
            "created_at_utc": utc_now(),
            "participant_windows": len(windows),
            "windows_with_usable_text": total_usable,
            "coverage": total_coverage,
            "minimum_required": 0.70,
            "status": "PASS" if coverage["FINAL_HOLDOUT"]["coverage"] >= 0.70 else "COVERAGE_BLOCK",
            "by_partition": coverage,
        },
    )
    print(json.dumps({"ok": True, "windows": len(windows), "coverage": total_coverage, "by_partition": coverage}, sort_keys=True))
    return 0


TOKEN_RE = re.compile(r"[a-z]+")
BOILERPLATE_TOKENS = {
    "accessibility", "archive", "careers", "contact", "copyright", "disclaimer", "facebook", "federalreserve",
    "instagram", "linkedin", "privacy", "subscribe", "twitter", "website", "youtube",
}
MODEL_NAMES = (
    "B0_PREVIOUS_DOT", "B1_PREVIOUS_MEDIAN", "B3_MACRO", "B4_MEMBER",
    "B5_MACRO_PREVIOUS", "B6_PLUS_SPEECH",
)


def text_terms(text: str, removed_tokens: set[str]) -> Counter[str]:
    words = [word for word in TOKEN_RE.findall(text.lower()) if word not in removed_tokens and word not in BOILERPLATE_TOKENS]
    terms = words + [f"{left}_{right}" for left, right in zip(words, words[1:])]
    return Counter(terms)


def build_vocabulary(documents: list[Counter[str]], minimum_df: int = 3, maximum: int = 500) -> list[str]:
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())
    eligible = [(term, count) for term, count in document_frequency.items() if count >= minimum_df]
    eligible.sort(key=lambda item: (-item[1], item[0]))
    return [term for term, _ in eligible[:maximum]]


def ridge_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, alpha: float = 10.0) -> np.ndarray:
    if train_x.ndim != 2 or test_x.ndim != 2 or train_x.shape[1] != test_x.shape[1]:
        raise ValueError("ridge feature dimensions do not align")
    intercept_train = np.column_stack([np.ones(len(train_x)), train_x])
    intercept_test = np.column_stack([np.ones(len(test_x)), test_x])
    penalty = np.eye(intercept_train.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(intercept_train.T @ intercept_train + penalty, intercept_train.T @ train_y)
    return intercept_test @ coefficients


def dense_matrix(
    rows: list[dict[str, str]],
    fields: list[str],
    train_means: np.ndarray | None = None,
    train_scales: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = np.array([[float(row[field]) if row[field] not in {"", "UNKNOWN"} else np.nan for field in fields] for row in rows])
    if train_means is None:
        train_means = np.nanmean(matrix, axis=0)
    matrix = np.where(np.isnan(matrix), train_means, matrix)
    if train_scales is None:
        train_scales = np.std(matrix, axis=0)
        train_scales = np.where(train_scales < 1e-12, 1.0, train_scales)
    return (matrix - train_means) / train_scales, train_means, train_scales


def direction_label(value: float, previous: float) -> str:
    rounded = round(value / 12.5) * 12.5
    return "HIGHER" if rounded > previous else "LOWER" if rounded < previous else "UNCHANGED"


def balanced_accuracy(actual: list[str], predicted: list[str]) -> float:
    classes = sorted(set(actual))
    recalls: list[float] = []
    for label in classes:
        indexes = [index for index, value in enumerate(actual) if value == label]
        recalls.append(sum(predicted[index] == label for index in indexes) / len(indexes))
    return sum(recalls) / len(recalls) if recalls else float("nan")


def model_metrics(rows: list[dict[str, object]], model: str) -> dict[str, object]:
    errors = [abs(float(row[f"prediction_{model}"]) - float(row["target_dot_bp"])) for row in rows]
    squared = [(float(row[f"prediction_{model}"]) - float(row["target_dot_bp"])) ** 2 for row in rows]
    actual_direction = [str(row["direction"]) for row in rows]
    predicted_direction = [str(row[f"direction_{model}"]) for row in rows]
    actual_relative = [str(row["relative_to_target_median"]) for row in rows]
    predicted_relative = [str(row[f"relative_{model}"]) for row in rows]
    return {
        "n": len(rows),
        "mae_bp": sum(errors) / len(errors),
        "rmse_bp": math.sqrt(sum(squared) / len(squared)),
        "direction_balanced_accuracy": balanced_accuracy(actual_direction, predicted_direction),
        "relative_balanced_accuracy": balanced_accuracy(actual_relative, predicted_relative),
    }


def command_run_model(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    examples = read_csv(data_dir / "features" / "sep_validation_examples.csv")
    macro = {row["target_sep_date"]: row for row in read_csv(data_dir / "features" / "macro_features.csv")}
    windows = {
        (row["target_sep_date"], row["member_id"]): row
        for row in read_csv(data_dir / "features" / "speech_windows.csv")
    }
    names = read_csv(data_dir / "parsed" / "sep_participant_keys.csv")
    removed_tokens = {token for row in names for token in TOKEN_RE.findall(row["member_name"].lower())}
    removed_tokens.update({"federal", "reserve", "bank", "board", "governors"})
    document_cache: dict[tuple[str, str], Counter[str]] = {}
    for key, window in windows.items():
        path_value = window["aggregate_text_file"]
        text = (data_dir / path_value).read_text(encoding="utf-8") if path_value else ""
        document_cache[key] = text_terms(text, removed_tokens)

    macro_fields = ["unemployment_rate", "cpi_yoy", "core_pce_yoy", "payroll_change_3m_thousands", "real_gdp_qoq_annualized"]
    prior_fields = [
        "previous_dot_bp", "previous_median_bp", "previous_gdp", "previous_unemployment",
        "previous_pce_inflation", "previous_core_pce_inflation",
    ]
    for row in examples:
        macro_row = macro[row["target_sep_date"]]
        for field in macro_fields:
            row[field] = macro_row[field]
        target = date.fromisoformat(row["target_sep_date"])
        row["season_sin"] = str(math.sin(2 * math.pi * target.month / 12))
        row["season_cos"] = str(math.cos(2 * math.pi * target.month / 12))

    dates = sorted({row["target_sep_date"] for row in examples})
    predictions: list[dict[str, object]] = []
    for target_date in dates:
        train = [row for row in examples if row["target_sep_date"] < target_date]
        test = [row for row in examples if row["target_sep_date"] == target_date]
        if len({row["target_sep_date"] for row in train}) < 4 or len(train) < 100:
            continue
        train_y = np.array([float(row["target_dot_bp"]) for row in train])
        outputs: dict[str, np.ndarray] = {
            "B0_PREVIOUS_DOT": np.array([float(row["previous_dot_bp"]) for row in test]),
            "B1_PREVIOUS_MEDIAN": np.array([float(row["previous_median_bp"]) for row in test]),
        }
        base_fields = macro_fields + ["horizon_offset", "season_sin", "season_cos"]
        for model, fields, include_member in (
            ("B3_MACRO", base_fields, False),
            ("B4_MEMBER", ["horizon_offset", "season_sin", "season_cos"], True),
            ("B5_MACRO_PREVIOUS", base_fields + prior_fields, False),
        ):
            train_dense, means, scales = dense_matrix(train, fields)
            test_dense, _, _ = dense_matrix(test, fields, means, scales)
            if include_member:
                member_columns = sorted({row["member_id"] for row in train})
                train_members = np.array([[1.0 if row["member_id"] == member else 0.0 for member in member_columns] for row in train])
                test_members = np.array([[1.0 if row["member_id"] == member else 0.0 for member in member_columns] for row in test])
                train_dense = np.column_stack([train_dense, train_members])
                test_dense = np.column_stack([test_dense, test_members])
            outputs[model] = ridge_predict(train_dense, train_y, test_dense)

        train_dense, means, scales = dense_matrix(train, base_fields + prior_fields)
        test_dense, _, _ = dense_matrix(test, base_fields + prior_fields, means, scales)
        unique_training_documents: dict[tuple[str, str], Counter[str]] = {}
        for row in train:
            key = (row["target_sep_date"], row["member_id"])
            unique_training_documents[key] = document_cache.get(key, Counter())
        vocabulary = build_vocabulary(list(unique_training_documents.values()))
        train_text = np.array([
            [math.log1p(document_cache.get((row["target_sep_date"], row["member_id"]), Counter()).get(term, 0)) for term in vocabulary]
            for row in train
        ])
        test_text = np.array([
            [math.log1p(document_cache.get((row["target_sep_date"], row["member_id"]), Counter()).get(term, 0)) for term in vocabulary]
            for row in test
        ])
        outputs["B6_PLUS_SPEECH"] = ridge_predict(
            np.column_stack([train_dense, train_text]), train_y,
            np.column_stack([test_dense, test_text]),
        )
        for index, source in enumerate(test):
            output: dict[str, object] = dict(source)
            output["training_target_count"] = len({row["target_sep_date"] for row in train})
            output["training_example_count"] = len(train)
            output["b6_vocabulary_size"] = len(vocabulary)
            output["has_usable_text"] = windows[(source["target_sep_date"], source["member_id"])]["has_usable_text"]
            for model in MODEL_NAMES:
                prediction = float(outputs[model][index])
                output[f"prediction_{model}"] = prediction
                output[f"abs_error_{model}"] = abs(prediction - float(source["target_dot_bp"]))
                output[f"direction_{model}"] = direction_label(prediction, float(source["previous_dot_bp"]))
            predictions.append(output)

    for model in MODEL_NAMES:
        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in predictions:
            grouped.setdefault((str(row["target_sep_date"]), str(row["horizon_year"])), []).append(row)
        for group in grouped.values():
            ordered = sorted(float(row[f"prediction_{model}"]) for row in group)
            middle = len(ordered) // 2
            median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
            for row in group:
                value = float(row[f"prediction_{model}"])
                row[f"relative_{model}"] = "ABOVE" if value > median else "BELOW" if value < median else "AT"

    prediction_fields = list(predictions[0].keys())
    write_csv(data_dir / "results" / "sep_predictions.csv", predictions, prediction_fields)
    scored = [row for row in predictions if row["partition"] in {"VALIDATION", "FINAL_HOLDOUT"}]
    metrics: dict[str, object] = {}
    for partition in ("VALIDATION", "FINAL_HOLDOUT"):
        subset = [row for row in scored if row["partition"] == partition]
        metrics[partition] = {model: model_metrics(subset, model) for model in MODEL_NAMES}
    final_rows = [row for row in scored if row["partition"] == "FINAL_HOLDOUT"]
    meeting_dates = sorted({str(row["target_sep_date"]) for row in final_rows})
    rng = random.Random(20260905)
    bootstrap_deltas: list[float] = []
    for _ in range(10000):
        sampled = [rng.choice(meeting_dates) for _ in meeting_dates]
        draw = [row for chosen in sampled for row in final_rows if row["target_sep_date"] == chosen]
        b6 = sum(float(row["abs_error_B6_PLUS_SPEECH"]) for row in draw) / len(draw)
        b5 = sum(float(row["abs_error_B5_MACRO_PREVIOUS"]) for row in draw) / len(draw)
        bootstrap_deltas.append(b6 - b5)
    ordered_deltas = sorted(bootstrap_deltas)
    ci = [ordered_deltas[249], ordered_deltas[9749]]
    by_year: dict[str, dict[str, float]] = {}
    for year in (2019, 2020):
        subset = [row for row in final_rows if str(row["target_sep_date"]).startswith(str(year))]
        by_year[str(year)] = {
            "B5_MAE_BP": float(model_metrics(subset, "B5_MACRO_PREVIOUS")["mae_bp"]),
            "B6_MAE_BP": float(model_metrics(subset, "B6_PLUS_SPEECH")["mae_bp"]),
        }
    coverage = json.loads((data_dir / "features" / "speech_text_coverage.json").read_text(encoding="utf-8"))
    b5_metrics = metrics["FINAL_HOLDOUT"]["B5_MACRO_PREVIOUS"]
    b6_metrics = metrics["FINAL_HOLDOUT"]["B6_PLUS_SPEECH"]
    gates = {
        "b6_mae_lt_b5": b6_metrics["mae_bp"] < b5_metrics["mae_bp"],
        "ci95_entirely_below_zero": ci[1] < 0,
        "b6_direction_not_lower": b6_metrics["direction_balanced_accuracy"] >= b5_metrics["direction_balanced_accuracy"],
        "b6_beats_b5_in_2019": by_year["2019"]["B6_MAE_BP"] < by_year["2019"]["B5_MAE_BP"],
        "b6_beats_b5_in_2020": by_year["2020"]["B6_MAE_BP"] < by_year["2020"]["B5_MAE_BP"],
        "final_text_coverage_at_least_70pct": coverage["by_partition"]["FINAL_HOLDOUT"]["coverage"] >= 0.70,
    }
    verdict = "COVERAGE_BLOCK" if not gates["final_text_coverage_at_least_70pct"] else "SEP_VALUE_PASS" if all(gates.values()) else "SEP_VALUE_FAIL"
    result = {
        "schema_version": "fomc-validation-sep-results/v1",
        "validation_spec_version": SPEC_VERSION,
        "created_at_utc": utc_now(),
        "partition_integrity": {
            "development": "TOUCHED_AS_PLANNED",
            "validation": "TOUCHED_PARSER_ONLY_NO_METRICS_OR_TUNING_BEFORE_FREEZE",
            "final_holdout": "TOUCHED_PARSER_ONLY_NO_METRICS_OR_TUNING_BEFORE_FREEZE",
            "strict_untouched_claim_allowed": False,
        },
        "b2_market_baseline": "NOT_RUN_NO_FROZEN_SOURCE",
        "metrics": metrics,
        "final_holdout_b6_minus_b5_mae_ci95_bp": ci,
        "final_holdout_b6_minus_b5_mae_bootstrap_mean_bp": sum(bootstrap_deltas) / len(bootstrap_deltas),
        "final_holdout_by_year": by_year,
        "gates": gates,
        "verdict": verdict,
    }
    write_json(data_dir / "results" / "sep_validation_results.json", result)
    write_csv(
        data_dir / "results" / "bootstrap_b6_minus_b5.csv",
        [{"replicate": index + 1, "mae_delta_bp": value} for index, value in enumerate(bootstrap_deltas)],
        ["replicate", "mae_delta_bp"],
    )
    print(json.dumps({"ok": True, "prediction_rows": len(predictions), "verdict": verdict, "gates": gates}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("enumerate", "fetch", "parse", "build-examples", "build-text", "build-macro", "run-model"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", default="data/fomc_validation")
        command.add_argument("--tracker-dir", default="data/fomc_tracker")
        command.set_defaults(function={
            "enumerate": command_enumerate,
            "fetch": command_fetch,
            "parse": command_parse,
            "build-examples": command_build_examples,
            "build-text": command_build_text,
            "build-macro": command_build_macro,
            "run-model": command_run_model,
        }[name])
    fetch_macro = commands.add_parser("fetch-macro")
    fetch_macro.add_argument("--data-dir", default="data/fomc_validation")
    fetch_macro.add_argument("--tracker-dir", default="data/fomc_tracker")
    fetch_macro.add_argument("--fred-env-file", required=True)
    fetch_macro.set_defaults(function=command_fetch_macro)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.function(args))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
