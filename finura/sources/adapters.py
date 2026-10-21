"""Source-adapter contract and the PSX listing adapter.

An adapter names a publisher, the access policy that governs it, and the
entry point it retrieves. Retrieval goes through `Fetcher`, which enforces
the recorded access policy; parsing is separate and offline.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from finura.schemas.types import HttpUrl, Identifier, NonEmptyStr
from finura.sources.fetch import FetchedArtifact, Fetcher


class AdapterDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: Identifier
    publisher: NonEmptyStr
    access_policy_id: Identifier
    entry_url: HttpUrl
    description: NonEmptyStr


class SourceAdapter(Protocol):
    @property
    def descriptor(self) -> AdapterDescriptor: ...

    def retrieve(self, fetcher: Fetcher) -> FetchedArtifact:
        """Fetch the adapter's entry point. Raises `AccessNotPermittedError`
        unless the access policy permits automated access."""
        ...


class PsxListingAdapter:
    """PSX listed-companies information.

    PSX's terms prohibit automated retrieval without written permission
    (`config/access_policies.json`, policy `psx`), so `retrieve` is refused
    by the fetcher until that policy records permission. No parser for PSX's
    own page format exists, because the format has not been inspected under
    permitted access. Listing evidence from PSX enters through manually
    downloaded notices and `finura.sources.transcription`.
    """

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="psx_listings",
        publisher="Pakistan Stock Exchange Limited",
        access_policy_id="psx",
        entry_url="https://www.psx.com.pk/psx/resources-and-tools/listings/listed-companies",
        description="PSX listed-companies lookup; automated access requires PSX's written permission.",
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def retrieve(self, fetcher: Fetcher) -> FetchedArtifact:
        policy = fetcher.policies.policy_for(self._DESCRIPTOR.entry_url)
        if policy is None or policy.policy_id != self._DESCRIPTOR.access_policy_id:
            raise LookupError(f"access policy {self._DESCRIPTOR.access_policy_id!r} does not cover the entry URL")
        return fetcher.fetch(self._DESCRIPTOR.entry_url)
