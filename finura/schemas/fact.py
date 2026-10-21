"""Canonical financial-fact record and its identity key."""

from collections import Counter
from collections.abc import Iterable
from datetime import date
from typing import Final, Literal, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, model_validator

from .enums import ExtractionMethod, FactClassification, PeriodType, Scope, Unit, VerificationStatus
from .types import AwareTimestamp, CompanyId, ConceptId, CurrencyCode, FiniteNumber, Identifier, IsoDate, NonEmptyStr

FACT_SCHEMA_VERSION: Final = 2


class ReportingPeriod(BaseModel):
    """The period a fact describes. `start` is `None` when not recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    end: IsoDate
    type: PeriodType
    start: IsoDate | None = None

    @model_validator(mode="after")
    def _start_precedes_end(self) -> Self:
        if self.start is not None and self.start > self.end:
            raise ValueError(f"period start {self.start} is after period end {self.end}")
        return self


class FactIdentity(NamedTuple):
    """Uniqueness key for a fact.

    v1 documents `metric + scope + period_end + period_type + unit` within a
    single-company file; v2 adds `company_id` because each fact carries its
    company. Two facts with the same identity are a conflict even if their
    values agree.
    """

    company_id: str
    concept: str
    scope: Scope
    period_end: date
    period_type: PeriodType
    unit: Unit


class DuplicateFactIdentityError(ValueError):
    """Raised when facts share an identity key."""

    def __init__(self, duplicates: dict[FactIdentity, int]):
        self.duplicates = duplicates
        listed = "; ".join(f"{identity} x{count}" for identity, count in duplicates.items())
        super().__init__(f"duplicate fact identities: {listed}")


class FinancialFact(BaseModel):
    """A single numeric financial value with its provenance.

    Optional provenance fields are `None` when not recorded; see
    `provenance_gaps`. Verification fields are only expected for `verified`
    facts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = FACT_SCHEMA_VERSION
    company_id: CompanyId
    concept: ConceptId
    value: FiniteNumber
    unit: Unit
    currency: CurrencyCode
    period: ReportingPeriod
    scope: Scope
    source_id: Identifier
    source_location: NonEmptyStr | None = None
    classification: FactClassification
    verification_status: VerificationStatus
    verified_by: NonEmptyStr | None = None
    verified_at: AwareTimestamp | None = None
    verification_evidence: NonEmptyStr | None = None
    extraction_method: ExtractionMethod | None = None
    extracted_at: AwareTimestamp | None = None

    @model_validator(mode="after")
    def _currency_matches_unit(self) -> Self:
        if self.currency != self.unit.currency:
            raise ValueError(f"currency {self.currency!r} does not match unit {self.unit.value!r}")
        return self

    @model_validator(mode="after")
    def _missing_is_not_a_value(self) -> Self:
        # A fact must hold a real number; recording "missing" with a value
        # would turn an absent figure into a fabricated one (often zero).
        if (
            self.classification is FactClassification.MISSING
            or self.verification_status is VerificationStatus.MISSING
        ):
            raise ValueError("a missing value is a data gap, not a fact; it cannot carry a numeric value")
        return self

    @model_validator(mode="after")
    def _provenance_is_consistent(self) -> Self:
        attested = (self.verified_by, self.verified_at, self.verification_evidence)
        if self.verification_status is not VerificationStatus.VERIFIED and any(item is not None for item in attested):
            raise ValueError(
                f"verification details recorded for a fact with status {self.verification_status.value!r}"
            )
        if self.extracted_at is not None and self.extraction_method is None:
            raise ValueError("extracted_at is recorded without an extraction_method")
        return self

    @property
    def identity(self) -> FactIdentity:
        return FactIdentity(
            self.company_id, self.concept, self.scope, self.period.end, self.period.type, self.unit
        )

    @property
    def provenance_gaps(self) -> tuple[str, ...]:
        """Names of provenance fields that were not recorded."""
        candidates = {
            "period.start": self.period.start,
            "source_location": self.source_location,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at,
        }
        if self.verification_status is VerificationStatus.VERIFIED:
            candidates |= {
                "verified_by": self.verified_by,
                "verified_at": self.verified_at,
                "verification_evidence": self.verification_evidence,
            }
        return tuple(name for name, value in candidates.items() if value is None)


def find_duplicate_identities(facts: Iterable[FinancialFact]) -> dict[FactIdentity, int]:
    counts = Counter(fact.identity for fact in facts)
    return {identity: count for identity, count in counts.items() if count > 1}


def ensure_unique_identities(facts: Iterable[FinancialFact]) -> None:
    duplicates = find_duplicate_identities(facts)
    if duplicates:
        raise DuplicateFactIdentityError(duplicates)
