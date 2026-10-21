"""Source registry, listing claims, transcription parsing, proposals, and the onboarding CLI."""

import json
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from finura.claims import (
    ClaimError,
    ClaimEvidence,
    ClaimStatus,
    ListingAssertion,
    ListingClaim,
    ListingClaimsDocument,
    check_claim_evidence,
    discover_claim,
    find_ambiguities,
    propose_company,
    review_claim,
)
from finura.companies import CompanyRegistryDocument, RegistryFileCompanies
from finura.onboarding import main as onboarding
from finura.schemas import SourceDocument, SourceRegistryDocument
from finura.schemas.io import load_model
from finura.sources.registry import RegistryFileSources, SourceConflictError, UnknownSourceError, new_source_id
from finura.sources.transcription import TranscriptionError, parse_listing_transcription
from finura.storage import StorageError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/listings"
SOURCES = FIXTURES / "source_registry.v2.json"
TRANSCRIPTION = FIXTURES / "transcription.csv"
DISCOVERED = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
REVIEWED = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
HEADER = "symbol,as_of,legal_name,listing_status,sector_label,valid_from,valid_to,previous_symbol,source_id,location,excerpt\n"


def parse(text=None, **overrides):
    content = TRANSCRIPTION.read_bytes() if text is None else text.encode("utf-8")
    return parse_listing_transcription(
        content,
        sources=overrides.get("sources", RegistryFileSources.load(SOURCES)),
        discovered_by="fixture transcriber",
        discovered_at=DISCOVERED,
    )


def claims_by_symbol(claims, symbol):
    return [claim for claim in claims if claim.assertion.symbol == symbol]


def verify_all(claims):
    return [review_claim(c, ClaimStatus.VERIFIED, reviewer="analyst", reviewed_at=REVIEWED) for c in claims]


class TestSourceRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = RegistryFileSources.load(SOURCES)
        self.existing = self.registry.get("src_synrename")

    def test_source_id_derivation_matches_legacy_registry(self):
        self.assertEqual(
            new_source_id(
                "FFC",
                "https://dps.psx.com.pk/download/document/269389.pdf",
                "a8962695859abc2e27bb780b0919a533f8e7dc6ae0652818d0735ce94cb41e2e",
            ),
            "src_e4abb64ff4886ffc",
        )

    def test_times_stay_distinct_and_unknown_stays_null(self):
        source = self.registry.get("src_syndelist")
        self.assertIsNone(source.published_at)
        self.assertIsNone(source.retrieved_at)
        self.assertIsNotNone(source.registered_at)
        self.assertIsNone(source.company_id)
        self.assertIn("upstream", source.provenance_gaps)
        self.assertNotIn("upstream", self.registry.get("src_synrename").provenance_gaps)

    def test_registering_identical_content_is_idempotent(self):
        before = len(self.registry.sources())
        again = self.existing.model_copy(update={"source_id": "src_other", "title": "Same bytes, new title"})
        self.assertEqual(self.registry.register(again), self.existing)
        self.assertEqual(self.registry.register(self.existing), self.existing)
        self.assertEqual(len(self.registry.sources()), before)

    def test_reusing_an_id_for_other_content_is_refused(self):
        with self.assertRaises(SourceConflictError):
            self.registry.register(self.existing.model_copy(update={"sha256": "4" * 64}))

    def test_new_source_is_added_and_saved_safely(self):
        new = SourceDocument.model_validate({**self.existing.model_dump(mode="json"), "source_id": "src_new", "sha256": "5" * 64})
        self.registry.register(new)
        self.assertEqual(self.registry.get("src_new"), new)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            self.registry.save(path, backup_dir=None, stamp=DISCOVERED)
            self.assertEqual(RegistryFileSources.load(path).get("src_new"), new)
            with self.assertRaises(StorageError):
                self.registry.save(path, backup_dir=None, stamp=DISCOVERED)
            backups = self.registry.save(path, backup_dir=Path(directory) / "bak", stamp=DISCOVERED)
            self.assertEqual(len(backups), 1)

    def test_unknown_source_is_an_error(self):
        with self.assertRaises(UnknownSourceError):
            self.registry.get("src_missing")


