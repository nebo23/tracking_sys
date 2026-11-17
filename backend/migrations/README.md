# Database migrations
Alembic tracks schema revisions using dedicated migration credentials. The API role only reads the revision table.

Run from the repository root using the project environment:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini current
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

The initial 0001_foundation revision introduces no business tables. Alembic creates its own version table; the revision grants tracking_app SELECT access. A downgrade revokes that grant and returns to the base revision.

Only run the following recovery exercise on the dedicated disposable test database, after verifying its name and contents:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini downgrade base
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

Do not treat a successful foundation downgrade as proof that later data migrations are reversible. Review future generated migrations, ownership/grants, locking, data loss, backfill, and recovery before execution. The API does not run migrations during startup.

Revision 0002_tenancy creates the six models approved in D-017. Composite keys prevent cross-agency grants and audit references; application services still enforce access for individual users. Runtime may append/read audit records but cannot update/delete/truncate them.

The 0002 downgrade takes exclusive table locks and refuses populated tables. Use a reviewed forward fix when data exists. Its upgrade and empty downgrade/recovery were tested on disposable PostgreSQL; tracking_sys received only the additive upgrade, with no sample records.

Revision 0003_auth implements D-019: ten authentication/access tables, nullable users.email_verified_at, expanded audit checks, and restricted grants. Runtime may insert identities and update their verification/timestamp columns, but cannot change user status. Security events remain append-only. Tokens and keys are stored as digests; queued mail payloads are encrypted.

The 0003 downgrade refuses non-empty auth tables, verified identities, or auth audit records under exclusive locks.

Revision 0004_identity implements D-022: external_identities, oauth_transactions, verification_challenges, nullable mail_outbox.expires_at, and the extended security_events action check. Runtime may insert into the new tables and update only their consumption, attempt, invalidation, and last-login columns; it cannot delete from them. The 0004 downgrade refuses populated identity state. Native tracking_sys received the additive 0004 upgrade on 2026-11-04 with owner approval and now has 19 application tables. See [current evidence](../../specs/002-tenancy-access/auth-evidence.md).

Revision 0005_lifecycle implements D-024 decision 4 for specification 003-A3: it grants the separately provisioned tracking_lifecycle role SELECT and DELETE on auth_sessions, auth_tokens, verification_challenges, oauth_transactions, auth_rate_limits, and mail_outbox, and changes no table, data, or tracking_app privilege. Upgrade stops with a message when the role does not exist; downgrade only revokes the grants. It has been applied only to disposable databases; the native rollout needs owner approval. See the [lifecycle guide](../../docs/engineering/data-lifecycle.md).

Revision 0006_account_closure implements D-024 decision 3 for specification 003-A5. It adds nullable users.closed_at with a check that a closed account is disabled, and the account_closed security action. It grants tracking_app UPDATE on only email_normalized, display_name, status, and closed_at. It grants tracking_lifecycle SELECT on users and SELECT and DELETE on password_credentials and external_identities. Audit and security events stay append-only. The downgrade refuses populated closure state. It has been applied only to disposable databases.

Revision 0008_links_tracker implements D-033 for specification 005. It adds six client-scoped tables (link_campaigns, link_content_references, link_utm_templates, link_destination_origins, link_domains, managed_links) and the nullable collected_events.link_id with a same-client composite foreign key. tracking_app may insert the new rows and update only their reviewed mutable columns (statuses, labels, template parameters, origin query names, domain verification state, link expiry) and collected_events.link_id; issued link provenance, slugs, hostnames and codes are not updatable, and it cannot delete from the new tables. tracking_lifecycle receives nothing new. The downgrade refuses populated 005 state, event link references, or 005 audit records. It has been applied only to disposable databases.

Revision 0009_connector_runtime implements D-048 for specification 009-A. It adds five client-scoped tables (connector_connections, connector_oauth_transactions, connector_token_secrets, connector_sync_runs, connector_records). Every reference to a connection is a composite (agency_id, client_id, id) foreign key. A partial unique index allows one live connection per client, provider and external account, so other clients may connect the same account independently. A check keeps sealed token material NULL exactly when a version is destroyed. tracking_app may insert rows and update only the columns that the lifecycle transitions write (listed in the 009 entry review, section 9.2). It may delete only connector_records, for the disconnect purge. tracking_lifecycle receives SELECT and DELETE on connector_oauth_transactions for the one-day cleanup. The audit constraints gain three connector actions and the connection resource. The downgrade refuses populated connector state. Apply it only to disposable databases until a native rollout is approved.

Revision 0010_connector_sync implements D-049 for specification 009-B. connector_sync_runs gains a kind (incremental or backfill), a window, a not-before time, a retry count and a page count. It adds connector_checkpoints (one per connection and stream: the opaque cursor of the next page and the coverage watermarks) and connector_usage_records (one per provider data call, reserved before the call and settled after), both with composite connection keys. tracking_app may insert both, update a checkpoint's position and watermarks, settle a usage record's outcome, update the new run columns except kind, and delete checkpoints for the disconnect purge; it cannot delete usage records. The downgrade refuses populated 009-B state. Apply it only to disposable databases until a native rollout is approved.

Revision 0011_connector_coverage implements D-049 for specification 009-C. connector_connections gains the provider's account_kind, cleared by the disconnect purge. connector_records gains source_run_id and adapter_version; the run reference is a composite (agency_id, client_id, connection_id, id) foreign key backed by a new unique constraint on connector_sync_runs, so a record can only name a run of its own connection. tracking_app may update the three new columns. The downgrade refuses populated 009-C state. Apply it only to disposable databases until a native rollout is approved.

Revision 0012_connector_webhooks implements D-049 for specification 009-D. It adds connector_webhook_deliveries, which records each verified provider webhook delivery by provider and SHA-256 digest of its event ID (unique together), with its receipt time and the number of connections notified. It holds no payload, account or tenant data, so it is not tenant-scoped. tracking_app may insert rows and update the notified count; tracking_lifecycle receives SELECT and DELETE for the 7-day cleanup. The downgrade refuses populated 009-D state. Apply it only to disposable databases until a native rollout is approved.

Revision 0013_connector_streams implements D-053 for specification 010-A. connector_sync_runs and connector_records gain a stream; the open-run index becomes one open run per connection and stream, and records are unique per connection, stream and provider object. connector_records also gains the media product type and a bounded JSON object of closed reasons for metrics the provider did not report. connector_connections accepts the provider synthetic_instagram and the reasons deauthorized and deletion_requested, and may reference connector_deletion_requests, a new table that keeps only the provider, a random confirmation code, the receipt and completion times and the number of connections stopped. tracking_app may insert and complete deletion requests, set a connection's deletion request, and write the new record columns; tracking_lifecycle receives SELECT and DELETE on connector_records for the 730-day limit. The downgrade refuses populated 010-A state. Apply it only to disposable databases until a native rollout is approved.

Revision 0014_instagram_provider implements D-055 for specification 010-C. The provider checks of connector_connections, connector_webhook_deliveries and connector_deletion_requests accept the live provider instagram next to the two synthetic providers. It changes no table, column, index or privilege. The downgrade refuses any connector state of the live provider, including OAuth transactions and usage records. Apply it only to disposable databases until a native rollout is approved.
