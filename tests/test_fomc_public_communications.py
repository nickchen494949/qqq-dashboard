import csv
import hashlib
import html
import json
import re
import unittest
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fomc_tracker"


def rows(name: str) -> list[dict[str, str]]:
    with (DATA / "output" / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class PublicCommunicationsAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = rows("communication_events.csv")
        cls.sources = rows("event_sources.csv")
        cls.artifacts = rows("artifacts.csv")
        cls.registry = json.loads((DATA / "spec" / "source_registry_v1.0.json").read_text())

    def test_frozen_source_universe_is_board_plus_twelve_banks_plus_fraser(self):
        sources = self.registry["sources"]
        self.assertEqual(len(sources), 14)
        self.assertEqual(len({row["domain"] for row in sources}), 14)
        manifest = json.loads((DATA / "spec" / "source_registry_v1.0.manifest.json").read_text())
        self.assertEqual(hashlib.sha256((DATA / "spec" / "source_registry_v1.0.json").read_bytes()).hexdigest(), manifest["sha256"])

    def test_universe_counts_are_derived_and_roles_resolve(self):
        memberships = rows("universe_memberships.csv")
        self.assertEqual(len({r["member_name"] for r in memberships if r["universe"] == "VOTE_UNIVERSE"}), 45)
        self.assertEqual(len({r["member_name"] for r in memberships if r["universe"] == "DELIBERATION_UNIVERSE"}), 57)
        self.assertFalse(any(r["institution"] == "UNKNOWN" for r in rows("policy_tenures.csv")))

    def test_event_source_and_artifact_referential_integrity(self):
        event_ids = [row["communication_event_id"] for row in self.events]
        self.assertEqual(len(event_ids), len(set(event_ids)))
        event_set = set(event_ids)
        source_ids = {row["event_source_id"] for row in self.sources}
        self.assertTrue(all(row["communication_event_id"] in event_set for row in self.sources))
        self.assertTrue(all(row["communication_event_id"] in event_set for row in self.artifacts))
        self.assertTrue(all(row["event_source_id"] in source_ids for row in self.artifacts))
        registered_source_ids = {row["source_id"] for row in self.registry["sources"]}
        self.assertTrue({row["source_id"] for row in self.sources} <= registered_source_ids)
        self.assertGreater(len(self.events), 3000)
        self.assertGreater(len(self.artifacts), len(self.sources))
        dudley_transition = [row for row in self.events if row["member_name"] == "William C. Dudley" and row["event_date"] == "2018-05-24"]
        self.assertEqual(len(dudley_transition), 1)
        kashkari_claremont_and_fink = [row for row in self.events if row["member_name"] == "Neel Kashkari" and row["event_date"] == "2017-04-24"]
        self.assertEqual(len(kashkari_claremont_and_fink), 2)

    def test_dates_names_urls_and_noncommunication_filter(self):
        summary = json.loads((DATA / "output" / "public_communications_summary.json").read_text())
        self.assertTrue(all(summary["coverage_start"] <= row["event_date"] <= summary["coverage_end"] for row in self.events))
        self.assertTrue(all(row["public_available_at"].endswith("T23:59:59Z") for row in self.events))
        self.assertTrue(all(row["public_availability_basis"] for row in self.events))
        self.assertFalse(any(re.search(r"\b(?:President|Governor|Chair)\b", row["member_name"]) for row in self.events))
        self.assertFalse(any(re.match(r"(?i)^(?:photos?|visit to)\b", row["title"]) for row in self.events))
        self.assertTrue(all(row["source_url"].startswith("http") for row in self.sources))
        self.assertTrue(all(row["raw_snippet"] for row in self.sources))
        self.assertFalse(any(row["member_name"] == "Loretta J. Mester" and row["event_date"] < "2014-06-01" for row in self.events))
        self.assertFalse(any(row["member_name"] == "Mark L. Mullinix" and row["event_date"] > "2018-01-01" for row in self.events))
        events_by_id = {row["communication_event_id"]: row for row in self.events}
        for source in self.sources:
            event = events_by_id[source["communication_event_id"]]
            if source["source_id"] == "fraser_fomc_participant_archive" and event["event_type"] == "PERSONAL_PUBLIC_STATEMENT":
                self.assertRegex(event["title"].lower(), r"statement|dissent")

    def test_every_claimed_frozen_artifact_hashes(self):
        checked = set()
        for row in self.artifacts:
            if row["retrieval_status"] != "VERIFIED_PRESENT":
                continue
            path = DATA / row["raw_file"]
            key = (path, row["sha256"])
            if key in checked:
                continue
            checked.add(key)
            self.assertTrue(path.exists(), path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
        self.assertFalse(any(row["artifact_type"] == "HTML_PREPARED_TEXT" for row in self.artifacts))

    def test_media_inventory_excludes_navigation_and_self_links(self):
        links = rows("artifact_links.csv")
        source_url_by_id = {row["event_source_id"]: row["source_url"] for row in self.sources}
        self.assertFalse(any(row["artifact_url"].rstrip("/").endswith(("/user/ClevelandFed", "/federalreserve", "/videos.htm")) for row in links))
        self.assertFalse(any(row["artifact_url"].rstrip("/") == source_url_by_id[row["event_source_id"]].rstrip("/") for row in links))
        for row in links:
            parts = urllib.parse.urlsplit(row["artifact_url"])
            host = parts.netloc.lower().removeprefix("www.")
            path = parts.path.lower()
            youtube_item = (host == "youtube.com" and (path == "/watch" or path.startswith(("/live/", "/shorts/")))) or (host == "youtu.be" and len(path.strip("/")) >= 6)
            direct_media = path.endswith((".mp3", ".mp4", ".m4a", ".wav", ".vtt", ".srt"))
            text_artifact = any(token in path for token in ("transcript", "caption"))
            self.assertTrue(youtube_item or direct_media or text_artifact, row["artifact_url"])

    def test_completeness_claim_keeps_open_gaps_visible(self):
        summary = json.loads((DATA / "output" / "public_communications_summary.json").read_text())
        self.assertEqual(summary["highest_global_completeness_level"], "C2_CROSS_SOURCE_RECONCILED")
        self.assertGreater(summary["known_gap_count"], 0)
        self.assertGreater(summary["unknown_date_count"], 0)
        self.assertNotIn("complete", summary["claim"].lower())
        coverage = rows("communication_coverage_cells.csv")
        self.assertTrue({"tenure_id", "institution", "year", "event_type", "source_id", "artifact_type"} <= set(coverage[0]))
        self.assertFalse(any(row["member_name"] == "Adriana D. Kugler" and row["year"] < "2023" for row in coverage))

    def test_manually_reviewed_stance_snippets_trace_to_raw(self):
        with (DATA / "curated" / "stance_annotations.csv").open(newline="", encoding="utf-8") as handle:
            annotations = list(csv.DictReader(handle))
        for row in annotations:
            raw = (DATA / row["raw_file"]).read_text(encoding="utf-8", errors="replace")
            plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
            self.assertIn(row["raw_snippet"], plain)

    def test_sep_snapshots_have_no_lookahead_and_cover_latest_participants(self):
        snapshots = rows("member_stance_by_sep.csv")
        for row in snapshots:
            if row["evidence_date"]:
                self.assertLessEqual(row["evidence_date"], row["sep_date"])
            if row["latest_communication_date"]:
                self.assertLess(row["latest_communication_date"], row["sep_date"])
        latest = rows("member_latest_stance.csv")
        self.assertEqual({row["sep_date"] for row in latest}, {"2026-06-17"})
        self.assertEqual(len(latest), 20)
        self.assertEqual(sum(row["stance_label"] == "UNKNOWN" for row in latest), 4)
        self.assertTrue(all(row["individual_sep_projection_known"] == "NO" for row in latest))


if __name__ == "__main__":
    unittest.main()
