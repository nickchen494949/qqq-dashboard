import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fomc_tracker", ROOT / "tools" / "fomc_tracker.py")
TRACKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(TRACKER)


def csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class FomcTrackerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = ROOT / "data" / "fomc_tracker" if (ROOT / "data" / "fomc_tracker").exists() else ROOT / "data"
        TRACKER.build(cls.data_dir)
        cls.output = cls.data_dir / "output"

    def test_historical_statement_coverage_starts_in_2012(self):
        members = csv_rows(self.output / "members.csv")
        self.assertEqual(len(members), 45)
        self.assertEqual(min(row["first_observed_vote_date"] for row in members), "2012-01-25")
        self.assertIn("Sarah Bloom Raskin", {row["member_name"] for row in members})
        logan = next(row for row in members if row["member_name"] == "Lorie K. Logan")
        self.assertEqual(logan["last_observed_vote_date"], "2026-07-29")

    def test_full_named_vote_history_and_known_dissents(self):
        votes = csv_rows(self.output / "votes.csv")
        by_key = {(row["meeting_date"], row["member_name"]): row for row in votes}
        self.assertEqual(len(votes), 1208)
        self.assertEqual(len({row["meeting_date"] for row in votes}), 118)
        self.assertFalse({"Chairman", "Vice Chairman", "Chair", "Vice Chair"} & {row["member_name"] for row in votes})
        self.assertEqual(min(row["meeting_date"] for row in votes), "2012-01-25")
        self.assertEqual(max(row["meeting_date"] for row in votes), "2026-07-29")
        self.assertEqual(by_key[("2013-06-19", "James Bullard")]["dissent_direction"], "EASIER")
        self.assertEqual(by_key[("2020-09-16", "Robert S. Kaplan")]["dissent_direction"], "TIGHTER_GUIDANCE")
        self.assertEqual(by_key[("2024-09-18", "Michelle W. Bowman")]["dissent_direction"], "TIGHTER")
        self.assertEqual(by_key[("2025-07-30", "Christopher J. Waller")]["dissent_direction"], "EASIER")
        self.assertEqual(by_key[("2026-07-29", "Lorie K. Logan")]["policy_preference"], "HIKE_25BP")
        self.assertEqual(by_key[("2026-06-17", "Kevin Warsh")]["raw_file"], "raw/minutes/fomcminutes20260617.htm")

    def test_all_dissents_are_resolved_and_alternate_is_not_dissenter(self):
        votes = csv_rows(self.output / "votes.csv")
        dissents = [row for row in votes if row["vote"] == "AGAINST"]
        self.assertEqual(len(dissents), 73)
        self.assertTrue(all(row["dissent_direction"] not in {"", "UNKNOWN"} for row in dissents))
        harker = next(row for row in votes if row["meeting_date"] == "2022-06-15" and row["member_name"] == "Patrick Harker")
        self.assertEqual(harker["vote"], "FOR")

    def test_no_lookahead(self):
        snapshots = csv_rows(self.output / "sep_snapshots.csv")
        self.assertEqual(len({row["sep_date"] for row in snapshots}), 58)
        self.assertEqual(min(row["sep_date"] for row in snapshots), "2012-01-25")
        self.assertEqual(max(row["sep_date"] for row in snapshots), "2026-06-17")
        self.assertTrue(all(row["evidence_date"] <= row["sep_date"] for row in snapshots))
        kugler_sep = next(
            row for row in snapshots
            if row["sep_date"] == "2024-09-18" and row["member_name"] == "Adriana D. Kugler"
        )
        self.assertLessEqual(kugler_sep["evidence_date"], "2024-09-18")
        self.assertNotEqual(kugler_sep["evidence_date"], "2024-09-25")

    def test_latest_output_is_one_sep_cohort(self):
        latest = csv_rows(self.output / "latest_stance.csv")
        self.assertEqual({row["sep_date"] for row in latest}, {"2026-06-17"})
        self.assertGreaterEqual(len(latest), 10)
        williams = next(row for row in latest if row["member_name"] == "John C. Williams")
        self.assertEqual(williams["evidence_basis"], "VOTE_ACTION_PROXY")

    def test_event_stream_and_coverage_boundary_are_explicit(self):
        votes = csv_rows(self.output / "votes.csv")
        events = csv_rows(self.output / "events.csv")
        coverage = {row["component"]: row for row in csv_rows(self.output / "coverage.csv")}
        statement_events = [row for row in events if row["source_type"] == "FOMC_STATEMENT_OR_MINUTES"]
        self.assertEqual(len(statement_events), len(votes))
        self.assertEqual(coverage["named_policy_votes"]["status"], "COMPLETE_OFFICIAL_ROLLCALLS")
        self.assertEqual(coverage["individual_speeches"]["status"], "SAMPLE_ONLY")

    def test_frozen_raw_manifest_hashes_and_urls_verify(self):
        manifest = json.loads((self.output / "sources_manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(manifest["file_count"], 150)
        for entry in manifest["files"]:
            path = self.data_dir / entry["path"]
            self.assertTrue(entry["source_url"], entry["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
