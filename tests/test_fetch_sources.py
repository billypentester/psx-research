import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline import fetch_sources


class TestFetchSources(unittest.TestCase):
    def test_provider_matching_uses_configured_domains(self):
        catalog = [{"provider": "PSX", "base_url": "https://dps.psx.com.pk/"}]
        self.assertEqual(
            fetch_sources.provider_for("https://dps.psx.com.pk/download/x", catalog)["provider"],
            "PSX",
        )

    def test_safe_name_is_stable_and_filesystem_safe(self):
        name = fetch_sources.safe_name("https://example.com/a report.pdf?q=1")
        self.assertRegex(name, r"^[a-f0-9]{12}_a_report\.pdf$")

    @patch("pipeline.fetch_sources.urlopen")
    def test_fetch_uses_research_user_agent(self, mocked_urlopen):
        response = MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html"}
        response.read.return_value = b"<html></html>"
        response.__enter__.return_value = response
        mocked_urlopen.return_value = response
        status, content_type, content = fetch_sources.fetch("https://example.com")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.headers["User-agent"], fetch_sources.USER_AGENT)
        self.assertEqual((status, content_type, content), (200, "text/html", b"<html></html>"))


if __name__ == "__main__":
    unittest.main()
