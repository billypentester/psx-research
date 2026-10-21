# Provider Due Diligence (Phase 3, Step 3)

Review date: 2026-10-21. Reviewer: Claude Code session on behalf of the
repository owner; **owner confirmation pending**.

**Conclusion: no provider is ready for an adapter.** Each of the five catalog
providers either prohibits automated access, publishes no applicable terms,
or could not be read. All stay blocked in `config/access_policies.json`.
PSX stays prohibited (see [SOURCES_AND_CLAIMS.md](./SOURCES_AND_CLAIMS.md)).

## Method

- Primary evidence is each provider's own legal and about pages. Web search
  was used only to locate those pages.
- Each legal page was read once through a page-to-text tool. Quotes are short
  extracts produced by that tool and must be confirmed against the live
  pages.
- No data pages, API endpoints, or undocumented URLs were requested.
  Exception: one request to the Ticker Analysts home page, only to find its
  footer legal links.
- Permission was never inferred from public accessibility, robots.txt, a
  working endpoint, or another site's use of the data.

## Summary

| Provider | Operator | Automated access | Reuse / commercial / derivative | Upstream data | Decision |
| --- | --- | --- | --- | --- | --- |
| [Sarmaaya](https://sarmaaya.pk/terms-of-service) | Sarmaaya Financials Private Limited | **Prohibited** | Prohibited without written permission; no building competing products | PSX via an authorised redistributor (CS Solutions) | Blocked: `prohibited` |
| [PSX Terminal](https://psxterminal.com/terms) | Runtime Technologies (SMC-Private) Limited | **Prohibited** "beyond normal use" without permission | Resale "at scale" needs permission; no licence granted | "Publicly available market data and company filings" (PSX-derived) | Blocked: `prohibited` |
| [Ticker Analysts](https://www.tickeranalysts.com/) | Not identified ("Powered by Nafa") | **Unclear**: no terms page linked | Unclear | Not stated | Blocked: `unclear` |
| [SCS Trade](https://scstrade.com/PrivacyPolicy.aspx) | Standard Capital Securities (Pvt.) Ltd | **Unclear**: not addressed | "All Rights Reserved"; data "for the purpose of information only" | Not stated | Blocked: `unclear` |
| [FinHisaab](https://finhisaab.com/legal/terms) | FinHisaab (entity not confirmed) | **Unclear**: terms page returned HTTP 429 twice | Not read | Not read | Blocked: `unclear` |

None of the five offers a documented data licence or a published API with
terms.

## Provider details

### Sarmaaya: prohibited

- **Terms:** [Master User Agreement](https://sarmaaya.pk/terms-of-service); no
  effective date shown.
  - Clause 4.4(c): "Use bots, automated systems, or scraping techniques to
    extract data."
  - Clause 6.3(b): "Use any automated tools (bots, scrapers, etc.) to collect
    or extract data from the Website."
  - Clause 6.3(a): "Copy, reproduce, distribute, transmit, modify, or create
    derivative works based on" (without explicit written permission).
  - Clause 26.1.12: no use "to develop competitive products or services".
- **Licence:** none granted. Content is "the exclusive property of Sarmaaya
  its licensors or subsidiaries" (6.1).
- **Provenance:** the disclaimer names "a PSX authorized data redistributor"
  and "CS Solutions (Pvt.) Ltd."; clause 18 says data is "sourced from third
  parties, including stock exchanges and brokerage firms".
- **API and rate limits:** no Sarmaaya API is described; "brokerage APIs" in
  clause 19.1 are third-party integrations.
- **Permission contact:** clause 9.2 reads "contact [Insert Contact Email]",
  an unfilled placeholder. The footer gives phone +92 51 8468053.
- **Data offered:** the services definition lists "financial data",
  investment tracking tools, and calculators. Coverage of statements,
  dividends, listing history, and sectors was not inspected.

### PSX Terminal: prohibited without permission

- **Terms:** [Terms of Service](https://psxterminal.com/terms), last updated
  July 2026. Users must not "scrape or resell its data at scale without
  permission" or "access it through automated means beyond normal use".
- **Licence, API, rate limits, attribution:** not addressed. No API
  documentation is published. A GitHub repository that advertised a
  psxterminal.com REST and WebSocket API (`github.com/mumtazkahn/psx-terminal`,
  seen only in search results) returned HTTP 404 when checked. An API that
  may once have been public is not permission.
- **Operator:** [About page](https://psxterminal.com/about): "A product of
  RUNTIME TECHNOLOGIES (SMC-PRIVATE) LIMITED", with SECP CUIN 0340194. It
  is "not affiliated with, endorsed by or connected to Pakistan Stock
  Exchange Limited, NCCPL or CDC".
- **Provenance:** "Built from publicly available market data and company
  filings". Prices "may be delayed or contain errors".
- **Permission contact:** contact@psxterminal.com.
- **Data offered:** live prices and market statistics, by its own
  description. Search results also mention financial statements and dividend
  records sourced from PSX. Neither claim was inspected.

### Ticker Analysts: unclear

- The home page footer links only product pages (`/screener`, `/stocks`,
  `/contact`, and similar). There is no terms, privacy, or licence page, and
  no operating company or regulatory registration is named. The site says it
  is "Powered by Nafa" (`/nafa`, a brokerage-style investing service whose
  footer lists "Terms & Conditions"; not read, because it governs Nafa's
  service rather than this site's data).
- **Data offered:** by self-description, financials, insider activity,
  broker targets, and a screener with sector filters. Not inspected.
- **Permission needed:** the operator's identity, plus published terms or
  written permission covering automated access and research use.

### SCS Trade: unclear

- The site of Standard Capital Securities (Pvt.) Ltd, a PSX broker. No terms
  of use page is linked. The [privacy policy](https://scstrade.com/PrivacyPolicy.aspx)
  and footer disclaimer say "Users are advised to use the data for the
  purpose of information only", "All Rights Reserved", and warn of action
  against those "who violate the proprietary rights". They do not address
  automated access, reuse, or redistribution.
- **Provenance:** not stated. Charts are by TradingView.
- **Data offered:** live rates and company snapshot pages, per search
  results. Not inspected.
- **Permission needed:** written terms or permission from Standard Capital
  Securities, including the source and licence of its market data.

### FinHisaab: unclear (unread)

- [Terms of Service](https://finhisaab.com/legal/terms) returned HTTP 429
  (rate limited) on two attempts, so I made no further requests. A search
  excerpt shows "last updated November 9, 2025" and describes mutual fund
  screening, market data, portfolio tracking, and calculators "for
  informational and educational purposes only".
- **Permission needed:** first, a full reading of the terms; then whatever
  they require.

## Lineage: no independent corroboration

Sarmaaya and PSX Terminal both describe their data as derived from PSX.
Sarmaaya names the same redistributor (CS Solutions) that co-operates the
PSX data portal under PSX's terms. A figure from either provider that matches
a PSX filing is therefore **not independent corroboration** of that figure.
Any future adapter must record `upstream` lineage to PSX, and reconciliation
must count independent upstreams, not providers.

## Recommendation

**No provider is ready, and no adapter should be implemented now.**

The only route to an automated source among the five is written permission.
If the owner wants to pursue one, **PSX Terminal is the best candidate to
ask**:

- its operator is a named, SECP-registered company;
- its terms explicitly contemplate granting permission ("without permission");
- it offers a contact address.

It is still unsuitable as a **primary** source of financial statements: its
data derives from PSX and company filings, and it disclaims accuracy.

**Permission to request from Runtime Technologies, in writing:**

1. Automated access, naming the endpoints, authentication, and rate limits.
2. Storing retrieved data and using it in research reports, including
   derived calculations.
3. Whether redistribution of derived research is allowed, and on what
   attribution terms.
4. A statement of data provenance (which PSX feeds or filings, and under
   what PSX licence) and how corrections and restatements are handled.

For financial statements, the primary sources remain the issuers' own
filings: PSX announcements and company reports, obtained manually and
registered. Automating those needs PSX's written permission or a PSX data
licence. Company investor-relations websites are a separate option not
covered in this review; each company's terms would need their own review.

## Conditional adapter contract (not implemented)

This applies only if written permission is obtained and recorded as
`automated_access: written_permission` with a `permission_reference`. It
targets end-of-day market observations, the narrowest useful scope. The
provider's response format is undocumented, so fixtures must come from the
documentation supplied with the permission. None is invented here.

```python
class MarketObservation(BaseModel):          # new v1 record type
    symbol: ListingSymbol                    # as published by the provider
    company_id: CompanyId                    # resolved via CompanyRegistry.resolve_symbol(symbol, on=observed_on)
    observed_on: IsoDate                     # trading date
    close: FiniteNumber                      # never defaulted; a missing price is a gap
    unit: Literal[Unit.PKR_PER_SHARE]
    volume: int | None
    source_id: Identifier                    # registered raw response
    upstream: tuple[EvidenceReference, ...]  # must name PSX as the upstream publisher

class MarketDataAdapter(Protocol):
    descriptor: AdapterDescriptor            # access_policy_id == "psx_terminal"
    def retrieve(self, fetcher: Fetcher, symbol: str, start: date, end: date) -> FetchedArtifact: ...
    def parse(self, content: bytes, source: SourceDocument,
              companies: CompanyRegistry) -> tuple[MarketObservation, ...]: ...   # offline
```

### Fixture-based acceptance tests

Write these before the implementation. All run offline under the socket
guard and PSX tripwire from `tests/test_fetch_sources.py`.

1. `retrieve` is refused while the policy is `prohibited` or `unclear`. It
   works only with `written_permission` and a `permission_reference`.
2. The policy's `min_request_interval_seconds` matches the rate limit in the
   permission letter.
3. Parsing a recorded fixture response yields observations whose `source_id`
   and SHA-256 match the registered raw response.
4. Every observation's `upstream` names PSX.
5. A missing, null, non-numeric, NaN, or zero-placeholder price is rejected.
   Nothing is substituted.
6. An unknown symbol, or a symbol not listed on `observed_on`, is rejected.
   Symbol reuse resolves by date. No company record is created.
7. Duplicate (symbol, date) observations in one response are rejected.
8. A response whose latest date is older than the requested end date is
   flagged as stale, not silently accepted.
9. Malformed or truncated payloads raise a parse error, with no partial
   output.
10. PSX URLs and redirects to PSX remain refused (existing tripwire tests).

## Unresolved questions for the owner

1. Do you want to request written permission from Runtime Technologies (PSX
   Terminal)? Or pursue a PSX or CS Solutions data licence instead, which
   would give a primary feed rather than a derived one?
2. Should FinHisaab's terms be read later from a normal browser session, now
   that it rate-limits automated page reads?
3. Should the project review issuer investor-relations websites as a source
   class for annual and quarterly reports?
4. Please confirm the quoted clauses for PSX, Sarmaaya, PSX Terminal, and SCS
   Trade against the live pages.
