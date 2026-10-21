"""Read-only loaders for the v1 JSON files written by `pipeline/`.

v1 files have no `schema_version`; they are identified by location and
shape. Each loader parses the file into a strict v1 mirror model (unknown
fields are rejected, not dropped) and then maps it to the canonical v2
model. Both are returned so callers can prove the mapping preserved the
original values. Loaders never write.

The field-by-field v1 -> v2 mapping is documented in docs/DATA_SCHEMA.md
("Canonical v2 schema"). No v2 field is inferred from content; anything
v1 does not record is `None` and reported by `provenance_gaps`.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .enums import FactClassification, PeriodType, RetrievalMethod, Scope, SourceType, Unit, VerificationStatus
from .fact import FinancialFact, ReportingPeriod, ensure_unique_identities
from .io import SchemaLoadError, read_json, validate_model
from .source import SourceDocument
from .types import AwareTimestamp, FiniteNumber, IsoDate, NonEmptyStr, Sha256


class V1SourceRecord(BaseModel):
    """One entry of the v1 source registry, exactly as stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: NonEmptyStr
    company_id: NonEmptyStr
    source_type: SourceType
    title: NonEmptyStr
    url: NonEmptyStr | None = None
    published_at: IsoDate | None = None
    retrieved_at: AwareTimestamp
    local_path: NonEmptyStr
    sha256: Sha256
    page_number: int | None = Field(default=None, strict=True)
    notes: str | None = None
    provider: str | None = None
    retrieval_method: RetrievalMethod | None = None
    http_status: int | None = Field(default=None, strict=True)
    content_type: str | None = None


class V1FinancialFact(BaseModel):
    """One v1 fact record, exactly as stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: NonEmptyStr
    scope: Scope
    period_end: IsoDate
    period_type: PeriodType
    value: FiniteNumber
    unit: Unit
    source_id: NonEmptyStr
    source_page: NonEmptyStr
    verification_status: VerificationStatus
    fact_classification: FactClassification
    # Written per fact by pipeline/normalize_external.py; optional in v1.
    company_id: NonEmptyStr | None = None


class V1FinancialFactsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: NonEmptyStr
    currency: NonEmptyStr
    facts: list[V1FinancialFact]


@dataclass(frozen=True)
class LoadedSourceRegistry:
    path: Path
    records: tuple[V1SourceRecord, ...]
    documents: tuple[SourceDocument, ...]


@dataclass(frozen=True)
class LoadedFinancialFacts:
    path: Path
    file: V1FinancialFactsFile
    # Aligned with `file.facts`: facts[i] is the v2 form of file.facts[i].
    facts: tuple[FinancialFact, ...]


def source_document_from_v1(record: V1SourceRecord) -> SourceDocument:
    return SourceDocument(
        source_id=record.source_id,
        company_id=record.company_id,
        source_type=record.source_type,
        title=record.title,
        canonical_url=record.url,
        published_at=record.published_at,
        registered_at=record.retrieved_at,
        retrieved_at=None,
        local_path=record.local_path,
        sha256=record.sha256,
        page_number=record.page_number,
        notes=record.notes,
        provider=record.provider,
        retrieval_method=record.retrieval_method,
        http_status=record.http_status,
        content_type=record.content_type,
    )


def financial_fact_from_v1(record: V1FinancialFact, *, company_id: str, currency: str) -> FinancialFact:
    if record.company_id is not None and record.company_id != company_id:
        raise ValueError(
            f"fact company_id {record.company_id!r} differs from file company_id {company_id!r}"
        )
    return FinancialFact(
        company_id=company_id,
        concept=record.metric,
        value=record.value,
        unit=record.unit,
        currency=currency,
        period=ReportingPeriod(end=record.period_end, type=record.period_type),
        scope=record.scope,
        source_id=record.source_id,
        source_location=record.source_page,
        classification=record.fact_classification,
        verification_status=record.verification_status,
    )


def load_v1_source_registry(path: Path) -> LoadedSourceRegistry:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise SchemaLoadError(path, "v1 source registry must be a JSON array")
    records = tuple(validate_model(path, f"[{index}]", V1SourceRecord, item) for index, item in enumerate(payload))
    documents = tuple(
        _convert(path, f"[{index}]", source_document_from_v1, record) for index, record in enumerate(records)
    )
    counts = Counter(document.source_id for document in documents)
    duplicate_ids = sorted(source_id for source_id, count in counts.items() if count > 1)
    if duplicate_ids:
        raise SchemaLoadError(path, f"duplicate source_id values: {duplicate_ids}")
    return LoadedSourceRegistry(path=path, records=records, documents=documents)


def load_v1_financial_facts(path: Path) -> LoadedFinancialFacts:
    file = validate_model(path, "", V1FinancialFactsFile, read_json(path))
    facts = tuple(
        _convert(
            path,
            f"facts[{index}]",
            lambda record: financial_fact_from_v1(record, company_id=file.company_id, currency=file.currency),
            record,
        )
        for index, record in enumerate(file.facts)
    )
    try:
        ensure_unique_identities(facts)
    except ValueError as exc:
        raise SchemaLoadError(path, str(exc)) from exc
    return LoadedFinancialFacts(path=path, file=file, facts=facts)


def _convert[R, T](path: Path, location: str, convert: Callable[[R], T], record: R) -> T:
    try:
        return convert(record)
    except (ValidationError, ValueError) as exc:
        raise SchemaLoadError(path, f"{location} cannot be mapped to v2: {exc}") from exc
