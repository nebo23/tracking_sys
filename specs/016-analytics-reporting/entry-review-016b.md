# Spec 016-B entry review: attribution reports

Prepared: 2026-11-26 under D-088.
- **Baseline:** merged `main` at `f15b6e4` (PR 16: Spec 008-B, persisted attribution).
- **Status:** approved. The owner approved D1-D14 as recommended, without amendment, on 2026-11-26 (D-089), including ROAS down to the ad with the adapter change of D7.
- **Handoff:** the [implementation handoff](implementation-prompt-016b.md) executes this packet after approval.

The decisions below are numbered within this packet. D1-D12 of the [016 entry review](entry-review.md), which D-072 approved for 016-A, stay in force and are cited as "016 D1" to "016 D12".

## 1. Intended result

A reader of one client can answer these questions from stored, revision-bound data:
- Which campaigns, content items and links earned the client's verified revenue and its leads, under a named attribution model?
- How does that credit differ between First Click, Last Click and Linear?
- What did each Meta campaign, ad set and ad return for its spend, and what did a lead cost?
- How many tracked visits, credited leads and credited sales did each campaign, content item or link bring?
- Which sales and leads make up these numbers, so that a reader with person-level access can open one and see why it was credited as it was?

Every number names its model, period, basis, currency and freshness. Direct, unknown, unmatched and missing credit stays visible as such. Nothing is recalculated on read: the reports aggregate the credit that 008-B stores.

016-B closes the four capabilities that 016-A answers as `dependency_unavailable`: attribution, content revenue, funnels and ROAS. It does not complete Spec 016: retained, scheduled and white-label reports (016-C) stay open.

## 2. Baseline on `main`

