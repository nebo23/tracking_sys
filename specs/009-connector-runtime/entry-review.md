# Spec 009 entry review

Status: proposal for owner review, prepared 2026-11-15. No decision below is approved. Implementation of 009-A, migration 0009, runtime privileges and every other choice in this document wait for an explicit owner decision recorded for a stated scope.

## 1. Verified baseline

| Item | Observation |
|---|---|
| Branch | `codex/spec-009-connector-runtime` in `.worktrees/spec-009-connector-runtime`, clean working tree. |
| Merged baseline | `origin/main` is `3f6dc06` (merge of [PR 7](https://github.com/nebo23/tracking_sys/pull/7), Spec 008-A), confirmed with `git ls-remote` on 2026-11-15. The branch adds one handoff commit, `447ba72`. The local `main` ref (`3a3bba1`, checked out in the 005 worktree) is stale and was not used. |
| Schema | Head revision `0008_links_tracker`. No connector, OAuth-grant or provider-data table exists. Native `tracking_sys` was not touched. |
| Dependencies | `cryptography` 50.0.2 provides AES-GCM. No HTTP client package is pinned; the Google client in `app.services.google` uses the standard library `urllib`. 009-A needs no new dependency. |
| Roles | Agency roles `owner`, `admin`, `analyst`, `client_viewer`; `MANAGERS` = Owner and Admin. Database roles `tracking_app` (runtime) and `tracking_lifecycle` (retention deletes, D-024). |

## 2. Reuse and limits of existing code

| Existing element | Reusable for 009 | Guarantee that does not transfer |
|---|---|---|
| `app.privacy.token_secrets` (D-025): `SecretContext`, `seal`, `open_secret`, `rewrap`, `LocalKeyring`, `TokenSecretReference.destroyed` | Seal access and refresh tokens per version. The associated data binds agency, client, connector, secret, kind and version, so a ciphertext copied to another row or tenant fails. `connector_id` becomes the connection ID. `require_token_keys` answers 503 when the keyring is blank. | The contract has no table. Destruction in code only drops material from a value object; 009 must persist it and destroy the stored columns. Provider revocation is explicitly left to 009. |
| `IngestionSourceSecret` (004) | Column layout for sealed material and the version uniqueness pattern. | A webhook signing secret is created by the platform and retired by time; it is never revoked at a provider. `tracking_app` has no DELETE or material UPDATE on that table, so it gives no destruction path. |
| Google OAuth transaction (D-022, `app.services.google`) | Single-use state stored only as a SHA-256 digest; browser-binding cookie bound to the session digest (`link_binding_digest`); PKCE verifier derived from the raw state with a purpose-separated keyed HMAC, so neither is stored; `SELECT ... FOR UPDATE` consumption with a savepoint, so a rejected exchange still consumes the state. | `oauth_transactions` has no agency or client, its purpose is limited to `login` and `link`, and the principal is the platform user's own identity. A connector grant authorizes access to a client's provider account. The two must not share tables, cookies, redirect URIs, OAuth client settings or scopes. |
| Gmail sender (D-022) | None beyond the warning it gives: its refresh token is a platform deployment secret in ignored `.env` with send authority over the owner's mailbox. | Connector tokens are tenant data in sealed rows, one set per connection, never deployment settings. |
| Tenant authorization: `TenancyService._manager`, `get_client`, `_audit`, `resolve_scope` | Owner/Admin checks with the agency write lock; client visibility through grants; audited mutations in the caller's transaction; `client:read` for status reads. | `audit_events.actor_user_id` is mandatory, so steps completed by a worker cannot be audited there. They are recorded on the connection row (section 5). |
| 004 webhook verification: `verify_webhook`, `sign_webhook`, `WEBHOOK_WINDOW_SECONDS = 300` | Constant-time HMAC comparison over the raw body, rotation through several live secrets, timestamp window. | This is the platform's own generic scheme for customer servers. A provider defines its own header, algorithm and replay rules; an adapter must verify that scheme before data enters the runtime. |
| 004 scoped deduplication: `uq_collected_events_client_event` with fingerprint `duplicate` or `conflict` | The pattern for provider records: a unique key per connection and provider object, identical content is a duplicate, changed content is a counted conflict or a new observation. | Consent admission (J1), subject tokens, the field matrix, browser origins and tombstone admission govern end-user events. Aggregate social metrics carry no end-user subject. |
| `app.privacy.providers` | `feature_allowed` keeps every real connector row blocked while stale, unsupported or overdue. | No connector row is current. A synthetic adapter changes none of them. |
| Bounded workers: `app.mail_worker`, `app.lifecycle` | One bounded batch per run, `FOR UPDATE SKIP LOCKED` claims, advisory locks. No scheduler. | — |

## 3. Proposed first slice: 009-A connection lifecycle

009-A delivers one complete connection lifecycle against an in-process synthetic provider: connect through OAuth, show a safe status, run one single-page synthetic sync, handle terminal credential failure, reconnect, and disconnect with revocation, secret destruction and purge. Pagination, checkpoints, backfill, rate limits, usage, budgets, coverage states and provider webhooks belong to later slices.

### 3.1 Synthetic fixture used throughout

| Agency | Client | Connection | External account | Synthetic tokens |
|---|---|---|---|---|
| A1 | C1 | K1 | `syn-acct-777` | access `syn_at_K1…`, refresh `syn_rt_K1…` |
| A1 | C2 | K2 | `syn-acct-777` (same account) | `syn_at_K2…`, `syn_rt_K2…` |
| A2 | C3 | K3 | `syn-acct-777` (same account, other agency) | `syn_at_K3…`, `syn_rt_K3…` |

The synthetic provider issues separate tokens for each authorization, requires S256 PKCE, accepts each authorization code once, revokes per token, and records every call for assertions. It exists only in development and test settings and is refused in production configuration.

### 3.2 Walkthrough: connect

1. An Owner or Admin of A1 opens C1 and calls `POST /agencies/A1/clients/C1/connections` with `{"provider": "synthetic"}`. The server locks the agency, checks the manager role and the active client, and inserts a `connector_oauth_transactions` row holding agency, client, initiating membership, purpose `connect`, the state digest, the binding digest (bound to the session) and an expiry 10 minutes ahead. It sets an HttpOnly binding cookie distinct from the Google cookie and redirects (303) to the provider with state, the S256 challenge and the requested scopes.
2. The provider redirects to the fixed callback `GET /connectors/oauth/callback?state=…&code=…`. The path carries no agency or client. The server finds the transaction by state digest `FOR UPDATE` and requires a matching binding cookie and session, no prior consumption and no expiry. It consumes the transaction before any provider call.
3. In a savepoint it rechecks the initiator (active verified user, active Owner/Admin membership, active client), exchanges the code with the derived PKCE verifier, reads the external account identifier, and inserts connection K1 (`active`, generation 1) with two sealed secret rows. It then enqueues one sync run and writes the audit event `connector.connected`. Any failure rolls back the savepoint, while the consumed transaction still commits.
4. The browser is redirected to the completion page with only the connection ID or a fixed error code. Tokens, codes and state never appear in a response body, URL, log record or audit row.

Repeated, expired, mismatched or concurrent callbacks find the transaction consumed, expired or bound to another session and yield the fixed error `connection_failed` without a second grant. If a reconnect returns a different external account, the server rejects it with `account_mismatch`, revokes the unused tokens at the provider and stores nothing.

### 3.3 Status: member view and worker-only state

`GET /agencies/A1/clients/C1/connections/K1` requires `client:read`. An active connection:

```json
{
  "id": "00000000-0000-4000-8000-0000000000b1",
  "provider": "synthetic",
  "account": {"external_account_id": "syn-acct-777", "label": "Synthetic Brand"},
  "status": "active",
  "status_reason": null,
  "granted_scopes": ["synthetic.metrics.read"],
  "connected_at": "2026-11-15T10:00:00Z",
  "last_successful_sync_at": "2026-11-15T10:01:12Z",
  "actions": {"reconnect": false, "disconnect": true},
  "disconnect": null
}
```

After a completed disconnect, the provider account reference is cleared as part of the purge:

```json
{
  "id": "00000000-0000-4000-8000-0000000000b1",
  "provider": "synthetic",
  "account": null,
  "status": "disconnected",
  "status_reason": "user_requested",
  "actions": {"reconnect": false, "disconnect": false},
  "disconnect": {
    "requested_at": "2026-11-15T12:00:00Z",
    "completed_at": "2026-11-15T12:00:03Z",
    "revocation": "done",
    "secret_destruction": "done",
    "data_purge": "done",
    "purge_due_at": "2026-11-18T12:00:00Z"
  }
}
```

The member never receives worker-only state: sealed material, key IDs, secret versions and provider expiry; the connection generation; sync-run leases, attempts and raw provider error details; OAuth transaction digests; and the initiating membership. Members of A2, or members of A1 without a grant to C1, receive the same 404 as for an unknown connection.

### 3.4 Walkthrough: disconnect and verification

1. The Owner/Admin calls `POST /agencies/A1/clients/C1/connections/K1/disconnect`. In one transaction the server locks the agency and then K1 `FOR UPDATE`, sets `disconnecting`, increments the generation from 1 to 2, cancels K1's queued runs, sets revocation, destruction and purge to `pending` with `purge_due_at`, and audits `connector.disconnect_requested`. It answers 202 with the status.
2. A sync already running for K1 writes provider records only in a transaction that takes K1 `FOR SHARE` and requires `active` and its own generation. If the disconnect committed first, the write sees generation 2 and is discarded. If the write holds the lock first, the disconnect waits, and the purge removes what was written. In both orders, no record of K1 survives.
3. The bounded worker (`python -m app.connector_worker`) performs the teardown: it opens the refresh token, calls provider revocation, and records `done`, `unsupported` or a failed attempt. It then destroys the material of both secret rows, deletes K1's provider records, clears the account reference and sets `disconnected`. Destruction and purge run in one transaction after the revocation outcome is recorded.

Tests verify, for K1: the mock provider lists `syn_rt_K1` and `syn_at_K1` as revoked; every K1 secret row has status `destroyed` with ciphertext, wrapped key and nonces NULL; `connector_records` has no row for K1; no queued or running run remains; and captured logs, responses and audit rows contain no synthetic token value. For K2 and K3: tokens remain valid at the mock, secret rows and records are unchanged, and a new sync of K2 succeeds after K1's disconnect. A member of A2 cannot read or disconnect K1, and an analyst of A1 cannot disconnect it.

### 3.5 Terminal credential failure and reconnect (AC2)

When the provider answers `401`, the worker tries one refresh. A refresh rejected as invalid makes only that connection `reconnect_required` with reason `credential_expired` or `provider_revoked`: its queued runs are canceled, the generation increases, secrets become `revoked`, and provider records are retained without new writes. Other connections, including those of the same external account, continue. A reconnect starts a `reconnect` transaction for the same connection. On success it seals a new secret version, destroys the previous one, returns to `active` and audits `connector.reconnected`. Explicit disconnect remains available in `reconnect_required` and then follows section 3.4.

### 3.6 State transitions

| From | Event | To | Effect |
|---|---|---|---|
| — | Valid callback (connect) | `active` | Connection, generation 1, sealed secrets, one queued sync |
| `active` | Refresh succeeds after expiry | `active` | New secret version; prior version destroyed |
| `active` | `401` and refresh rejected | `reconnect_required` | Generation +1, runs canceled, secrets revoked, data retained |
| `reconnect_required` | Valid callback (reconnect), same account | `active` | New secret version, generation +1 |
| `active`, `reconnect_required` | Disconnect request | `disconnecting` | Generation +1, runs canceled, teardown pending |
| `disconnecting` | Teardown completes | `disconnected` | Revoked or reported, destroyed, purged; account cleared |
| `disconnecting` | Revocation still failing at the deadline | `disconnected` | Revocation `failed` is reported; secrets destroyed and data purged regardless (decision D6) |

`disconnected` is terminal. A new connection of the same account in the same client is a new row and a new authorization.

### 3.7 Permissions

| Action | Who | Check |
|---|---|---|
| Initiate, reconnect, disconnect | Owner or Admin of the agency | `_manager(agency, write=True)`, active client, audited |
| Inspect status | Any member with client visibility; read service keys with a grant to the client | `resolve_scope(..., "client:read")` |
| Complete the callback | The browser session that initiated it | State digest, binding cookie and session digest; the initiator is rechecked at completion |
| Sync and teardown | The bounded worker under `tracking_app` | Context read from the run and the connection row, joined on agency, client and connection; the generation fence on every write |
| Ingest keys, analysts, client viewers | No connector mutation | — |

## 4. Schema, privileges and transactions proposed for 009-A

Migration `0009_connector_runtime`, applied only to disposable databases until a separate native rollout decision.

| Table | Minimum columns | Keys and constraints |
|---|---|---|
| `connector_oauth_transactions` | id, agency_id, client_id, connection_id (reconnect only), initiator_membership_id, provider, purpose (`connect`, `reconnect`), state_digest, binding_digest, created_at, expires_at, consumed_at | Unique state_digest; client and membership composite foreign keys; reconnect requires connection_id |
| `connector_connections` | id, agency_id, client_id, provider, external_account_id, account_label, status, status_reason, generation, granted_scopes, created_by_membership_id, connected_at, last_successful_sync_at, disconnect_requested_at, disconnected_at, revocation_status, destruction_status, purge_status, purge_due_at, teardown_attempts, updated_at | Unique (agency_id, client_id, id); partial unique (client_id, provider, external_account_id) while not `disconnected`; a disconnected row has a NULL account reference; provider limited to `synthetic` in 009-A |
| `connector_token_secrets` | TokenSecretReference row of 003 section 8: id, agency_id, client_id, connection_id, kind, version, alg, aad_version, kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext, status, provider_expires_at, last_refreshed_at, created_at, destroyed_at | Unique (connection_id, kind, version); `status = 'destroyed'` exactly when all material is NULL; composite foreign key to the connection |
| `connector_sync_runs` | id, agency_id, client_id, connection_id, connection_generation, status (`queued`, `running`, `succeeded`, `failed`, `canceled`), lease_expires_at, attempt, error_kind, created_at, started_at, finished_at | At most one queued or running run per connection; composite foreign key |
| `connector_records` | id, agency_id, client_id, connection_id, connection_generation, provider_object_id, observed_at, values (bounded JSONB of synthetic metrics), fetched_at | Unique (connection_id, provider_object_id); composite foreign key; deletion by connection |

Runtime privileges for `tracking_app`: SELECT and INSERT on the five tables; UPDATE only on status, outcome, timing and generation columns, and on secret material columns only for destruction and rewrap; DELETE only on `connector_records`. `tracking_lifecycle` deletes consumed or expired connector OAuth transactions one day after the end, mirroring the D-024 rule for `oauth_transactions`. The audit action and resource constraints gain `connector.connected`, `connector.reconnected`, `connector.disconnect_requested` and the resource type `connection`.

Lock order: the agency row (administration), then the connection row. The callback locks its transaction before the connection. Disconnect, fencing and teardown each commit in short transactions without holding locks across provider calls, except the code exchange, which runs under the consumed transaction lock as in D-022.

Disposable PostgreSQL checks: migration upgrade and downgrade with grants; two threads submitting the same callback produce one connection and one exchange; a callback racing a second transaction for the same client and account produces one live connection; a sync write racing a disconnect leaves no record of K1 in either order; the runtime role cannot delete secret rows or read another table outside its grants.

## 5. Runtime contracts

| Contract | Tenant scope | Writer | Minimum fields | Reader-visible | Slice |
|---|---|---|---|---|---|
| Connection | agency, client, connection | API (connect, disconnect) and worker (status, teardown) | Section 4 | Provider, account reference, status and reason, scopes, connected and last-sync times, actions, disconnect outcomes | 009-A |
| SyncRun | agency, client, connection, generation | Worker; API enqueues | Section 4; 009-B adds kind (incremental, backfill), window and page count | Status, started and finished times, coarse error kind | 009-A (single page), 009-B |
| Checkpoint | agency, client, connection, stream | Worker, in the same transaction as the page it covers | Stream, cursor or time position, complete_through, updated_at, run ID | complete_through only | 009-B |
| Capability | Provider adapter version (code data, no tenant) | Adapter declaration, reviewed per provider | OAuth flow and PKCE, refresh, revocation scope (token or grant), account kinds, metric catalog with units and intervals, history window, pagination, rate-limit signals, cost unit, webhooks | Metric availability per connection | 009-A (OAuth fields), 009-C |
| ProviderError | Run attempt | Adapter mapping to runtime kinds | Kind (`unauthorized`, `forbidden`, `rate_limited`, `retryable`, `permanent`, `budget_exhausted`), retry-after, provider code | Kind only | 009-A (`unauthorized`), 009-B |
| UsageRecord | agency, client, connection, run | Worker per provider call, including failed and retried calls | Provider, unit, quantity, call outcome, occurred_at, budget period | Consumed and remaining budget | 009-B |

## 6. Acceptance mapping

| Criterion | Slice | Observable result |
|---|---|---|
| 1. State, replay, PKCE, no token exposure | 009-A | Section 3.2 cases; one connection under concurrent callbacks; the mock rejects a missing or wrong verifier; token search over captured logs, responses, URLs and audit rows finds nothing |
| 2. Expiry or revocation disconnects only the affected connection | 009-A | Section 3.5: K1 `reconnect_required`, runs canceled; K2 and K3 continue |
| 3. 429 backoff, 401 reconnection, crash recovery without duplicates | 009-A for 401; 009-B for the rest | 401 as above; 009-B injects a crash between page write and checkpoint and verifies each record once and no skipped page |
| 4. Availability, last sync, coverage and cost | 009-C (009-A shows status and last successful sync only) | Status after a successful page, a delayed page, an unsupported metric and a budget stop; observed zero distinct from missing, unsupported and stale |
| 003 case D3 | 009-A | Section 3.4: revocation at the mock, destroyed material, purge within `purge_due_at`, honest `failed` or `unsupported` outcomes |
| Webhook delivery | 009-D | A synthetic provider signature scheme with a valid delivery, a duplicate (deduplicated by provider event ID per connection) and a signature failure (rejected before parsing) |

Still planned after 009-A: 429 with `Retry-After`, `403`, retryable `5xx`, pagination, backfill, overlapping runs, crash recovery, usage accounting and budget stops (009-B); coverage and provenance states (009-C); provider webhook verification (009-D).

## 7. Decisions for 009-A

| ID | Recommendation | Main alternative | Effect | Acceptance cases enabled |
|---|---|---|---|---|
| D1 Slice boundary | 009-A as sections 3 and 4: complete lifecycle, synthetic provider, single-page sync | Secrets table and OAuth only, disconnect later | Proves D3 and AC2 end to end in one reviewable slice | AC1, AC2, AC3 (401), D3 |
| D2 Schema | The five tables of section 4 in migration 0009 | Fewer tables now (no runs or records), with stop and purge shown only in code | Without runs and records, stopping in-flight work and purge cannot be observed in the database | D3 purge and fencing |
| D3 OAuth transactions | A separate tenant-scoped `connector_oauth_transactions` table reusing the D-022 mechanism | Widen `oauth_transactions` with agency and client columns | Keeps sign-in and connector principals apart | AC1 isolation |
| D4 Permissions | Owner/Admin connect, reconnect and disconnect; `client:read` inspects | Allow analysts too; or a client self-connect link, deferred | Matches the 004 administration rule | Permission denials in 3.4 |
| D5 Same external account | Allowed in several clients and agencies; one live connection per client, provider and account; tokens, runs and data never shared between connections | Global uniqueness of the account | A global block would reveal another tenant's connection and couple tenants | The K1/K2/K3 isolation case |
| D6 Teardown order and failure | Revoke, then destroy and purge in one transaction, by the bounded worker; 72-hour synthetic deadline (the 003 candidate); after the deadline, destroy and purge anyway and report revocation `failed` with instructions to remove the app at the provider | Keep the secrets until revocation succeeds | Bounds how long secret material can remain; reporting stays honest | D3 and D4 |
| D7 Terminal credential failure | One refresh attempt, then `reconnect_required`, data retained without writes until reconnect or disconnect; per-provider purge periods decided in 010-013 | Purge automatically on expiry | Avoids losing history on a temporary expiry; the retention period stays a Q-012 provider decision | AC2 |
| D8 Secret destruction | Keep the row as evidence, NULL all material, enforced by a constraint | Delete the secret rows | Preserves the destroyed status of the D-025 contract | D3 destruction check |
| D9 Worker and scheduling | No scheduler and no queue product in 009-A: a bounded `python -m app.connector_worker` with `SKIP LOCKED` claims and leases; Q-009 stays open | Adopt a queue now | No new dependency; durable scheduling is decided before 009-B or real providers | Fencing and teardown tests |
| D10 Privileges and dependencies | No new package; `tracking_app` with the column-limited grants of section 4; lifecycle deletion of connector OAuth transactions after one day | A dedicated connector database role now | Same model as 004; role separation can follow hosting (020) | Grant and denial checks |

Note for 010-013: some providers may revoke the whole application grant of an account rather than one token. When K1 and K2 share such a grant, revoking K1 can invalidate K2. The proposal still revokes, and K2 then shows `reconnect_required` instead of failing silently. Each provider's revocation scope needs dated evidence and is declared in its Capability.

## 8. Open questions placed by slice

- Q-001: the first consumers are 010 Instagram, 011 YouTube, 012 LinkedIn and 013 X. Each declares the Capability fields of section 5. The stale 2026-11-03 provider rows indicate what to verify: Instagram deauthorize and deletion callbacks and refresh windows; YouTube 30-day authorization recheck, 7-day deletion and limited use; LinkedIn token and refresh lifetimes and short caches for member data; X paid credits, batch compliance and 24-hour deletion. None is evidence of access, and each needs dated, provider-specific confirmation before live use.
- Q-010: a third-party integration changes who holds provider tokens (an aggregator account instead of TokenSecretReference rows), the processor chain, the revocation path, whether provider terms allow the intermediary, and the per-account cost. The adapter contract keeps both routes possible; 009-A decides neither.
- Q-004: 009-A uses synthetic call limits for tests only. Commercial budgets, account counts and history depth remain open and are first needed for 009-B budget stops and 013 pricing.
- Q-009: 009-A needs no scheduler. 009-B needs leases, checkpoints and usage accounting; periodic scheduling and queue selection are needed before a real provider syncs on a schedule.
- Launch scope remains both social analytics and attribution (D-004, D-045). Aggregate social metrics cannot identify a buyer or establish revenue; attribution continues to rely on 005 links, 006 identity and 007 ledger evidence.
