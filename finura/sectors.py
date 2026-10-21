"""Sector profiles, selected from a company's verified classification.

Profiles are configuration (`config/sector_profiles.json`), not code paths
keyed by company. A profile is chosen only when the company's sector
classification has been verified; an unverified or missing classification is
an error the caller must surface, never a silent fallback to a default
sector.
"""

from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finura.schemas.company import Company
from finura.schemas.io import load_model
from finura.schemas.types import NonEmptyStr, SectorKey


class StatementModel(StrEnum):
    """Shape of a company's primary statements.

    Banks report mark-up/interest income, deposits, and advances instead of
    turnover, cost of sales, and gross profit, so validation and analysis
    must not assume one statement structure for every sector.
    """

    GENERAL = "general"
    BANKING = "banking"


class SectorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: SectorKey
    title: NonEmptyStr
    sector_keys: tuple[SectorKey, ...] = Field(min_length=1)
    statement_model: StatementModel


class SectorProfileSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_type: Literal["sector_profiles"] = "sector_profiles"
    profiles: tuple[SectorProfile, ...]

    @model_validator(mode="after")
    def _mapping_is_unambiguous(self) -> Self:
        ids = Counter(profile.profile_id for profile in self.profiles)
        duplicate_ids = sorted(profile_id for profile_id, count in ids.items() if count > 1)
        if duplicate_ids:
            raise ValueError(f"duplicate profile_id values: {duplicate_ids}")
        keys = Counter(key for profile in self.profiles for key in profile.sector_keys)
        shared_keys = sorted(key for key, count in keys.items() if count > 1)
        if shared_keys:
            raise ValueError(f"sector keys mapped to more than one profile: {shared_keys}")
        return self


class SectorProfileSelectionError(LookupError):
    """No sector profile can be selected for a company."""


def load_sector_profiles(path: Path) -> SectorProfileSet:
    return load_model(path, SectorProfileSet)


def select_sector_profile(company: Company, profiles: SectorProfileSet) -> SectorProfile:
    classification = company.classification
    if classification is None:
        raise SectorProfileSelectionError(f"{company.company_id}: no sector classification recorded")
    if not classification.attestation.is_verified:
        raise SectorProfileSelectionError(
            f"{company.company_id}: sector classification {classification.sector_key!r} is not verified"
        )
    for profile in profiles.profiles:
        if classification.sector_key in profile.sector_keys:
            return profile
    raise SectorProfileSelectionError(
        f"{company.company_id}: no sector profile covers sector {classification.sector_key!r}"
    )
