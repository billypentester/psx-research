"""Fetch permitted public source pages and preserve them with provenance.

Every request, including discovered links and redirects, goes through
`finura.sources.fetch.Fetcher`. The fetcher refuses any host without a
reviewed policy in `config/access_policies.json` that permits automated
access, before making a network request. PSX hosts (psx.com.pk and all
subdomains) are recorded as prohibited, so PSX content must be downloaded
manually and registered with `pipeline/register_source.py`. robots.txt is
never treated as permission.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from finura.sources.access import AccessNotPermittedError, load_access_policies
from finura.sources.fetch import FetchError, Fetcher

try:
    from .register_source import register_file
except ImportError:
    from register_source import register_file


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "source_catalog.json"
ACCESS_POLICIES = ROOT / "config" / "access_policies.json"
MAX_BYTES = 25 * 1024 * 1024
ALLOWED_SCHEMES = {"http", "https"}
REFUSAL_GUIDANCE = (
    "Automated access requires a reviewed policy in config/access_policies.json that permits it. "
    "Download the document manually and register it with pipeline/register_source.py, "
    "or record written permission from the publisher."
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["sources"]


def provider_for(url, catalog):
    hostname = (urlparse(url).hostname or "").lower()
    for source in catalog:
        base_hostname = (urlparse(source["base_url"]).hostname or "").lower()
        if hostname == base_hostname or hostname.endswith("." + base_hostname):
            return source
    return None


def safe_name(url):
    parsed = urlparse(url)
    name = Path(parsed.path).name or "index.html"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{digest}_{name}"


def build_fetcher(policies_path=ACCESS_POLICIES, transport=None):
    options = {"transport": transport} if transport is not None else {}
    return Fetcher(policies=load_access_policies(policies_path), max_bytes=MAX_BYTES, **options)


def fetch(url, fetcher):
    if urlparse(url).scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Unsupported URL scheme: {url}")
    artifact = fetcher.fetch(url)
    return artifact.status, artifact.content_type, artifact.body


def save_response(company, url, status, content_type, content):
    provider = provider_for(url, load_catalog())
    provider_name = provider["provider"] if provider else "unlisted"
    directory = ROOT / "data" / "raw" / company / "external" / re.sub(
        r"[^A-Za-z0-9_-]+", "_", provider_name.lower()
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_name(url)
    path.write_bytes(content)
    record = register_file(
        company=company,
        title=f"{provider_name} public response: {url}",
        source_type="market_data" if provider_name != "PSX" else "announcement",
        file=path,
        url=url,
        notes="Fetched by the permitted public-source collector; content requires normalization and review.",
        provider=provider_name,
        retrieval_method="http",
        http_status=status,
        content_type=content_type,
    )
    return path, record


def discover(url, company, fetcher):
    status, content_type, content = fetch(url, fetcher)
    if not content_type or "html" not in content_type.lower():
        return [(url, status, content_type, content)]
    parser = LinkParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    needle = company.lower()
    links = []
    for href in parser.links:
        absolute = urljoin(url, href)
        if urlparse(absolute).scheme not in ALLOWED_SCHEMES:
            continue
        if needle in absolute.lower():
            links.append(absolute)
    responses = [(url, status, content_type, content)]
    for link in sorted(set(links)):
        try:
            link_status, link_type, link_content = fetch(link, fetcher)
        except AccessNotPermittedError as error:
            print(f"REFUSED: {link}: {error}", file=sys.stderr)
            continue
        responses.append((link, link_status, link_type, link_content))
    return responses


def main():
    parser = argparse.ArgumentParser(description="Fetch permitted public PSX research sources.")
    parser.add_argument("--company", required=True, help="Ticker/company ID, e.g. FFC")
    parser.add_argument("--url", action="append", help="Explicit public URL; repeatable")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Fetch each configured landing page and preserve links containing the company ID",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = parser.parse_args()
    urls = list(args.url or [])
    if args.discover:
        urls.extend(source["base_url"] for source in load_catalog())
    if not urls:
        parser.error("Provide --url or --discover.")

    fetcher = build_fetcher()
    successes = 0
    failures = 0
    refused = 0
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            discovered = (
                discover(url, args.company, fetcher)
                if args.discover
                else [(url, *fetch(url, fetcher))]
            )
            for item in discovered:
                item_url, status, content_type, content = item
                save_response(args.company, item_url, status, content_type, content)
                successes += 1
                time.sleep(args.delay)
        except AccessNotPermittedError as error:
            refused += 1
            print(f"REFUSED: {url}: {error}. {REFUSAL_GUIDANCE}", file=sys.stderr)
        except (FetchError, OSError, ValueError) as error:
            failures += 1
            print(f"ERROR: {url}: {error}", file=sys.stderr)
    print(f"Fetched: {successes}; failures: {failures}; refused: {refused}")
    return 1 if (failures or refused) and not successes else 0


if __name__ == "__main__":
    raise SystemExit(main())
