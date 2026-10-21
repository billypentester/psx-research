"""Migrate one company's v1 facts file and the v1 source registry to v2.

The migration is company-independent: every input and output is an explicit
path, and nothing is inferred from file names or company identifiers. It:

- loads both v1 files strictly (unknown fields and invalid values abort);
- maps them to v2 documents without inventing provenance;
- checks that every fact's source exists and belongs to the same company;
- optionally checks company identity against a `CompanyRegistry` and raw
  evidence files against their registered SHA-256;
- serializes the v2 documents, re-parses the serialized text, and compares it
  field by field with the original v1 JSON;
- writes outputs only if every check passes, never over an input, and never
  over an existing file unless a backup directory is given;
- confirms the inputs are byte-identical afterwards and writes a manifest.

Any failure raises `MigrationError` before an output is written.

Usage:
    python -m finura.migrations.v1_to_v2 --facts IN --registry IN \
        --facts-out OUT --registry-out OUT --manifest-out OUT \
        [--evidence-root DIR] [--company-registry FILE] [--backup-dir DIR]
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

import finura
from finura.companies import CompanyRegistry, RegistryFileCompanies, UnknownCompanyError
from finura.schemas.documents import FinancialFactsDocument, MigrationLineage, SourceRegistryDocument
from finura.schemas.source import SourceDocument
from finura.schemas.types import AwareTimestamp
from finura.schemas.io import SchemaLoadError, dump_model, read_json
from finura.schemas.v1 import load_v1_financial_facts, load_v1_source_registry
from finura.storage import BackupRecord, StorageError, plan_backups, write_files
from finura.storage import sha256_bytes as _sha256

# (v1 fact field, v2 fact field path). See docs/DATA_SCHEMA.md.
FACT_FIELD_MAP = (
    ("metric", "concept"),
    ("value", "value"),
    ("unit", "unit"),
    ("period_end", "period.end"),
    ("period_type", "period.type"),
    ("scope", "scope"),
    ("source_id", "source_id"),
    ("source_page", "source_location"),
    ("verification_status", "verification_status"),
    ("fact_classification", "classification"),
)
# v2 fact fields v1 never recorded; they must stay unknown.
UNRECORDED_FACT_FIELDS = (
    "period.start",
    "verified_by",
    "verified_at",
    "verification_evidence",
    "extraction_method",
    "extracted_at",
)
# (v1 source field, v2 source field); absent optional v1 fields compare as null.
SOURCE_FIELD_MAP = tuple(
    (field, field)
    for field in (
        "source_id",
        "company_id",
        "source_type",
        "title",
        "published_at",
        "local_path",
        "sha256",
        "page_number",
        "notes",
        "provider",
        "retrieval_method",
        "http_status",
        "content_type",
    )
) + (("url", "canonical_url"),)
UNRECORDED_SOURCE_FIELDS = ("retrieved_at", "publisher", "access_basis", "upstream")


class MigrationError(Exception):
    """The migration was refused or failed a check; no output was written."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileRecord(_Record):
    role: Literal["v1_financial_facts", "v1_source_registry", "v2_financial_facts", "v2_source_registry"]
    path: str
    sha256: str
    schema_version: Literal[1, 2]
    record_count: int


class EvidenceCheck(_Record):
    source_id: str
    local_path: str
    result: Literal["sha256_match"]


class EquivalenceResult(_Record):
    records_compared: int
    fields_compared: tuple[str, ...]
    unknown_fields_confirmed_absent: tuple[str, ...]
    mismatches: tuple[str, ...]


class ValidationSummary(_Record):
    v2_schema_valid: bool
    fact_identities_unique: bool
    source_links_resolved: int
    source_links_same_company: int
    company_identity: Literal["verified", "unverified", "not_checked"]
    raw_evidence: Literal["checked", "not_checked"]
    evidence_checks: tuple[EvidenceCheck, ...]


class MigrationManifest(_Record):
    manifest_version: Literal[1] = 1
    migration: Literal["v1_to_v2"] = "v1_to_v2"
    finura_version: str
    executed_at: AwareTimestamp
    status: Literal["succeeded"] = "succeeded"
    company_id: str
    inputs: tuple[FileRecord, ...]
    outputs: tuple[FileRecord, ...]
    backups: tuple[BackupRecord, ...]
    validation: ValidationSummary
    fact_equivalence: EquivalenceResult
    source_equivalence: EquivalenceResult
    source_timestamps_text_identical: int
    verification_status_counts_v1: dict[str, int]
    verification_status_counts_v2: dict[str, int]
    fact_provenance_gaps: dict[str, int]
    source_provenance_gaps: dict[str, int]
    inputs_unchanged: bool


