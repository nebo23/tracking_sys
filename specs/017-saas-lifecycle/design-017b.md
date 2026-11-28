# Spec 017-B design: offboarding export, provider disconnection and the purge of closed agencies

Prepared: 2026-11-28 under D-098. Revision: 2 (2026-11-28). Status: approved scope ([D1-D14](entry-review-017b.md#3-decisions-for-the-owner), D-098, without amendment), implemented. This note fixed the exact schema, statements, answers, error codes, grants and tests before any code; section 4 of the [entry review](entry-review-017b.md) is its source. Section 12 lists the routine details resolved here. No material new choice was found that needs the owner. Revision 2 aligns the test inventory of section 10 with the implemented test names; the [evidence](evidence-017b.md) records the results and the details found during implementation (section 6).

## 1. Inventory on the branch (P0)

### 1.1 Baseline

- **Branch.** `codex/spec-017b-agency-offboarding` was created from `origin/claude/keen-fermat-otlr9d` at `dc92506`; merged `main` at `e3b3005` (PR 20) is an ancestor (`git merge-base --is-ancestor e3b3005 HEAD` succeeds).
- **`main`.** `origin/main` has not moved beyond `e3b3005`, so nothing was merged into the branch. Pull request 17 (Spec 018) is still open; `frontend/` holds only the placeholder README files of the initial commit, with no `package.json`, so the frontend checks of P5 do not apply.
- **Gate.** D-098 is recorded in `AGENTS.md` and `docs/planning/decisions.md`. It approves D1-D14 as recommended and names no amendment.
- **Decision numbers.** The highest number is D-098 on this branch; `main` ends at D-096, the open pull request 17 uses D-081 to D-087, and `codex/spec-018-workspace-screens` reuses D-093 and D-094 (unchanged, reported under D-096). This work records no new decision.

### 1.2 Tenant tables

The migrated schema at `0032_report_delivery` has 95 application tables; 80 carry `agency_id` or `client_id`. Migration `0033` adds three more, so 83 are scoped. The purge deletes 81 of them in the order below, children first; it keeps `agency_plan_assignments` and `agency_purges` (D8). The order is the cleanup order of `tests/integration/conftest.py`, restricted to scoped tables, with the two export tables first. Every foreign key between two purged tables points to a later row of this table, except the two self-references (`identity_merges.reverses_id` and `identity_subjects.merged_into_id`), which the purge resolves leaves first (section 2.5).

The access path is the predicate of the purge step. A path through a parent uses a non-null key column of the child and an index that starts with it, so every row is reached through an index; the three tables without such an index (`agency_closures`, `payment_callback_diagnostics`, `connector_oauth_transactions`) are small, and the last two are cleared after 30 days and one day. `clients` is the array of the agency's client IDs, read at the start of each call.

| # | Table | Purge access path | Index used | References | Exported (D4) |
|---|---|---|---|---|---|
| 1 | `agency_export_parts` | `export_id` in `agency_exports` where `agency_id = agency` | pk (export_id, part) | (agency_id, export_id)->agency_exports | no: the export itself or the purge record |
| 2 | `agency_exports` | `agency_id = agency` | ix (agency_id, requested_at) | agency_id->agencies; (agency_id, requested_by_membership_id)->memberships | no: the export itself or the purge record |
| 3 | `report_export_contents` | `export_id` in `report_exports` where `agency_id = agency` | parent key: `pk_report_export_contents` (export_id) | report_exports | no: earlier report files (derived, sealed) |
| 4 | `report_exports` | `agency_id = agency` | `ix_report_exports_listing` (agency_id, client_id, created_at, id) | agency_memberships, client_workspaces, connector_connections, report_schedules set null | no: earlier report files (derived, sealed) |
| 5 | `report_schedule_recipients` | `agency_id = agency` | `ix_report_schedule_recipients_membership` (agency_id, membership_id) | agency_memberships, report_schedules cascade | `report_schedule_recipients.jsonl`, all columns |
| 6 | `report_schedules` | `agency_id = agency` | `ix_report_schedules_client` (agency_id, client_id, created_at) | agency_memberships, client_workspaces | `report_schedules.jsonl`, all columns |
| 7 | `agency_branding` | `agency_id = agency` | `pk_agency_branding` (agency_id) | agencies, agency_memberships | no: agency administration, not a client's first-party data |
| 8 | `agency_closures` | `agency_id = agency` | none: a sequential scan of a short-lived table | agencies, agency_memberships | no: agency administration, not a client's first-party data |
| 9 | `attribution_credit_changes` | `client_id = ANY (clients)` | `ix_attribution_credit_changes_generation` (client_id, generation) | attribution_model_versions, attribution_runs, client_workspaces | `attribution_credit_changes.jsonl`, all columns |
| 10 | `attribution_allocations` | `run_id` in `attribution_runs` where `client_id = ANY (clients)` | parent key: `uq_attribution_allocations_ordinal` (run_id, ordinal) | attribution_runs, client_workspaces | `attribution_allocations.jsonl`, all columns |
| 11 | `attribution_runs` | `client_id = ANY (clients)` | `ix_attribution_runs_generation` (client_id, generation) | attribution_conversions, attribution_model_versions, client_workspaces | `attribution_runs.jsonl`, all columns |
| 12 | `attribution_conversions` | `client_id = ANY (clients)` | `ix_attribution_conversions_client_effective` (client_id, effective_at, id) | client_workspaces | `attribution_conversions.jsonl`, without `slot_key`, `conversion_key` |
| 13 | `attribution_model_versions` | `client_id = ANY (clients)` | `uq_attribution_model_versions_key` (client_id, version_key) | agency_memberships, client_workspaces | `attribution_model_versions.jsonl`, all columns |
| 14 | `attribution_consumer_state` | `client_id = ANY (clients)` | `pk_attribution_consumer_state` (client_id) | client_workspaces | no: erasure records, diagnostics or processing state |
| 15 | `revenue_identity_bindings` | `client_id = ANY (clients)` | `ix_revenue_identity_bindings_sale` (client_id, source_account_id, sale_operation_id) | agency_memberships, client_workspaces, collection_subjects, identity_assertions, identity_subjects, service_credentials | `revenue_identity_bindings.jsonl`, without `request_fingerprint` |
| 16 | `ledger_reconciliation_actions` | `client_id = ANY (clients)` | `ix_ledger_reconciliation_actions_issue` (client_id, issue_id) | agency_memberships, client_workspaces | `ledger_reconciliation_actions.jsonl`, without `issue_fingerprint`, `request_fingerprint` |
| 17 | `ledger_transactions` | `client_id = ANY (clients)` | `uq_ledger_transactions_key` (client_id, generation, source_account_id, operation_id) | client_workspaces | `ledger_transactions.jsonl`, all columns |
| 18 | `ledger_movements` | `client_id = ANY (clients)` | `ix_ledger_movements_transaction` (client_id, generation, source_account_id, transaction_id) | client_workspaces, ledger_receipts, revenue_evidence | `ledger_movements.jsonl`, all columns |
| 19 | `ledger_receipts` | `client_id = ANY (clients)` | `uq_ledger_receipts_evidence` (client_id, generation, evidence_id) | client_workspaces, revenue_evidence | `ledger_receipts.jsonl`, without `input_digest`, `previous_digest`, `receipt_digest` |
| 20 | `ledger_projection_state` | `client_id = ANY (clients)` | `pk_ledger_projection_state` (client_id) | client_workspaces | no: erasure records, diagnostics or processing state |
| 21 | `identity_erasure_holds` | `client_id = ANY (clients)` | `uq_identity_erasure_holds_event` (client_id, deletion_request_id, collected_event_id) | client_workspaces, collected_events, deletion_requests | no: erasure records, diagnostics or processing state |
| 22 | `identity_changes` | `client_id = ANY (clients)` | `uq_identity_changes_seq` (client_id, seq) | client_workspaces | no: erasure records, diagnostics or processing state |
| 23 | `identity_feed_state` | `client_id = ANY (clients)` | `pk_identity_feed_state` (client_id) | client_workspaces | no: erasure records, diagnostics or processing state |
| 24 | `identity_handoffs` | `client_id = ANY (clients)` | `uq_identity_handoffs_challenge` (client_id, challenge_digest) | client_workspaces, collection_subjects | no: secrets, keys, digests or tokens |
| 25 | `identity_links` | `collection_subject_id` in `collection_subjects` where `client_id = ANY (clients)` | parent key: `ix_identity_links_collection_subject_id` (collection_subject_id) | client_workspaces, collection_subjects, identity_assertions, identity_merges, identity_subjects | `identity_links.jsonl`, all columns |
| 26 | `identity_assertion_receipts` | `client_id = ANY (clients)` | `uq_identity_receipts_assertion` (client_id, assertion_id) | client_workspaces | no: erasure records, diagnostics or processing state |
| 27 | `identity_assertions` | `client_id = ANY (clients)` | `uq_identity_assertions_assertion` (client_id, assertion_id) | client_workspaces, collection_subjects, identity_merges, identity_subjects, service_credentials | no: erasure records, diagnostics or processing state |
| 28 | `identity_keys` | `client_id = ANY (clients)` | `uq_identity_keys_value` (client_id, kind, key_bytes) | client_workspaces, identity_merges, identity_subjects | no: secrets, keys, digests or tokens |
| 29 | `identity_merges` | `client_id = ANY (clients)` | `uq_identity_merges_operation` (client_id, operation_id) | agency_memberships, client_workspaces, itself (leaves first) | `identity_merges.jsonl`, without `fingerprint` |
| 30 | `identity_subjects` | `client_id = ANY (clients)` | `ix_identity_subjects_client_evidence` (client_id, last_evidence_at) | client_workspaces, itself (leaves first) | `identity_subjects.jsonl`, all columns |
| 31 | `identity_key_secrets` | `client_id = ANY (clients)` | `uq_identity_key_secrets_version` (client_id, version) | client_workspaces | no: secrets, keys, digests or tokens |
| 32 | `whatsapp_messages` | `client_id = ANY (clients)` | `ix_whatsapp_messages_client_received` (client_id, received_at) | whatsapp_numbers | `whatsapp_messages.jsonl`, without `message_digest` |
| 33 | `whatsapp_numbers` | `agency_id = agency` | `uq_whatsapp_numbers_scope` (agency_id, client_id, id) | agency_memberships, client_workspaces | `whatsapp_numbers.jsonl`, all columns |
| 34 | `crm_deals` | `client_id = ANY (clients)` | `ix_crm_deals_client_updated` (client_id, updated_at) | client_workspaces, integration_sources | `crm_deals.jsonl`, all columns |
| 35 | `crm_stage_rules` | `client_id = ANY (clients)` | `uq_crm_stage_rules_stage` (client_id, pipeline, stage) | agency_memberships, client_workspaces | `crm_stage_rules.jsonl`, all columns |
| 36 | `booking_events` | `source_id` in `integration_sources` where `agency_id = agency` | parent key: `ix_booking_events_source_previous` (source_id, previous_ref) | bookings cascade, integration_sources | `booking_events.jsonl`, all columns |
| 37 | `bookings` | `client_id = ANY (clients)` | `ix_bookings_client_updated` (client_id, updated_at) | client_workspaces, collection_subjects set null, integration_sources | `bookings.jsonl`, all columns |
| 38 | `integration_deliveries` | `source_id` in `integration_sources` where `agency_id = agency` | parent key: `uq_integration_deliveries_digest` (source_id, delivery_digest) | integration_sources | no: erasure records, diagnostics or processing state |
| 39 | `integration_source_secrets` | `source_id` in `integration_sources` where `agency_id = agency` | parent key: `uq_integration_source_secrets_version` (source_id, version) | integration_sources | no: secrets, keys, digests or tokens |
| 40 | `integration_sources` | `agency_id = agency` | `ix_integration_sources_agency_client` (agency_id, client_id) | agency_memberships, client_workspaces | `integration_sources.jsonl`, without `public_key` |
| 41 | `revenue_imports` | `client_id = ANY (clients)` | `uq_revenue_imports_file` (client_id, file_digest) | agency_memberships, client_workspaces | no: erasure records, diagnostics or processing state |
| 42 | `payment_callback_diagnostics` | `client_id = ANY (clients)` | none: a sequential scan of a short-lived table | payment_sources | no: erasure records, diagnostics or processing state |
| 43 | `payment_source_secrets` | `source_id` in `payment_sources` where `agency_id = agency` | parent key: `uq_payment_source_secrets_version` (source_id, version) | payment_sources | no: secrets, keys, digests or tokens |
| 44 | `payment_sources` | `agency_id = agency` | `ix_payment_sources_agency_client` (agency_id, client_id) | agency_memberships, client_workspaces | `payment_sources.jsonl`, without `public_key` |
| 45 | `revenue_evidence` | `client_id = ANY (clients)` | `ix_revenue_evidence_receipt` (client_id, received_at, sequence) | client_workspaces | `revenue_evidence.jsonl`, without `content_digest` |
| 46 | `conversion_acknowledgements` | `delivery_id` in `conversion_deliveries` where `agency_id = agency` | parent key: `uq_conversion_acknowledgements_attempt` (delivery_id, attempt) | conversion_deliveries | no: provider-sourced data or provider state |
| 47 | `conversion_deliveries` | `agency_id = agency` | `uq_conversion_deliveries_scope` (agency_id, client_id, id) | connector_connections, conversion_destinations | no: erasure records, diagnostics or processing state |
| 48 | `conversion_destinations` | `agency_id = agency` | `uq_conversion_destinations_scope` (agency_id, client_id, id) | agency_memberships, connector_connections | no: provider-sourced data or provider state |
| 49 | `ad_spend_facts` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `ix_ad_spend_facts_connection_date` (connection_id, spend_date) | connector_connections, connector_sync_runs | no: provider-sourced data or provider state |
| 50 | `ad_objects` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `uq_ad_objects_object` (connection_id, object_id) | connector_connections, connector_sync_runs | no: provider-sourced data or provider state |
| 51 | `ad_accounts` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `uq_ad_accounts_connection` (connection_id) | connector_connections | no: provider-sourced data or provider state |
| 52 | `connector_records` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `uq_connector_records_object` (connection_id, stream, provider_object_id) | connector_connections, connector_sync_runs | no: provider-sourced data or provider state |
| 53 | `connector_usage_records` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `ix_connector_usage_records_connection_period` (connection_id, period) | connector_connections, connector_sync_runs | no: provider-sourced data or provider state |
| 54 | `connector_checkpoints` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `uq_connector_checkpoints_stream` (connection_id, stream) | connector_connections, connector_sync_runs | no: provider-sourced data or provider state |
| 55 | `connector_sync_runs` | `agency_id = agency` | `uq_connector_sync_runs_scope` (agency_id, client_id, connection_id, id) | connector_connections | no: provider-sourced data or provider state |
| 56 | `connector_token_secrets` | `connection_id` in `connector_connections` where `agency_id = agency` | parent key: `uq_connector_token_secrets_version` (connection_id, kind, version) | connector_connections | no: secrets, keys, digests or tokens |
| 57 | `connector_oauth_transactions` | `client_id = ANY (clients)` | none: a sequential scan of a short-lived table | agency_memberships, client_workspaces, connector_connections | no: secrets, keys, digests or tokens |
| 58 | `connector_connections` | `agency_id = agency` | `ix_connector_connections_agency_client` (agency_id, client_id) | agency_memberships, client_workspaces, connector_deletion_requests | no: provider-sourced data or provider state |
| 59 | `deletion_tombstones` | `client_id = ANY (clients)` | `ix_deletion_tombstones_match` (client_id, match_type, match_key) | deletion_requests | no: erasure records, diagnostics or processing state |
| 60 | `deletion_requests` | `client_id = ANY (clients)` | `ix_deletion_requests_client_received` (client_id, received_at, id) | agency_memberships, client_workspaces | no: erasure records, diagnostics or processing state |
| 61 | `event_diagnostics` | `client_id = ANY (clients)` | `uq_event_diagnostics_key` (client_id, day, channel, outcome, reason) | client_workspaces | no: erasure records, diagnostics or processing state |
| 62 | `collected_events` | `client_id = ANY (clients)` | `ix_collected_events_client_received` (client_id, first_received_at, id) | client_workspaces, collection_subjects, ingestion_sources, managed_links, service_credentials | `collected_events.jsonl`, without `fingerprint` |
| 63 | `managed_links` | `client_id = ANY (clients)` | `ix_managed_links_client_created` (client_id, created_at, id) | client_workspaces, link_campaigns, link_content_references, link_destination_origins, link_domains, link_utm_templates | `managed_links.jsonl`, all columns |
| 64 | `link_domains` | `agency_id = agency` | `uq_link_domains_scope` (agency_id, client_id, id) | client_workspaces | `link_domains.jsonl`, without `challenge_digest` |
| 65 | `link_destination_origins` | `client_id = ANY (clients)` | `uq_link_destination_origins_client_origin` (client_id, origin) | client_workspaces | `link_destination_origins.jsonl`, all columns |
| 66 | `link_utm_templates` | `client_id = ANY (clients)` | `uq_link_utm_templates_client_name` (client_id, name) | client_workspaces | `link_utm_templates.jsonl`, all columns |
| 67 | `link_content_references` | `client_id = ANY (clients)` | `uq_link_content_references_client_code` (client_id, external_code) | client_workspaces | `link_content_references.jsonl`, all columns |
| 68 | `link_campaigns` | `client_id = ANY (clients)` | `uq_link_campaigns_client_code` (client_id, public_code) | client_workspaces | `link_campaigns.jsonl`, all columns |
| 69 | `consent_records` | `subject_id` in `collection_subjects` where `client_id = ANY (clients)` | parent key: `ix_consent_records_subject_purpose` (subject_id, purpose, received_at, id) | collection_subjects | `consent_records.jsonl`, without `notice_sha256` |
| 70 | `collection_subjects` | `client_id = ANY (clients)` | `ix_collection_subjects_client_activity` (client_id, last_activity_at) | client_workspaces | `collection_subjects.jsonl`, without `token_digest` |
| 71 | `collection_forms` | `client_id = ANY (clients)` | `uq_collection_forms_client_form` (client_id, form_key) | client_workspaces | `collection_forms.jsonl`, all columns |
| 72 | `ingestion_source_secrets` | `source_id` in `ingestion_sources` where `agency_id = agency` | parent key: `uq_ingestion_source_secrets_version` (source_id, version) | ingestion_sources | no: secrets, keys, digests or tokens |
| 73 | `ingestion_sources` | `agency_id = agency` | `ix_ingestion_sources_agency_client` (agency_id, client_id) | agency_memberships, client_workspaces | `ingestion_sources.jsonl`, without `public_key`, `notice_sha256` |
| 74 | `audit_events` | `agency_id = agency` | `ix_audit_events_agency_time` (agency_id, occurred_at, id) | agencies, agency_memberships, client_workspaces, users | no: audit log |
| 75 | `service_client_grants` | `agency_id = agency` | `pk_service_client_grants` (agency_id, credential_id, client_id) | client_workspaces, service_credentials | no: agency administration, not a client's first-party data |
| 76 | `invitation_client_grants` | `agency_id = agency` | `pk_invitation_client_grants` (agency_id, invitation_id, client_id) | agency_invitations, client_workspaces | no: agency administration, not a client's first-party data |
| 77 | `service_credentials` | `agency_id = agency` | `uq_service_credentials_agency_id` (agency_id, id) | agencies, agency_memberships | no: secrets, keys, digests or tokens |
| 78 | `agency_invitations` | `agency_id = agency` | `uq_invitations_agency_id` (agency_id, id) | agencies, agency_memberships, users | no: secrets, keys, digests or tokens |
| 79 | `client_grants` | `agency_id = agency` | `ix_client_grants_agency_membership` (agency_id, membership_id) | agency_memberships, client_workspaces | no: agency administration, not a client's first-party data |
| 80 | `agency_memberships` | `agency_id = agency` | `uq_memberships_agency_id` (agency_id, id) | agencies, users | no: agency administration, not a client's first-party data |
| 81 | `client_workspaces` | `agency_id = agency` | `uq_client_workspaces_agency_id` (agency_id, id) | agencies | `client_workspaces.jsonl`, all columns |
| kept | `agency_plan_assignments` | not purged (D8) | - | agencies, saas_plans | no: agency administration, not a client's first-party data |
| kept | `agency_purges` | not purged (D8) | - | agencies | no: the export itself or the purge record |

### 1.3 Unscoped tables

No unscoped table references a tenant row. `agencies` is kept (D8). `users`, `password_credentials`, `auth_sessions`, `auth_tokens`, `external_identities`, `oauth_transactions`, `verification_challenges`, `security_events` and `user_agreements` belong to platform accounts, which stay (D8). `saas_plans` is platform data. `connector_deletion_requests` (provider deletion requests), `connector_webhook_deliveries` (7 days), `auth_rate_limits` and `mail_outbox` carry no agency or client column; queued messages of the agency (invitations, `report_ready`) expire with their invitation or export and follow the outbox rule (section 13).

## 2. Migration `0033_agency_offboarding` (after `0032_report_delivery`)

### 2.1 `agency_exports`

One offboarding export of one agency (D3, D5).

| Column | Type | Rule |
|---|---|---|
| `id` | uuid | primary key |
| `agency_id` | uuid | foreign key to `agencies` |
| `requested_by_membership_id` | uuid | `(agency_id, requested_by_membership_id)` references `agency_memberships (agency_id, id)` |
| `status` | varchar(16), default `pending` | `pending`, `ready`, `failed`, `revoked` |
| `error_code` | varchar(32) | `export_too_large`, `closure_completed`, `build_failed`; set exactly when `failed` |
| `requested_at` | timestamptz, default `now()` | |
| `ready_at`, `revoked_at` | timestamptz | set exactly when ready, and when revoked |
| `expires_at` | timestamptz | `requested_at < expires_at <= requested_at + 7 days` |
| `part_count` | smallint | 1-64, set when ready |
| `byte_size` | integer | 1-536,870,912 (512 MiB), set when ready |
| `row_count` | integer | 0-2,000,000, set when ready |
| `row_counts` | jsonb | object `{path: rows}`, set when ready |
| `manifest_sha256` | varchar(64) | lowercase hex, set when ready |
| `download_count` | integer, default 0 | non-negative; positive only with `last_downloaded_at` |
| `last_downloaded_at` | timestamptz | |

The state check is:

```sql
(status = 'pending' AND error_code IS NULL AND ready_at IS NULL AND revoked_at IS NULL
   AND part_count IS NULL AND byte_size IS NULL AND row_count IS NULL AND row_counts IS NULL
   AND manifest_sha256 IS NULL)
OR (status = 'ready' AND error_code IS NULL AND ready_at IS NOT NULL AND revoked_at IS NULL
   AND part_count IS NOT NULL AND byte_size IS NOT NULL AND row_count IS NOT NULL
   AND row_counts IS NOT NULL AND manifest_sha256 IS NOT NULL)
OR (status = 'failed' AND error_code IS NOT NULL AND ready_at IS NULL AND revoked_at IS NULL
   AND part_count IS NULL)
OR (status = 'revoked' AND error_code IS NULL AND revoked_at IS NOT NULL)
```

Keys and indexes: `uq_agency_exports_scope (agency_id, id)` for the parts' composite key; `uq_agency_exports_open (agency_id) WHERE status IN ('pending', 'ready')`, so one export at a time per agency; `ix_agency_exports_agency (agency_id, requested_at)`; `ix_agency_exports_pending (requested_at) WHERE status = 'pending'` for the worker; `ix_agency_exports_expires_at (expires_at)` for the runner.

### 2.2 `agency_export_parts`

The sealed parts of a ready export, at most 8 MiB of the ZIP each.

| Column | Type | Rule |
|---|---|---|
| `export_id`, `part` | uuid, smallint | primary key; `part` 1-64 |
| `agency_id` | uuid | `(agency_id, export_id)` references `agency_exports (agency_id, id)` |
| `kek_id` | varchar(32) | `^[a-z0-9][a-z0-9-]{0,31}$` |
| `wrap_nonce`, `wrapped_dek`, `nonce` | bytea | 12, 48 and 12 bytes |
| `ciphertext` | bytea | 17 to 8,388,624 bytes (8 MiB plus the tag) |
| `alg`, `aad_version` | varchar(32), smallint | `A256GCM-ENV-v1` and 1 |
| `created_at` | timestamptz, default `now()` | |

The associated data binds a part to its agency, its export and its part number: the token envelope of `app.privacy.token_secrets` with `SecretContext(agency_id, client_id=export_id, connector_id=export_id, secret_id=export_id, kind="agency_export", version=part)`. A part copied to another export, agency or part number does not open (OV04).

### 2.3 `agency_purges`

One row per closed agency (D7, D8).

| Column | Type | Rule |
|---|---|---|
| `agency_id` | uuid | primary key, foreign key to `agencies` |
| `state` | varchar(16) | `offboarding`, `waiting`, `purging`, `purged` |
| `closure_requested_at`, `closes_at`, `closure_completed_at` | timestamptz | copied from the completed closure; `closes_at > closure_requested_at`, `closure_completed_at >= closes_at` |
| `export_summary` | jsonb, default `{}` | object (section 6) |
| `offboarding_started_at` | timestamptz, default `now()` | |
| `offboarding_completed_at`, `teardown_settled_at`, `purge_started_at`, `purge_completed_at` | timestamptz | set in this order |
| `deleted_counts` | jsonb, default `{}` | object `{table: rows}` accumulated over the batches |

The progress check ties the state to its times:

```sql
(state = 'offboarding' AND offboarding_completed_at IS NULL AND teardown_settled_at IS NULL
   AND purge_started_at IS NULL AND purge_completed_at IS NULL)
OR (state = 'waiting' AND offboarding_completed_at IS NOT NULL AND teardown_settled_at IS NULL
   AND purge_started_at IS NULL AND purge_completed_at IS NULL)
OR (state = 'purging' AND offboarding_completed_at IS NOT NULL
   AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL
   AND purge_completed_at IS NULL)
OR (state = 'purged' AND offboarding_completed_at IS NOT NULL
   AND teardown_settled_at IS NOT NULL AND purge_started_at IS NOT NULL
   AND purge_completed_at IS NOT NULL)
```

Index: `ix_agency_purges_open (state) WHERE state <> 'purged'`.

### 2.4 Changes to existing tables

- `agencies.purged_at` (timestamptz, nullable), with `ck_agencies_purged`: `purged_at IS NULL OR status = 'closed'`.
- `connector_connections.status_reason` accepts `agency_closed`.
- `report_exports.revoked_reason` accepts `agency_closed` (the D6 revocation of report exports).
- `audit_events` accepts the actions `agency.export_requested` and `agency.export_revoked` and the resource `agency_export`.

### 2.5 `purge_agency_batch(p_agency uuid, p_budget integer) RETURNS jsonb`

PL/pgSQL, `SECURITY DEFINER`, owned by the migration role, `SET search_path = pg_catalog, pg_temp`, with every table qualified by `public.`; `EXECUTE` is revoked from `PUBLIC` and granted to `tracking_lifecycle` only. The migration generates the body from its own ordered table list (the 81 steps of section 1.2), so the list is frozen with the revision.

```sql
DECLARE
    v_status text; v_purge public.agency_purges%ROWTYPE;
    v_clients uuid[]; v_left integer := p_budget; v_count integer;
    v_deleted jsonb := '{}'::jsonb;
BEGIN
    IF p_budget IS NULL OR p_budget < 1 OR p_budget > 10000 THEN
        RAISE EXCEPTION 'invalid_budget' USING ERRCODE = 'P0001';
    END IF;
    SELECT status INTO v_status FROM public.agencies WHERE id = p_agency FOR UPDATE;
    IF v_status IS DISTINCT FROM 'closed' THEN
        RAISE EXCEPTION 'agency_not_closed' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_purge FROM public.agency_purges WHERE agency_id = p_agency FOR UPDATE;
    IF NOT FOUND OR v_purge.offboarding_completed_at IS NULL
            OR EXISTS (SELECT 1 FROM public.connector_connections
                       WHERE agency_id = p_agency
                         AND status IN ('active', 'reconnect_required')) THEN
        RAISE EXCEPTION 'offboarding_not_completed' USING ERRCODE = 'P0001';
    END IF;
    IF v_purge.state = 'purged' THEN
        RETURN jsonb_build_object('state', 'purged', 'deleted', '{}'::jsonb);
    END IF;
    IF v_purge.state = 'waiting' THEN
        IF EXISTS (SELECT 1 FROM public.connector_connections
                   WHERE agency_id = p_agency AND status = 'disconnecting'
                     AND purge_due_at > now()) THEN
            RAISE EXCEPTION 'teardown_pending' USING ERRCODE = 'P0001';
        END IF;
        UPDATE public.agency_purges SET state = 'purging', teardown_settled_at = now(),
            purge_started_at = now() WHERE agency_id = p_agency;
    END IF;
    v_clients := ARRAY(SELECT id FROM public.client_workspaces WHERE agency_id = p_agency);
    -- one step per table, in the order of section 1.2:
    DELETE FROM public.<table> WHERE ctid = ANY (ARRAY(
        SELECT ctid FROM public.<table> WHERE <access path> LIMIT v_left));
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count > 0 THEN
        v_deleted := v_deleted || jsonb_build_object('<table>', v_count);
        v_left := v_left - v_count;
    END IF;
    IF v_left = 0 THEN <record v_deleted; RETURN state 'purging'>; END IF;
    -- ... 81 steps ...
    UPDATE public.agencies SET name = 'Closed agency ' || p_agency::text,
        purged_at = now(), updated_at = now() WHERE id = p_agency;
    <record v_deleted>; UPDATE public.agency_purges SET state = 'purged',
        purge_completed_at = now() WHERE agency_id = p_agency;
    RETURN jsonb_build_object('state', 'purged', 'deleted', v_deleted);
END;
```

- **Self-references.** The steps of `identity_merges` and `identity_subjects` delete only rows that no remaining row of the same table references (`NOT EXISTS (... reverses_id = t.id)`, `NOT EXISTS (... merged_into_id = t.id)`) and repeat while a statement deletes rows and budget is left. If rows remain and none is a leaf, which the merge rules exclude, one statement deletes the rest together, so the constraint holds at its end.
- **Recording.** `<record v_deleted>` adds each count to `agency_purges.deleted_counts` (`jsonb_each_text` of both objects, summed by key).
- **Guard (D9).** The function refuses with `P0001` and one of the messages `invalid_budget`, `agency_not_closed`, `offboarding_not_completed` or `teardown_pending`. It locks the agency row first, which also blocks every insert into a table with a foreign key to `agencies` for the length of the call.
- **Completeness.** Each call walks every step from the first, so a row inserted after its table's step of an earlier call is deleted by the next call. A row inserted into a client table during a call either breaks the final `client_workspaces` step (the foreign key) or makes it wait past the lock timeout, and the batch rolls back. A call that reaches the end has therefore emptied every step, and only then marks the purge complete and replaces the name.
- **Budget.** At most `p_budget` rows per call (1-10,000; the runner passes `lifecycle_batch_size`, at most 5,000). Cascading foreign keys delete nothing extra, because children go first.

### 2.6 Grants

| Role | Grant |
|---|---|
| `tracking_app` | `SELECT, INSERT` on `agency_exports`, `agency_export_parts` and `agency_purges` |
| `tracking_app` | `UPDATE (status, error_code, ready_at, revoked_at, part_count, byte_size, row_count, row_counts, manifest_sha256, download_count, last_downloaded_at)` on `agency_exports`; never `DELETE` |
| `tracking_app` | `DELETE` on `agency_export_parts` (revocation) |
| `tracking_app` | `UPDATE (state, offboarding_completed_at, export_summary)` on `agency_purges`; the other times are written only by the function, so the progress check keeps the runtime at `offboarding` and `waiting` |
| `tracking_lifecycle` | `EXECUTE` on `purge_agency_batch(uuid, integer)`; revoked from `PUBLIC` |
| `tracking_lifecycle` | `SELECT (agency_id, state)` on `agency_purges` |
| `tracking_lifecycle` | `SELECT (id, expires_at)` on `agency_exports`; `SELECT (export_id)` and `DELETE` on `agency_export_parts` (expiry) |

The lifecycle role gets no other right on a tenant table: it still cannot delete tenant configuration (`client_workspaces`, `agency_memberships`, `managed_links` and the rest) directly (OV12).

### 2.7 Data policy

New classes: `agency.export` (medium, pseudonymous through the membership, system), `agency.export_content` (high, direct, derived: the sealed ZIP holds client names and personal data) and `agency.purge` (low, not personal, system). `agencies.purged_at` is `tenancy.configuration`.

| Table | Rule |
|---|---|
| `agency_exports` | approved (D-098): kept with the agency until its purge; its parts end at revocation, expiry or purge |
| `agency_export_parts` | approved (D-098): deleted at revocation, by `tracking_lifecycle` at the export's expiry (7 days after the request) and by the purge |
| `agency_purges` | approved (D-098): kept after the purge as the minimal record (D8) |
| `agencies` | approved (D-098): kept after the purge with status `closed`, a pseudonymous name and `purged_at` (D8) |
| `agency_plan_assignments` | approved (D-098): kept after the purge for 017-C billing (D8) |
| every other scoped table | the rule `D-098`: "Deleted by the purge of its closed agency (017-B), after the closing period and the teardowns", added to its rules; the existing texts that said "offboarding is 017" name the 017-B purge, and client offboarding without closing the agency stays undecided |

The registry adds this rule to every table with an `agency_id` or `client_id` column except the two kept tables, so a new scoped table gets it by construction. `audit_events` and `agency_invitations` keep their pending retention rules and gain the approved purge rule; `security_events` stays unapproved. The table counts become 99 (98 application tables and `alembic_version`).

### 2.8 Guarded downgrade

The downgrade takes `ACCESS EXCLUSIVE` locks on the three tables, `agencies`, `connector_connections`, `report_exports` and `audit_events`, and refuses ("Refuse to remove stored offboarding state; use a forward fix.") if any export, part or purge row exists, any agency has `purged_at`, any connection has `status_reason = 'agency_closed'`, any report export has `revoked_reason = 'agency_closed'` or any audit row has a new action or resource. Otherwise it revokes the grants, drops the function, the tables and the column, and restores the four checks.

## 3. Export (D2 to D5)

### 3.1 Routes (`app/api/offboarding.py`)

Browser sessions only (a read or ingest key is refused by `BrowserDep`). The caller is resolved as for the closure routes: an active Owner of an active or closing agency, otherwise `403 access_denied`.

| Route | Answer | Refusals, in check order |
|---|---|---|
| `POST /agencies/{agency_id}/closure/export` with `{"password"?}` | `202` with the export state | `429 rate_limited` (per peer, and three per user per hour in scope `agency-export`); `403 access_denied`; `409 agency_not_closing`; `409 export_window_ended` (`now >= closes_at - 24 hours`); `503 not_configured` (no token keyring); `401 invalid_credentials`; `403 reauthentication_required` |
| `GET /agencies/{agency_id}/closure/export` | `200` with the export state | `403 access_denied` |
| `GET /agencies/{agency_id}/closure/export/download` | `200 application/zip`, streamed part by part, `Content-Length`, `Content-Disposition: attachment; filename="agency-export.zip"`, `Cache-Control: no-store` | `403 access_denied`; `409 agency_not_closing`; `404 export_not_found`; `409 export_not_ready`; `410 export_gone` (failed, revoked or expired); `503 not_configured` |

The export state is `{"agency_id", "window_ends_at", "export": null | {"id", "status", "error_code", "requested_at", "ready_at", "expires_at", "revoked_at", "part_count", "byte_size", "row_count", "manifest_sha256", "download_count", "last_downloaded_at"}}`, with `status` one of `pending`, `ready`, `failed`, `revoked` and `expired` (a ready export past its expiry). `window_ends_at` is `closes_at - 24 hours` while the agency is closing, otherwise `null`.

A request locks the agency row (as every agency mutation does), checks the state, reauthenticates as account closure does (D-024), revokes the open export, inserts the new pending row with `expires_at = requested_at + 7 days` and audits `agency.export_requested` (and `agency.export_revoked` for a replaced export, resource `agency_export`, actor the Owner). The cancellation of the closure (017-A) revokes the open export in the same transaction and audits `agency.export_revoked`.

A download resolves the caller again in the request session, checks that the agency is closing and the export ready and unexpired, counts the download, and commits before the response starts. The parts are then read in one `REPEATABLE READ READ ONLY` snapshot opened before the response, which also checks the export again: a revocation committed after that snapshot cannot cut the stream short. Each part is opened for exactly its export, agency and part number; a part that fails to open ends the stream and logs `agency_export_unreadable`.

### 3.2 Catalog (D4)

One JSON Lines file per table and client, in the client's folder, with the columns below in this order and rows ordered by primary key. Values are JSON: UUIDs, times (ISO 8601 with offset) and dates as strings, arrays and JSONB values as JSON. The excluded columns are digests or routing keys, never first-party content.

| File | Exported columns | Excluded columns |
|---|---|---|
| `client_workspaces.jsonl` | agency_id, name, status, id, created_at, updated_at | none |
| `link_campaigns.jsonl` | id, agency_id, client_id, public_code, label, status, created_at, updated_at | none |
| `link_content_references.jsonl` | id, agency_id, client_id, external_code, platform_label, status, created_at, updated_at | none |
| `link_utm_templates.jsonl` | id, agency_id, client_id, name, parameters, revision, status, created_at, updated_at | none |
| `link_destination_origins.jsonl` | id, agency_id, client_id, origin, hostname, query_names, status, created_at, updated_at | none |
| `link_domains.jsonl` | id, agency_id, client_id, hostname, status, challenge_generation, failure_code, version, created_at, updated_at, challenge_expires_at, verified_at, verification_expires_at, certificate_expires_at, last_checked_at | `challenge_digest` |
| `managed_links.jsonl` | id, agency_id, client_id, domain_id, slug, origin_id, destination, utm, target_url, campaign_id, content_reference_id, template_id, template_revision, status, created_at, updated_at, expires_at | none |
| `collection_forms.jsonl` | id, agency_id, client_id, form_key, version, fields, status, created_at, updated_at | none |
| `ingestion_sources.jsonl` | id, agency_id, client_id, creator_membership_id, kind, name, status, allowed_origins, created_at, updated_at | `public_key`, `notice_sha256` |
| `collection_subjects.jsonl` | id, agency_id, client_id, created_at, last_activity_at, issuance_channel, identity_floor_at, identity_shared_at | `token_digest` |
| `collected_events.jsonl` | id, agency_id, client_id, event_id, event_type, subject_id, channel, source_id, credential_id, trust_rank, occurred_at, first_received_at, last_received_at, revision, payload, consent_basis, traffic_label, policy_version, conflict_count, last_conflict_at, expires_at, link_id, identity_excluded_at | `fingerprint` |
| `consent_records.jsonl` | id, agency_id, client_id, subject_id, purpose, state, source, jurisdiction_profile, policy_version, received_at, captured_at, expires_at, supersedes_id | `notice_sha256` |
| `identity_subjects.jsonl` | id, agency_id, client_id, status, merged_into_id, version, journey_revision, created_at, updated_at, last_evidence_at | none |
| `identity_links.jsonl` | id, agency_id, client_id, collection_subject_id, status, subject_id, candidate_ids, assertion_ref, asserted_at, eligible_from, provisional_from, eligible_until, closed_reason, merge_id, original_owner_ids, key_ids, grant_started_at | none |
| `identity_merges.jsonl` | id, agency_id, client_id, operation_id, kind, survivor_id, merged_id, reverses_id, status, closed_reason, survivor_version_before, merged_version_before, survivor_version_after, merged_version_after, result, actor_membership_id, reason_code, created_at, ended_at | `fingerprint` |
| `revenue_evidence.jsonl` | id, sequence, agency_id, client_id, delivery_id, source_account_id, operation_id, kind, classification, currency, currency_exponent, amount_minor, effective_at, received_at, parent_operation_id, reason, actor, source_reference, intake, intake_id | `content_digest` |
| `ledger_receipts.jsonl` | id, agency_id, client_id, generation, receipt_ordinal, evidence_id, evidence_sequence, outcome, closing_states, created_at | `input_digest`, `previous_digest`, `receipt_digest` |
| `ledger_movements.jsonl` | id, agency_id, client_id, generation, movement_sequence, receipt_id, source_account_id, transaction_id, operation_id, kind, direction, amount_minor, currency, currency_exponent, effective_at, trigger_evidence_id, reason | none |
| `ledger_transactions.jsonl` | id, agency_id, client_id, generation, source_account_id, operation_id, currency, currency_exponent, sale_effective_at, captured, refunded, charged_back, reversed, corrected, net, entries, evidence_ids, financial_revision, updated_at | none |
| `ledger_reconciliation_actions.jsonl` | id, agency_id, client_id, operation_id, issue_id, issue_version, evidence_ids, action, reason_code, actor_membership_id, created_at | `issue_fingerprint`, `request_fingerprint` |
| `revenue_identity_bindings.jsonl` | id, agency_id, client_id, association_id, revision, request_id, source_account_id, sale_operation_id, credential_id, actor_membership_id, assertion_ref, collection_subject_id, owner_subject_id, key_ids, state, reason, detach_reason, expected_revision, received_at, closed_at | `request_fingerprint` |
| `payment_sources.jsonl` | id, agency_id, client_id, provider, region, name, status, live_integration_ids, created_by_membership_id, created_at, updated_at | `public_key` |
| `integration_sources.jsonl` | id, agency_id, client_id, kind, name, status, created_by_membership_id, created_at, updated_at | `public_key` |
| `bookings.jsonl` | id, agency_id, client_id, source_id, provider, status, event_type_ref, start_at, end_at, reschedule_count, subject_id, linked_at, first_received_at, updated_at | none |
| `booking_events.jsonl` | id, agency_id, client_id, booking_id, source_id, provider, kind, ref, previous_ref, event_type_ref, occurred_at, start_at, end_at | none |
| `crm_stage_rules.jsonl` | id, agency_id, client_id, pipeline, stage, outcome, status, created_by_membership_id, created_at, updated_at | none |
| `crm_deals.jsonl` | id, agency_id, client_id, source_id, deal_ref, pipeline, stage, previous_stage, stage_at, amount_minor, currency, currency_exponent, amount_at, payment_reference, payment_reference_at, first_received_at, updated_at | none |
| `whatsapp_numbers.jsonl` | id, agency_id, client_id, phone_number_id, name, status, created_by_membership_id, created_at, updated_at, verified_at | none |
| `whatsapp_messages.jsonl` | id, agency_id, client_id, number_id, message_at, received_at, has_referral, source_type, source_id, click_id_present | `message_digest` |
| `attribution_model_versions.jsonl` | id, agency_id, client_id, version_key, model, window_seconds, rules, is_default, status, created_by_membership_id, operations, created_at, retired_at | none |
| `attribution_conversions.jsonl` | id, agency_id, client_id, generation, kind, owner_person_id, association_id, binding_id, source_account_id, sale_operation_id, lead_event_id, effective_at, status, superseded_generation, superseded_at, superseded_reason, scrubbed_at, recheck_at, created_at | `slot_key`, `conversion_key` |
| `attribution_runs.jsonl` | id, agency_id, client_id, generation, conversion_id, model_version_id, revision, status, basis, causes, currency, currency_exponent, verified_net_minor, window_start, window_end, ledger_generation, receipt_ordinal, identity_seq, excluded_touchpoint_ids, excluded_reasons, touch_bound_exceeded, recorded_at | none |
| `attribution_allocations.jsonl` | id, agency_id, client_id, run_id, ordinal, credited, recipient, basis, position, share_numerator, share_denominator, amount_minor, touchpoint_id, evidence_class, occurred_at, source, campaign_ref, content_ref, link_ref | none |
| `attribution_credit_changes.jsonl` | id, agency_id, client_id, run_id, model_version_id, generation, ordinal, conversion_kind, effective_at, recipient, touchpoint_id, source, campaign_ref, content_ref, link_ref, delta_share_numerator, delta_share_denominator, delta_minor, currency, currency_exponent, recorded_at | none |
| `report_schedules.jsonl` | id, agency_id, client_id, name, family, parameters, sale_values, compare, cadence, weekday, hour, time_zone, status, pause_reason, owner_membership_id, next_run_at, last_run_at, last_outcome, last_error_code, last_notified, last_skipped, consecutive_failures, created_at, updated_at | none |
| `report_schedule_recipients.jsonl` | schedule_id, membership_id, agency_id, client_id, created_at | none |

- `challenge_digest`: digest of a domain challenge
- `content_digest`: content digest
- `conversion_key`: keyed digest
- `fingerprint`: content digest
- `input_digest`: receipt chain digest
- `issue_fingerprint`: content digest
- `message_digest`: digest of a provider message ID
- `notice_sha256`: digest of a notice text
- `previous_digest`: receipt chain digest
- `public_key`: public routing key of a source
- `receipt_digest`: receipt chain digest
- `request_fingerprint`: request digest
- `slot_key`: keyed digest
- `token_digest`: digest of a subject token

Every other scoped table is excluded with the reason of section 1.2: provider-sourced data and provider state (connections, records, spend, CAPI destinations and answers), secrets, keys, digests and tokens, the audit log, erasure records, diagnostics and processing state, earlier report files, agency administration (memberships, grants, invitations, keys, branding, closures, plan history) and the export and purge rows themselves. A unit test checks that the catalog names only existing columns, that no exported column is binary or a digest, and that the tables of section 1.2 are each either exported or excluded.

### 3.3 Build (`python -m app.offboarding_worker`)

1. **Claim.** The pass selects pending exports of closing agencies, oldest first, at most `--limit`. Each build holds a session advisory lock on its export (namespace 17017), so two workers never build one export; a held lock skips it.
2. **Check.** A pending export of an agency that is no longer closing is marked `failed` with `closure_completed`, or `revoked` when the agency is active again (a cancellation always revokes it first).
3. **Snapshots.** For each client of the agency, in ID order, one `REPEATABLE READ READ ONLY` transaction reads every catalog table with a server-side cursor, so each client's files are consistent with each other.
4. **ZIP.** The worker writes the ZIP to a temporary file (`zipfile`, `ZIP_DEFLATED`, ZIP64 members), one member per table and client, then `manifest.json` last.
5. **Bounds.** It counts rows and checks the temporary file's size as it writes: beyond 2,000,000 rows or 512 MiB it stops with `export_too_large` and stores nothing (OV03).
6. **Checks before storing.** It reopens the ZIP: `testzip()` finds no damaged member, the member list is exactly the manifest's files plus the manifest, each member's row count and SHA-256 match the manifest, and the total matches the bounds.
7. **Store.** One transaction locks the agency row, requires `closing` (otherwise `failed` / `closure_completed`), locks the export row and requires `pending` (otherwise it stops, superseded), inserts the sealed parts of 8 MiB each and makes the export `ready` with its counts and the manifest's SHA-256. The temporary file is deleted in every case.

The completion and the store both lock the agency row first, so an export becomes ready only while the agency is closing (OV06, OV17). Outcomes are counted as `built`, `failed`, `discarded`, `superseded` and `skipped`; an unexpected error marks the export `failed` with `build_failed` and logs `agency_export_failed`.

### 3.4 ZIP layout and manifest

```text
clients/<client_id>/client_workspaces.jsonl
clients/<client_id>/<table>.jsonl          (every file of section 3.2, possibly empty)
manifest.json
```

```json
{"format": "tracking-agency-export", "format_version": 1,
 "schema_version": "0033_agency_offboarding", "agency_id": "...", "export_id": "...",
 "created_at": "...", "total_rows": 0,
 "files": [{"path": "clients/<client_id>/client_workspaces.jsonl", "rows": 1,
            "bytes": 120, "sha256": "..."}]}
```

The manifest names no agency, client or person: identifiers, counts and digests only. `schema_version` is the database revision the build read. `row_counts` on the export row is the `{path: rows}` object of the manifest, and `manifest_sha256` the SHA-256 of `manifest.json`.

### 3.5 Storage, expiry and revocation

- **Storage.** Parts are sealed under the token keyring and inserted with Core statements, so no part stays in an ORM session.
- **Expiry.** `python -m app.lifecycle` deletes the parts of exports whose `expires_at` has passed, in bounded batches (`agency_export_parts`, reported only when not zero). The export row stays with the agency until its purge, so the purge record can summarize it; its view shows `expired`.
- **Revocation.** A new request or a cancellation marks the open export `revoked` and deletes its parts at once. A ready export of a closed agency is kept until its expiry or the purge (D5) but can no longer be downloaded (D2).

## 4. Offboarding (D6)

`python -m app.offboarding_worker` runs, after the export builds, the offboarding of closed agencies that have no purge row or whose row is still `offboarding`, at most `--limit` per pass, as `tracking_app`.

1. **Record.** A first transaction locks the agency row (`FOR UPDATE SKIP LOCKED`, so a second worker skips it), requires `closed`, and inserts the purge row in state `offboarding` with the copied closure times. An agency that already has a later state is skipped (OV17).
2. **Effects.** A second transaction locks the agency row and the purge row and, unless the state moved on, applies each effect once:

| Effect | Statement | Idempotence |
|---|---|---|
| Connections | each `active` or `reconnect_required` connection, locked, goes through `start_disconnect` with reason `agency_closed`; its connection exports are revoked there | only live connections are selected |
| Service keys | `UPDATE service_credentials SET status = 'revoked'` where `active` | only active keys |
| Invitations | `UPDATE agency_invitations SET status = 'revoked'` where `pending` | only pending ones |
| Report exports | `revoke_exports(..., "agency_closed")` for every client | only pending and ready ones |
| Agency export | a pending export becomes `failed` with `closure_completed` (OV06); a ready one is kept | only pending ones |
| Sources | `ingestion_sources`, `payment_sources` and `integration_sources` `active` to `disabled` | only active ones |
| Destinations | `conversion_destinations.enabled` to false | only enabled ones |
| WhatsApp | `active` to `disabled`, `pending` claims to `revoked`, so the operator can no longer verify them | only those states |

The same transaction writes the export summary (section 6), sets `offboarding_completed_at` and moves the state to `waiting`. A second pass finds nothing to do (OV07). No audit row is written: the actor is the platform, and the agency's audit log is purged; the purge record carries the times.

## 5. Teardown wait and purge (D7)

- **Teardown.** The 009 connector worker tears down every `disconnecting` connection whatever the agency's status: it revokes each token at its provider, destroys the sealed material and purges the provider data, and at the 72-hour deadline it records unsettled revocations as `failed` and completes the teardown anyway.
- **Wait.** The function refuses `teardown_pending` while any connection of the agency is `disconnecting` with `purge_due_at` in the future. A teardown has therefore settled when its connection is `disconnected`, or when its deadline has passed; the purge then deletes the connection with its sealed material and provider rows.
- **Purge step.** `python -m app.lifecycle` runs it after the closure completion and the export steps, as `tracking_lifecycle`: it reads the agencies whose purge row is `waiting` or `purging`, in ID order, and calls the function with `lifecycle_batch_size` until it answers `purged`, at most `max_batches` calls per agency. Each call is one transaction with the 100 ms lock timeout. A `teardown_pending` or `offboarding_not_completed` refusal leaves the agency waiting; a lock timeout or another error rolls back the batch and reports `agency_purges` incomplete; the next run resumes from the first step (OV13).
- **Counts.** The run reports `agency_rows_purged` and `agencies_purged`, only when not zero. Per-table counts are kept in the purge record, never printed.

## 6. What stays (D8)

- **Agency row.** Status `closed`, the name `Closed agency <agency id>` (a pseudonym that names nothing, like the account-closure pseudonym of D-024) and `purged_at`.
- **Plan history.** Every `agency_plan_assignments` row, for 017-C billing.
- **Purge record.** The copied closure times, the export summary, the offboarding, teardown and purge times and the deleted row count of each table.
- **Export summary.** `{"status": "none"}`, or the latest export's `status` (with `expired` derived), `requested_at`, `ready_at`, `expires_at`, `revoked_at`, `part_count`, `byte_size`, `row_count`, `manifest_sha256`, `download_count` and `last_downloaded_at`. No client ID, path or name.
- **Accounts.** Users stay as platform accounts and can still sign in; their memberships of the agency, its audit log and everything else are deleted.

## 7. Operator command (D11)

`python -m app.agency_offboarding` prints one JSON document and exits 0, 1 with `{"error": code}` on a refusal, and 2 with an argparse message when the arguments are invalid or `--confirm` is missing for `run`.

| Subcommand | Effect and output |
|---|---|
| `status --agency UUID` | `{"agency_id", "status", "purged_at", "closure", "export", "offboarding", "connections"}`: the closure times (from the closure row or the purge record), the export summary, the purge row's state, times and total deleted rows with their per-table counts, and the connections counted by state (`live`, `disconnecting`, `past_deadline`, `disconnected`); as `tracking_app`, read only |
| `run --agency UUID --confirm` | for a closed agency: the offboarding if it is not done, one teardown pass for the agency's connections (normal deadline), then the purge batches as `tracking_lifecycle` until `purged` or a refusal; prints each step's counts and the purge state |

Refusals: `agency_not_found`, `agency_not_closed` (with the current status, for `run`). The command never prints a name, an email, a token or a figure. `run` needs `TRACKING_LIFECYCLE_PASSWORD`, like the lifecycle runner. It does not move a teardown deadline earlier: a teardown that cannot revoke completes at its deadline, and `run` after it purges.

## 8. Logs and outputs (OV19)

Three registered events, each without fields: `agency_export_failed`, `agency_offboarding_failed` and `agency_export_unreadable`. The worker, the runner and the command print counts, closed codes, identifiers and times only.

## 9. API changes

Additions: the three routes of section 3.1 and the schemas `AgencyExportInput`, `AgencyExportState` and `AgencyExportView`. No existing path or schema changes; the OpenAPI snapshot gains these only (OV20).

## 10. Test inventory (OV01-OV20)

| Case | Test (modules under `backend/tests/`) |
|---|---|
| OV01 | `integration/test_agency_export.py::test_ov01_export_request_is_owner_only_reauthenticated_and_audited`, `::test_ov01_export_window_and_agency_status` |
| OV02 | `test_agency_export.py::test_ov02_export_contents_match_the_catalog_and_manifest`; `test_agency_export_contract.py` (catalog against the registry) |
| OV03 | `test_agency_export.py::test_ov03_export_beyond_the_bound_fails_without_storing`, `::test_ov03_a_zip_that_fails_its_checks_is_not_stored` |
| OV04 | `test_agency_export.py::test_ov04_parts_are_sealed_and_bound_to_their_export` |
| OV05 | `test_agency_export.py::test_ov05_download_streams_the_built_zip_for_owners_only`, `::test_ov05_download_is_gone_after_expiry_revocation_or_purge` |
| OV06 | `test_agency_export.py::test_ov06_export_pending_at_completion_is_discarded` |
| OV07 | `integration/test_agency_offboarding.py::test_ov07_offboarding_disconnects_revokes_and_disables_once` |
| OV08 | `test_agency_offboarding.py::test_ov08_teardown_revokes_at_the_provider_and_the_purge_waits`, `::test_ov08_a_teardown_past_its_deadline_no_longer_holds_the_purge` |
| OV09 | `integration/test_agency_offboarding_migration.py::test_ov09_function_covers_every_scoped_table`; `test_agency_offboarding.py::test_ov09_purge_leaves_no_row_of_the_agency` |
| OV10 | `test_agency_offboarding.py::test_ov10_what_stays_after_the_purge` |
| OV11 | `test_agency_offboarding.py::test_ov11_other_agencies_keep_every_row` |
| OV12 | `test_agency_offboarding_migration.py::test_ov12_function_refuses_agencies_not_closed_and_offboarded`, `::test_ov12_lifecycle_role_cannot_delete_tenant_configuration` |
| OV13 | `test_agency_offboarding.py::test_ov13_purge_is_bounded_and_resumable` |
| OV14 | `test_agency_offboarding.py::test_ov14_whatsapp_number_and_custom_domain_are_released` |
| OV15 | `test_agency_offboarding.py::test_ov15_workers_skip_closed_and_purged_agencies`, `::test_ov15_delivery_worker_skips_a_closed_agency` |
| OV16 | `test_agency_offboarding.py::test_ov16_operator_command_status_and_run`; `test_agency_offboarding_command.py` (arguments, `--confirm`) |
| OV17 | `test_agency_export.py::test_ov17_a_completion_between_build_and_store_discards_the_export`; `integration/test_agency_offboarding_journey.py::test_ov17_completion_against_an_export_build`, `::test_ov17_two_offboarding_workers`, `::test_ov17_purge_against_a_late_worker` |
| OV18 | `test_agency_offboarding_migration.py::test_ov18_upgrade_from_populated_0032`, `::test_ov18_grants`, `::test_ov18_downgrade_refuses_stored_rows`; the data policy rows in `test_data_policy.py` and `integration/test_data_policy_schema.py` |
| OV19 | `test_agency_offboarding_journey.py::test_journey_export_completion_offboarding_teardown_purge` (every log line and output of the journey), `::test_ov19_failures_log_codes_only` |
| OV20 | every existing module, updated only for the new head (`0033`), the table counts and the known tables; `test_contract.py`; the semantic OpenAPI diff of section 9 |

The journey of P4 is `test_agency_offboarding_journey.py::test_journey_export_completion_offboarding_teardown_purge`. The mutation check of P5 disables, one at a time, each safeguard listed in the handoff and records which test fails.

## 11. Helper and existing-test changes

- `tests/integration/conftest.py`: `TABLES` gains `agency_export_parts`, `agency_exports` and `agency_purges` before `report_export_contents`; `world` and the guards are otherwise unchanged.
- `test_postgres.py` knows the three new tables; the migration tests that pin the head (`test_attribution_models`, `test_identity_ledger_migrations`, `test_report_delivery_migration`, `test_saas_plans`) move to `0033_agency_offboarding`.
- `test_data_policy.py` and `test_data_policy_schema.py`: 99 tables, 11 user references, and the approved set gains the D-098 rules.

## 12. Routine details resolved here

1. The export window, its 24-hour cut-off, the 7-day lifetime, the bounds and the part size are module constants; tests change them through the module.
2. The download is refused once the closure completes (D2: nothing can be exported after completion); the ready file stays stored, unreachable, until its expiry or the purge (D5).
3. The request answers `202`, because the file is built in the background; the GET states derive `expired` like the 016-C view.
4. A cancellation revokes the open export, because the file holds every client's data and the agency no longer leaves.
5. Pending WhatsApp claims are revoked at offboarding, because the operator's verification does not check the agency's status.
6. Report exports revoked at offboarding carry the new reason `agency_closed`; connection exports keep the 009 reason `disconnection`.
7. The purge record's export summary holds totals only, no client ID or path.
8. `run` does not shorten the 72-hour teardown deadline (D7): the deadline already bounds the wait, and an operator who must end a provider's access uses `app.connector_purge`.
9. The pseudonym follows D-024 (`Closed agency <agency id>`).
10. The offboarding writes no audit rows (the actor is the platform and the audit log is purged); requests and revocations by Owners are audited.

## 13. Limits

- **Queued mail.** Invitation and `report_ready` messages carry no agency reference; they expire with their invitation or export and leave under the outbox rule (30 days after expiry). Their links stop working at once, because the offboarding revokes the invitations and exports.
- **Backups.** Not edited (D10); a restore must reapply the recorded purges (the 003 journal, 020).
- **Scale.** The bounds and the single-transaction offboarding are sized for development and the plan limits (5 clients, 10 connections); foreign keys without an index on the referencing side (the two self-references and `bookings.subject_id`) make each deleted parent scan its client's rows, as the existing retention does. Production sizes come with Q-004 and 020.
- **Live providers.** The teardown of live connections is an owner-operated check after the merge (D13).