| Area | Available | Consequence for 016-B |
|---|---|---|
| 008-B stored credit | `attribution_credit_changes` holds the signed credit of every revision per model version: conversion time, kind, recipient class, campaign, content and link references, an exact share fraction and an amount in original-currency minor units. Summing the rows whose generation is at most the published one gives the current credit. A rebuild is invisible until it is published. | The reports aggregate these rows in SQL. No journey is recalculated on read, and the 200-evidence bound of the 016-A revenue report does not apply. |
| 008-B conversions and runs | Conversions carry kind, owner, conversion time and status. The runs route explains one conversion and is a person-level read. No route lists conversions. | 016-B adds the list (D11). |
| 008-B consumer state | One row per client: the published generation, its checkpoint and status. Its version changes with every write of the worker, the scrub and the lifecycle. | The state gives the freshness labels (D6) and a change token for report revisions (D10). |
| 008-B input adapter | A touch's campaign reference is the managed link's campaign code, or else the retained `utm_campaign` value. Its content reference is the managed link's content reference code only. Its source is the evidence source (`tracker` or `trusted_sender`). The event URL also retains `utm_source` and `utm_content`, which the adapter does not read. | The 014-C join (`utm_source=meta`, campaign ID, ad ID) cannot be evaluated from stored credit as it is. D7 decides. |
| 007-B ledger | `ledger_transactions` holds one row per sale of the published ledger generation, with its net and sale time. | The reports reconcile credited revenue with ledger revenue in SQL (D5). |
| 014 spend and ROAS | `ad_spend_facts` per ad and account-local day. `app/advertising/roas.py` is an in-memory contract over engine runs; it has no route. | 016-B keeps its rules and computes from stored credit (D7). |
| 016-A reports | Social, spend and revenue families with one snapshot per report, revisions, a release check, bounds and direct CSV. | 016-B follows the same contract (016 D6 to D10) and replaces the dependency states (D6). |
| 005 links and events | A managed link may name a campaign and a content reference. The redirect stores nothing. A consenting visitor's landing page view carries the link ID. Campaign labels and platform labels are free text. | Visits are known only for managed links and consenting visitors (D8). Labels stay out of reports (D4). |
| Social content (010, 011) | `connector_records` holds each content item under its provider ID, per connection. | A content reference whose code equals a stored content ID can point to that item (D4). |
| 006 identity | A person's stage is derived at read time; no stage history is stored. | No person-cohort funnel in this slice (D8). |

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product choices, not legal advice, and they leave Q-004, Q-006, Q-011 and production Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 016-B adds four read-only parts: an attribution report (credit by campaign, content, link or recipient class, with a model comparison view); a ROAS report per spend connection; a funnel report; and a person-level list of stored conversions. Phases P0-P5 run on one branch, `codex/spec-016b-attribution-reports`. Verified commits are pushed after each phase (D-051), and a pull request opens for review at the end; merge is a separate decision. 016-C, the React UI, native rollout and live providers stay outside. | Deliver the attribution report and the conversions list first, and ROAS and the funnel in a second slice: two smaller reviews, but the dashboard waits longer for ROAS and the funnel. |
| D2 Basis and periods | Credit is reported on the **conversion date**: the sale's effective time or the lead's time, as known at the current read. Dates are UTC for the attribution and funnel reports, and the ad account's local dates for ROAS (014 D11). Periods follow 016-A: start inclusive, end exclusive, at most 31 days, optional `compare=previous`. A refund in February of a January sale lowers January's credited revenue. The 016-A revenue report keeps its posting-date basis; each report names its basis, and the two are never added. | A posting-date basis for credit: closer to the revenue report, but a credit change does not store its posting time, so it needs new stored data. Longer periods (for example 92 days): more convenient, but the ROAS and funnel inputs grow and the D10 bounds need new measurements. |
| D3 Model | Every report names one model version: the one requested, or the client's default (Linear under D-079, unless an Owner or Admin changed it). The attribution report has a `models` view that shows the same period and groups under every active version side by side (PDF-038). Versions are never added together. A retired version can be requested and is labeled retired. | Default model only: simpler, but no model comparison. |
| D4 Groups and provenance | Group by `campaign`, `content`, `link` or `recipient`. A group is the stored reference: the link campaign's code or the retained `utm_campaign` value; the content reference's code (or `utm_content` under D7); the managed link's ID. Direct credit and unknown credit are always rows of their own, never hidden or spread over campaigns. Reports carry no name, label or title; the interface reads those through the links API. Each group says whether a registered campaign, content reference or link has that code. A content group whose code equals the ID of a stored content item of one of the client's social connections also names that connection and item, so the interface can show the post or video beside its revenue. The match is exact ID equality within the client, never a title. | No pointer to social content: smaller, and the interface matches content itself. A mapping table between content references and social content: more flexible, but a schema and product decision of its own. |
| D5 Values | Per group: credited revenue per original currency (exact minor units and decimal text); credited sales and credited leads as exact fractions with a 4-decimal text; and the number of conversions that hold credit in the group. Totals are per currency and per recipient class. Currencies are never added or converted (Q-006), and lead credit has no currency. A reconciliation block compares the total credited revenue with the verified net of the period's sales in the persisted ledger, per currency, and reports any difference. No conversion rate, average order value or forecast is derived. | Revenue only: smaller, but lead-generation clients have no report. |
| D6 Freshness and missing states | Every report carries the client's attribution state (`caught_up`, `behind`, `rebuilding` or `failed`), its watermarks and the publication time. Aggregate reports read the published generation only. While attribution is behind, they are served and labeled `behind`, and comparisons give no authoritative percentage. Before the first publication, values are null with the reason `attribution_not_ready`, never 0. The person-level conversions list answers the retryable `503 attribution_stale` unless attribution is caught up (008-B D8). The 016-A families then report the four capabilities as available instead of `dependency_unavailable`. | Refuse aggregate reports while behind (`503`): an outdated number is never shown, but every dashboard is empty whenever the worker is late. |
| D7 ROAS and cost per lead (amends 014 D11) | The ROAS report covers one spend connection and gives rows per ad, rolled up per ad set and campaign, under the 014-C rules: spend on the account's local dates; credited revenue on the conversion date; no value for zero spend or mixed currencies; the spend states `complete`, `provisional` and `incomplete`; unmatched credit reported apart. Rows also carry credited leads and the cost per lead: spend divided by credited leads, when leads are above zero and the spend is in one currency. Two changes make the join work with stored credit. (a) The attribution input adapter also reads the retained `utm_content` value as the content reference when the event has no managed-link content reference, as it already does for `utm_campaign`; stored conversions are rebuilt once and keep their history. (b) Credit matches an ad when its campaign reference equals the ad's campaign ID and its content reference equals the ad ID, for an ad stored under that connection. `utm_source=meta` is not tested, because the traffic source is not stored. | Campaign-level ROAS only, with no adapter change: credit matches by campaign ID alone, and ad and ad set rows are `unavailable`. Smaller, and 008-B is untouched; but there is no ROAS per creative, and one matching value is weaker evidence than two. Storing the traffic source as well gives the full D11 join, but it needs new columns and a new engine field. |
| D8 Funnel | The funnel report gives four stages per group (campaign, content or link) and for the client: tracked visits, credited leads, credited sales and credited revenue. A tracked visit is a consenting visitor's landing page view that arrived through a managed link, counted on its received date; the redirect itself stores nothing (005). A group without a managed link has `unsupported` visits, never 0. No rate between stages is reported: visits count page views of consenting visitors, while leads and sales are credited conversions, so a later stage is not a subset of an earlier one. Each stage names its basis. | No funnel in this slice: smaller, and PDF-067 stays open. A person-cohort funnel (people first seen in the period who became leads and customers) gives a true conversion rate, but it needs stored stage history and privacy thresholds, which do not exist. |
| D9 Permissions | The attribution and funnel reports need `client:read`. Their sale and revenue values and the reconciliation also need `finance:read`; without it they answer `permission_unavailable`, with no amount, currency or sale count, because customer status is a financial disclosure (as in 006). The ROAS report needs `finance:read`, like the spend report. Read service keys follow the same rules, and ingest keys are refused. The conversions list needs `identity:read`, is never open to a service key, and lists sale conversions only with `finance:read`. Every release rechecks the current scope. | Require `finance:read` for every attribution report: one rule, but members without financial access see no lead credit either. |
| D10 Consistency, pages, CSV and bounds | As 016-A (016 D7 to D10): one REPEATABLE READ snapshot per report; a revision bound to the reader, the query, the contract and the inputs, including the published attribution generation; `409 report_changed` on any change; a fresh scope and input check before release; `Cache-Control: no-store`; direct bounded CSV with fixed typed columns. References that can come from a URL are identifier cells with the `id:` prefix. The conversions list is JSON only. Development bounds: 10,000 groups per report, 10,000 spend facts, 50,000 link-tagged events, pages of at most 500, and CSV of at most 5,000 records and 2 MiB. Excess is refused explicitly, never truncated. Aggregation runs in SQL over stored credit. A3 stays open, and no SLO is set. | Retained report files or a cache: these need the 016-C artifact lifecycle first. |
| D11 Conversions list | `GET /attribution/conversions` lists the stored conversions of a period: kind, status, conversion time, the owner person when one exists, supersession and scrub state, and a summary of the latest run under the requested model version. A reader opens one through the existing runs route. Filters: period, kind, status and person. It is person-level: `identity:read`, `attribution_stale` unless caught up, a scope recheck before release, and no CSV. The list and the existing runs route also recheck the attribution change token before release, so an erasure or a worker pass that commits while an answer is being built refuses it; and the status route reads in one snapshot. These two corrections close observations O1 and O2 of the [008-B merge review](../008-attribution-engine/merge-review-008b.md). | No list: conversions stay reachable only through the database, and the runs route has no entry point in the interface. Leave O1 and O2 for a later slice: smaller, but a known gap in the person-level release stays open. |
| D12 Schema | No new table and no new column. One additive migration, `0030_reporting_indexes`, adds two indexes: stored conversions by client and conversion time, and link-tagged events by client and received time. It is tested on disposable PostgreSQL only; native rollout stays a separate decision. | No migration: both reads scan more rows as volume grows, which is acceptable only for development. |
| D13 Boundaries | Backend only, with synthetic data, disposable PostgreSQL, no new dependency and no live provider call. `attribute()` and every 008-A and 008-B safeguard stay unchanged; the only changes to 008-B are the adapter and its one-time rebuild under D7 and the two release corrections of D11. The 014-C contract is reused, not copied. The 016-A families change only in their dependency block. No agency-wide rollup, no channel dimension, no exchange rate and no person data in aggregate reports. | A channel dimension (`utm_source` and `utm_medium`) in this slice: common in dashboards, but the traffic source is not stored and needs a schema decision. |
| D14 Completion evidence | The [verification matrix](#5-verification-matrix) BV01-BV20 is executed with the existing suites, and every command and count is recorded. Each new safeguard is shown to fail its test when disabled. Costs are measured at 1,000, 10,000 and 100,000 stored credit rows. The completed branch is presented for independent review in its pull request. | Unit tests only: fast, but they would miss scope, snapshot and release behavior. |

## 4. Design for implementation after approval

The implementing model writes the exact statements, answer shapes, error codes and CSV columns in a design note (`design-016b.md`) before any code. This section is its source.

### 4.1 Routes

Below `/agencies/{agency_id}/clients/{client_id}`:

| Route | Parameters | Access |
|---|---|---|
| `GET /reports/attribution` | `start`, `end`, `group_by` (`campaign`, `content`, `link`, `recipient`), `view` (`groups` or `models`), `model_version`, `compare=previous` (groups view only), `page`, `page_size`, `expected_revision`, `format` | `client:read`; sale values need `finance:read` |
| `GET /reports/roas` | `connection_id`, `start`, `end`, `level` (`ad`, `adset`, `campaign`), `model_version`, `compare=previous`, `page`, `page_size`, `expected_revision`, `format` | `finance:read` |
| `GET /reports/funnel` | `start`, `end`, `group_by` (`campaign`, `content`, `link`), `model_version`, `compare=previous`, `page`, `page_size`, `expected_revision`, `format` | `client:read`; sale values need `finance:read` |
| `GET /attribution/conversions` | `start`, `end`, `kind`, `status`, `person_id`, `model_version`, `after`, `limit` | `identity:read`; sales need `finance:read`; never a service key |

- An unknown or repeated parameter is refused, as in 016-A, and filters are never broadened.
- An unknown or foreign model version, connection or person answers the standard denial, with no hint that it exists elsewhere.
- The report routes reuse the 016-A error codes. The list adds `attribution_stale` (`503` with `Retry-After`).
- The conversions list pages by an opaque cursor in conversion-time order, like the identity routes.

### 4.2 Reading stored credit

- **Snapshot.** Inside the report snapshot, read the consumer state (generation, version, status, checkpoint, publication time) and the client's model versions.
- **Selection.** Aggregate the `attribution_credit_changes` rows of the client and the model version whose generation is at most the published one and whose conversion time lies in the period.
- **Exact sums.** Group by the dimension, the currency, the kind and the share denominator; sum numerators and minor units as integers in SQL; add the fractions exactly in Python. No floating point.
- **Conversions.** Count the conversions whose credit in the group does not net to zero, through `attribution_runs`.
- **Registered flags.** Look up the group codes among the client's link campaigns, content references and managed links.
- **Social content pointer.** Match content codes against `connector_records.provider_object_id` of the client's social connections in their current generation, and name every match: connection, provider, stream and content ID.
- **Not ready.** With no published generation, every value is null with `attribution_not_ready`.
- **Reconciliation.** Sum the net of the `ledger_transactions` rows of the published ledger generation whose sale time lies in the period, per currency, with a negative net counted as zero, as the worker credits it. A difference from the credited total is reported with its reason, for example `attribution_behind`. An unavailable ledger gives `unavailable`, never an amount.

### 4.3 ROAS

- **Spend.** The spend inputs, their coverage, bounds and states come from the 016-A spend read, in the same snapshot.
- **Credit.** Aggregate credited revenue and credited leads by campaign reference, content reference and currency over the account-local period.
- **Rules.** `app/advertising/roas.py` gains an entry point that takes aggregated credit and shares the row rules and roll-up with `roas_report`. A test shows that both give equal rows for the same synthetic journeys.
- **Adapter.** `attribution_inputs.touchpoints()` reads `utm_content` under the same text rule as `utm_campaign`. A managed link's content reference always wins. The class of a touch (campaign or direct) does not change.
- **Rebuild.** An input-adapter revision joins the model-set digest, so the first pass after the change rebuilds each client once. History stays; a changed reference moves credit by signed changes, and totals do not change.
- **Cost per lead.** Spend divided by credited leads as an exact fraction, with a decimal text in the spend currency; null with `zero_leads`, `zero_spend` or `currency_mismatch`.

### 4.4 Funnel

- **Visits.** Count the client's `page_view` events that carry a link ID and are not marked excluded, by received date, grouped through `managed_links` to the link, its campaign code and its content reference code.
- **Credit.** Credited leads, credited sales and credited revenue come from the attribution aggregation of 4.2.
- **Client totals.** All consented page views, those that arrived through a managed link, lead conversions, sale conversions (associated and unassociated), and the verified net of the reconciliation.
- **No rate.** The answer has no rate field.

### 4.5 Conversions list

- **Rows.** Conversions of the published generation with their conversion time in the period, newest first.
- **Barrier.** The list is built in the report snapshot and answers `attribution_stale` unless the status read of 008-B says `caught_up`. The reader's scope is resolved again before the response.
- **Change token.** After the answer is built, a fresh read compares the consumer state's generation, version and scrub epoch with those of the snapshot; a difference answers `attribution_stale`. The runs route gains the same check (O1), and the status route reads inside one snapshot (O2).
- **Scrubbed rows.** A scrubbed conversion shows no person and no lead event.
- **Finance.** Without `finance:read` only lead conversions are listed, and the answer says that sales are withheld.

### 4.6 Consistency, pages, CSV and bounds

- **Revision.** It digests the reader, the scope and permission class (with the finance flag), the normalized query, the contract version (`016b.1`), the consumer generation and version, the model versions, the ledger position, the spend input digest (ROAS) and the aggregated visit counts (funnel).
- **Release.** A fresh snapshot resolves the scope again and reads the same tokens and digests; any difference answers `report_changed`.
- **CSV.** One fixed schema per family, listed in the reporting guide. Every reference cell has the `id:` prefix; no name, label, person ID, touchpoint ID or event ID is written.
- **Dependency block.** Its `state` gains `available`, and each entry names the report family that serves it.

### 4.7 Schema

`0030_reporting_indexes`, after `0029_attribution_persistence`:
- `attribution_conversions (client_id, effective_at, id)`;
- `collected_events (client_id, first_received_at)` where `link_id` is not null.

The downgrade drops both. No data policy row changes, because no column is added.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| BV01 Isolation | Two agencies and several clients with identical campaign codes, links, ad IDs and operations: no report mixes them, and a foreign connection, model version, person or conversion answers the standard denial. |
| BV02 Permissions | Every role and grant combination: `client:read` without `finance:read` gets lead credit and visits only, with `permission_unavailable` for sales, revenue and reconciliation, and no currency or sale count. ROAS needs `finance:read`. The list needs `identity:read` and shows sales only with `finance:read`. Read keys follow the same rules and never reach the list; ingest keys are refused. |
| BV03 Credit equals stored allocations | For First Click, Last Click and Linear over the AV01 journey, the report's credit per campaign equals the latest stored allocations. Direct and unknown credit are rows of their own, an unassociated sale credits unknown, and the total reconciles with the ledger net. |
| BV04 Revisions | A refund lowers the credited revenue of the sale's own date. A late touch, an owner change and a moved sale time each leave every sale credited exactly once, on the right date. |
| BV05 Periods | Inclusive start and exclusive end at UTC midnight, to the microsecond. ROAS on account-local dates across daylight-saving days. Reversed dates, 32 days and an invalid zone are refused. |
| BV06 Comparison | The previous period has equal length. The percentage is exact; a zero baseline gives null with its reason; a behind, rebuilding, provisional or incomplete input gives no authoritative percentage. |
| BV07 Model comparison | The same cohort under every active version; each version's total reconciles; versions are never added; a retired version is labeled; an unknown version is refused. |
| BV08 Groups | Campaign, content, link and recipient groups; registered flags; a missing content reference is a group of its own; the social content pointer appears only on exact ID equality within the client; no name or label appears anywhere. |
| BV09 Currency and fractions | EGP and USD stay apart in every family. Lead credit has no currency. Thirds under Linear sum to exactly 1, and decimal texts round half-even. |
| BV10 Freshness | No published generation gives null values with `attribution_not_ready`, never 0. A behind consumer is labeled and served from the published generation. A rebuild is invisible until published, then the report changes at once. A failed consumer and an unavailable ledger are reported as such. |
| BV11 ROAS equals the contract | From stored credit, the rows equal `roas_report` for the same synthetic journeys: ads, ad sets and campaigns, zero spend, mixed currencies, provisional and incomplete spend, refused facts, unmatched credit, and an ad with credit and no spend. |
| BV12 ROAS join and adapter | A touch with the campaign ID and the ad ID is credited to the ad. A managed link's content reference wins over `utm_content`; an unusable value is ignored; an ad ID under another campaign or another account stays unmatched. The adapter change rebuilds once, keeps history byte-identical and leaves totals unchanged. |
| BV13 Cost per lead | Credited leads per ad and the cost per lead; zero leads, zero spend and mixed currencies give null with their reasons. |
| BV14 Funnel | Visits count only the client's consented landing page views with a link ID, on the received date; a marked event and another client's event are not counted; a group without a managed link has `unsupported` visits; no rate field exists; 50,000 events pass and 50,001 are refused. |
| BV15 Conversions list | `attribution_stale` while behind, and after a withdrawal until the next pass. A scrubbed conversion shows no person. Pages are stable; the person filter works; sales need `finance:read`; a service key is refused. An erasure or a worker pass that commits while the list or a runs answer is being built refuses that answer, and the status route never mixes two moments. |
| BV16 Pages and revision | Totals do not depend on the page size; every group appears once across pages; a later page without a revision is refused; a worker pass between two pages answers `report_changed`. |
| BV17 Release race | Pause between building and release: a worker pass, a scrub, a changed default model, a changed spend fact or a revoked grant refuses the response, for JSON and CSV. |
| BV18 CSV | CSV equals JSON under one revision. Fixed columns; the `id:` prefix on every reference, including values that start with `=`, `+`, `-` or `@`; 5,000 records pass and 5,001 fail; the 2 MiB bound; no name, person ID, touchpoint ID or event ID. |
| BV19 Bounds and measurements | 10,000 groups pass and 10,001 are refused before any total. The number of statements does not grow with the number of credit rows. Costs are measured at 1,000, 10,000 and 100,000 credit rows and recorded as observations. |
| BV20 Existing behavior | The 016-A families are unchanged except their dependency block. The 008 suites (AV and R008), 006, 007, 014 and 015 pass. The OpenAPI snapshot has additions only, apart from the documented dependency change. Migration `0030` upgrades a populated `0029` and downgrades. No person, token or secret appears in a log line. |
