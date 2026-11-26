# Reports over stored facts (specification 016-A and 016-B)
Status: 016-A is implemented under D-072 (decisions D1-D12 of the [entry review](../../specs/016-analytics-reporting/entry-review.md)); see its [evidence](../../specs/016-analytics-reporting/evidence.md). 016-B, the attribution, ROAS and funnel reports over the credit that 008-B stores, is implemented under D-089 (decisions D1-D14 of the [016-B entry review](../../specs/016-analytics-reporting/entry-review-016b.md)); see its [design note](../../specs/016-analytics-reporting/design-016b.md) and [evidence](../../specs/016-analytics-reporting/evidence-016b.md). Both use synthetic fixtures on disposable PostgreSQL and read only stored facts: no provider call, no synchronization, no worker pass, no new table, cache, stored file, download link or job. Retained, scheduled and white-label reports (016-C) are not implemented.

## Routes and permissions
Six read-only routes per client, all `GET`:

| Route | Family | Permission | Source |
|---|---|---|---|
| `/agencies/{agency_id}/clients/{client_id}/reports/social` | social | `client:read` | one Instagram or YouTube connection (`connection_id`) |
| `/agencies/{agency_id}/clients/{client_id}/reports/spend` | spend | `finance:read` | one spend connection (`connection_id`) |
| `/agencies/{agency_id}/clients/{client_id}/reports/revenue` | revenue | `finance:read` | the client's revenue ledger |
| `/agencies/{agency_id}/clients/{client_id}/reports/attribution` | attribution | `client:read`; sale values also `finance:read` | the client's stored credit |
| `/agencies/{agency_id}/clients/{client_id}/reports/roas` | roas | `finance:read` | one spend connection and the stored credit |
| `/agencies/{agency_id}/clients/{client_id}/reports/funnel` | funnel | `client:read`; sale values also `finance:read` | link-tagged page views and the stored credit |

