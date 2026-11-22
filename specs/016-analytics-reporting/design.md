# Spec 016-A reporting design

Prepared: 2026-11-22. Revision: 2. Status: approved with [D1-D12](entry-review.md#3-decisions-for-the-owner) by D-072 and implemented as 016-A; section 8 records the choices the implementation made within this design.

## 1. API and scope

Add three read-only report families under the existing client-scoped API routing convention: social, spend and revenue. Each accepts `start`, `end`, optional `compare=previous`, `page_size`, `page`, `expected_revision` and `format=json|csv`. Social/spend require a connection ID owned by the authorized client. Social additionally selects `daily` or `content_cohort`; spend selects an existing approved ad level. Reject unknown query fields, unsupported metrics and incompatible options with `422`; do not silently broaden filters. CSV rejects page parameters and exports the complete bounded filtered result.

Use the established reader authentication and `resolve_scope`; social requires `client:read`, spend/revenue require `finance:read`. Apply the same rules to browser sessions and read service credentials. Ingest credentials do not become report credentials. Derive principal and effective scope from authentication; never trust a client-supplied agency, permission or principal. Scope every source, count, status and metadata query, including empty results and revisions. Reuse the repository's denial/not-found conventions without exposing cross-client existence.

There is no combined financial/social response, agency-wide endpoint, provider call or sync trigger. Bookings, CRM and referral APIs retain their existing contracts. Missing attribution is returned as an explicit `dependency_unavailable` capability, never numeric revenue or ROAS; there is no synthetic attribution fallback in a real report.

## 2. Result contract

JSON identifies `contract_version`, `family`, `client_id`, connection where applicable, `period`, `day_zone`, `basis`, `generated_at`, `revision`, `totals`, `rows`, `comparison`, `source_status` and page metadata. Metric rows identify metric, unit, definition version, source/provider/stream, effective date or content ID, and value. Money includes currency, exponent, integer minor units and canonical decimal text. Do not convert financial values through binary floating point.

Availability, coverage, freshness and provisional status are independent:

- Availability distinguishes available, missing, unsupported and not-synced values with reason codes. `0` is allowed only when supported by stored evidence or the defined complete ledger calculation.
- Coverage describes observed dates, expected dates where knowable, missing dates and sync limitations. A successful connection-level sync does not prove every stream or requested range complete. A content publication cohort whose inventory coverage is unproven stays partial/unknown.
- Freshness records source fetch times and the relevant policy, with stale/unknown states. Expose a connection-level success time only with that label; never substitute it for every record/stream's freshness.
- Provisional status preserves source revision windows independently of age. A complete range may still contain provisional facts.

Return partial subtotals with their status and missingness; reserve a complete total for proven complete, compatible input. A completely absent social/spend period is not a zero-valued complete report. For revenue, zero postings means zero recorded verified activity in the bounded evidence set, not proof that all external payments have been imported. Include unresolved counts and `external_completeness=unknown`.

Never include raw provider payloads, names/titles, URLs, emails, phone numbers, subject tokens, payment delivery IDs, reasons entered by people, actors, secrets or match keys. Allow only reviewed opaque source/object IDs where needed for grouping, not customer identifiers or revenue operation IDs. Internal full-source fingerprints are not response data.

## 3. Metric and period semantics

Build a closed reporting catalog keyed by provider, stream, metric and applicable product type. Each entry defines unit, aggregation, date basis, definition changes, valid breakdowns and comparison eligibility. Do not inherit `MetricSpec.additive=True` as approval to aggregate. Any metric lacking a reviewed entry is unsupported in reporting even if a connector can store it.

| Class | Examples from current adapters | Permitted behavior |
|---|---|---|
| Daily additive activity | Instagram daily views, likes, comments, shares, saves, replies and interactions where the stored definition is a count; YouTube daily views, watch minutes, likes/comments/shares and subscriber gains/losses | Sum only within one connection, metric, unit and compatible definition. Never combine overlapping streams or platforms into a deduplicated audience. |
| Daily non-additive audience | Instagram reach and accounts engaged | Return daily observations; period unique-audience total and its percentage comparison are null with `non_additive`. |
| Snapshot | YouTube channel subscriber count, total views and video count | Not part of the first daily report; a later snapshot view must label observation time and rounded counts. Never sum snapshots or imply historical snapshots exist. |
| Content lifetime cohort | Instagram media/story metrics and YouTube video lifetime metrics | Select content by stored publication time in native calendar dates; report latest stored lifetime values per content. Label `basis=published_cohort_lifetime`, publication time and fetched time. No period-earned claim or previous-period comparison; no aggregate unique audience across content. |
| Average or ratio | Average view duration, average view percentage, watch-time averages, skip rate | Return source observations only. No sum or average of averages without compatible numerator/denominator evidence. No inferred engagement-rate formula. |

The implementation review must include the complete supported catalog table; the examples above do not authorize an unreviewed metric or dimension. Source changes inside a requested period split compatible groups or make the period total/comparison unavailable with `definition_changed`. They must not be blended silently.

Dates are required, with `start < end` and at most 31 calendar days. Revenue uses UTC posting dates. Social daily/cohort filters use the provider's native day zone; advertising uses the stored account zone. Reject an arbitrary requested timezone. Translate half-open reporting dates explicitly when calling an existing service with inclusive end dates. Calendar arithmetic, not multiples of 86,400 seconds, defines Pacific/account-local boundaries across daylight-saving changes.

For `compare=previous`, the previous interval ends at `start` and contains the same number of calendar days. Differences require identical metric, currency, unit, basis, definition and supported completeness. If either period is partial, stale, provisional or incompatible, retain the two labeled values but return no authoritative percentage change, with the applicable reason. A zero previous denominator produces null percentage and `zero_baseline`; never infinity. Content lifetime cohorts reject this option rather than comparing differently aged content as equal exposure.

## 4. Revenue and spend

Count up to 201 evidence rows for the whole authorized client before loading/calculating financial data; over 200 rejects the report with `409 report_requires_ledger_upgrade`. This is a proposed development guard, not a solution to A3. Date filtering before this count or before calculation is forbidden: earlier sales, later receipts and adjustments can change current valid postings.

Within the bound, consume `client_ledger(...).calculation` and its held evidence handling; never call `.journal` for these reports. Use the final verified transactions' signed entries, selecting by each posting's `effective_at` in the requested UTC interval. A sale of 100 in January and refund of 20 in February yield January activity +100 and February activity -20, as known at the current read. A later correction can change a reread; this is not a historical, immutable accounting close. Counts of pending, held and reconciliation items describe the whole client calculation and are explicitly labeled `scope=all_evidence`, not falsely restricted to the display period.

Report captured, refunded, charged back, reversed, corrected and net per original currency; use operation kinds and signs from the ledger contract. Preserve the ledger's currency-exponent consistency checks before combining entries; the same currency code with conflicting exponents must fail explicitly, never be summed by code alone. Declared totals remain a separate unverified block and use their declared effective time and the existing declaration deduplication rules. No raw-evidence totals, duplicated agreeing evidence, pending refund impact, cross-order Paymob refund impact, booking revenue or CRM-won revenue without the verified ledger. A ledger with unresolved items exposes them even when a currently retained posting contributes to totals.

Spend aggregates existing valid daily facts for one connection and account-local interval. Keep every `(level object ID, currency)` group, including a null object ID. Preserve refusal counters, source coverage, currency changes and provisional dates. No implicit exchange rates or summed EGP/USD total. The report cannot derive attributed revenue by dividing or allocating recorded client revenue across ads. A real ROAS report is 016-B work.

## 5. Consistency, limits and pagination

Use a separate short read-only Repeatable Read transaction for report inputs. Authentication can have its own session writes; configure isolation before the report transaction's first statement. Read the full bounded input set once, compute full filtered totals before slicing pages, and close the transaction promptly. Do not keep transactions or result sets across HTTP requests.

Compute `revision` from canonical report inputs: authenticated principal identity, agency/client, permission class, normalized query excluding pagination/format, contract/catalog version, relevant source IDs/generations, facts and source status. Include both comparison periods. Exclude the response's generation clock; include semantic states whose change affects the result. Recompute against currently authorized data on every request. A hash is an equality check, not a bearer credential, signature, or authorization grant.

Use deterministic ordering and an integer page index starting at 1. Social keys include connection, stream, metric, date/content ID and any grouping dimensions; spend keys include level/object ID and currency; revenue keys include currency, date and operation kind for aggregate rows. Sorting must distinguish all output groups. Later pages require `expected_revision`; any mismatch returns `409 report_changed` with no rows or totals. A changed filter, principal, permission or data revision cannot reuse a page position. CSV may accept `expected_revision` to export exactly the current JSON result revision, or omit it to request a fresh complete report.

At most 10,000 selected source rows for social/spend across both periods; fetch at most cap + 1 and reject excess with `422 report_too_large` before claiming totals. Count all input facts, including refused/unavailable facts, rather than only valid monetary rows. Page size is 1-500, default 100. Financial input cap is 200 whole-client evidence rows. CSV caps are 5,000 output rows and 2 MiB encoded bytes including headers/metadata rows. Exceeding a bound fails the entire request, never returns a deceptively complete prefix. Request deadlines and measurement evidence must demonstrate bounded failure without weakening existing API behavior.

Before releasing the buffered body, perform a fresh authorization and source-validity read outside the original data snapshot. Recheck active client/agency, membership/credential grants, connection ownership/status/generation and relevant source revision. A deletion/disconnection or changed source set observed at this check rejects the old result; concurrent ordinary updates return `report_changed` for a retry. Tests must coordinate these races explicitly. The security boundary is the final release check; no API can recall bytes already delivered after a later revocation.

## 6. CSV and privacy

CSV uses the same report calculation, filters and current permission checks as JSON, without pagination. Serialize a fixed long-form schema containing row type (value, total or status), family, source/stream, native period/zone, basis, metric, unit, currency, date, object identifier when approved, value, availability, coverage, freshness and provisional state. Every total/status represented in the JSON result must remain understandable in CSV; use typed status rows for unresolved counts and missing-source reasons. Give comparison rows a fixed current/previous period label. Publish exact columns and fixtures during implementation review.

Use the standard library CSV writer with explicit quoting and newline rules. All textual cells come from closed enums, canonical dates/timezones or approved identifiers prefixed `id:`; validate timezone strings against the accepted timezone database. Numeric cells are generated from validated numbers, never user text; signed negative financial amounts remain valid numbers. Names, captions, URLs, manual reasons and arbitrary provider text are excluded. Reject unexpected types instead of falling back to `str(payload)`. Test delimiter/newline and formula-prefix identifiers, Unicode variants and encoded byte limits. This protects the defined export; it does not promise safety after arbitrary spreadsheet edits or resaving.

Build bounded bytes in memory and perform the release check before sending headers/body; do not start a streaming response before authorization is complete. Use a fixed server-generated download filename, attachment content disposition and `Cache-Control: no-store`. Do not log content, values, identifiers or revision input payloads. Operational logs may record report family, outcome, duration and row-count buckets under existing logging rules.

There are no retained artifacts, public URLs, tokens, caches or background generation jobs. Deleted source data cannot be served from an old server cache. Files already downloaded by an authorized user are outside server revocation. This slice therefore does **not** close the retained-export/cache invalidation tests assigned by D-025 or full Spec 016 AC5. 016-C must design artifact ownership, encryption, access-time authorization, expiry, deletion and key rotation before adding storage or download links.

## 7. Acceptance boundary

No new migration, table, dependency, role or provider call is proposed. Existing source lifecycles and current APIs retain their contracts. Relevant disposable-database, unit, contract and API tests must pass, including the [verification matrix](verification-matrix.md). OpenAPI and the engineering guide must describe only implemented routes. A successful 016-A review records a completed slice and keeps 016-B/C and their predecessor work open.

## 8. Implementation choices (revision 2, D-072)

The implementation follows sections 1 to 7. Where they left a choice open, it made the following ones; the [reporting guide](../../docs/engineering/reporting.md) is the reference for the observable behavior.

- **Catalog.** The complete catalog is the table in the guide, and a unit test compares it with every Instagram and YouTube adapter.
  - Instagram `follows_and_unfollows` is unreviewed and unsupported: without the follow_type breakdown its total mixes follows and unfollows.
  - YouTube channel statistics and the public `videos` counters are snapshots, listed as excluded.
  - Instagram `profile_links_taps` and YouTube `dislikes`, `engagedViews` and the playlist counts are additive daily counts.
  - Day zones, data delays and freshness windows are part of the catalog and equal the adapters' values, so stored data stays reportable, labeled `adapter_state: unavailable`, while an adapter is switched off.
- **Social parameters.** `view` is required. An optional `metrics` list narrows the view; an unknown or non-reportable name is refused. A content cohort with `compare=previous` is refused before any input is read.
- **Content cohorts.**
  - Cohort totals sum lifetime counts across content, with the range of fetch times. They are complete only with a value for every applicable content item and a proven inventory.
  - YouTube publication times come from the `published_at` attribute of the `videos` stream. A video without one is counted as `publication_unknown` and makes the inventory unproven. A listed video without a totals record is `missing` (`no_record`).
- **Freshness.** Each stream's freshness is its latest successful run against the family window. Coverage is that stream's own checkpoint; a checkpoint with a cursor is reported as a read in progress and blocks comparisons (`sync_in_progress`).
- **Spend.** Object and account names and the account ID are not reported. A period without facts has an empty totals list and the reason `no_spend_facts`. Facts in a zone other than the account's current zone make the totals partial (`time_zone_changed`).
- **Revenue.**
  - Verified totals are given for every currency of the client's verified transactions, so a quiet period shows zero activity computed by the complete calculation.
  - Declarations form a separate block of sales and refunds; another declared kind is refused (`unsupported_declaration`).
  - Rows aggregate by block, currency, date and kind.
- **Revision.** The revision digests the principal, the scope, the normalized query, the versions, the connection generation and status, a canonical digest of every input row and status, and the clock-dependent states (provisional records, freshness and synchronization states). The response body itself is not hashed.
- **Release check.**
  - A fresh read-only snapshot resolves the scope again and recomputes the input digest. For revenue only the evidence digest is recomputed, since evidence is append-only, and the ledger is not recalculated.
  - A bound exceeded at release answers `report_changed`.
  - Tests reach this point through the hook `app.services.reporting.before_release`.
  - Every source query is also scoped by agency and client, in addition to the connection.
- **Periods** are limited to 2000-01-01 through 2100-01-01.
- **Error codes:**
  - `422`: `unknown_parameter`, `invalid_period`, `unsupported_metric`, `comparison_unsupported`, `csv_pagination_unsupported`, `revision_required`, `invalid_page`, `not_a_social_connection`, `not_a_spend_connection`, `report_too_large` and `export_too_large`.
  - `409`: `report_changed`, `source_unavailable`, `report_requires_ledger_upgrade`, `currency_exponent_conflict` and `unsupported_declaration`.
  - `500`: `export_refused`.
  - Access errors keep the existing codes.
- **CSV.** One fixed schema of 37 columns, listed in the guide. Spend values have one record per group and metric. The 5,000-record bound counts every record after the header; the byte bound counts the encoded file including the header.

## 9. D-073 correction clarification

Full daily values do not by themselves establish completed source coverage. Daily totals require the complete coverage range and no partial synchronization; a pending page also makes spend totals partial. Unknown content product types cannot prove that a metric is inapplicable, so the known subtotal stays partial, while known inapplicable products remain excluded. CSV period metadata is mandatory even for empty reports. Contract `016a.2` gives these corrected outputs a new revision identity; the metric catalog is unchanged. These corrections enforce D3, D6, D7 and D9 without changing product scope or storage.
