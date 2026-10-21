"""Recorded terms reviews that decide whether a host may be fetched automatically.

An access policy is a human review of a site's published terms, with the
clauses that support its conclusion. Finura does not interpret robots.txt or
terms text itself: absent a policy that records automated access as
permitted, every automated fetch is refused.
"""

from enum import StrEnum
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from finura.schemas.io import load_model
from finura.schemas.types import AwareTimestamp, HttpUrl, Identifier, NonEmptyStr

# Lowercase DNS names without a trailing dot, e.g. "www.example.com".
HostName = Annotated[
    str,
    StringConstraints(strict=True, max_length=253, pattern=r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$"),
]


class AutomatedAccess(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    # Reviewed, but the terms are silent, ambiguous, or could not be read.
    UNCLEAR = "unclear"
    PROHIBITED = "prohibited"
    PERMITTED = "permitted"
    # The terms prohibit it, but the publisher granted written permission.
    WRITTEN_PERMISSION = "written_permission"


class AccessNotPermittedError(PermissionError):
    """Automated access to a URL is not allowed by any recorded policy."""


class TermsClause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    terms_url: HttpUrl
    # A short verbatim quotation from the terms.
    quote: NonEmptyStr


class AccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: Identifier
    publisher: NonEmptyStr
    # Exact hostnames covered.
    hosts: tuple[HostName, ...] = ()
    # Domains covered together with every subdomain, matched on label
    # boundaries: "example.com" covers "a.example.com" but not "notexample.com".
    domains: tuple[HostName, ...] = ()
    automated_access: AutomatedAccess
    reviewed_by: NonEmptyStr
    reviewed_at: AwareTimestamp
    clauses: tuple[TermsClause, ...] = ()
    # Reference to the permission letter or licence; required for written_permission.
    permission_reference: NonEmptyStr | None = None
    min_request_interval_seconds: float = Field(default=2.0, ge=0)
    notes: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _covers_something(self) -> Self:
        if not self.hosts and not self.domains:
            raise ValueError(f"policy {self.policy_id}: list at least one host or domain")
        return self

    def covers(self, host: str) -> bool:
        return host in self.hosts or any(_within(host, domain) for domain in self.domains)

    @model_validator(mode="after")
    def _conclusion_is_supported(self) -> Self:
        if self.automated_access in {AutomatedAccess.PROHIBITED, AutomatedAccess.PERMITTED} and not self.clauses:
            raise ValueError(f"policy {self.policy_id}: a {self.automated_access.value} conclusion must quote the terms")
        if self.automated_access is AutomatedAccess.UNCLEAR and self.notes is None:
            raise ValueError(f"policy {self.policy_id}: an unclear conclusion must explain what is missing in notes")
        if (self.automated_access is AutomatedAccess.WRITTEN_PERMISSION) != (self.permission_reference is not None):
            raise ValueError(f"policy {self.policy_id}: permission_reference is required only for written_permission")
        return self

    @property
    def allows_automated_access(self) -> bool:
        return self.automated_access in {AutomatedAccess.PERMITTED, AutomatedAccess.WRITTEN_PERMISSION}


class AccessPolicySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    record_type: Literal["access_policies"] = "access_policies"
    policies: tuple[AccessPolicy, ...]

    @model_validator(mode="after")
    def _coverage_is_unambiguous(self) -> Self:
        # No host may fall under two policies, so a narrower "permitted"
        # entry can never override a broader "prohibited" one.
        for a, b in (*combinations(self.policies, 2), *((b, a) for a, b in combinations(self.policies, 2))):
            for name in a.hosts:
                if b.covers(name):
                    raise ValueError(f"host {name!r} is covered by both {a.policy_id!r} and {b.policy_id!r}")
            for domain in a.domains:
                if b.covers(domain) or any(_within(name, domain) for name in (*b.hosts, *b.domains)):
                    raise ValueError(f"domain {domain!r} overlaps policies {a.policy_id!r} and {b.policy_id!r}")
        return self

    def policy_for(self, url: str) -> AccessPolicy | None:
        """The policy covering the URL's host, if any. Hostless URLs match nothing."""
        host = normalize_host(url)
        if host is None:
            return None
        return next((policy for policy in self.policies if policy.covers(host)), None)

    def require_automated_access(self, url: str) -> AccessPolicy:
        policy = self.policy_for(url)
        if policy is None:
            raise AccessNotPermittedError(f"no recorded access policy covers {url}")
        if not policy.allows_automated_access:
            raise AccessNotPermittedError(
                f"automated access to {url} is {policy.automated_access.value} under policy {policy.policy_id!r}"
            )
        return policy


def load_access_policies(path: Path) -> AccessPolicySet:
    return load_model(path, AccessPolicySet)


def normalize_host(url: str) -> str | None:
    """Lowercase host of a URL without a trailing dot, or None if it has none."""
    host = urlparse(url).hostname
    if not host:
        return None
    return host.rstrip(".").lower() or None


def _within(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)
