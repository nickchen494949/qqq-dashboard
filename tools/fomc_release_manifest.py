#!/usr/bin/env python3
"""Build or verify the compact provenance manifest for an FOMC release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_FILES = [
    "members.csv", "members_full.csv", "participants_by_meeting.csv",
    "participant_meeting_coverage.csv", "universe_memberships.csv",
    "policy_tenures.csv", "sep_universe.csv", "votes.csv",
    "communication_events.csv", "event_sources.csv", "artifacts.csv",
    "artifact_links.csv", "communication_rejections.csv",
    "communication_coverage_cells.csv", "member_stance_by_sep.csv",
    "member_latest_stance.csv", "member_latest_stance.md",
    "participant_master_summary.json", "public_communications_summary.json",
    "stance_snapshot_summary.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def aggregate(entries: dict[str, str]) -> str:
    payload = "".join(f"{path}\0{digest}\n" for path, digest in sorted(entries.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def current_commit(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def calculate(data_dir: Path, code_commit: str | None = None) -> dict:
    repo = data_dir.parents[1]
    output = data_dir / "output"
    raw_entries: dict[str, str] = {}
    raw_bytes: dict[str, int] = {}
    for table, path_field, hash_field, bytes_field in [
        ("event_sources.csv", "raw_file", "raw_sha256", None),
        ("artifacts.csv", "raw_file", "sha256", "bytes"),
    ]:
        for row in csv_rows(output / table):
            raw_path = row[path_field]
            digest = row[hash_field]
            if not raw_path or not digest:
                continue
            if raw_path in raw_entries and raw_entries[raw_path] != digest:
                raise ValueError(f"conflicting hashes for {raw_path}")
            full_path = data_dir / raw_path
            if not full_path.exists():
                raise FileNotFoundError(full_path)
            actual_digest = sha256(full_path)
            if actual_digest != digest:
                raise ValueError(f"hash mismatch for {raw_path}: table={digest} file={actual_digest}")
            raw_entries[raw_path] = actual_digest
            raw_bytes[raw_path] = full_path.stat().st_size
    output_entries = {name: sha256(output / name) for name in OUTPUT_FILES}
    spec_path = data_dir / "spec" / "completeness_spec_v1.0.json"
    registry_path = data_dir / "spec" / "source_registry_v1.0.json"
    public_summary = json.loads((output / "public_communications_summary.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "release_id": "fomc-public-communications-2012-present-2026-09-05",
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "coverage_start": public_summary["coverage_start"],
        "coverage_end": public_summary["coverage_end"],
        "snapshot_created_at": public_summary["snapshot_created_at"],
        "source_checked_through": public_summary["source_checked_through"],
        "spec_version": "1.0.0",
        "spec_sha256": sha256(spec_path),
        "source_registry_version": "1.0.0",
        "source_registry_sha256": sha256(registry_path),
        "code_commit": code_commit or current_commit(repo),
        "raw_file_count": len(raw_entries),
        "raw_known_bytes": sum(raw_bytes.values()),
        "raw_aggregate_sha256": aggregate(raw_entries),
        "raw_aggregate_formula": "sha256(sorted(relative_path + NUL + sha256 + LF)) over raw files referenced by event_sources.csv and VERIFIED artifacts.csv rows",
        "output_file_count": len(output_entries),
        "output_aggregate_sha256": aggregate(output_entries),
        "output_aggregate_formula": "sha256(sorted(filename + NUL + sha256 + LF))",
        "output_files": output_entries,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "run_parameters": {"workers": 12, "same_day_unknown_time": "EXCLUDED_FROM_SEP_SNAPSHOT"},
    }


def build(data_dir: Path) -> None:
    manifest = calculate(data_dir)
    path = data_dir / "output" / "release_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def verify(data_dir: Path) -> None:
    path = data_dir / "output" / "release_manifest.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    # A GitHub source archive has no .git directory.  The release manifest's
    # bound implementation commit remains the value to verify in that case.
    actual = calculate(data_dir, code_commit=expected["code_commit"])
    stable = [
        "coverage_start", "coverage_end", "snapshot_created_at", "source_checked_through",
        "spec_sha256", "source_registry_sha256", "code_commit", "raw_file_count",
        "raw_aggregate_sha256", "output_file_count", "output_aggregate_sha256",
    ]
    mismatches = {key: {"expected": expected.get(key), "actual": actual.get(key)} for key in stable if expected.get(key) != actual.get(key)}
    if mismatches:
        raise SystemExit(json.dumps({"status": "FAIL", "mismatches": mismatches}, indent=2))
    print(json.dumps({"status": "PASS", "verified_fields": stable}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    (build if args.command == "build" else verify)(args.data_dir.resolve())


if __name__ == "__main__":
    main()
