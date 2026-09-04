import csv
import hashlib
import importlib.util
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "fomc_tracker" if (ROOT / "data" / "fomc_tracker").exists() else ROOT / "data"
SPEC = importlib.util.spec_from_file_location(
    "fomc_speech_catalog", ROOT / "tools" / "fomc_speech_catalog.py"
)
CATALOG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(CATALOG)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class FomcSpeechCatalogRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CATALOG.build(DATA)
        cls.catalog = rows(DATA / "output" / "speech_catalog.csv")
        cls.targets = {row["member_name"] for row in rows(DATA / "output" / "members.csv")}

    def test_board_role_prefixes_do_not_leak_into_member_names(self):
        names = {row["member_name"] for row in self.catalog}
        self.assertFalse(any("for Supervision" in name for name in names))
        self.assertFalse(names - self.targets)

    def test_fraser_is_not_a_single_author_sample(self):
        fraser = [row for row in self.catalog if row["source_archive"] == "FRASER_OAI_PMH"]
        counts = Counter(row["member_name"] for row in fraser)
        self.assertGreaterEqual(len(fraser), 1_400)
        self.assertGreaterEqual(len(counts), 20)
        self.assertGreaterEqual(counts["Charles I. Plosser"], 40)

    def test_fraser_global_resumption_noise_is_excluded(self):
        fraser_names = {
            row["member_name"]
            for row in self.catalog
            if row["source_archive"] == "FRASER_OAI_PMH"
        }
        self.assertLessEqual(fraser_names, self.targets)
        self.assertTrue(
            all("fraser.stlouisfed.org" in row["source_url"] for row in self.catalog
                if row["source_archive"] == "FRASER_OAI_PMH")
        )

    def test_unknown_publication_time_is_explicit(self):
        self.assertTrue(all(row["published_date"] == "UNKNOWN" for row in self.catalog))
        self.assertTrue(all(row["published_time_local"] == "UNKNOWN" for row in self.catalog))

    def test_four_district_supplements_close_the_zero_member_gap(self):
        counts = Counter(row["member_name"] for row in self.catalog)
        self.assertGreaterEqual(counts["Alberto G. Musalem"], 20)
        self.assertGreaterEqual(counts["Jeffrey R. Schmid"], 20)
        self.assertGreaterEqual(counts["Lorie K. Logan"], 30)
        self.assertGreaterEqual(counts["Neel Kashkari"], 250)
        coverage = rows(DATA / "output" / "speech_catalog_coverage.csv")
        self.assertEqual(len(coverage), len(self.targets))
        self.assertTrue(all(row["status"] == "HAS_OFFICIAL_EVENTS" for row in coverage))

    def test_district_fetch_manifest_preserves_failures_and_hashes(self):
        path = DATA / "raw" / "speech_catalog" / "district_supplements" / "fetch_manifest.json"
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        self.assertTrue(any(entry.get("fetch_error") for entry in payload["files"]))
        for entry in payload["files"]:
            if entry.get("fetch_error"):
                continue
            raw_path = DATA / entry["path"]
            self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