@dataclass(frozen=True)
class MigrationRequest:
    facts_input: Path
    registry_input: Path
    facts_output: Path
    registry_output: Path
    manifest_output: Path
    # Directory that registry `local_path` values are relative to. `None`
    # skips the raw-evidence check and records it as not checked.
    evidence_root: Path | None = None
    company_registry: CompanyRegistry | None = None
    # Required when any output path already exists.
    backup_dir: Path | None = None


def migrate_v1_to_v2(request: MigrationRequest, *, migrated_at: datetime) -> MigrationManifest:
    if migrated_at.tzinfo is None:
        raise MigrationError("migrated_at must be timezone-aware")
    _check_paths(request)
    input_hashes = {path: _sha256(path.read_bytes()) for path in (request.facts_input, request.registry_input)}

    try:
        v1_facts = load_v1_financial_facts(request.facts_input)
        v1_registry = load_v1_source_registry(request.registry_input)
    except SchemaLoadError as exc:
        raise MigrationError(f"v1 input rejected: {exc}") from exc
    raw_facts = read_json(request.facts_input)
    raw_sources = read_json(request.registry_input)
    company_id = v1_facts.file.company_id

    try:
        facts_document = FinancialFactsDocument(
            company_id=company_id,
            facts=v1_facts.facts,
            lineage=_lineage(request.facts_input, input_hashes[request.facts_input], migrated_at),
        )
        registry_document = SourceRegistryDocument(
            sources=v1_registry.documents,
            lineage=_lineage(request.registry_input, input_hashes[request.registry_input], migrated_at),
        )
    except ValidationError as exc:
        raise MigrationError(f"v2 validation failed: {exc}") from exc

    linked_sources = _check_source_links(facts_document, registry_document)
    company_identity = _check_company(company_id, request.company_registry)
    evidence_checks = _check_evidence(linked_sources, request.evidence_root)

    facts_text = dump_model(facts_document)
    registry_text = dump_model(registry_document)
    # Compare what will be written, not the in-memory models.
    written_facts = FinancialFactsDocument.model_validate_json(facts_text)
    written_registry = SourceRegistryDocument.model_validate_json(registry_text)
    fact_equivalence = _fact_equivalence(raw_facts, json.loads(facts_text))
    source_equivalence, identical_timestamps = _source_equivalence(raw_sources, json.loads(registry_text))
    mismatches = fact_equivalence.mismatches + source_equivalence.mismatches
    if mismatches:
        raise MigrationError("field equivalence failed: " + "; ".join(mismatches))

    try:
        backups = plan_backups(
            (request.facts_output, request.registry_output, request.manifest_output), request.backup_dir, migrated_at
        )
    except StorageError as exc:
        raise MigrationError(str(exc)) from exc
    if any(_sha256(path.read_bytes()) != digest for path, digest in input_hashes.items()):
        raise MigrationError("an input file changed during migration")

    manifest = MigrationManifest(
        finura_version=finura.__version__,
        executed_at=migrated_at,
        company_id=company_id,
        inputs=(
            _file_record("v1_financial_facts", request.facts_input, input_hashes[request.facts_input], 1, len(raw_facts["facts"])),
            _file_record("v1_source_registry", request.registry_input, input_hashes[request.registry_input], 1, len(raw_sources)),
        ),
        outputs=(
            _file_record("v2_financial_facts", request.facts_output, _sha256(facts_text.encode()), 2, len(written_facts.facts)),
            _file_record("v2_source_registry", request.registry_output, _sha256(registry_text.encode()), 2, len(written_registry.sources)),
        ),
        backups=backups,
        validation=ValidationSummary(
            v2_schema_valid=True,
            fact_identities_unique=True,
            source_links_resolved=len(written_facts.facts),
            source_links_same_company=len(written_facts.facts),
            company_identity=company_identity,
            raw_evidence="not_checked" if request.evidence_root is None else "checked",
            evidence_checks=evidence_checks,
        ),
        fact_equivalence=fact_equivalence,
        source_equivalence=source_equivalence,
        source_timestamps_text_identical=identical_timestamps,
        verification_status_counts_v1=dict(Counter(fact["verification_status"] for fact in raw_facts["facts"])),
        verification_status_counts_v2=dict(Counter(fact.verification_status.value for fact in written_facts.facts)),
        fact_provenance_gaps=dict(Counter(gap for fact in written_facts.facts for gap in fact.provenance_gaps)),
        source_provenance_gaps=dict(Counter(gap for source in written_registry.sources for gap in source.provenance_gaps)),
        inputs_unchanged=True,
    )
    try:
        write_files(
            {
                request.facts_output: facts_text,
                request.registry_output: registry_text,
                request.manifest_output: dump_model(manifest),
            },
            backups,
        )
    except StorageError as exc:
        raise MigrationError(str(exc)) from exc
    return manifest


