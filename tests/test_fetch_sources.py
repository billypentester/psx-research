import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from finura.sources.access import AccessNotPermittedError, normalize_host
from finura.sources.fetch import TransportResponse
from finura.sources.registry import new_source_id
from pipeline import fetch_sources, register_source
from tests.network_guard import NoNetworkTestCase

ROOT = Path(__file__).resolve().parents[1]
# Captured before tests patch `build_fetcher`.
BUILD_FETCHER = fetch_sources.build_fetcher
PSX_URLS = (
    "https://psx.com.pk/",
    "https://www.psx.com.pk/psx/resources-and-tools/listings/listed-companies",
    "https://dps.psx.com.pk/",
    "https://dps.psx.com.pk/download/document/269389.pdf",
    "https://any.sub.domain.psx.com.pk/x",
    "https://PSX.COM.PK./",
    "http://psx.com.pk:8080/",
)


def is_psx(url):
    host = normalize_host(url) or ""
    return host == "psx.com.pk" or host.endswith(".psx.com.pk")


class TripwireTransport:
    """Network mock that fails the test outright if a PSX request reaches it."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []

    def send(self, url, *, headers, timeout, max_bytes):
        if is_psx(url):
            raise AssertionError(f"PSX request reached the network mock: {url}")
        self.calls.append(url)
        if url not in self.responses:
            raise AssertionError(f"unexpected request to {url}")
        return self.responses[url]


def html(url, links=()):
    body = "".join(f'<a href="{link}">x</a>' for link in links).encode()
    return TransportResponse(url, 200, {"Content-Type": "text/html"}, body)


class TestHelpers(unittest.TestCase):
    def test_provider_matching_uses_configured_domains(self):
        catalog = [{"provider": "PSX", "base_url": "https://dps.psx.com.pk/"}]
        self.assertEqual(
            fetch_sources.provider_for("https://dps.psx.com.pk/download/x", catalog)["provider"],
            "PSX",
        )

    def test_safe_name_is_stable_and_filesystem_safe(self):
        name = fetch_sources.safe_name("https://example.com/a report.pdf?q=1")
        self.assertRegex(name, r"^[a-f0-9]{12}_a_report\.pdf$")


class TestPsxIsBlockedBeforeNetwork(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.transport = TripwireTransport()
        self.fetcher = fetch_sources.build_fetcher(transport=self.transport)

    def test_psx_domains_and_subdomains_are_refused(self):
        for url in PSX_URLS:
            with self.subTest(url=url):
                with self.assertRaisesRegex(AccessNotPermittedError, "prohibited under policy 'psx'"):
                    fetch_sources.fetch(url, self.fetcher)
        self.assertEqual(self.transport.calls, [])

    def test_lookalike_domains_are_not_psx_but_are_still_refused(self):
        for url in ("https://notpsx.com.pk/", "https://psx.com.pk.evil.example/", "https://psx.com.pk@evil.example/"):
            with self.subTest(url=url):
                self.assertIsNone(self.fetcher.policies.policy_for(url))
                with self.assertRaisesRegex(AccessNotPermittedError, "no recorded access policy"):
                    fetch_sources.fetch(url, self.fetcher)
        self.assertEqual(self.transport.calls, [])

    def test_unknown_hosts_fail_closed(self):
        for url in ("https://sarmaaya.pk/", "https://example.org/", "http://127.0.0.1/"):
            with self.subTest(url=url):
                with self.assertRaises(AccessNotPermittedError):
                    fetch_sources.fetch(url, self.fetcher)
        self.assertEqual(self.transport.calls, [])

    def test_tripwire_detects_a_psx_request(self):
        with self.assertRaisesRegex(AssertionError, "PSX request reached"):
            self.transport.send("https://dps.psx.com.pk/", headers={}, timeout=1, max_bytes=1)


class TestCommandLineEnforcement(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.transport = TripwireTransport()
        self.policies = fetch_sources.ACCESS_POLICIES
        for name, value in (
            ("pipeline.fetch_sources.ROOT", self.dir),
            ("pipeline.register_source.ROOT", self.dir),
            ("pipeline.register_source.REGISTRY", self.dir / "data/source_registry.json"),
            ("pipeline.fetch_sources.build_fetcher", lambda: BUILD_FETCHER(self.policies, transport=self.transport)),
        ):
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["fetch_sources.py", *arguments]), redirect_stdout(stdout), redirect_stderr(stderr):
            status = fetch_sources.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def use_policies(self, *policies):
        path = self.dir / "access_policies.json"
        payload = json.loads(fetch_sources.ACCESS_POLICIES.read_text(encoding="utf-8"))
        payload["policies"].extend(policies)
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.policies = path

    def test_discover_cannot_fetch_psx_or_unreviewed_catalog_providers(self):
        status, stdout, stderr = self.run_main("--company", "FFC", "--discover", "--delay", "0")
        self.assertEqual(status, 1)
        self.assertEqual(self.transport.calls, [])
        self.assertIn("https://dps.psx.com.pk/", stderr)
        self.assertIn("prohibited under policy 'psx'", stderr)
        self.assertIn("pipeline/register_source.py", stderr)
        self.assertIn("refused: 6", stdout)
        self.assertFalse((self.dir / "data").exists())

    def test_explicit_psx_url_is_refused(self):
        status, _, stderr = self.run_main("--company", "FFC", "--url", "https://dps.psx.com.pk/download/document/269389.pdf")
        self.assertEqual(status, 1)
        self.assertIn("REFUSED", stderr)
        self.assertEqual(self.transport.calls, [])

    def test_approved_host_still_fetches_and_registers(self):
        self.use_policies(approved_policy())
        url = "https://approved.example/report.pdf"
        self.transport.responses[url] = TransportResponse(url, 200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 fixture")
        status, stdout, _ = self.run_main("--company", "ABC", "--url", url, "--delay", "0")
        self.assertEqual(status, 0, stdout)
        registry = json.loads((self.dir / "data/source_registry.json").read_text(encoding="utf-8"))
        self.assertEqual(registry[0]["url"], url)
        self.assertEqual(registry[0]["retrieval_method"], "http")
        self.assertEqual(registry[0]["source_id"], new_source_id("ABC", url, registry[0]["sha256"]))

    def test_discovery_on_approved_host_skips_psx_and_unknown_links(self):
        self.use_policies(approved_policy())
        page = "https://approved.example/abc"
        allowed = "https://approved.example/abc-2025.pdf"
        self.transport.responses[page] = html(page, ["https://dps.psx.com.pk/abc.pdf", "https://unknown.example/abc", allowed])
        self.transport.responses[allowed] = TransportResponse(allowed, 200, {"Content-Type": "application/pdf"}, b"%PDF")
        status, stdout, stderr = self.run_main("--company", "ABC", "--url", page, "--discover", "--delay", "0")
        # The configured catalog landing pages are also tried and refused.
        self.assertEqual(self.transport.calls, [page, allowed])
        self.assertIn("REFUSED: https://dps.psx.com.pk/abc.pdf", stderr)
        self.assertIn("REFUSED: https://unknown.example/abc", stderr)
        self.assertEqual(status, 0, stdout)

    def test_redirect_to_psx_is_refused_before_it_is_followed(self):
        self.use_policies(approved_policy())
        url = "https://approved.example/moved"
        self.transport.responses[url] = TransportResponse(url, 302, {"Location": "https://dps.psx.com.pk/listings"}, b"")
        status, _, stderr = self.run_main("--company", "ABC", "--url", url, "--delay", "0")
        self.assertEqual(status, 1)
        self.assertEqual(self.transport.calls, [url])
        self.assertIn("prohibited under policy 'psx'", stderr)

    def test_redirect_to_unknown_host_is_refused_before_it_is_followed(self):
        self.use_policies(approved_policy())
        url = "https://approved.example/moved"
        self.transport.responses[url] = TransportResponse(url, 301, {"Location": "https://mirror.example.net/x"}, b"")
        status, _, stderr = self.run_main("--company", "ABC", "--url", url, "--delay", "0")
        self.assertEqual(status, 1)
        self.assertEqual(self.transport.calls, [url])
        self.assertIn("no recorded access policy", stderr)


class TestManualRegistrationIsOffline(NoNetworkTestCase):
    def test_register_existing_download_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "data/raw/FFC/notice.pdf"
            document.parent.mkdir(parents=True)
            document.write_bytes(b"%PDF manually downloaded notice")
            with patch("pipeline.register_source.ROOT", root), patch(
                "pipeline.register_source.REGISTRY", root / "data/source_registry.json"
            ), redirect_stdout(io.StringIO()):
                record = register_source.register_file(
                    company="FFC",
                    title="Manually downloaded PSX notice",
                    source_type="announcement",
                    file=document,
                    url="https://dps.psx.com.pk/download/document/1.pdf",
                )
        self.assertEqual(record["local_path"], "data/raw/FFC/notice.pdf")
        self.assertEqual(record["retrieval_method"], "manual")
        self.assertEqual(record["source_id"], new_source_id("FFC", record["url"], record["sha256"]))


def approved_policy():
    return {
        "policy_id": "approved_fixture",
        "publisher": "Approved Fixture Publisher",
        "hosts": ["approved.example"],
        "automated_access": "permitted",
        "reviewed_by": "test fixture",
        "reviewed_at": "2026-10-21T00:00:00+00:00",
        "clauses": [{"terms_url": "https://approved.example/terms", "quote": "automated retrieval is permitted"}],
        "min_request_interval_seconds": 0,
    }



if __name__ == "__main__":
    unittest.main()