class TestListingClaims(unittest.TestCase):
    def setUp(self):
        self.claims = parse()

    def test_parsing_produces_only_discovered_claims(self):
        self.assertEqual(len(self.claims), 4)
        self.assertTrue(all(claim.status is ClaimStatus.DISCOVERED and claim.review is None for claim in self.claims))

    def test_same_statement_from_two_sources_becomes_one_claim(self):
        (rename,) = claims_by_symbol(self.claims, "SYNIND")
        self.assertEqual([item.source_id for item in rename.evidence], ["src_synrename", "src_synlisting2024"])

    def test_evidence_pins_registered_hash(self):
        (rename,) = claims_by_symbol(self.claims, "SYNIND")
        self.assertEqual(rename.evidence[0].source_sha256, "2" * 64)

    def test_claim_ids_are_stable_across_reparsing(self):
        self.assertEqual([c.claim_id for c in parse()], [c.claim_id for c in self.claims])

    def test_claim_id_must_match_content(self):
        claim = self.claims[0]
        tampered = {**claim.model_dump(mode="json"), "assertion": {**claim.assertion.model_dump(mode="json"), "legal_name": "Other Limited"}}
        with self.assertRaisesRegex(ValidationError, "does not match"):
            ListingClaim.model_validate(tampered)

    def test_review_transitions(self):
        claim = self.claims[0]
        verified = review_claim(claim, ClaimStatus.VERIFIED, reviewer="analyst", reviewed_at=REVIEWED)
        self.assertEqual((verified.status, verified.review.reviewer), (ClaimStatus.VERIFIED, "analyst"))
        with self.assertRaisesRegex(ClaimError, "already verified"):
            review_claim(verified, ClaimStatus.REJECTED, reviewer="analyst", reviewed_at=REVIEWED, note="changed mind")
        with self.assertRaisesRegex(ClaimError, "explaining why"):
            review_claim(claim, ClaimStatus.REJECTED, reviewer="analyst", reviewed_at=REVIEWED)
        with self.assertRaisesRegex(ClaimError, "before it was discovered"):
            review_claim(claim, ClaimStatus.VERIFIED, reviewer="analyst", reviewed_at=datetime(2020, 1, 1, tzinfo=UTC))

    def test_status_cannot_be_set_without_a_review(self):
        with self.assertRaisesRegex(ValidationError, "matching review"):
            ListingClaim.model_validate({**self.claims[0].model_dump(mode="json"), "status": "verified"})

    def test_symbol_reuse_after_delisting_is_not_ambiguous(self):
        self.assertEqual(len(claims_by_symbol(self.claims, "SYNO")), 2)
        self.assertEqual(find_ambiguities(self.claims), [])

    def test_conflicting_overlapping_claims_are_ambiguous_until_one_is_rejected(self):
        old = claims_by_symbol(self.claims, "SYNI")[0]
        conflicting = discover_claim(
            old.assertion.model_copy(update={"legal_name": "Different Name Limited"}),
            old.evidence,
            discovered_by="other transcriber",
            discovered_at=DISCOVERED,
        )
        self.assertTrue(find_ambiguities([old, conflicting]))
        with self.assertRaises(ValidationError):
            ListingClaimsDocument(claims=(old, conflicting))
        rejected = review_claim(conflicting, ClaimStatus.REJECTED, reviewer="analyst", reviewed_at=REVIEWED, note="misread row")
        self.assertEqual(find_ambiguities([old, rejected]), [])

    def test_merging_keeps_existing_review_state(self):
        reviewed = review_claim(self.claims[0], ClaimStatus.VERIFIED, reviewer="analyst", reviewed_at=REVIEWED)
        document = ListingClaimsDocument(claims=(reviewed,)).merged(self.claims)
        self.assertEqual(len(document.claims), 4)
        self.assertIs(document.get(reviewed.claim_id).status, ClaimStatus.VERIFIED)

    def test_evidence_must_still_match_registry(self):
        registry = RegistryFileSources.load(SOURCES)
        check_claim_evidence(self.claims, registry)
        payload = json.loads(SOURCES.read_text(encoding="utf-8"))
        payload["sources"][1]["sha256"] = "9" * 64
        changed = RegistryFileSources(SourceRegistryDocument.model_validate(payload))
        with self.assertRaisesRegex(ClaimError, "no longer has the cited SHA-256"):
            check_claim_evidence(self.claims, changed)


