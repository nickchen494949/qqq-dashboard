import csv
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fomc_tracker" if (ROOT / "data" / "fomc_tracker").exists() else ROOT / "data"
SPEC = importlib.util.spec_from_file_location(
    "fomc_participant_master", ROOT / "tools" / "fomc_participant_master.py"
)
MASTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MASTER)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class FomcParticipantMasterRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MASTER.build(DATA)
        cls.participants = rows(DATA / "output" / "participants_by_meeting.csv")
        cls.members = rows(DATA / "output" / "members_full.csv")
        cls.coverage = rows(DATA / "output" / "participant_meeting_coverage.csv")

    def test_every_vote_date_has_an_official_participant_record(self):
        summary = json.loads((DATA / "output" / "participant_master_summary.json").read_text())
        self.assertEqual(summary["requested_vote_dates"], 118)
        self.assertEqual(summary["full_attendance_meetings"], 117)
        self.assertEqual(summary["vote_list_only_meetings"], 1)
        self.assertEqual(summary["missing_meetings"], 0)
        self.assertEqual(summary["parse_failures"], [])
        self.assertEqual(min(row["meeting_date"] for row in self.participants), "2012-01-25")

    def test_full_master_contains_voters_and_nonvoting_participants(self):
        full_names = {row["member_name"] for row in self.members}
        voter_names = {row["member_name"] for row in rows(DATA / "output" / "members.csv")}
        self.assertEqual(len(full_names), 57)
        self.assertLessEqual(voter_names, full_names)
        self.assertIn("Christine Cumming", full_names)
        self.assertIn("Kathleen O'Neill Paese", full_names)
        self.assertIn("Sushmita Shukla", full_names)
        self.assertNotIn("St. Louis", full_names)

    def test_roles_and_staff_are_not_parsed_as_names(self):
        names = {row["member_name"] for row in self.participants}
        self.assertFalse(any("President" in name or "Secretary" in name for name in names))
        self.assertNotIn("James A. Clouse", names)
        categories = {row["attendance_category"] for row in self.participants}
        self.assertEqual(
            categories,
            {"MEMBER_OR_VOTING_BANK_PRESIDENT", "ALTERNATE_MEMBER", "NONVOTING_BANK_PRESIDENT", "VOTE_LIST_ONLY"},
        )

    def test_name_alias_is_auditable(self):
        alias_rows = [row for row in self.participants if row["raw_member_name"] == "Kathleen O'Neill"]
        self.assertTrue(alias_rows)
        self.assertTrue(all(row["member_name"] == "Kathleen O'Neill Paese" for row in alias_rows))

    def test_march_2020_official_cross_reference_is_explicit(self):
        item = next(row for row in self.coverage if row["meeting_date"] == "2020-03-03")
        self.assertEqual(item["coverage_status"], "VOTE_LIST_ONLY_OFFICIAL_CROSS_REFERENCE")
        voters = [row for row in self.participants if row["meeting_date"] == "2020-03-03"]
        self.assertEqual(len(voters), 10)
        self.assertTrue(all(row["attendance_category"] == "VOTE_LIST_ONLY" for row in voters))

    def test_every_normalized_row_traces_to_frozen_raw_text(self):
        plain_by_file = {}
        for row in self.participants:
            raw_file = DATA / row["raw_file"]
            if raw_file not in plain_by_file:
                plain_by_file[raw_file] = re.sub(
                    r"\s+", " ", MASTER.strip_tags(raw_file.read_text(encoding="utf-8", errors="replace"))
                )
            self.assertIn(row["raw_snippet"], plain_by_file[raw_file])

    def test_fetch_manifest_hashes_verify(self):
        manifest = json.loads((DATA / "raw" / "minutes_history" / "fetch_manifest.json").read_text())
        self.assertEqual(manifest["requested_meetings"], 118)
        self.assertEqual(manifest["unique_minutes_documents"], 117)
        self.assertEqual(manifest["failed_minutes"], 0)
        for entry in manifest["files"]:
            raw_file = DATA / entry["path"]
            self.assertEqual(hashlib.sha256(raw_file.read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
