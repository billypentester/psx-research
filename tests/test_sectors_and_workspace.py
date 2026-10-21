"""Sector-profile selection and company/run-scoped paths."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from finura.companies import RegistryFileCompanies
from finura.schemas import SchemaLoadError
from finura.sectors import SectorProfileSelectionError, StatementModel, load_sector_profiles, select_sector_profile
from finura.workspace import UnverifiedCompanyError, Workspace, new_run_id

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "config/sector_profiles.json"
COMPANIES = RegistryFileCompanies.load(ROOT / "tests/fixtures/v1_synthetic/companies.json")


class TestSectorProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_sector_profiles(PROFILES)

    def test_shipped_configuration_is_valid(self):
        self.assertEqual(
            {profile.profile_id for profile in self.profiles.profiles},
            {"commercial_banks", "fertilizer", "cement", "oil_and_gas_exploration"},
        )

    def test_verified_classification_selects_profile(self):
        profile = select_sector_profile(COMPANIES.get("SYNBANK"), self.profiles)
        self.assertEqual(profile.profile_id, "commercial_banks")
        self.assertIs(profile.statement_model, StatementModel.BANKING)

    def test_unverified_classification_is_not_used(self):
        with self.assertRaisesRegex(SectorProfileSelectionError, "not verified"):
            select_sector_profile(COMPANIES.get("SYNIND"), self.profiles)

    def test_missing_classification_has_no_default(self):
        with self.assertRaisesRegex(SectorProfileSelectionError, "no sector classification"):
            select_sector_profile(COMPANIES.get("SYNOLD"), self.profiles)

    def test_sector_key_cannot_map_to_two_profiles(self):
        payload = json.loads(PROFILES.read_text(encoding="utf-8"))
        payload["profiles"][1]["sector_keys"].append("cement")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(SchemaLoadError, "more than one profile"):
                load_sector_profiles(path)


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(Path("/repo"))
        self.run_id = new_run_id(datetime(2026, 10, 21, 18, 15, tzinfo=UTC))

    def test_paths_use_stable_company_id_not_current_symbol(self):
        company = COMPANIES.get("SYNIND")
        self.assertEqual(company.current_symbol, "SYNIND")
        self.assertEqual(self.workspace.raw_dir(company), Path("/repo/data/raw/SYNIND"))
        self.assertEqual(self.workspace.run_dir(company, self.run_id), Path("/repo/runs/SYNIND") / self.run_id)

    def test_unverified_company_gets_no_paths(self):
        with self.assertRaises(UnverifiedCompanyError):
            self.workspace.normalized_dir(COMPANIES.get("SYNNEW"))

    def test_run_ids_are_utc_and_validated(self):
        local = datetime(2026, 10, 21, 23, 15, tzinfo=timezone(timedelta(hours=5)))
        self.assertRegex(new_run_id(local), r"^20261021T181500Z-[0-9a-f]{8}$")
        with self.assertRaises(ValueError):
            new_run_id(datetime(2026, 10, 21))
        with self.assertRaises(ValueError):
            self.workspace.run_dir(COMPANIES.get("SYNBANK"), "../escape")


if __name__ == "__main__":
    unittest.main()
