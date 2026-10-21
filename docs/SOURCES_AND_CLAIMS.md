# Sources, Access, and Listing Claims

How Finura obtains evidence, records where it came from, and turns it into
reviewable claims about listed companies. Applies to every publisher; PSX is
the first one reviewed.

## 1. Access policies: may this host be fetched automatically?

`config/access_policies.json` records a human review of each publisher's
published terms (`finura.sources.access.AccessPolicy`):

| Field | Meaning |
| --- | --- |
| `hosts` | Exact hostnames covered |
| `domains` | Domains covered with all subdomains, on label boundaries (`psx.com.pk` covers `dps.psx.com.pk`, not `notpsx.com.pk`) |
| `automated_access` | `not_reviewed`, `unclear` (reviewed but silent or unreadable), `prohibited`, `permitted`, or `written_permission` |
| `clauses` | Short verbatim quotes from the terms, with the terms URL; required for `prohibited` and `permitted` |
| `permission_reference` | The permission letter or licence; required for `written_permission` |
| `reviewed_by`, `reviewed_at` | Who reviewed the terms, and when |
| `min_request_interval_seconds` | Minimum gap between requests to one host |

Finura does not read robots.txt or interpret terms automatically. A host with
no policy, or with a policy that does not permit automated access, is never
fetched.

### PSX (reviewed 2026-10-21, owner confirmation pending)

- `www.psx.com.pk/psx/terms-of-use` prohibits retrieving content with
  "engines, software, spiders, robots, avatars, agents, tools" and
  "systematic retrieval to create collections, compilations, databases or
  directories" without PSX's prior written permission. Content is licensed
  "for your personal, non-commercial use only". A user "may print or
  download a single, unaltered, permanent copy".
- The DPS portal's terms say users will not use web browsers "other than
  generally available third-party browsers". Its legal notice requires
  "rights/license from the PSX" for dissemination or commercial use of
  market data.
- `dps.psx.com.pk/robots.txt` returns 404; `www.psx.com.pk/robots.txt`
  disallows only `/cgi-bin/`. Robots rules do not override the terms.

The `psx` policy therefore records automated access as **prohibited**. The
quotes were captured through a page-to-text tool and need confirming against
the live pages.

**Legacy collector.** `pipeline/fetch_sources.py` (including `--discover`)
now sends every request through the same policy-gated `Fetcher`. PSX hosts
and unreviewed hosts are refused before any network contact.

## 2. Retrieval: `finura.sources.fetch.Fetcher`

- Refuses any URL whose host lacks a permitting policy
  (`AccessNotPermittedError`), before touching the network.
- Never lets urllib follow redirects: each `Location` is checked against
  policy before it is requested, up to 5 redirects.
- 30 s timeout per request by default; responses over 25 MiB are rejected.
- Retries timeouts, connection failures, HTTP 429 and 5xx up to 3 attempts,
  with exponential backoff (2 s, 4 s). Other 4xx fail at once.
- Waits at least the policy's interval between requests to the same host.
- Error types: `FetchTimeoutError`, `NetworkError`, `HttpStatusError`,
  `ResponseTooLargeError`, `RetriesExhaustedError`.
- Returns bytes and metadata (`FetchedArtifact`) only. It never parses,
  registers, or verifies.

Network I/O sits behind the `Transport` protocol, so the standard test suite
uses a fake transport. One live test exists and runs only with
`FINURA_LIVE_TESTS=1`; it fetches the IANA example domain, never a PSX host.

## 3. Adapters

`SourceAdapter` (`finura.sources.adapters`) pairs a publisher, its access
policy, and an entry URL; `retrieve(fetcher)` goes through the policy gate.
`PsxListingAdapter` exists so the PSX entry point and policy are declared in
one place. Under the current policy its retrieval is refused. No parser for
PSX's own page format exists, because that format has not been inspected
under permitted access.

## 4. Sources: what was obtained, from whom, and when

`SourceDocument` (schema v2) fields, beyond identity and hash:

| Field | Meaning; `null` = not recorded |
| --- | --- |
| `company_id` | Company the document concerns; `null` for exchange-wide notices |
| `canonical_url` | Official location of the document |
| `publisher` | Organisation that issued it |
| `provider` | Site or service it was obtained from (may differ from publisher) |
| `published_at` | Date the publisher issued it |
| `retrieved_at` | When it was downloaded |
| `registered_at` | When it entered the registry (always set) |
| `access_basis` | `manual_download`, `automated_permitted`, `written_permission`, or `licensed` |
| `upstream` | Sources it derives from; `[]` = original, `null` = unknown |

The `SourceRegistry` protocol (`finura.sources.registry`) has `get`,
`find_by_sha256`, `register`, and `sources`:

- Registering identical bytes for the same company returns the existing
  record.
- Reusing a `source_id` for different content is refused.
- `new_source_id` uses the same derivation as `pipeline/register_source.py`,
  so the FFC filing keeps `src_e4abb64ff4886ffc`.

## 5. Listing claims

A `ListingClaim` (`finura.claims`) states something about a symbol as of a
date: legal name, listing status, sector label (verbatim), validity dates,
or a symbol change (`previous_symbol` plus `valid_from`). Each claim cites
evidence: a source ID, that source's SHA-256 at claim time, a location, and
an optional verbatim excerpt. Claim IDs are derived from content, so
re-ingesting the same transcription is idempotent.

| Status | How a claim gets there |
| --- | --- |
| `discovered` | Created by parsing. Fetching or parsing can produce nothing else |
| `verified` | `review_claim` with a reviewer and time, after the evidence is inspected |
| `rejected` | `review_claim` with a reviewer, time, and a note saying why |

Only `discovered` claims can be reviewed. Claims whose date ranges overlap
and that state different legal names or statuses are ambiguous: transcription
and the claims document refuse them until one is rejected. A symbol reused
after a delisting is not ambiguous, because its date ranges do not overlap.

### Intake when automated access is not permitted

1. A person downloads one copy of the notice or page, as the terms allow,
   and registers it with `access_basis: manual_download`.
2. They transcribe what it states into a CSV with these columns:
   `symbol, as_of, legal_name, listing_status, sector_label, valid_from,
   valid_to, previous_symbol, source_id, location, excerpt`.
3. `python -m finura.onboarding ingest` parses it into discovered claims.
4. A reviewer checks each claim against the source:
   `python -m finura.onboarding review`.
5. `python -m finura.onboarding propose` builds the company record from the
   selected claims.

## 6. Company proposals

`propose_company` builds a `Company` from claims a reviewer selects for one
company:

- Rejected claims are refused.
- Symbols must form a single chain of symbol changes.
- A symbol's dates come only from symbol-change claims, `listed` claims with
  a start date, the successor's change date, or the delisting date.
- Identity is `verified` only if every claim used is verified. Otherwise it
  is `unverified`, with the claims' evidence listed as candidates and no
  reviewer recorded.
- Sector labels are returned for review and never turned into a
  classification automatically.

Historical symbol lookups (`CompanyRegistry.resolve_symbol(symbol, on=date)`)
always need an explicit date.
