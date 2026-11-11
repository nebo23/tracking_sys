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
