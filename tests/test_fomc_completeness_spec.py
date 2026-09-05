import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data" / "fomc_tracker" / "spec" / "completeness_spec_v1.0.json"
DOC_PATH = ROOT / "docs" / "FOMC_COMPLETENESS_SPEC.md"
MANIFEST_PATH = (
    ROOT
    / "data"
    / "fomc_tracker"
    / "spec"
    / "completeness_spec_v1.0.manifest.json"
)


class FomcCompletenessSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.doc = DOC_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_contract_is_frozen_without_hard_coded_universe_counts(self):
        self.assertEqual(self.spec["version"], "1.0.0")
        self.assertEqual(self.spec["status"], "FROZEN")
        self.assertTrue(self.spec["counts_are_outputs_not_requirements"])
        for universe in self.spec["universes"].values():
            self.assertNotIn("expected_count", universe)

    def test_three_rule_derived_universes_are_distinct(self):
        self.assertEqual(
            set(self.spec["universes"]),
            {"VOTE_UNIVERSE", "DELIBERATION_UNIVERSE", "SEP_UNIVERSE"},
        )
        sep_rule = self.spec["universes"]["SEP_UNIVERSE"]
        self.assertIn("sep_identity_public", sep_rule["fields"])
        self.assertIn("official released key", sep_rule["rule"])

    def test_market_time_and_database_vintage_are_separate(self):
        self.assertEqual(
            set(self.spec["snapshot_views"]),
            {"MARKET_TIME_SNAPSHOT", "DATABASE_VINTAGE"},
        )
        self.assertIn("public_available_at", self.spec["snapshot_views"]["MARKET_TIME_SNAPSHOT"])
        self.assertIn("first_seen_at", self.spec["snapshot_views"]["DATABASE_VINTAGE"])
        self.assertEqual(
            self.spec["same_day_unknown_time_rule"],
            "EXCLUDE_FROM_SAME_DAY_MARKET_TIME_SNAPSHOT",
        )

    def test_source_universe_contains_board_twelve_banks_and_fraser(self):
        primary = self.spec["source_universe"]["primary_institution_domains"]
        self.assertEqual(len(primary), 13)
        self.assertIn("federalreserve.gov", primary)
        self.assertIn("frbsf.org", primary)
        self.assertEqual(
            self.spec["source_universe"]["mandatory_archive_domains"],
            ["fraser.stlouisfed.org"],
        )
        self.assertTrue(
            self.spec["source_universe"]["closure_requires_versioned_endpoint_registry"]
        )

    def test_gap_states_and_bounded_closure_are_explicit(self):
        self.assertEqual(
            set(self.spec["evidence_states"]),
            {
                "VERIFIED_PRESENT",
                "VERIFIED_ABSENT",
                "KNOWN_GAP",
                "UNKNOWN",
                "NOT_APPLICABLE",
            },
        )
        self.assertEqual(
            self.spec["completeness_levels"][-1],
            "C5_CLOSED_WITHIN_FROZEN_SOURCE_UNIVERSE",
        )
        self.assertEqual(self.spec["current_automated_target"], "C3_ARTIFACT_VERIFIED")

    def test_existing_catalog_is_not_promoted_by_the_spec(self):
        self.assertEqual(self.spec["existing_catalog_status"], "PRE_SPEC_WIP_UNASSESSED")
        self.assertIn("2,701-row catalog predates this frozen specification", self.doc)
        self.assertIn("must not be called complete or C3", self.doc)

    def test_frozen_contract_hashes_match(self):
        for relative_path, expected_hash in self.manifest["files"].items():
            actual_hash = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, relative_path)


if __name__ == "__main__":
    unittest.main()
