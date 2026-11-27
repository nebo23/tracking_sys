# Spec 016-B design: attribution reports

Prepared: 2026-11-26 under D-089. Revision: 1. Status: approved scope ([D1-D14](entry-review-016b.md#3-decisions-for-the-owner), D-089, without amendment); this note fixed the exact statements, answers, states and tests before any code, and the implementation follows it (see the [evidence](evidence-016b.md), which also records one change found by the measurements: the conversion counts join by key). Section 4 of the entry review is its source. Section 11 lists the routine details resolved here; no material new choice was found that needed the owner.

Inputs confirmed on the branch (P0 inventory):

| Input | Table and columns read |
|---|---|
| Stored credit | `attribution_credit_changes`: `agency_id`, `client_id`, `model_version_id`, `generation`, `conversion_kind`, `effective_at`, `recipient`, `campaign_ref`, `content_ref`, `link_ref`, `delta_share_numerator`, `delta_share_denominator`, `delta_minor`, `currency`, `currency_exponent`. Reporting index `(client_id, model_version_id, effective_at)`. |
| Latest revisions | `attribution_runs` (`conversion_id`, `model_version_id`, `revision`, `generation`, `status`, `window_end`, `currency`, `currency_exponent`, `verified_net_minor`) and `attribution_allocations` (`run_id`, `credited`, `recipient`, provenance). |
| Conversions | `attribution_conversions`: `generation`, `kind`, `status`, `superseded_generation`, `superseded_at`, `superseded_reason`, `owner_person_id`, `lead_event_id`, `source_account_id`, `sale_operation_id`, `effective_at`, `scrubbed_at`. |
| Consumer state | `attribution_consumer_state`: `generation`, `version`, `scrub_epoch`, `status`, `failure_code`, `unit_kind`, `ledger_generation`, `receipt_ordinal`, `identity_seq`, `model_set_digest`, `published_at`; the 008-B status read (`attribution_reads.status`). |
| Model versions | `attribution_model_versions`: `id`, `version_key`, `model`, `window_seconds`, `rules`, `is_default`, `status`, `retired_at`. |
| Ledger | `ledger_store.published_state()` and `ledger_transactions` (`generation`, `currency`, `currency_exponent`, `sale_effective_at`, `net`). |
| Links and events | `link_campaigns.public_code`, `link_content_references.external_code`, `managed_links` (`id`, `campaign_id`, `content_reference_id`), `collected_events` (`event_type`, `link_id`, `first_received_at`, `identity_excluded_at`). |
| Social content | `connector_records.provider_object_id`, `stream`, `connection_generation` under `connector_connections` (`provider`, `status`, `generation`). |
| Spend | the 016-A spend read (`read_spend_inputs`) and `ad_objects` (`object_id`, `level`, `campaign_id`, `adset_id`). |

## 1. Routes, parameters and errors

Below `/agencies/{agency_id}/clients/{client_id}`:

| Route | Parameters | Access |
|---|---|---|
| `GET /reports/attribution` | `start`, `end`, `group_by` (`campaign`, `content`, `link`, `recipient`; default `campaign`), `view` (`groups`, `models`; default `groups`), `model_version`, `compare=previous`, `page`, `page_size`, `expected_revision`, `format` | `client:read`; sale values need `finance:read` |
| `GET /reports/roas` | `connection_id`, `start`, `end`, `level` (`ad`, `adset`, `campaign`; default `ad`), `model_version`, `compare=previous`, `page`, `page_size`, `expected_revision`, `format` | `finance:read` |
| `GET /reports/funnel` | `start`, `end`, `group_by` (`campaign`, `content`, `link`; default `campaign`), `model_version`, `compare=previous`, `page`, `page_size`, `expected_revision`, `format` | `client:read`; sale values need `finance:read` |
| `GET /attribution/conversions` | `start`, `end`, `kind` (`sale`, `lead`), `status` (`active`, `superseded`), `person_id`, `model_version`, `after`, `limit` (1-100, default 100) | `identity:read`; sales need `finance:read`; never a service key |

Errors reuse the 016-A codes: `unknown_parameter` and `csv_pagination_unsupported` (422) from the strict parameter check, `invalid_period` (422: reversed, empty, more than 31 days, outside 2000-2100), `invalid_page` (422), `revision_required` (422), `report_changed` (409), `report_too_large` (422, before any total), `export_too_large` (422), `export_refused` (500), `source_unavailable` (409), `not_a_spend_connection` (422) and `currency_exponent_conflict` (409). New codes:

| Code | Status | When |
|---|---|---|
| `comparison_unsupported` | 422 | `compare=previous` with `view=models` (as 016-A for content cohorts) |
| `model_version_not_applicable` | 422 | `model_version` with `view=models`, which always shows every active version |
| `day_zone_unknown` | 409 | ROAS for a spend connection with neither an ad account zone nor a connection day zone (a never-synced connection), so credit has no account-local date |
| `attribution_stale` | 503, `Retry-After: 1` | conversions list while not caught up, or when the change token moved (section 7) |
| `invalid_cursor` | 422 | a malformed conversions cursor |

A malformed enum value fails request validation (`422 validation_failed`), as for the 016-A `level`. An unknown or foreign model version, connection or person answers the standard `403 access_denied`, with no hint that it exists elsewhere.

## 2. Reading stored credit

Every report family reads its inputs in one `report_snapshot` (READ ONLY, REPEATABLE READ), as 016-A.

**Attribution context** (all three families), in this order:
1. The consumer state row of the client; absent means generation 0.
2. The 008-B status read (`attribution_reads.status`) in the same snapshot. The report state is `failed` when the consumer status is `failed`, else the status read's `caught_up`, `behind` or `rebuilding`.
3. The client's model versions (`attribution_models.versions`, no seeding: a report writes nothing). The version is the requested one, or the default. A requested ID that is not one of the client's versions is refused with `AccessDenied`. A client never processed has no version: the model is null and the values are not ready.
4. The published generation `G` of the consumer state. `G = 0` means not ready: every value is null with `attribution_not_ready`.

**Aggregation statement** (one per report; `:ref` is `campaign_ref`, `content_ref`, `link_ref` or a constant null for `recipient`; the period column splits the current and previous periods of one statement):

```sql
SELECT model_version_id,
       CASE WHEN effective_at >= :current_start THEN 'current' ELSE 'previous' END AS period,
       recipient, :ref AS ref, conversion_kind, currency, currency_exponent,
       delta_share_denominator AS denominator,
       SUM(delta_share_numerator) AS numerator, SUM(delta_minor) AS minor
FROM attribution_credit_changes
WHERE agency_id = :agency AND client_id = :client
  AND model_version_id IN (:versions)
  AND generation <= :published_generation
  AND effective_at >= :low AND effective_at < :high
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;
```

Python adds `Fraction(numerator, denominator)` per group exactly; amounts stay integers in minor units. No floating point is used anywhere. A currency code that appears with two exponents is refused with `currency_exponent_conflict`.

**Group bound** (before the aggregation, D10): `SELECT count(*) FROM (SELECT DISTINCT recipient, :ref ... current period ... LIMIT 10001)`; more than 10,000 groups answers `report_too_large`.

**Conversions per group** (a conversion holds credit in a group when its credit there does not net to zero). The reporting ledger of a conversion nets to its latest revision's credited allocations at that revision's anchor (008-B design; a moved anchor is reversed at the old date), so one statement over the latest revisions counts it exactly:

```sql
WITH latest AS (
  SELECT DISTINCT ON (conversion_id, model_version_id)
         id, conversion_id, model_version_id, status, window_end, currency, currency_exponent
  FROM attribution_runs
  WHERE agency_id = :agency AND client_id = :client AND model_version_id IN (:versions)
    AND generation <= :published_generation
  ORDER BY conversion_id, model_version_id, revision DESC)
SELECT latest.model_version_id, <period>, a.recipient, <ref of a>, c.kind,
       latest.currency, latest.currency_exponent,
       count(DISTINCT latest.conversion_id),
       count(DISTINCT latest.conversion_id) FILTER (WHERE c.owner_person_id IS NULL)
FROM latest
JOIN attribution_allocations a ON a.run_id = latest.id AND a.credited
JOIN attribution_conversions c ON c.id = latest.conversion_id
WHERE latest.status = 'complete'
  AND latest.window_end >= :low AND latest.window_end < :high
GROUP BY 1, 2, 3, 4, 5, 6, 7;
```

The totals use the same statement without the group columns. A superseded conversion's latest revision is its closing revision, so it holds nothing.

**Registered flags.** For the codes of the page-independent result, in batches of 1,000: `link_campaigns.public_code` (campaign), `link_content_references.external_code` (content) or `managed_links.id` (link) of the same agency and client. `registered` is `true` or `false`; it is null for direct, unknown and recipient groups and for campaign credit without that reference.

**Social content pointer** (content groups only), in batches of 1,000:

```sql
SELECT r.provider_object_id, r.connection_id, c.provider, r.stream
FROM connector_records r
JOIN connector_connections c
  ON c.id = r.connection_id AND c.agency_id = r.agency_id AND c.client_id = r.client_id
WHERE r.agency_id = :agency AND r.client_id = :client
  AND c.status IN ('active', 'reconnect_required')
  AND r.connection_generation = c.generation
  AND ((c.provider IN (:instagram) AND r.stream IN ('media', 'stories'))
    OR (c.provider IN (:youtube) AND r.stream IN ('video_totals', 'videos')))
  AND r.provider_object_id IN (:codes)
ORDER BY r.provider_object_id, r.connection_id, r.stream;
```

Every match is named (`connection_id`, `provider`, `stream`, `content_id`); the match is exact equality of text within the client, never a title.

**Reconciliation** (sale values, D5), per currency and period:

```sql
SELECT CASE WHEN sale_effective_at >= :current_start THEN 'current' ELSE 'previous' END,
       currency, currency_exponent, SUM(GREATEST(net, 0))
FROM ledger_transactions
WHERE agency_id = :agency AND client_id = :client AND generation = :ledger_generation
  AND sale_effective_at >= :low AND sale_effective_at < :high
GROUP BY 1, 2, 3;
```

`:ledger_generation` is the published ledger state (`published_state`); a ledger behind its evidence (`LedgerUnavailable`) gives the block `unavailable` with `ledger_unavailable`, never an amount, and a client without evidence has a ledger total of nothing. Per currency (the union of credited and ledger currencies): `credited_revenue`, `ledger_net` and `difference = credited - ledger`. The item state is `reconciled` when the difference is 0, otherwise `difference` with the reason `attribution_behind`, `attribution_rebuilding` or `attribution_failed` when the consumer is not caught up, and `unexplained_difference` when it is (for example a sale whose net the engine refuses as out of range).

## 3. Answers

Common fields of the three report families: `contract_version` (`016b.1`), `family`, `client_id`, `period`, `comparison_period`, `day_zone`, `basis` (`conversion_date`), `generated_at`, `revision`, `page`, `dependencies`, and:

- `model_version`: the 008-B version view (`id`, `version_key`, `model`, `window_days`, `rules`, `is_default`, `status`, `retired_at`), or null for a client never processed. A retired version is reported with `status: retired`.
- `attribution`: `state` (`caught_up`, `behind`, `rebuilding`, `failed`), `reason` (null, or `attribution_not_ready` when `G = 0`), `published_generation`, `published_at`, `failure_code`, the consumer watermarks (`ledger_generation`, `receipt_ordinal`, `identity_seq`, `unit`) and the current ones (`ledger`, `ledger_generation`, `receipt_ordinal`, `identity_seq`).
- `finance`: `available` or `permission_unavailable`.

Values: money is `{minor, decimal}` with the currency and exponent beside it; a share is `{numerator, denominator, decimal}` in lowest terms with a 4-decimal text rounded half-even; a ratio (ROAS, cost per lead) is the same shape. A missing value is null with a reason, never 0.

### 3.1 Attribution (`groups` view)

- `group_by`, `values` (`{state: available | not_ready, reason}`).
- `totals`: per period, `sales` (`state` `available`, `permission_unavailable` or `not_ready`; items per currency and recipient class `all`, `campaign`, `direct`, `unknown`: `credited_revenue`, `credited_sales`, `conversions`) and `leads` (`state`; items per recipient class: `credited_leads`, `conversions`). Lead credit has no currency.
- `reconciliation`: `{state, reason, ledger, items}` as section 2; `permission_unavailable` without finance.
- `comparison` (with `compare=previous`): rows per metric (`credited_revenue` and `credited_sales` per currency, `credited_leads`, `sale_conversions` per currency, `lead_conversions`) with `current_value`, `previous_value`, `difference`, `percent_change`, `comparable` and `reason`.
- `rows`: one per group, in the order recipient (`campaign`, `direct`, `unknown`), then reference ascending with the missing reference last: `recipient`, `group_ref`, `registered`, `content_items` (content groups: the pointers, possibly empty; null otherwise), `sales` (`{state, items}` per currency: `credited_revenue`, `credited_sales`, `conversions`) and `leads` (`credited_leads`, `conversions`).

Direct and unknown credit are always rows of their own. Campaign credit without the grouped reference (a link without a content reference, for example) is a campaign row with a null `group_ref`.

### 3.2 Attribution (`models` view)

The same period and groups under every active version, never added together: `model_versions` (the active versions in creation order), `totals` and `reconciliation` per version, and `rows` with one entry per group holding `models`, one item per version (`model_version_id`, `sales`, `leads`). Each version's totals reconcile with the ledger on their own.

### 3.3 ROAS

- `connection_id`, `level`, `day_zone` (the account zone), `values` and `spend_source` (the 016-A spend `source_status`: coverage, freshness, synchronization, periods and refusals).
- `rows` at the requested level, from `app.advertising.roas`: `level`, `object_id`, `campaign_id`, `adset_id`, `currency`, `exponent`, `spend`, `credited_revenue`, `roas` and `roas_reason` (`zero_spend`, `currency_mismatch`, `attribution_not_ready`), `spend_state` (`complete`, `provisional`, `incomplete`), `credited_leads`, `cost_per_lead` and `cost_per_lead_reason` (`zero_leads`, `zero_spend`, `currency_mismatch`, `attribution_not_ready`).
- `totals` per period: the same row rules over every ad of the connection (`level: account`).
- `unmatched` per period: credited revenue per currency and credited leads that match no ad of the connection (direct and unknown credit included).
- `comparison`: `spend`, `credited_revenue` and `credited_leads` of the account totals.

The cost per lead is the spend in minor units divided by the credited leads, an exact fraction of minor units, with a decimal text in the spend currency's exponent (half-even).

### 3.4 Funnel

- `group_by`, `values`.
- `totals` per period: `page_views` (every stored page view of the client, not marked), `link_page_views` (those with a link ID), `leads` (`credited_leads`, `lead_conversions`), `sales` (`state`; items per currency: `credited_sales`, `credited_revenue`, `sale_conversions`, `associated`, `unassociated`, `ledger_net`).
- `rows`: per group (section 3.1 order and keys), `visits` (`{state: available | unsupported, count}`), `leads` and `sales`.
- No field holds a rate between stages.

A group whose reference no managed link of the client carries (NULL-safe on the reference) has `unsupported` visits with a null count; a group with a managed link and no view in the period has `available` visits of 0. Direct and unknown rows always have `unsupported` visits.

### 3.5 Dependency block

Every family, the 016-A ones included, reports: `attribution` and `content_revenue` served by `attribution`, `funnels` by `funnel` and `roas` by `roas`, each `state: available` with its `requires` list kept. The 016-A answers change only in this block and the contract version.

## 4. Comparisons

The previous period has equal length and ends at `start` (016-A). A value is compared only when both are known: the percentage is exact (half-even, two places) and a zero baseline keeps the difference with `zero_baseline`. No authoritative percentage is given while the consumer is `behind` (`attribution_behind`), `rebuilding`, `failed` or not ready; for ROAS also while the spend of either period is `partial` or provisional (the 016-A spend reasons). A currency present in only one period of a caught-up report compares with a known zero. Shares compare as exact fractions.

## 5. ROAS entry point, adapter change and rebuild

**Entry point.** `app/advertising/roas.py` gains `roas_from_credit(facts, credit, ...)` over `CreditTotal(campaign_ref, content_ref, currency, minor, leads)` items aggregated by the caller over the account-local period. It shares with `roas_report` the spend aggregation, the coverage rule, the match predicate, `_row` and the roll-up; `roas_report` keeps its behavior and its `source == "meta"` test. Credit matches an ad when `content_ref` is an ad ID of the connection (its stored ad objects and spend facts) and `campaign_ref` equals that ad's campaign ID (D7b). Leads are rolled up beside revenue, and the cost per lead uses the row's currency rule.

**Adapter (D7a).** `attribution_inputs.touchpoints()` reads the retained `utm_content` value as the content reference when the touch is a campaign interaction whose managed link has no content reference, under `usable_reference`. A managed link's content reference wins. The class of a touch never changes, and a direct visit keeps no content reference (section 11).

**Rebuild.** `attribution_records.INPUT_ADAPTER_REVISION = 2` joins the model-set digest (`model_set_digest` adds it when above 1, so the 008-B digests are unchanged for revision 1). Every client's stored digest then differs, and its first pass rebuilds once. The rebuild recalculates against the stored history: old revisions and their rows stay byte-identical, a touch whose content reference changed gives a new revision with the cause `evidence_changed` and signed differences (minus the old key, plus the new one), and every total by campaign, recipient and currency is unchanged. The next pass finds the digest current and rebuilds nothing.

## 6. Funnel visits

```sql
SELECT CASE WHEN e.first_received_at >= :current_start THEN 'current' ELSE 'previous' END,
       :dimension, count(*)
FROM collected_events e
JOIN managed_links l ON l.id = e.link_id AND l.agency_id = e.agency_id AND l.client_id = e.client_id
LEFT JOIN link_campaigns c ON c.id = l.campaign_id
LEFT JOIN link_content_references r ON r.id = l.content_reference_id
WHERE e.agency_id = :agency AND e.client_id = :client
  AND e.event_type = 'page_view' AND e.link_id IS NOT NULL
  AND e.identity_excluded_at IS NULL
  AND e.first_received_at >= :low AND e.first_received_at < :high
GROUP BY 1, 2;
```

`:dimension` is `coalesce(c.public_code, l.utm->>'utm_campaign')`, `coalesce(r.external_code, l.utm->>'utm_content')` or `e.link_id`, so a visit takes the reference that the input adapter gives its touches (corrected under D-090, finding R016B-01 of the [merge review](merge-review-016b.md)). Without `finance:read`, the credit and count rows that shape the groups are lead rows only (R016B-02). The bound counts the link-tagged page views of both periods first (`LIMIT 50001`): more than 50,000 answers `report_too_large`. The page view totals are one `count(*) ... FILTER (WHERE link_id IS NOT NULL)` statement. Every stored event has a consent basis (004), so a stored page view is a consenting visitor's view; traffic labels are not filtered, as in the attribution touches.

## 7. Conversions list and release corrections

**Rows.** Conversions of the published generation (`generation <= G`) whose `effective_at` (the stored conversion time) lies in the UTC period, newest first (`effective_at DESC, id DESC`, index `0030`). Status at `G`: `superseded` when `superseded_generation <= G`, else `active`. Filters: `kind`, `status` and `person_id` (the owner is in the person's group: its visible root and the members merged into it; an unknown person is denied). Each item: `id`, `kind`, `status`, `effective_at`, `superseded_at`, `superseded_reason`, `scrubbed`, `person_id` (null when scrubbed or unassociated), `lead_event_id` (null when scrubbed), `transaction` (`source_account_id`, `sale_operation_id`; sales only) and `latest_run` under the version (`revision`, `status`, `basis`, `causes`, `recorded_at`, `window_end`, `currency`, `currency_exponent`, `verified_net_minor`, `touch_bound_exceeded`; null without a revision). The answer also holds `generation`, `model_version`, `sales` (`available` or `permission_unavailable`) and `next_cursor` (base64 of the last item's `[effective_at, id]`, as the identity routes).

**Barrier.** The list is built in a report snapshot and answers `attribution_stale` unless the status read in that snapshot says `caught_up`.

**Change token.** `attribution_reads.change_token()` reads `(generation, version, scrub_epoch)` of the consumer state. The route reads it inside the snapshot, builds the answer, then reads it again in a fresh statement of the request session; a difference answers `attribution_stale`. The runs route does the same (O1). Then the scope is resolved again (`identity:read`, and `finance:read` when the answer holds sales) before the response.

**Status (O2).** `GET /attribution/status` runs the status read inside one report snapshot; the default seeding stays in the request session.

**Finance.** Without `finance:read` only lead conversions are listed and `sales` is `permission_unavailable`; `kind=sale` then lists nothing.

## 8. Revision and release

The revision digests: the principal, agency, client, permission and finance flag, the normalized query, the contract version `016b.1`, the catalog version, and the inputs digest. The inputs digest holds the consumer tokens (`generation`, `version`, `scrub_epoch`, `status`, `failure_code`, `unit_kind`, watermarks, `model_set_digest`, `published_at`), the status read (state and current watermarks), the model versions (`id`, `version_key`, `model`, `window_seconds`, `rules`, `is_default`, `status`, `retired_at`), the ledger position (`ledger` state, generation, receipt ordinal), the registered flags and content pointers of the result's groups, and, per family, the 016-A spend inputs digest with the ad objects (ROAS) or the aggregated visit counts (funnel).

Stored credit at a generation `<= G` changes only through a write that also changes the consumer version (the worker's compare-and-swap, the scrub and the lifecycle), so the release check does not aggregate again. It runs in a fresh snapshot after the answer is built: it resolves the scope again (the family permission, and `finance:read` when sale values were built), reads the tokens, the flags and pointers of the same groups, and, per family, the spend inputs or the visit counts again. Any difference answers `report_changed`; a revoked grant answers `access_denied`. `before_release` stays the test hook.

## 9. CSV

The three new families share one fixed long-form schema (`COLUMNS_016B`), typed with the 016-A writers; the 016-A schema is unchanged. Columns: `row_type` (metadata, status, total, comparison, value), `family`, `view`, `period`, `period_start`, `period_end`, `day_zone`, `basis`, `model_version_id` (identifier), `model_version`, `model`, `model_status`, `level`, `recipient`, `group_ref` (identifier), `campaign_id` (identifier), `adset_id` (identifier), `registered`, `connection_id` (identifier), `object_id` (identifier), `source`, `metric`, `unit`, `currency`, `exponent`, `value` (number), `value_minor`, `numerator`, `denominator`, `count`, `current_value`, `previous_value`, `percent_change`, `comparable`, `availability`, `status`, `reason`, `timestamp`, `detail`.

Every reference that can come from a URL (`group_ref`, ad and content IDs) is an identifier cell with the `id:` prefix, so a value starting with `=`, `+`, `-` or `@` is never a formula. No name, label, person ID, touchpoint ID or event ID has a column. Files: `report-attribution.csv`, `report-roas.csv`, `report-funnel.csv`; bounds 5,000 records and 2 MiB, refused whole. In the 016-A files the dependency rows keep their columns, with `status` now `available` and `detail` naming the serving family.

## 10. Schema

```sql
-- 0030_reporting_indexes (after 0029_attribution_persistence)
CREATE INDEX ix_attribution_conversions_client_effective
    ON attribution_conversions (client_id, effective_at, id);
CREATE INDEX ix_collected_events_client_link_received
    ON collected_events (client_id, first_received_at) WHERE link_id IS NOT NULL;
-- downgrade
DROP INDEX ix_collected_events_client_link_received;
DROP INDEX ix_attribution_conversions_client_effective;
```

No table, column, grant or data policy row changes. The ORM models declare both indexes, so the metadata comparison stays empty. The downgrade loses no data and needs no guard.

## 11. Routine details resolved here

1. **Direct visits keep no content reference.** `utm_content` is read for campaign interactions only, so direct credit stays a row of its own without provenance.
2. **Totals-level comparison.** Comparisons cover the report totals, not each group, as in 016-A.
3. **Retired versions.** A retired version is reported as it stood at retirement (it receives no closing revisions); the `models` view shows active versions only.
4. **Conversion time in the list.** The list uses the stored `effective_at` (D11, D12). A conversion never changes, so a sale whose time a later receipt corrects keeps its opening time in the list; its runs and the reports use the corrected time, which `latest_run.window_end` shows.
5. **Fully refunded sales.** A sale with a net of 0 still holds its share (the engine credits it with amount 0), so it counts in credited sales and conversions with revenue 0, exactly as stored.
6. **Never-synced spend connection.** ROAS answers `409 day_zone_unknown` instead of placing credit on undefined local dates.

## 12. Test inventory

| Case | Tests |
|---|---|
| BV01 | `test_attribution_reports.py::test_bv01_isolation_across_agencies_clients_and_versions`; `test_roas_reports.py::test_roas_isolation_permissions_and_periods`; `test_funnel_reports.py::test_funnel_isolation_permissions_and_comparison`; `test_attribution_conversions.py::test_bv15_scrub_pages_filters_finance_and_keys` |
| BV02 | `test_attribution_reports.py::test_bv02_lead_credit_without_finance_and_key_rules`; `test_roas_reports.py::test_roas_isolation_permissions_and_periods`; `test_funnel_reports.py::test_funnel_isolation_permissions_and_comparison`; `test_attribution_conversions.py::test_bv15_scrub_pages_filters_finance_and_keys` |
| BV03 | `test_attribution_reports.py::test_bv03_credit_equals_stored_allocations_and_reconciles`; `test_attribution_reporting.py::test_groups_keep_direct_and_unknown_apart` |
| BV04 | `test_attribution_reports.py::test_bv04_refund_late_touch_owner_change_and_moved_sale` |
| BV05 | `test_attribution_reports.py::test_bv05_utc_bounds_to_the_microsecond_and_refusals`; `test_roas_reports.py::test_roas_isolation_permissions_and_periods` (daylight-saving days) |
| BV06 | `test_attribution_reporting.py::test_comparisons_are_exact_and_blocked_when_not_authoritative`; `test_attribution_reports.py::test_bv06_comparison_of_equal_periods`; ROAS and funnel module tests |
| BV07 | `test_attribution_reports.py::test_bv07_models_view_side_by_side` |
| BV08 | `test_attribution_reports.py::test_bv08_groups_flags_and_social_content_pointer` |
| BV09 | `test_attribution_reporting.py::test_exact_fractions_and_half_even_text`; `test_attribution_reports.py::test_bv09_currencies_stay_apart_and_thirds_sum_to_one` |
| BV10 | `test_attribution_reports.py::test_bv10_not_ready_behind_rebuild_failed_and_ledger_unavailable` |
| BV11 | `test_attribution_reporting.py::test_roas_from_credit_equals_roas_report`; `test_roas_reports.py::test_bv11_roas_from_stored_credit_equals_the_contract` |
| BV12 | `test_roas_reports.py::test_bv12_join_needs_campaign_and_ad_of_the_connection`; `test_roas_reports.py::test_bv12_adapter_change_rebuilds_once_and_keeps_history` |
| BV13 | `test_attribution_reporting.py::test_cost_per_lead_rules`; `test_roas_reports.py::test_bv13_cost_per_lead` |
| BV14 | `test_funnel_reports.py::test_bv14_visits_are_consented_link_page_views_of_the_client`; `test_attribution_report_bounds.py::test_bv14_link_event_bound` |
| BV15 | `test_attribution_conversions.py::test_bv15_stale_while_behind_and_after_withdrawal`, `::test_bv15_scrub_pages_filters_finance_and_keys`, `::test_bv15_commit_during_build_refuses_list_and_runs`, `::test_bv15_status_reads_one_snapshot` |
| BV16 | `test_attribution_reports.py::test_bv16_pages_and_revision`; ROAS and funnel module tests |
| BV17 | `test_attribution_reports.py::test_bv17_release_race` (worker pass, scrub, default model, revoked grant; JSON and CSV); `test_roas_reports.py::test_roas_release_race_on_spend` |
| BV18 | `test_attribution_reports.py::test_bv18_csv_equals_json_and_bounds`; `test_attribution_reporting.py::test_csv_identifier_prefix_and_record_bound`; ROAS and funnel module tests |
| BV19 | `test_attribution_report_bounds.py::test_bv19_group_bound`, `::test_bv19_statements_do_not_grow_with_credit_rows`, `::test_bv19_measurements` (opt-in) |
| BV20 | `test_reports.py::test_v17_v19_no_storage_and_dependency_states` (updated block); `test_attribution_models.py::test_bv20_0030_upgrade_and_downgrade`; the existing AV, R008, 006, 007, 014 and 015 suites; the OpenAPI snapshot comparison |
