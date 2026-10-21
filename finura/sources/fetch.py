"""Policy-gated HTTP retrieval with timeouts, bounded retries, and pacing.

Network I/O lives behind the `Transport` protocol so that everything above it
(policy checks, retries, pacing, parsing) is tested offline with a fake
transport. The fetcher returns bytes and metadata only; it never parses,
validates, registers, or verifies anything.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from finura.sources.access import AccessPolicy, AccessPolicySet

USER_AGENT = "finura/0.1 (evidence-first PSX research; contact: repository owner)"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchError(Exception):
    """Base class for retrieval failures."""

    def __init__(self, url: str, detail: str):
        self.url = url
        super().__init__(f"{url}: {detail}")


class FetchTimeoutError(FetchError):
    """The request did not complete within the timeout."""


class NetworkError(FetchError):
    """The connection failed before an HTTP response was received."""


class HttpStatusError(FetchError):
    def __init__(self, url: str, status: int):
        self.status = status
        super().__init__(url, f"HTTP {status}")


class ResponseTooLargeError(FetchError):
    """The response exceeded the configured size limit."""


class RedirectError(FetchError):
    """A redirect was malformed or the redirect limit was exceeded."""


class RetriesExhaustedError(FetchError):
    def __init__(self, url: str, attempts: int, last_error: FetchError):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(url, f"gave up after {attempts} attempts; last error: {last_error}")


@dataclass(frozen=True)
class TransportResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def send(self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int) -> TransportResponse:
        """Perform one GET without following redirects. Raise `FetchTimeoutError`
        or `NetworkError`; return non-2xx responses (including 3xx) rather than
        raising."""
        ...


class _DoNotFollowRedirects(HTTPRedirectHandler):
    # Returning None makes urllib surface the 3xx as an HTTPError, so the
    # fetcher can check the destination's policy before any request to it.
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class UrllibTransport:
    """Standard-library transport used for real network access. Never follows redirects."""

    def send(self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int) -> TransportResponse:
        request = Request(url, headers=dict(headers))
        opener = build_opener(_DoNotFollowRedirects)
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
                return TransportResponse(response.geturl(), response.status, dict(response.headers), body)
        except HTTPError as exc:
            return TransportResponse(url, exc.code, dict(exc.headers or {}), b"")
        except TimeoutError as exc:
            raise FetchTimeoutError(url, f"timed out after {timeout}s") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise FetchTimeoutError(url, f"timed out after {timeout}s") from exc
            raise NetworkError(url, str(exc.reason)) from exc
        except (HTTPException, OSError) as exc:
            raise NetworkError(url, str(exc)) from exc


@dataclass(frozen=True)
class FetchedArtifact:
    """Raw bytes and retrieval metadata. Not yet registered or validated."""

    requested_url: str
    final_url: str
    status: int
    content_type: str | None
    body: bytes
    retrieved_at: datetime
    policy_id: str
    attempts: int


@dataclass
class Fetcher:
    """Fetch URLs that a recorded access policy allows, politely.

    - Refuses any URL whose host lacks a policy permitting automated access,
      before any network request.
    - Follows at most `max_redirects` redirects, checking each destination's
      policy before requesting it.
    - Waits at least the policy's minimum interval between requests to a host.
    - Retries timeouts, connection failures, 429 and 5xx up to `max_attempts`
      with exponential backoff; other 4xx fail immediately.
    """

    policies: AccessPolicySet
    transport: Transport = field(default_factory=UrllibTransport)
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    backoff_seconds: float = 2.0
    max_bytes: int = 25 * 1024 * 1024
    max_redirects: int = 5
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_request: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.timeout_seconds <= 0 or self.max_bytes < 1 or self.max_redirects < 0:
            raise ValueError("max_attempts, timeout_seconds, and max_bytes must be positive; max_redirects >= 0")

    def fetch(self, url: str) -> FetchedArtifact:
        current = url
        for _ in range(self.max_redirects + 1):
            policy = self._permitted(current)
            response, attempts = self._get(current, policy.min_request_interval_seconds)
            if response.status not in REDIRECT_STATUSES:
                return FetchedArtifact(
                    requested_url=url,
                    final_url=current,
                    status=response.status,
                    content_type=_header(response.headers, "Content-Type"),
                    body=response.body,
                    retrieved_at=self.clock(),
                    policy_id=policy.policy_id,
                    attempts=attempts,
                )
            location = _header(response.headers, "Location")
            if not location:
                raise RedirectError(current, f"HTTP {response.status} without a Location header")
            current = urljoin(current, location)
        raise RedirectError(url, f"more than {self.max_redirects} redirects")

    def _permitted(self, url: str) -> AccessPolicy:
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError(f"only http(s) URLs can be fetched: {url!r}")
        return self.policies.require_automated_access(url)

    def _get(self, url: str, interval: float) -> tuple[TransportResponse, int]:
        """One URL with retries; returns a 2xx or 3xx response and the attempt count."""
        host = (urlparse(url).hostname or "").lower()
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        last_error: FetchError | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace(host, interval)
            try:
                response = self.transport.send(url, headers=headers, timeout=self.timeout_seconds, max_bytes=self.max_bytes)
            except (FetchTimeoutError, NetworkError) as exc:
                last_error = exc
            else:
                if len(response.body) > self.max_bytes:
                    raise ResponseTooLargeError(url, f"response exceeds {self.max_bytes} bytes")
                if response.url != url:
                    raise FetchError(url, f"transport followed a redirect to {response.url}; refusing its content")
                if 200 <= response.status < 300 or response.status in REDIRECT_STATUSES:
                    return response, attempt
                if response.status not in RETRYABLE_STATUSES:
                    raise HttpStatusError(url, response.status)
                last_error = HttpStatusError(url, response.status)
            if attempt < self.max_attempts:
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        if last_error is None:  # unreachable: every failed attempt records its error
            raise RuntimeError("retry loop ended without an error")
        raise RetriesExhaustedError(url, self.max_attempts, last_error)

    def _pace(self, host: str, interval: float) -> None:
        previous = self._last_request.get(host)
        if previous is not None:
            wait = interval - (self.monotonic() - previous)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.monotonic()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)
