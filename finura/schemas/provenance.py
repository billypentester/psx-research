"""Shared provenance references."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from .types import HttpUrl, Identifier, NonEmptyStr


class EvidenceReference(BaseModel):
    """Where a claim can be checked: a registered source, a URL, or both."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: NonEmptyStr
    source_id: Identifier | None = None
    url: HttpUrl | None = None

    @model_validator(mode="after")
    def _points_somewhere(self) -> Self:
        if self.source_id is None and self.url is None:
            raise ValueError("evidence needs a source_id or a url")
        return self
