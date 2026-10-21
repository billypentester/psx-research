"""Access policies, the policy-gated fetcher, and the PSX listing adapter.

Network behaviour is simulated with a fake transport. The single live test
runs only when FINURA_LIVE_TESTS=1.
"""

import json
import os
import threading
import unittest
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pydantic import ValidationError

from finura.sources.access import AccessNotPermittedError, AccessPolicy, AccessPolicySet, load_access_policies
from finura.sources.adapters import PsxListingAdapter
from finura.sources.fetch import (
    Fetcher,
    FetchError,
    FetchTimeoutError,
    HttpStatusError,
    NetworkError,
    RedirectError,
    ResponseTooLargeError,
    RetriesExhaustedError,
    TransportResponse,
    UrllibTransport,
)

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_AT = "2026-10-21T19:30:00+00:00"
CLAUSE = [{"terms_url": "https://example.com/terms", "quote": "automated access is permitted"}]


def policy(**overrides):
    payload = {
        "policy_id": "example",
        "publisher": "Example Publisher",
        "hosts": ["example.com"],
        "automated_access": "permitted",
        "reviewed_by": "reviewer",
        "reviewed_at": REVIEWED_AT,
        "clauses": CLAUSE,
        "min_request_interval_seconds": 5.0,
    }
    payload.update(overrides)
    return payload


def policy_set(*policies):
    return AccessPolicySet.model_validate({"policies": list(policies) or [policy()]})


