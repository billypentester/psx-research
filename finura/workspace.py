"""Company- and run-scoped artifact paths.

Every company-specific path is derived from a verified `Company` and, for run
outputs, a run identifier. Paths use the stable `company_id`, never the
current listing symbol, so a ticker change does not move or split a
company's evidence.
"""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from finura.schemas.company import Company

_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


class UnverifiedCompanyError(ValueError):
    """A company-scoped path was requested for a company whose identity is unverified."""


def new_run_id(started_at: datetime) -> str:
    """Return a sortable, collision-resistant run identifier, e.g. `20261021T181500Z-1a2b3c4d`."""
    if started_at.tzinfo is None:
        raise ValueError("run start time must be timezone-aware")
    return f"{started_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class Workspace:
    root: Path

    def raw_dir(self, company: Company) -> Path:
        return self.root / "data" / "raw" / _verified_id(company)

    def normalized_dir(self, company: Company) -> Path:
        return self.root / "data" / "normalized" / _verified_id(company)

    def run_dir(self, company: Company, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError(f"invalid run id {run_id!r}")
        return self.root / "runs" / _verified_id(company) / run_id


def _verified_id(company: Company) -> str:
    if not company.identity.is_verified:
        raise UnverifiedCompanyError(f"company {company.company_id!r} identity is not verified")
    return company.company_id
