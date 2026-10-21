"""Versioned v2 file documents: one company's facts, and the source registry.

Facts and sources live in separate documents. A facts document belongs to
exactly one company; the source registry is shared across companies.
"""

from collections import Counter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from .fact import FinancialFact, ensure_unique_identities
from .source import SourceDocument
from .types import AwareTimestamp, CompanyId, NonEmptyStr, Sha256


class MigrationLineage(BaseModel):
    """Which legacy file a document was migrated from, and when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    migration: Literal["v1_to_v2"]
    from_schema_version: Literal[1]
    from_path: NonEmptyStr
    from_sha256: Sha256
    migrated_at: AwareTimestamp


class FinancialFactsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    record_type: Literal["financial_facts"] = "financial_facts"
    company_id: CompanyId
    facts: tuple[FinancialFact, ...]
    lineage: MigrationLineage | None = None

    @model_validator(mode="after")
    def _facts_belong_to_company(self) -> Self:
        foreign = sorted({fact.company_id for fact in self.facts} - {self.company_id})
        if foreign:
            raise ValueError(f"facts for other companies {foreign} in document for {self.company_id!r}")
        ensure_unique_identities(self.facts)
        return self


class SourceRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    record_type: Literal["source_registry"] = "source_registry"
    sources: tuple[SourceDocument, ...]
    lineage: MigrationLineage | None = None

    @model_validator(mode="after")
    def _source_ids_are_unique(self) -> Self:
        counts = Counter(source.source_id for source in self.sources)
        duplicates = sorted(source_id for source_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate source_id values: {duplicates}")
        return self

    def get(self, source_id: str) -> SourceDocument | None:
        return next((source for source in self.sources if source.source_id == source_id), None)