class FakeTransport:
    """Replays scripted outcomes: a TransportResponse or an exception to raise."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def send(self, url, *, headers, timeout, max_bytes):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def ok(url="https://example.com/a", body=b"payload", content_type="text/html"):
    return TransportResponse(url, 200, {"Content-Type": content_type}, body)


def redirect(url, location, status=302):
    return TransportResponse(url, status, {"Location": location}, b"")


def fetcher(transport, policies=None, **overrides):
    clock = FakeClock()
    instance = Fetcher(
        policies=policies or policy_set(),
        transport=transport,
        clock=lambda: datetime(2026, 10, 21, 20, 0, tzinfo=UTC),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        **overrides,
    )
    return instance, clock


class TestAccessPolicies(unittest.TestCase):
    def test_shipped_psx_policy_prohibits_automated_access(self):
        policies = load_access_policies(ROOT / "config/access_policies.json")
        psx = policies.policy_for("https://dps.psx.com.pk/listings")
        self.assertEqual(psx.policy_id, "psx")
        self.assertFalse(psx.allows_automated_access)
        self.assertTrue(all(clause.quote for clause in psx.clauses))
        with self.assertRaises(AccessNotPermittedError):
            policies.require_automated_access("https://www.psx.com.pk/psx/resources-and-tools/listings/listed-companies")

    def test_unlisted_hosts_are_refused(self):
        with self.assertRaisesRegex(AccessNotPermittedError, "no recorded access policy"):
            policy_set().require_automated_access("https://other.example.org/")

    def test_subdomains_are_not_covered_implicitly(self):
        self.assertIsNone(policy_set().policy_for("https://data.example.com/"))

    def test_conclusions_must_quote_terms(self):
        with self.assertRaises(ValidationError):
            AccessPolicy.model_validate(policy(clauses=[]))
        AccessPolicy.model_validate(policy(automated_access="not_reviewed", clauses=[]))

    def test_written_permission_needs_a_reference(self):
        with self.assertRaises(ValidationError):
            AccessPolicy.model_validate(policy(automated_access="written_permission"))
        granted = AccessPolicy.model_validate(policy(automated_access="written_permission", permission_reference="letter 2026-11-01"))
        self.assertTrue(granted.allows_automated_access)

    def test_host_cannot_have_two_policies(self):
        with self.assertRaises(ValidationError):
            policy_set(policy(), policy(policy_id="other"))

    def test_domains_cover_subdomains_on_label_boundaries(self):
        policies = policy_set(policy(hosts=[], domains=["example.com"]))
        for url in ("https://example.com/", "https://a.b.example.com/", "https://EXAMPLE.COM./x", "http://example.com:8080/"):
            with self.subTest(url=url):
                self.assertEqual(policies.policy_for(url).policy_id, "example")
        for url in ("https://notexample.com/", "https://example.com.evil.org/", "https://example.com@evil.org/", "file:///x"):
            with self.subTest(url=url):
                self.assertIsNone(policies.policy_for(url))

    def test_a_narrower_policy_cannot_override_a_domain(self):
        prohibited = policy(policy_id="parent", hosts=[], domains=["example.com"], automated_access="prohibited")
        for child in (policy(policy_id="child", hosts=["data.example.com"]), policy(policy_id="child", hosts=[], domains=["x.example.com"])):
            with self.subTest(child=child):
                with self.assertRaisesRegex(ValidationError, "parent"):
                    policy_set(prohibited, child)
        policy_set(policy(policy_id="exact", hosts=["example.com"]), policy(policy_id="sub", hosts=["a.example.com"]))

    def test_policy_must_cover_a_valid_host_name(self):
        for bad in ({"hosts": []}, {"hosts": ["Example.com"]}, {"hosts": ["https://example.com"]}, {"hosts": ["example.com."]}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    AccessPolicy.model_validate(policy(**bad))

    def test_unclear_conclusion_must_explain_what_is_missing(self):
        with self.assertRaisesRegex(ValidationError, "unclear"):
            AccessPolicy.model_validate(policy(automated_access="unclear", clauses=[]))
        unclear = AccessPolicy.model_validate(policy(automated_access="unclear", clauses=[], notes="terms page unreadable"))
        self.assertFalse(unclear.allows_automated_access)

    def test_every_catalog_provider_is_reviewed_and_none_is_permitted(self):
        policies = load_access_policies(ROOT / "config/access_policies.json")
        catalog = json.loads((ROOT / "data/source_catalog.json").read_text(encoding="utf-8"))["sources"]
        for entry in catalog:
            with self.subTest(provider=entry["provider"]):
                reviewed = policies.policy_for(entry["base_url"])
                self.assertIsNotNone(reviewed, "catalog provider has no recorded terms review")
                self.assertFalse(reviewed.allows_automated_access)

    def test_psx_policy_covers_every_psx_subdomain(self):
        policies = load_access_policies(ROOT / "config/access_policies.json")
        for url in ("https://psx.com.pk/", "https://www.psx.com.pk/", "https://dps.psx.com.pk/", "https://new.dps.psx.com.pk/"):
            with self.subTest(url=url):
                self.assertEqual(policies.policy_for(url).policy_id, "psx")
        self.assertIsNone(policies.policy_for("https://notpsx.com.pk/"))


class TestFetcher(unittest.TestCase):
    def test_successful_fetch_records_metadata_without_parsing(self):
        transport = FakeTransport(ok())
        instance, _ = fetcher(transport)
        artifact = instance.fetch("https://example.com/a")
        self.assertEqual((artifact.status, artifact.body, artifact.content_type), (200, b"payload", "text/html"))
        self.assertEqual(artifact.retrieved_at, datetime(2026, 10, 21, 20, 0, tzinfo=UTC))
        self.assertEqual((artifact.policy_id, artifact.attempts), ("example", 1))
        self.assertIn("finura", transport.calls[0]["headers"]["User-Agent"])
        self.assertEqual(transport.calls[0]["timeout"], 30.0)

    def test_refused_policy_never_touches_the_network(self):
        transport = FakeTransport()
        instance, _ = fetcher(transport, policy_set(policy(automated_access="prohibited")))
        with self.assertRaises(AccessNotPermittedError):
            instance.fetch("https://example.com/a")
        self.assertEqual(transport.calls, [])

    def test_retries_timeouts_and_server_errors_with_backoff(self):
        transport = FakeTransport(
            FetchTimeoutError("https://example.com/a", "timed out"),
            TransportResponse("https://example.com/a", 503, {}, b""),
            ok(),
        )
        instance, clock = fetcher(transport, backoff_seconds=1.0)
        artifact = instance.fetch("https://example.com/a")
        self.assertEqual(artifact.attempts, 3)
        # Backoff 1s then 2s; pacing then waits out the rest of the 5s interval.
        self.assertEqual(clock.sleeps, [1.0, 4.0, 2.0, 3.0])

    def test_gives_up_after_max_attempts(self):
        transport = FakeTransport(*[NetworkError("https://example.com/a", "connection refused")] * 3)
        instance, _ = fetcher(transport)
        with self.assertRaises(RetriesExhaustedError) as caught:
            instance.fetch("https://example.com/a")
        self.assertEqual(caught.exception.attempts, 3)
        self.assertIsInstance(caught.exception.last_error, NetworkError)
        self.assertEqual(len(transport.calls), 3)

    def test_client_errors_are_not_retried(self):
        transport = FakeTransport(TransportResponse("https://example.com/a", 404, {}, b""))
        instance, _ = fetcher(transport)
        with self.assertRaises(HttpStatusError) as caught:
            instance.fetch("https://example.com/a")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(len(transport.calls), 1)

    def test_rate_limit_is_retried(self):
        transport = FakeTransport(TransportResponse("https://example.com/a", 429, {}, b""), ok())
        instance, _ = fetcher(transport)
        self.assertEqual(instance.fetch("https://example.com/a").attempts, 2)

    def test_paces_requests_to_the_same_host(self):
        transport = FakeTransport(ok(), ok("https://example.com/b"))
        instance, clock = fetcher(transport)
        instance.fetch("https://example.com/a")
        instance.fetch("https://example.com/b")
        self.assertEqual(clock.sleeps, [5.0])

    def test_redirect_within_permitted_host_is_followed(self):
        transport = FakeTransport(redirect("https://example.com/a", "/b"), ok("https://example.com/b"))
        instance, _ = fetcher(transport)
        artifact = instance.fetch("https://example.com/a")
        self.assertEqual((artifact.requested_url, artifact.final_url), ("https://example.com/a", "https://example.com/b"))
        self.assertEqual([call["url"] for call in transport.calls], ["https://example.com/a", "https://example.com/b"])

    def test_redirect_to_unpermitted_host_is_refused_before_following(self):
        for target in ("https://elsewhere.example.org/a", "https://dps.psx.com.pk/listings"):
            with self.subTest(target=target):
                transport = FakeTransport(redirect("https://example.com/a", target))
                instance, _ = fetcher(transport)
                with self.assertRaises(AccessNotPermittedError):
                    instance.fetch("https://example.com/a")
                self.assertEqual(len(transport.calls), 1)

    def test_redirect_to_non_http_scheme_is_refused(self):
        instance, _ = fetcher(FakeTransport(redirect("https://example.com/a", "file:///etc/passwd")))
        with self.assertRaises(ValueError):
            instance.fetch("https://example.com/a")

    def test_redirect_limits(self):
        loop = [redirect("https://example.com/a", "https://example.com/a")] * 3
        instance, _ = fetcher(FakeTransport(*loop), max_redirects=2)
        with self.assertRaisesRegex(RedirectError, "more than 2 redirects"):
            instance.fetch("https://example.com/a")
        instance, _ = fetcher(FakeTransport(TransportResponse("https://example.com/a", 302, {}, b"")))
        with self.assertRaisesRegex(RedirectError, "without a Location"):
            instance.fetch("https://example.com/a")

    def test_transport_that_follows_redirects_itself_is_rejected(self):
        instance, _ = fetcher(FakeTransport(ok("https://elsewhere.example.org/a")))
        with self.assertRaisesRegex(FetchError, "transport followed a redirect"):
            instance.fetch("https://example.com/a")

    def test_oversized_response_is_rejected(self):
        transport = FakeTransport(ok(body=b"x" * 11))
        instance, _ = fetcher(transport, max_bytes=10)
        with self.assertRaises(ResponseTooLargeError):
            instance.fetch("https://example.com/a")

    def test_rejects_non_http_urls_and_bad_settings(self):
        instance, _ = fetcher(FakeTransport())
        with self.assertRaises(ValueError):
            instance.fetch("file:///etc/passwd")
        with self.assertRaises(ValueError):
            fetcher(FakeTransport(), max_attempts=0)


class TestPsxListingAdapter(unittest.TestCase):
    def test_retrieval_is_refused_under_recorded_psx_terms(self):
        transport = FakeTransport()
        instance, _ = fetcher(transport, load_access_policies(ROOT / "config/access_policies.json"))
        adapter = PsxListingAdapter()
        self.assertEqual(adapter.descriptor.access_policy_id, "psx")
        with self.assertRaisesRegex(AccessNotPermittedError, "prohibited"):
            adapter.retrieve(instance)
        self.assertEqual(transport.calls, [])

    def test_retrieval_needs_the_matching_policy(self):
        instance, _ = fetcher(FakeTransport(), policy_set())
        with self.assertRaises(LookupError):
            PsxListingAdapter().retrieve(instance)


class TestUrllibTransportDoesNotFollowRedirects(unittest.TestCase):
    """Loopback only. The redirect target uses the reserved .invalid TLD, so
    even a following transport could not reach a real host."""

    def test_returns_the_redirect_instead_of_following_it(self):
        class Redirecting(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://redirect-target.invalid/")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Redirecting)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/start"
        response = UrllibTransport().send(url, headers={}, timeout=5, max_bytes=1024)
        self.assertEqual((response.url, response.status), (url, 302))
        self.assertEqual(response.headers["Location"], "http://redirect-target.invalid/")


@unittest.skipUnless(os.environ.get("FINURA_LIVE_TESTS") == "1", "live network tests are opt-in: set FINURA_LIVE_TESTS=1")
class TestLiveTransport(unittest.TestCase):
    def test_fetches_iana_example_domain(self):
        # example.com is reserved by IANA for documentation and testing.
        policies = policy_set(policy(hosts=["example.com"], min_request_interval_seconds=0))
        artifact = Fetcher(policies=policies, timeout_seconds=10, max_attempts=2).fetch("https://example.com/")
        self.assertEqual(artifact.status, 200)
        self.assertIn(b"Example Domain", artifact.body)


if __name__ == "__main__":
    unittest.main()