Without `finance:read`, the attribution and funnel reports keep lead credit and visits and answer sales, revenue and the reconciliation as `permission_unavailable`, with no currency, amount or sale count. Only lead credit then shapes the groups, so a group that holds sale credit alone is not listed, counted or exported (R016B-02, D-090); the flag is part of the revision and is checked again before release. The person-level conversions list (`/attribution/conversions`) is described in the [attribution guide](attribution.md#reading).

Browser sessions and read service keys follow the existing scope rules: managers read every active client of their agency; analysts and client viewers need a client grant, and `finance:read` needs that grant's financial flag. A read key needs its own client grant, with the financial flag for spend and revenue. Ingest keys are refused (`401`). A foreign or unknown client or connection answers `403 access_denied`, so a caller cannot tell them apart. A social report never carries an amount, a currency or another financial field. There is no agency-wide report and no combined social and financial report.

## Parameters
| Parameter | Families | Meaning |
|---|---|---|
| `start`, `end` | all | Calendar dates; `start` is included and `end` excluded. At most 31 days, between 2000-01-01 and 2100-01-01. |
| `compare=previous` | all | Adds the period of equal length that ends at `start`. Refused for a content cohort (`comparison_unsupported`). |
| `connection_id` | social, spend, roas | A connection of the same client. |
| `view=daily\|content_cohort` | social | Required. |
| `metrics` | social | Optional comma-separated metric names; each must be a reportable metric of the view (`unsupported_metric`). |
| `level=ad\|adset\|campaign` | spend, roas | Default `ad`. |
| `group_by` | attribution (`campaign`, `content`, `link`, `recipient`), funnel (`campaign`, `content`, `link`) | Default `campaign`. |
| `view=groups\|models` | attribution | Default `groups`; `models` shows every active model version and refuses `compare` and `model_version`. |
| `model_version` | attribution, roas, funnel | A model version of the client; the client's default when omitted. A foreign or unknown one answers `403`. |
| `page`, `page_size` | all (JSON) | Page from 1, size 1-500 (default 100). |
| `expected_revision` | all | The `revision` of an earlier answer. Required for any page after the first. |
| `format=json\|csv` | all | CSV refuses `page` and `page_size`. |

An unknown or repeated parameter answers `422 unknown_parameter`; there is no time zone parameter and no "as of" parameter. Each source uses its own day: Instagram UTC, YouTube `America/Los_Angeles`, spend the ad account's stored zone, revenue UTC. Daily aggregates are never rebucketed into another zone, and daylight-saving days stay single calendar days.

## Answer
Every JSON answer has `contract_version` (`016b.1`), `family`, `client_id`, `connection_id` where one applies, `period` and `comparison_period`, `day_zone`, `basis`, `generated_at`, `revision`, `totals`, `comparison`, `rows`, `page`, a status block and `dependencies`. Totals and comparisons always cover the complete filtered result; pages slice only `rows`. Money is `{"minor": <integer>, "decimal": "<text>"}` with the currency and its exponent. Percentages are exact decimal text rounded half-even to two places.

Availability, coverage, freshness and provisional status are separate fields:

- **Availability** of a value: `available`, `missing` (with the stored reason, such as `not_returned` or `below_threshold`, or `no_record`, `invalid_value`, `conflicting_records`), `unsupported` (`product_type`, `product_type_unknown`) or `not_synced` (`outside_coverage`). A zero appears only when it is stored or follows from the complete ledger calculation.
- **Total status**: `complete`, `partial` (a labeled subtotal with the reason, for example `incomplete_days`, `incomplete_contents`, `inventory_unproven`, `coverage_incomplete`, `refused_facts`, `time_zone_changed`) or `unavailable` (value `null`, for example `non_additive`, `definition_changed`, `no_content`, `missing`, `not_synced`).
- **Coverage** of each stream comes from that stream's own checkpoint, never from another stream or the connection.
- **Freshness** of each stream is its latest successful run against the family's window (Instagram 24 hours, YouTube 36, spend 48): `fresh`, `stale` or `never_synced`. The connection's last successful synchronization is reported only as `connection_last_successful_sync_at`.
- **Provisional** values are inside the stream's data delay (Instagram 48 hours, YouTube channel days 193 hours) or before the record's own provisional end; a complete total can be provisional.
- `adapter_state` is `unavailable` when the provider adapter is switched off or its rules lapsed; stored data stays reportable with that label.

`dependencies` lists the capabilities `attribution`, `content_revenue`, `funnels` and `roas`, each `available` with the `family` that serves it (`attribution`, `attribution`, `funnel`, `roas`) and the specifications it `requires`. Before 016-B these were `dependency_unavailable`.

A comparison has `current_value`, `previous_value`, both statuses, `difference`, `percent_change`, `comparable` and `reason`. Difference and percentage are given only for additive values whose periods are both complete, final, fresh and of one definition, with no read between pages. Otherwise both stay `null` with the first applicable reason: `definition_changed`, `non_additive`, `unavailable`, `sync_in_progress`, `partial`, `provisional`, `stale`. A zero baseline keeps the difference and gives `percent_change: null` with `zero_baseline`.

## Metric catalog
The closed catalog (`app.reporting.catalog`, version `016a.1`) classifies every metric the adapters store; a unit test compares it with the synthetic and live Instagram and YouTube adapters. Only additive counts total.

| Family and stream | Metric class | Metrics |
|---|---|---|
| Instagram `account` (daily, UTC) | daily_additive | `views`, `total_interactions`, `likes`, `comments`, `shares`, `saves`, `replies`, `profile_links_taps` |
| | daily_non_additive | `reach`, `accounts_engaged` |
| | unreviewed (excluded) | `follows_and_unfollows` (one total mixes follows and unfollows) |
| Instagram `media` (feed and reels, lifetime) | lifetime_additive | `views`, `likes`, `comments`, `saved`, `shares`, `total_interactions`, `profile_visits`, `follows`, `ig_reels_video_view_total_time` |
| | lifetime_non_additive | `reach` |
| | ratio | `ig_reels_avg_watch_time`, `reels_skip_rate` |
| Instagram `stories` (lifetime) | lifetime_additive | `views`, `shares`, `total_interactions`, `profile_visits`, `follows`, `replies`, `navigation` |
| | lifetime_non_additive | `reach` |
| YouTube `channel_daily` (daily, Pacific) | daily_additive | `views`, `engagedViews`, `estimatedMinutesWatched`, `likes`, `dislikes`, `comments`, `shares`, `subscribersGained`, `subscribersLost`, `videosAddedToPlaylists`, `videosRemovedFromPlaylists` |
| | ratio | `averageViewDuration`, `averageViewPercentage` |
| YouTube `video_totals` (lifetime) | lifetime_additive | the same counts as `channel_daily` |
| | ratio | `averageViewDuration`, `averageViewPercentage` |
| YouTube `channel`, `videos` | snapshot (excluded) | `subscriberCount`, `viewCount`, `videoCount`; `viewCount`, `likeCount`, `commentCount` |

Each media metric applies only to the product types its adapter declares; another product type, or none, is `unsupported`. YouTube `views` changed definition on 2025-04-30, 2026-08-27 and 2026-11-16 (the public counters on 2025-03-31, 2026-08-27 and 2026-11-16): rows carry `definition_since`, a change inside a period makes its total `definition_changed`, and a change between the compared periods blocks the comparison.

## Social views
- **daily**: the daily stream only. Every reportable metric has one row per date, ordered by stream, metric and date; a date without a record is `missing` (`no_record`) inside the stream's coverage and `not_synced` outside it. Two records on one date are `conflicting_records`. `basis` is `native_daily_activity`.
- **content_cohort**: content published on the requested native dates, with its latest stored lifetime values (`basis` `published_cohort_lifetime`). Instagram uses the publication time of media and stories records. YouTube takes `published_at` from the `videos` stream's attributes and the values from `video_totals`; a listed video without totals is `missing` (`no_record`), and a video without a publication time is counted in `publication_unknown`. Rows are ordered by stream, content ID and metric, with the publication and fetch times. Cohort totals sum lifetime counts across content and are `complete` only when every applicable content item has a value and the inventory is proven: for Instagram, the stream's coverage holds the whole period; for YouTube, both listings are complete and every video has a publication time. Values are what content earned up to its fetch time, never during the period, so a cohort is never compared.

## Spend
Facts of one connection on account-local dates. Rows group valid facts by the complete key (level object ID, currency), including a missing object ID; totals are per original currency; refused facts are counted per reason, never valued. A total is `complete` only when the `ad_daily` coverage holds the whole period, no synchronization page is pending, no fact was refused and every fact uses the account's current zone. A period without facts answers an empty `totals` list with `no_spend_facts`, never a zero. Names of accounts and objects are not reported. The report never allocates client revenue to ads.

## Revenue
The complete 007-A calculation over every stored evidence record of the client, with the D-070 held Paymob refunds kept out, exactly as the ledger read derives it. Dates are never filtered before the calculation. The report then selects the final verified transactions' signed entries whose effective time falls on the requested UTC dates: a January sale of 100 refunded by 20 in February gives +100 in January and -20 in February, as known at this read. A later receipt can change a reread; nothing here is an immutable close.

- `totals` has a `verified` block per currency (captured, refunded, charged back, reversed, corrected, net and posting count) for every currency the ledger holds, and a separate `declared` block (unverified declarations: sales, refunds and item count).
- `rows` aggregate by block, currency, date and operation kind; no operation, delivery or source reference, actor or reason is reported.
- `unresolved` counts pending, held and reconciliation items of the whole client (`scope: all_evidence`), with `external_completeness: unknown`.
- One currency code with two exponents answers `409 currency_exponent_conflict`. The prefix journal is never evaluated.

## Attribution
The stored credit changes of the published generation, aggregated in SQL by period, model version, recipient class, grouped reference, kind, currency and share denominator; shares are added exactly as fractions. The basis is the conversion date (the sale's effective time or the lead's time) on UTC dates; it is never added to the revenue report's posting dates.

- `view=groups` names one `model_version` and gives one row per group: `recipient` (`campaign`, `direct`, `unknown`), `group_ref` (the campaign code or retained `utm_campaign` value, the content code or retained `utm_content` value, or the managed link ID), `registered` (whether a link campaign, content reference or managed link of the client has that code), `content_items` (content groups only: the stored Instagram or YouTube items of the client with exactly that ID, by connection, provider and stream), `sales` per currency (`credited_revenue`, `credited_sales`, `conversions`) and `leads` (`credited_leads`, `conversions`). Direct and unknown credit are always rows of their own; campaign credit without the grouped reference is a campaign row with no `group_ref`. A group whose credit nets to nothing is left out.
- `view=models` gives the same groups with one entry per active version in `models`, and `model_totals` and `model_reconciliation` per version; versions are never added up.
- `totals` has `sales` (per period, currency and recipient class `all`, `campaign`, `direct`, `unknown`) and `leads` (per period and recipient class); lead credit has no currency.
- `reconciliation` compares credited revenue with the verified net of the period's sales in the persisted ledger, per currency, a negative net counted as zero: `reconciled`, or `difference` with `attribution_behind`, `attribution_rebuilding`, `attribution_failed` or `unexplained_difference`; `unavailable` (`ledger_unavailable`) while the ledger is behind its evidence.
- `attribution` reports `state` (`caught_up`, `behind`, `rebuilding`, `failed`), the published generation and time, and the consumer and current watermarks. Before the first publication every value is null with `attribution_not_ready`, never 0; while not caught up, values come from the published generation and no comparison percentage is authoritative.
- `comparison` (groups view) covers the totals: `credited_revenue`, `credited_sales` and `sale_conversions` per currency, `credited_leads` and `lead_conversions`.

## ROAS
One spend connection on the ad account's local dates, from `app.advertising.roas.roas_from_credit`, which shares the 014-C row rules and roll-up with `roas_report`. Credit matches an ad when its content reference is an ad ID stored under the connection (its ad objects and spend facts) and its campaign reference equals that ad's campaign ID; the traffic source is not stored, so it is not tested. Rows at the requested level carry `spend`, `credited_revenue`, `roas` (`zero_spend`, `currency_mismatch`), `spend_state` (`complete`, `provisional`, `incomplete`), `credited_leads` and `cost_per_lead` (spend in minor units per credited lead, with a decimal text in the spend currency; `zero_leads`, `zero_spend`, `currency_mismatch`). `totals` applies the same rules to every ad of the connection (`level: account`), `unmatched` and `unmatched_leads` hold the credit that matches no ad (direct and unknown credit included), and `spend_source` is the 016-A spend status. A connection without any zone answers `409 day_zone_unknown`. Before the first publication the credit values are null with `attribution_not_ready`; spend stays as stored.

## Funnel
Four stages per campaign, content or link and for the client, each with its basis in `bases`: tracked visits (`received_date`) and credited leads, sales and revenue (`conversion_date`). A tracked visit is a stored page view of the client with a link ID that is not marked, counted on its UTC received date; every stored event has a consent basis, and traffic labels are not filtered. A visit takes the reference that the input adapter gives its touches: the link's registered campaign or content code, else the `utm_campaign` or `utm_content` value of its UTM snapshot (R016B-01, D-090). A group whose reference no managed link of the client carries in either way has `visits: unsupported` with a null count; direct and unknown rows always do. `totals` per period holds `page_views`, `link_page_views`, the lead credit and conversions, and per currency the credited sales and revenue, the sale conversions (associated and unassociated) and the ledger's verified net. There is no rate between stages: visits count page views, while leads and sales are credited conversions.

## Consistency, pages and release
1. The route resolves the caller's scope with the family's permission.
2. All inputs, counts and statuses of both periods are read once in a separate `READ ONLY` `REPEATABLE READ` transaction, scoped by agency, client and connection.
3. The complete result is computed, and its `revision` is the SHA-256 digest of the principal, agency, client, permission, normalized query (without page or format), contract and catalog versions, connection generation and status, the input digest and the clock-dependent states (provisional and freshness). A different `expected_revision` answers `409 report_changed` with no rows or totals.
4. A fresh snapshot then resolves the scope again and rereads the inputs. Revoked access (`403` or `401`), an archived client (`403`), a connection that is no longer active (`409 source_unavailable`) or any changed, added or deleted input (`409 report_changed`) refuses the response; no byte of the result is sent. The hook `app.services.reporting.before_release` lets tests change data at that point.

For the attribution, ROAS and funnel families, the inputs digest holds the consumer state's tokens (generation, version, scrub epoch, status and watermarks), the 008-B status read, the model versions (with the default flag), the ledger position, the registered flags and content items of the result's groups, and the 016-A spend inputs with the ad objects (ROAS) or the visit counts (funnel). Stored credit at a published generation changes only with the consumer version, so the release check rereads these tokens instead of aggregating again; a worker pass, a scrub, a changed default model, a changed spend fact or a new visit answers `report_changed`, and a revoked grant `access_denied`.

A revision is an equality check, not a credential or signature. A file already downloaded cannot be recalled.

## Bounds
| Bound | Value | Excess |
|---|---|---|
| Social or spend source rows across both periods (refused facts included) | 10,000 | `422 report_too_large` |
| Revenue evidence records of the whole client, counted before the calculation | 200 | `409 report_requires_ledger_upgrade` |
| Attribution groups (current period), funnel groups, or ROAS campaign and content pairs | 10,000 | `422 report_too_large` |
| Link-tagged page views of a funnel report across both periods | 50,000 | `422 report_too_large` |
| Ads stored under a ROAS connection | 10,000 | `422 report_too_large` |
| Page size | 1-500, default 100 | `422` |
| CSV records after the header | 5,000 | `422 export_too_large` |
| CSV encoded bytes including the header | 2 MiB (2,097,152) | `422 export_too_large` |

These are development bounds, not capacity targets (Q-004, Q-011). An excess fails the whole request; no prefix is returned. Measured times at each bound are in the evidence.

## CSV
`format=csv` answers `text/csv; charset=utf-8` with `Content-Disposition: attachment; filename="report-<family>.csv"`, built in memory and released only after the release check. Every record has the 37 fixed columns of `app.reporting.csv_export.COLUMNS`, in this order: `row_type`, `family`, `period`, `period_start`, `period_end`, `day_zone`, `basis`, `source`, `metric`, `unit`, `metric_class`, `currency`, `exponent`, `date`, `definition_since`, `object_id`, `product_type`, `published_at`, `fetched_at`, `timestamp`, `value`, `value_minor`, `current_value`, `previous_value`, `percent_change`, `comparable`, `availability`, `status`, `previous_status`, `reason`, `provisional`, `expected_count`, `available_count`, `missing_count`, `unsupported_count`, `not_synced_count`, `detail`.

The row types are `metadata`, `status`, `total`, `comparison` and `value`:

- Metadata includes the contract version, the revision, the generation time, the client and connection, and the source states.
- Status records hold coverage, freshness, synchronization, refusals, provisional dates, unresolved counts and `dependencies`.
- Spend values have one record per group and metric (`spend`, `impressions`, `clicks`).

Cells are typed:

- Closed codes start with a letter or digit.
- Dates and UTC instants are canonical, and zones come from the IANA database.
- Identifiers are written as `id:<identifier>`, so no identifier can start a formula.
- Numbers are generated from validated values; negative amounts stay numbers.

The 016-B families (attribution, roas, funnel) share a second fixed schema, `COLUMNS_016B` (39 columns): `row_type`, `family`, `view`, `period`, `period_start`, `period_end`, `day_zone`, `basis`, `model_version_id`, `model_version`, `model`, `model_status`, `level`, `recipient`, `group_ref`, `campaign_id`, `adset_id`, `registered`, `connection_id`, `object_id`, `source`, `metric`, `unit`, `currency`, `exponent`, `value`, `value_minor`, `numerator`, `denominator`, `count`, `current_value`, `previous_value`, `percent_change`, `comparable`, `availability`, `status`, `reason`, `timestamp`, `detail`. Every reference that can come from a URL (`group_ref`, ad, ad set, campaign and content IDs) is an identifier cell with the `id:` prefix, so a code starting with `=`, `+`, `-` or `@` is never a formula. Shares are written as their decimal text with `numerator` and `denominator`. In every family the dependency records carry the state and the serving family (`detail`).

Names, titles, URLs, free text, reasons entered by people, actors, payloads, personal identifiers and secrets have no column. A cell of an unexpected type is refused (`500 export_refused`), never converted with `str()`. The file is safe as generated; this is no claim about a file after spreadsheet edits.

## Tests
- Unit: `pytest tests/test_reporting.py` (catalog against every adapter, periods and daylight saving, aggregation, comparisons, spend, revenue, CSV cells and bounds).
- Integration on the disposable database: `tests/integration/test_reports.py` (V01-V13, V15-V17, V19) and `tests/integration/test_report_bounds.py` (V14, V15, V18). With `REPORT_MEASUREMENTS=<file>`, the bound cases append their time, size and statement count as JSON lines.
- 016-B unit: `pytest tests/test_attribution_reporting.py` (exact fractions, groups, comparisons, reconciliation, ROAS from credit against `roas_report`, cost per lead, CSV).
- 016-B integration: `test_attribution_reports.py`, `test_roas_reports.py`, `test_funnel_reports.py`, `test_attribution_conversions.py` and `test_attribution_report_bounds.py` (BV01-BV20). With `TRACKING_REPORT_MEASURE=1`, the measurement cases print one JSON line per size.

## Not covered by 016-A
- A person-cohort funnel, a channel dimension (`utm_source`, `utm_medium`) and per-group comparisons (016-B design section 11).
- Retained or revocable exports, scheduled and white-label reports, and the 003 export-deletion obligations: 016-C.
- Snapshot views, agency-wide rollups, segmentation beyond connection, metric, date and level, and LinkedIn and X (deferred by D-063).
- Production limits and freshness objectives: Q-004 and Q-011.

## Independent review corrections (D-073, 2026-11-23)

Contract `016a.2` labels daily totals partial when coverage is absent or incomplete and labels social/spend subtotals `sync_in_progress` while a checkpoint has another page. These states cannot produce a percentage comparison. A content item with an unknown product type keeps the known lifetime subtotal partial (`product_type_unknown`); a known product that does not offer a metric remains legitimately excluded. Every CSV includes explicit current/previous period metadata, even when there are no revenue rows or totals. The catalog remains `016a.1`. See the [independent review](../../specs/016-analytics-reporting/merge-review-2026-11-23.md).
