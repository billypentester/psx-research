"""Canonical Finura record schemas and read-only v1 loaders."""

from .company import (
    COMPANY_SCHEMA_VERSION,
    Attestation,
    Company,
    SectorClassification,
    SymbolPeriod,
)
from .provenance import EvidenceReference
from .documents import FinancialFactsDocument, MigrationLineage, SourceRegistryDocument
from .enums import (
    AttestationState,
    ExtractionMethod,
    FactClassification,
    ListingStatus,
    PeriodType,
    RetrievalMethod,
    Scope,
    SourceType,
    Unit,
    VerificationStatus,
)
from .fact import (
    FACT_SCHEMA_VERSION,
    DuplicateFactIdentityError,
    FactIdentity,
    FinancialFact,
    ReportingPeriod,
    ensure_unique_identities,
    find_duplicate_identities,
)
from .io import SchemaLoadError
from .source import SOURCE_SCHEMA_VERSION, SourceDocument
from .v1 import (
    LoadedFinancialFacts,
    LoadedSourceRegistry,
    load_v1_financial_facts,
    load_v1_source_registry,
)

__all__ = [
    "COMPANY_SCHEMA_VERSION",
    "FACT_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "Attestation",
    "AttestationState",
    "Company",
    "DuplicateFactIdentityError",
    "EvidenceReference",
    "ExtractionMethod",
    "FactClassification",
    "FactIdentity",
    "FinancialFact",
    "FinancialFactsDocument",
    "ListingStatus",
    "LoadedFinancialFacts",
    "LoadedSourceRegistry",
    "MigrationLineage",
    "PeriodType",
    "ReportingPeriod",
    "RetrievalMethod",
    "SchemaLoadError",
    "Scope",
    "SectorClassification",
    "SourceDocument",
    "SourceRegistryDocument",
    "SourceType",
    "SymbolPeriod",
    "Unit",
    "VerificationStatus",
    "ensure_unique_identities",
    "find_duplicate_identities",
    "load_v1_financial_facts",
    "load_v1_source_registry",
]