def _check_paths(request: MigrationRequest) -> None:
    for path in (request.facts_input, request.registry_input):
        if not path.is_file():
            raise MigrationError(f"input file not found: {path}")
    inputs = {request.facts_input.resolve(), request.registry_input.resolve()}
    resolved = [path.resolve() for path in (request.facts_output, request.registry_output, request.manifest_output)]
    if len(set(resolved)) != len(resolved):
        raise MigrationError("output paths must be distinct")
    if inputs & set(resolved):
        raise MigrationError("refusing to write over an input file; choose a new output path")


def _lineage(path: Path, digest: str, migrated_at: datetime) -> MigrationLineage:
    return MigrationLineage(
        migration="v1_to_v2", from_schema_version=1, from_path=str(path), from_sha256=digest, migrated_at=migrated_at
    )


def _check_source_links(facts: FinancialFactsDocument, registry: SourceRegistryDocument) -> dict[str, SourceDocument]:
    linked: dict[str, SourceDocument] = {}
    for index, fact in enumerate(facts.facts):
        source = registry.get(fact.source_id)
        if source is None:
            raise MigrationError(f"facts[{index}] cites unregistered source {fact.source_id!r}")
        if source.company_id != fact.company_id:
            raise MigrationError(
                f"facts[{index}] cites source {fact.source_id!r} registered to {source.company_id!r}, "
                f"not {fact.company_id!r}"
            )
        linked[source.source_id] = source
    return linked


def _check_company(company_id: str, registry: CompanyRegistry | None) -> Literal["verified", "unverified", "not_checked"]:
    if registry is None:
        return "not_checked"
    try:
        company = registry.get(company_id)
    except UnknownCompanyError as exc:
        raise MigrationError(f"company {company_id!r} is not in the company registry") from exc
    return "verified" if company.identity.is_verified else "unverified"


def _check_evidence(sources: dict[str, SourceDocument], evidence_root: Path | None) -> tuple[EvidenceCheck, ...]:
    if evidence_root is None:
        return ()
    root = evidence_root.resolve()
    checks = []
    for source_id, source in sorted(sources.items()):
        path = (root / source.local_path).resolve()
        if not path.is_relative_to(root):
            raise MigrationError(f"source {source_id!r} evidence path escapes the evidence root")
        if not path.is_file():
            raise MigrationError(f"source {source_id!r} evidence file not found: {source.local_path}")
        if _sha256(path.read_bytes()) != source.sha256:
            raise MigrationError(f"source {source_id!r} evidence SHA-256 does not match the registry")
        checks.append(EvidenceCheck(source_id=source_id, local_path=source.local_path, result="sha256_match"))
    return tuple(checks)


def _fact_equivalence(raw: dict[str, Any], written: dict[str, Any]) -> EquivalenceResult:
    mismatches = []
    raw_facts, written_facts = raw["facts"], written["facts"]
    if len(raw_facts) != len(written_facts):
        mismatches.append(f"fact count: v1={len(raw_facts)}, v2={len(written_facts)}")
    for index, (old, new) in enumerate(zip(raw_facts, written_facts)):
        expected = [(old_field, old[old_field], new_field) for old_field, new_field in FACT_FIELD_MAP]
        expected += [("company_id (file)", raw["company_id"], "company_id"), ("currency (file)", raw["currency"], "currency")]
        if "company_id" in old:
            expected.append(("company_id", old["company_id"], "company_id"))
        for old_field, old_value, new_field in expected:
            new_value = _lookup(new, new_field)
            # `1 == 1.0` in Python; require the same JSON type as well.
            if old_value != new_value or type(old_value) is not type(new_value):
                mismatches.append(f"facts[{index}].{old_field}: v1={old_value!r}, v2 {new_field}={new_value!r}")
        for field in UNRECORDED_FACT_FIELDS:
            if _lookup(new, field) is not None:
                mismatches.append(f"facts[{index}]: {field} was not recorded in v1 but is set in v2")
    return EquivalenceResult(
        records_compared=len(raw_facts),
        fields_compared=tuple(f"{old}->{new}" for old, new in FACT_FIELD_MAP) + ("company_id(file)->company_id", "currency(file)->currency"),
        unknown_fields_confirmed_absent=UNRECORDED_FACT_FIELDS,
        mismatches=tuple(mismatches),
    )


