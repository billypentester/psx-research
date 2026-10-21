"""Company registry: the only place company identity is resolved.

Callers depend on the `CompanyRegistry` protocol. `RegistryFileCompanies` is
the JSON-file implementation; another backend (for example one fed by a PSX
listings adapter) can replace it without changing callers.
"""

from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from finura.schemas.company import Company, SymbolPeriod
from finura.schemas.io import load_model


class UnknownCompanyError(LookupError):
    """No company matches the requested identifier or symbol."""


class CompanyRegistry(Protocol):
    def get(self, company_id: str) -> Company: ...

    def resolve_symbol(self, symbol: str, on: date) -> Company: ...

    def companies(self) -> tuple[Company, ...]: ...


class CompanyRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_type: Literal["company_registry"] = "company_registry"
    companies: tuple[Company, ...]

    @model_validator(mode="after")
    def _identities_are_unambiguous(self) -> Self:
        seen: set[str] = set()
        for company in self.companies:
            if company.company_id in seen:
                raise ValueError(f"duplicate company_id {company.company_id!r}")
            seen.add(company.company_id)
        # A symbol may be reused after a delisting, but never by two
        # companies over overlapping dates.
        for first, second in combinations(self.companies, 2):
            for a in first.symbols:
                for b in second.symbols:
                    if a.symbol == b.symbol and _overlaps(a, b):
                        raise ValueError(
                            f"symbol {a.symbol!r} is assigned to both {first.company_id!r} "
                            f"and {second.company_id!r} over overlapping dates"
                        )
        return self


class RegistryFileCompanies:
    """Read-only `CompanyRegistry` backed by a validated registry document."""

    def __init__(self, document: CompanyRegistryDocument):
        self._document = document
        self._by_id = {company.company_id: company for company in document.companies}

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls(load_model(path, CompanyRegistryDocument))

    def get(self, company_id: str) -> Company:
        try:
            return self._by_id[company_id]
        except KeyError:
            raise UnknownCompanyError(f"no company with company_id {company_id!r}") from None

    def resolve_symbol(self, symbol: str, on: date) -> Company:
        # The document validator guarantees at most one match.
        for company in self._document.companies:
            if company.symbol_on(on) == symbol:
                return company
        raise UnknownCompanyError(f"no company listed as {symbol!r} on {on.isoformat()}")

    def companies(self) -> tuple[Company, ...]:
        return self._document.companies


def _overlaps(a: SymbolPeriod, b: SymbolPeriod) -> bool:
    a_before_b = a.valid_to is not None and b.valid_from is not None and a.valid_to <= b.valid_from
    b_before_a = b.valid_to is not None and a.valid_from is not None and b.valid_to <= a.valid_from
    return not (a_before_b or b_before_a)
