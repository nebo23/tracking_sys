# Reports over stored facts (specification 016-A)
Status: 016-A is implemented under D-072 (decisions D1-D12 of the [entry review](../../specs/016-analytics-reporting/entry-review.md)) with synthetic fixtures on disposable PostgreSQL; see the [evidence](../../specs/016-analytics-reporting/evidence.md). It reads only stored facts: no provider call, no synchronization, no new table, cache, stored file, download link or job. Attribution, funnels, content revenue and ROAS (016-B) and retained, scheduled and white-label reports (016-C) are not implemented, and every report says so in `dependencies`.

## Routes and permissions
Three read-only routes per client, all `GET`:

| Route | Family | Permission | Source |
|---|---|---|---|
| `/agencies/{agency_id}/clients/{client_id}/reports/social` | social | `client:read` | one Instagram or YouTube connection (`connection_id`) |
| `/agencies/{agency_id}/clients/{client_id}/reports/spend` | spend | `finance:read` | one spend connection (`connection_id`) |
| `/agencies/{agency_id}/clients/{client_id}/reports/revenue` | revenue | `finance:read` | the client's revenue ledger |

Browser sessions and read service keys follow the existing scope rules: managers read every active client of their agency; analysts and client viewers need a client grant, and `finance:read` needs that grant's financial flag. A read key needs its own client grant, with the financial flag for spend and revenue. Ingest keys are refused (`401`). A foreign or unknown client or connection answers `403 access_denied`, so a caller cannot tell them apart. A social report never carries an amount, a currency or another financial field. There is no agency-wide report and no combined social and financial report.

## Parameters
| Parameter | Families | Meaning |
|---|---|---|
| `start`, `end` | all | Calendar dates; `start` is included and `end` excluded. At most 31 days, between 2000-01-01 and 2100-01-01. |
| `compare=previous` | all | Adds the period of equal length that ends at `start`. Refused for a content cohort (`comparison_unsupported`). |
| `connection_id` | social, spend | A connection of the same client. |
| `view=daily\|content_cohort` | social | Required. |
| `metrics` | social | Optional comma-separated metric names; each must be a reportable metric of the view (`unsupported_metric`). |
| `level=ad\|adset\|campaign` | spend | Default `ad`. |
| `page`, `page_size` | all (JSON) | Page from 1, size 1-500 (default 100). |
| `expected_revision` | all | The `revision` of an earlier answer. Required for any page after the first. |
| `format=json\|csv` | all | CSV refuses `page` and `page_size`. |

An unknown or repeated parameter answers `422 unknown_parameter`; there is no time zone parameter and no "as of" parameter. Each source uses its own day: Instagram UTC, YouTube `America/Los_Angeles`, spend the ad account's stored zone, revenue UTC. Daily aggregates are never rebucketed into another zone, and daylight-saving days stay single calendar days.

## Answer
Every JSON answer has `contract_version` (`016a.2`), `family`, `client_id`, `connection_id` where one applies, `period` and `comparison_period`, `day_zone`, `basis`, `generated_at`, `revision`, `totals`, `comparison`, `rows`, `page`, a status block and `dependencies`. Totals and comparisons always cover the complete filtered result; pages slice only `rows`. Money is `{"minor": <integer>, "decimal": "<text>"}` with the currency and its exponent. Percentages are exact decimal text rounded half-even to two places.

Availability, coverage, freshness and provisional status are separate fields:

- **Availability** of a value: `available`, `missing` (with the stored reason, such as `not_returned` or `below_threshold`, or `no_record`, `invalid_value`, `conflicting_records`), `unsupported` (`product_type`, `product_type_unknown`) or `not_synced` (`outside_coverage`). A zero appears only when it is stored or follows from the complete ledger calculation.
- **Total status**: `complete`, `partial` (a labeled subtotal with the reason, for example `incomplete_days`, `incomplete_contents`, `inventory_unproven`, `coverage_incomplete`, `refused_facts`, `time_zone_changed`) or `unavailable` (value `null`, for example `non_additive`, `definition_changed`, `no_content`, `missing`, `not_synced`).
- **Coverage** of each stream comes from that stream's own checkpoint, never from another stream or the connection.
- **Freshness** of each stream is its latest successful run against the family's window (Instagram 24 hours, YouTube 36, spend 48): `fresh`, `stale` or `never_synced`. The connection's last successful synchronization is reported only as `connection_last_successful_sync_at`.
- **Provisional** values are inside the stream's data delay (Instagram 48 hours, YouTube channel days 193 hours) or before the record's own provisional end; a complete total can be provisional.
- `adapter_state` is `unavailable` when the provider adapter is switched off or its rules lapsed; stored data stays reportable with that label.