def _source_equivalence(raw: list[dict[str, Any]], written: dict[str, Any]) -> tuple[EquivalenceResult, int]:
    mismatches = []
    identical_timestamps = 0
    written_sources = written["sources"]
    if len(raw) != len(written_sources):
        mismatches.append(f"source count: v1={len(raw)}, v2={len(written_sources)}")
    for index, (old, new) in enumerate(zip(raw, written_sources)):
        for old_field, new_field in SOURCE_FIELD_MAP:
            old_value, new_value = old.get(old_field), new[new_field]
            if old_value != new_value or type(old_value) is not type(new_value):
                mismatches.append(f"sources[{index}].{old_field}: v1={old_value!r}, v2 {new_field}={new_value!r}")
        old_time, new_time = datetime.fromisoformat(old["retrieved_at"]), datetime.fromisoformat(new["registered_at"])
        if old_time != new_time or old_time.utcoffset() != new_time.utcoffset():
            mismatches.append(f"sources[{index}].retrieved_at: v1={old['retrieved_at']!r}, v2 registered_at={new['registered_at']!r}")
        identical_timestamps += old["retrieved_at"] == new["registered_at"]
        for field in UNRECORDED_SOURCE_FIELDS:
            if new[field] is not None:
                mismatches.append(f"sources[{index}]: {field} was not recorded in v1 but is set in v2")
    return (
        EquivalenceResult(
            records_compared=len(raw),
            fields_compared=tuple(f"{old}->{new}" for old, new in SOURCE_FIELD_MAP) + ("retrieved_at->registered_at",),
            unknown_fields_confirmed_absent=UNRECORDED_SOURCE_FIELDS,
            mismatches=tuple(mismatches),
        ),
        identical_timestamps,
    )


def _file_record(
    role: Literal["v1_financial_facts", "v1_source_registry", "v2_financial_facts", "v2_source_registry"],
    path: Path,
    digest: str,
    schema_version: Literal[1, 2],
    record_count: int,
) -> FileRecord:
    return FileRecord(role=role, path=str(path), sha256=digest, schema_version=schema_version, record_count=record_count)


def _lookup(record: dict[str, Any], dotted: str) -> Any:
    value: Any = record
    for part in dotted.split("."):
        value = value[part]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate a v1 facts file and source registry to v2.")
    parser.add_argument("--facts", type=Path, required=True, help="v1 financial_facts.json")
    parser.add_argument("--registry", type=Path, required=True, help="v1 source_registry.json")
    parser.add_argument("--facts-out", type=Path, required=True)
    parser.add_argument("--registry-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, help="directory registry local_path values are relative to")
    parser.add_argument("--company-registry", type=Path, help="v1 company registry JSON to check identity against")
    parser.add_argument("--backup-dir", type=Path, help="required to replace existing outputs")
    args = parser.parse_args(argv)
    try:
        companies = RegistryFileCompanies.load(args.company_registry) if args.company_registry else None
        manifest = migrate_v1_to_v2(
            MigrationRequest(
                facts_input=args.facts,
                registry_input=args.registry,
                facts_output=args.facts_out,
                registry_output=args.registry_out,
                manifest_output=args.manifest_out,
                evidence_root=args.evidence_root,
                company_registry=companies,
                backup_dir=args.backup_dir,
            ),
            migrated_at=datetime.now(UTC),
        )
    except (MigrationError, SchemaLoadError) as exc:
        print(f"Migration refused: {exc}", file=sys.stderr)
        return 1
    print(
        f"Migrated {manifest.company_id}: {manifest.outputs[0].record_count} facts, "
        f"{manifest.outputs[1].record_count} sources; equivalence mismatches: 0; "
        f"company identity: {manifest.validation.company_identity}; raw evidence: {manifest.validation.raw_evidence}"
    )
    print(f"Manifest: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