class TestTranscriptionRejections(unittest.TestCase):
    def assertRejected(self, body, pattern, header=HEADER):
        with self.assertRaisesRegex(TranscriptionError, pattern):
            parse(header + body)

    def test_missing_and_unknown_columns(self):
        self.assertRejected("", "missing \\['excerpt'\\]", header=HEADER.replace(",excerpt", ""))
        self.assertRejected("", "unknown \\['isin'\\]", header=HEADER.strip() + ",isin\n")

    def test_empty_transcription(self):
        self.assertRejected("", "no rows")

    def test_malformed_values(self):
        self.assertRejected("SYNI,15-06-2024,Name Limited,,,,,,src_synrename,p1,\n", "line 2")
        self.assertRejected("SYNI,2024-06-15,Name Limited,trading,,,,,src_synrename,p1,\n", "line 2")
        self.assertRejected("syni,2024-06-15,Name Limited,,,,,,src_synrename,p1,\n", "line 2")
        self.assertRejected("SYNI,2024-06-15,,,,,,,src_synrename,p1,\n", "states nothing")
        self.assertRejected("SYNI,2024-06-15,,,,,,SYNO,src_synrename,p1,\n", "needs the valid_from")

    def test_missing_evidence(self):
        self.assertRejected("SYNI,2024-06-15,Name Limited,,,,,,,p1,\n", "source_id is required")
        self.assertRejected("SYNI,2024-06-15,Name Limited,,,,,,src_synrename,,\n", "line 2")
        self.assertRejected("SYNI,2024-06-15,Name Limited,,,,,,src_unknown,p1,\n", "no registered source")

    def test_duplicate_rows(self):
        row = "SYNI,2024-06-15,Name Limited,,,,,,src_synrename,p1,\n"
        self.assertRejected(row + row, "line 3: duplicate row")

    def test_ambiguous_rows(self):
        body = (
            "SYNI,2024-06-15,Name One Limited,,,,,,src_synrename,p1,\n"
            "SYNI,2024-06-15,Name Two Limited,,,,,,src_synlisting2024,p3,\n"
        )
        self.assertRejected(body, "ambiguous")

    def test_ragged_rows_and_encoding(self):
        self.assertRejected("SYNI,2024-06-15,Name Limited\n", "wrong number of cells")
        with self.assertRaisesRegex(TranscriptionError, "not UTF-8"):
            parse_listing_transcription(b"\xff\xfe", sources=RegistryFileSources.load(SOURCES), discovered_by="x", discovered_at=DISCOVERED)


class TestCompanyProposals(unittest.TestCase):
    def setUp(self):
        self.claims = parse()
        self.industries = claims_by_symbol(self.claims, "SYNI") + claims_by_symbol(self.claims, "SYNIND")

    def test_ticker_change_builds_symbol_history(self):
        proposal = propose_company("SYNIND", verify_all(self.industries))
        company = proposal.company
        self.assertEqual(
            [(p.symbol, p.valid_from, p.valid_to) for p in company.symbols],
            [("SYNI", date(2010, 3, 1), date(2024, 7, 1)), ("SYNIND", date(2024, 7, 1), None)],
        )
        self.assertEqual(company.listing_status.value, "listed")
        self.assertTrue(company.identity.is_verified)
        self.assertEqual(company.identity.verified_by, "analyst")
        self.assertEqual(proposal.sector_labels, ("CEMENT",))
        self.assertIsNone(company.classification)

    def test_unverified_claims_give_unverified_identity_with_candidate_evidence(self):
        proposal = propose_company("SYNIND", self.industries)
        identity = proposal.company.identity
        self.assertFalse(identity.is_verified)
        self.assertIsNone(identity.verified_by)
        self.assertEqual({ref.source_id for ref in identity.evidence}, {"src_synlisting2024", "src_synrename"})
        self.assertEqual(set(proposal.unverified_claim_ids), {c.claim_id for c in self.industries})

    def test_one_unverified_claim_keeps_identity_unverified(self):
        claims = verify_all(self.industries[:1]) + self.industries[1:]
        self.assertFalse(propose_company("SYNIND", claims).company.identity.is_verified)

    def test_delisting_closes_the_symbol(self):
        delisted = [c for c in claims_by_symbol(self.claims, "SYNO") if c.assertion.listing_status.value == "delisted"]
        company = propose_company("SYNOLD", verify_all(delisted)).company
        self.assertEqual(company.delisted_on, date(2023, 6, 30))
        self.assertEqual(company.symbols[-1].valid_to, date(2023, 6, 30))
        self.assertIsNone(company.current_symbol)

    def test_reused_symbol_resolves_by_date_once_registered(self):
        syno = claims_by_symbol(self.claims, "SYNO")
        old = next(c for c in syno if c.assertion.listing_status.value == "delisted")
        new = next(c for c in syno if c.assertion.listing_status.value == "listed")
        registry = RegistryFileCompanies(
            CompanyRegistryDocument(
                companies=(propose_company("SYNOLD", verify_all([old])).company, propose_company("SYNNEW", verify_all([new])).company)
            )
        )
        self.assertEqual(registry.resolve_symbol("SYNO", date(2024, 3, 1)).company_id, "SYNNEW")

    def test_rejected_and_mixed_company_claims_are_refused(self):
        rejected = review_claim(self.industries[0], ClaimStatus.REJECTED, reviewer="analyst", reviewed_at=REVIEWED, note="wrong row")
        with self.assertRaisesRegex(ClaimError, "rejected claims"):
            propose_company("SYNIND", [rejected])
        with self.assertRaisesRegex(ClaimError, "different legal_name|unconnected"):
            propose_company("MIXED", self.claims)

    def test_needs_a_legal_name(self):
        claim = discover_claim(
            ListingAssertion(symbol="SYNX", as_of=date(2024, 1, 1), listing_status="listed"),
            (ClaimEvidence(source_id="src_synrename", source_sha256="2" * 64, location="p1"),),
            discovered_by="x",
            discovered_at=DISCOVERED,
        )
        with self.assertRaisesRegex(ClaimError, "legal name"):
            propose_company("SYNX", [claim])