A comparison has `current_value`, `previous_value`, both statuses, `difference`, `percent_change`, `comparable` and `reason`. Difference and percentage are given only for additive values whose periods are both complete, final, fresh and of one definition, with no read between pages. Otherwise both stay `null` with the first applicable reason: `definition_changed`, `non_additive`, `unavailable`, `partial`, `provisional`, `stale`, `sync_in_progress`. A zero baseline keeps the difference and gives `percent_change: null` with `zero_baseline`.

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
Facts of one connection on account-local dates. Rows group valid facts by the complete key (level object ID, currency), including a missing object ID; totals are per original currency; refused facts are counted per reason, never valued. A total is `complete` only when the `ad_daily` coverage holds the whole period, no fact was refused and every fact uses the account's current zone. A period without facts answers an empty `totals` list with `no_spend_facts`, never a zero. Names of accounts and objects are not reported. The report never allocates client revenue to ads.

## Revenue
The complete 007-A calculation over every stored evidence record of the client, with the D-070 held Paymob refunds kept out, exactly as the ledger read derives it. Dates are never filtered before the calculation. The report then selects the final verified transactions' signed entries whose effective time falls on the requested UTC dates: a January sale of 100 refunded by 20 in February gives +100 in January and -20 in February, as known at this read. A later receipt can change a reread; nothing here is an immutable close.

- `totals` has a `verified` block per currency (captured, refunded, charged back, reversed, corrected, net and posting count) for every currency the ledger holds, and a separate `declared` block (unverified declarations: sales, refunds and item count).
- `rows` aggregate by block, currency, date and operation kind; no operation, delivery or source reference, actor or reason is reported.
- `unresolved` counts pending, held and reconciliation items of the whole client (`scope: all_evidence`), with `external_completeness: unknown`.
- One currency code with two exponents answers `409 currency_exponent_conflict`. The prefix journal is never evaluated.

## Consistency, pages and release
1. The route resolves the caller's scope with the family's permission.
2. All inputs, counts and statuses of both periods are read once in a separate `READ ONLY` `REPEATABLE READ` transaction, scoped by agency, client and connection.
3. The complete result is computed, and its `revision` is the SHA-256 digest of the principal, agency, client, permission, normalized query (without page or format), contract and catalog versions, connection generation and status, the input digest and the clock-dependent states (provisional and freshness). A different `expected_revision` answers `409 report_changed` with no rows or totals.
4. A fresh snapshot then resolves the scope again and rereads the inputs. Revoked access (`403` or `401`), an archived client (`403`), a connection that is no longer active (`409 source_unavailable`) or any changed, added or deleted input (`409 report_changed`) refuses the response; no byte of the result is sent. The hook `app.services.reporting.before_release` lets tests change data at that point.

A revision is an equality check, not a credential or signature. A file already downloaded cannot be recalled.

## Bounds
| Bound | Value | Excess |
|---|---|---|
| Social or spend source rows across both periods (refused facts included) | 10,000 | `422 report_too_large` |
| Revenue evidence records of the whole client, counted before the calculation | 200 | `409 report_requires_ledger_upgrade` |
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

Names, titles, URLs, free text, reasons entered by people, actors, payloads, personal identifiers and secrets have no column. A cell of an unexpected type is refused (`500 export_refused`), never converted with `str()`. The file is safe as generated; this is no claim about a file after spreadsheet edits.

## Tests
- Unit: `pytest tests/test_reporting.py` (catalog against every adapter, periods and daylight saving, aggregation, comparisons, spend, revenue, CSV cells and bounds).
- Integration on the disposable database: `tests/integration/test_reports.py` (V01-V13, V15-V17, V19) and `tests/integration/test_report_bounds.py` (V14, V15, V18). With `REPORT_MEASUREMENTS=<file>`, the bound cases append their time, size and statement count as JSON lines.

## Not covered by 016-A
- Attribution, funnels, content revenue, model comparisons and ROAS: 016-B, after 006, 007-B/C and persisted 008.
- Retained or revocable exports, scheduled and white-label reports, and the 003 export-deletion obligations: 016-C.
- Snapshot views, agency-wide rollups, segmentation beyond connection, metric, date and level, and LinkedIn and X (deferred by D-063).
- Production limits and freshness objectives: Q-004 and Q-011.

## Independent review corrections (D-073, 2026-11-23)

Contract `016a.2` labels daily totals partial when coverage is absent or incomplete and labels social/spend subtotals `sync_in_progress` while a checkpoint has another page. These states cannot produce a percentage comparison. A content item with an unknown product type keeps the known lifetime subtotal partial (`product_type_unknown`); a known product that does not offer a metric remains legitimately excluded. Every CSV includes explicit current/previous period metadata, even when there are no revenue rows or totals. The catalog remains `016a.1`. See the [independent review](../../specs/016-analytics-reporting/merge-review-2026-11-23.md).