class TestOnboardingCli(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.claims = self.dir / "claims.json"
        self.companies = self.dir / "companies.json"
        shutil.copy(SOURCES, self.dir / "sources.json")

    def run_cli(self, *arguments):
        return onboarding([str(argument) for argument in arguments])

    def test_ingest_review_propose_round_trip(self):
        ingest = ("ingest", "--transcription", TRANSCRIPTION, "--sources", self.dir / "sources.json", "--claims", self.claims, "--discovered-by", "tester")
        self.assertEqual(self.run_cli(*ingest), 0)
        # Re-ingesting replaces the claims file, so it needs a backup directory.
        self.assertEqual(self.run_cli(*ingest), 1)
        self.assertEqual(self.run_cli(*ingest, "--backup-dir", self.dir / "bak"), 0)
        document = load_model(self.claims, ListingClaimsDocument)
        self.assertEqual(len(document.claims), 4)

        ids = [c.claim_id for c in document.claims if c.assertion.symbol in {"SYNI", "SYNIND"}]
        propose = ["propose", "--claims", self.claims, "--sources", self.dir / "sources.json", "--company-id", "SYNIND", "--companies", self.companies]
        for claim_id in ids:
            propose += ["--claim-id", claim_id]
        self.assertEqual(self.run_cli(*propose), 0)
        unverified = load_model(self.companies, CompanyRegistryDocument).companies[0]
        self.assertFalse(unverified.identity.is_verified)

        for claim_id in ids:
            review = ("review", "--claims", self.claims, "--claim-id", claim_id, "--decision", "verified", "--reviewer", "analyst", "--backup-dir", self.dir / f"bak-{claim_id}")
            self.assertEqual(self.run_cli(*review), 0)
        self.assertEqual(self.run_cli(*propose, "--backup-dir", self.dir / "bak2"), 1)  # already registered
        self.assertEqual(self.run_cli(*propose, "--replace", "--backup-dir", self.dir / "bak3"), 0)
        verified = load_model(self.companies, CompanyRegistryDocument).companies[0]
        self.assertTrue(verified.identity.is_verified)

    def test_review_of_unknown_claim_fails(self):
        self.assertEqual(self.run_cli("ingest", "--transcription", TRANSCRIPTION, "--sources", self.dir / "sources.json", "--claims", self.claims, "--discovered-by", "tester"), 0)
        self.assertEqual(self.run_cli("review", "--claims", self.claims, "--claim-id", "clm_0000000000000000", "--decision", "verified", "--reviewer", "a", "--backup-dir", self.dir / "b"), 1)


if __name__ == "__main__":
    unittest.main()
