# Specification 004: ingestion design for review

Prepared: 2026-11-10. Revision 2: 2026-11-10, after comparison with the code merged in `main` at `bab3a33` (PR 2). Status: approved for local and disposable implementation as D-027 (2026-11-10), which accepts every recommendation in the [decision packet](decision-packet.md). Real customer intake, native migration and publication keep their separate gates. Read with the [spec](spec.md), [entry review](entry-review.md) and [predecessor readiness](../../docs/planning/spec-004-readiness.md).

## 1. Verified baseline

Facts checked in code at `bab3a33`, which the 004 design must respect:

| Area | Current behavior | Consequence for 004 |
|---|---|---|
| Service credentials | Agency-level `tsk_` keys, documented as read-only. A grant row means `client:read`; `can_view_financials` adds `finance:read`. Every use rechecks expiry (1-90 days), agency, creator Owner/Admin membership and verified user. | No write authority exists. A write flag on the existing grant row would also give every ingestion key client read access. |
| Request bodies | `RequestBoundary` buffers every mutation body and rejects anything over 16 KiB before routing. | The draft's 64 KiB limit would need a middleware change. |
| CORS | One credentialed `CORSMiddleware` limited to configured platform origins. | Customer origins must never join this credentialed policy. Public routes get their own per-source, uncredentialed policy (R004-01). |
| Logging | Allowlisted events only; uvicorn access lines are written as templates without the request line. | URL path keys are not logged by the server. No per-event log is needed. |
| Locks | Agency mutations lock the agency row `FOR UPDATE`; user/session locks use `FOR NO KEY UPDATE`; email creation uses a one-key advisory lock; the lifecycle runner uses the two-key space with namespace 3003. | 004 uses its own two-key advisory namespace and never takes agency or user locks while holding it. |
| Audit | `audit_events` has check constraints on action and resource type, and its actor must be an agency member user. | New administrative actions extend both constraints. Machine ingestion is not written to the audit table. |
| Privacy contracts | `consent.ConsentRecord` requires 64-hex subject and notice digests; `collection.sanitize_submission` needs stored field descriptors and a mapping; `minimize_url` keeps one allowlisted parameter set; `deletion.admission` takes subject and replay tombstones; keyed identifiers need at least 32 key bytes. | Ingestion supplies server-side descriptors, splits URL parameters by purpose, and needs one independent tombstone key. |
| Keys | Settings hold the auth, verification and mail keys. The D-025 token keyring is a library contract (`LocalKeyring`) without a setting. | Webhook secrets and tombstones need new settings and approved custody. |
| Test guards | Integration fixtures accept only the listed tables on `tracking_foundation_test:55433`, and the registry test compares every column with the migrated database. | New tables must be classified and added to the fixture list. |

Baseline verification: the full suite on `bab3a33` passed 380 tests with PostgreSQL enabled on fresh disposable storage on 2026-11-10 (section 15).

## 2. Changes from the first draft

1. **Body limit**: keep the existing 16 KiB boundary; the draft's 64 KiB value is withdrawn.
2. **Public transport** (corrected after review finding R004-01): public routes accept `text/plain` (a CORS simple request) or `application/json` (which browsers preflight). They read no cookies. A dedicated policy lets only the source's registered origins read responses, without credentials. The credentialed platform policy never covers public routes, and customer origins never join it. See section 6.
3. **Write authority**: a distinct ingestion credential kind replaces a per-grant write flag, so an ingestion key has no read or finance access.
4. **Consent binding**: the client no longer presents a receipt. The server derives the consent basis from current records under the subject lock and stores the record IDs with the event. Substitution is impossible by construction.
5. **Subjects**: a subject token is created only by an explicit consent action, never before consent, and every 004 event requires one.
6. **Identifiers and free text**: they are excluded from 004 payloads. Deleting them by email or phone requires keyed identifier indexes that belong with identity (006).
7. **Receipts**: the separate lifetime receipt table is removed. The event row is the receipt. The lateness bound makes deduplication complete for honest retries after a row expires, and replay tombstones cover deleted subjects.
8. **Event ID keying**: the event ID is stored as a scoped UUID. Only replay tombstones use the keyed form defined by 003.
9. **Conflicts**: conflicts update counters on the accepted row and in daily diagnostics. No incoming content or fingerprint is retained.
10. **Retention**: the draft's 30-day payload period would remove attribution history before lookback and year-over-year reporting exist. Revision 2 proposes a provisional 13-month development value and keeps Q-012 open for real intake.

## 3. Scope and traceability

| Source | 004 deliverable | Boundary |
|---|---|---|
| PDF-001/002/005 | Public and authenticated event APIs with one envelope | Tracker/pixel delivery is 005; native SDKs are 021. |
| PDF-004/008 | Fixed v1 event types; registered forms with mapped non-identifying fields | No arbitrary DOM capture, keystrokes, free text or contact identifiers in 004. |
| PDF-006/007 | Minimized URLs; campaign parameters and click identifiers split by purpose | No query values other than allowlisted parameters; no fragments or credentials. |
| PDF-009 | Generic HMAC-signed webhook with raw-body verification and a replay window | Provider-specific adapters require named provider contracts in their own specifications. |
| PDF-013 | Daily outcome counters and single-event metadata lookup | No payload display and no frontend debugger in 004. |
| PDF-014 | Atomic scoped deduplication, conflict counting and trusted upgrade | Never global event ID uniqueness. |
| PDF-082/084 | Versioned bot heuristics and a trusted internal flag, stored as a traffic label | Labels are heuristic; no IP or user-agent retention. |

Out of scope: attribution and revenue models, financial truth (007), identity linking (006), outbound delivery (014), tracker scripts (005), React, brokers, paid providers and new dependencies.

## 4. EventEnvelope v1

Request bodies are strict JSON objects. Unknown fields are rejected, and at most one event is accepted per request.

| Field | Rule |
|---|---|
| `schema_version` | Literal `1`. |
| `event_id` | UUID created once by the sender and reused for every retry and every browser/server copy. |
| `event_type` | `page_view`, `link_click`, `form_submit`, `lead_signal` or `purchase_signal`. Custom types require a later reviewed schema. |
| `occurred_at` | Timezone-aware; at most 5 minutes after and 7 days before the database receipt time (decision packet D6). It never orders consent or deletion. |
| `subject_token` | Required server-issued `sbj_` token (section 7). Raw email, phone or name is never accepted. |
| `internal` | Optional boolean, accepted only from trusted server and webhook sources; public input is rejected. |
| `payload` | The event type's schema below. |

| Event type | Payload | Required purpose |
|---|---|---|
| `page_view` | `url` (required), `referrer_origin` (optional, scheme and host only) | `analytics.first_party` |
| `link_click` | `url`, `link_url` (both required) | `analytics.first_party` |
| `form_submit` | `url`, `form_key` (registered), `fields` (object of mapped fields) | `analytics.first_party` |
| `lead_signal` | `action` (`[a-z0-9_]{1,64}`), optional `url` | `attribution` |
| `purchase_signal` | `external_ref` (`[A-Za-z0-9_.:-]{1,128}`), `amount_minor` (integer 0 to 10^12), `currency` (`[A-Z]{3}`), optional `url` | `attribution` |

The server adds agency/client (from credentials or source), `first_received_at`/`last_received_at` (database clock), the source channel and trust rank, the consent basis, the traffic label, policy versions, the revision and the fingerprint. Senders cannot set them. A `purchase_signal` is an unverified claim from its sender; it is never revenue evidence and creates no financial record (007 owns financial truth).

## 5. Field, purpose and data-class matrix

| Input | Treatment | Stored as | Purpose | Class (proposed) |
|---|---|---|---|---|
| Page and link URLs | `minimize_url`: scheme, host, port, path; no credentials or fragment. Query: `utm_*` kept when analytics is granted; click identifiers (`gclid`, `gbraid`, `wbraid`, `fbclid`, `msclkid`, `ttclid`, `li_fat_id`, `twclid`) kept only when attribution is also granted, otherwise dropped and counted. A path holding an email-like value or a Luhn-valid card number rejects the event. A retained query value holding one is removed and counted as `sensitive_query_value` (review observation). Both checks run on the decoded text and on one further decoding level. They recognize these patterns only, not personal data in general. | `payload.url` | analytics; click IDs also attribution | `event.content` |
| Referrer | Origin only. | `payload.referrer_origin` | analytics | `event.content` |
| Form fields | `sanitize_submission` with stored descriptors (never-collect, unmapped, card scan), then a class allowlist: `form.option` (value in the registered options), `form.code` (`[A-Za-z0-9_.-]{1,64}`), `form.quantity` (integer 0 to 10^6). Free text, email, phone, name, address and every other class are dropped with a reason code. At most 32 fields. | `payload.fields` | analytics | `event.content` |
| Lead action, purchase claim | Pattern and range validation. | `payload.*` | attribution | `event.content`; purchase fields readable only with `finance:read` |
| Subject token | SHA-256 digest only. | `collection_subjects.token_digest` | consent evaluation and linkage of one browser's events | `collection.subject` |
| IP address, user agent | Used transiently for rate-limit buckets and bot heuristics; never stored. | Keyed rate-limit bucket (existing `security.telemetry`) | necessary (abuse control) | existing class |
| Event ID | Scoped UUID. | `collected_events.event_id` | necessary (deduplication) | `event.delivery_state` |

An optional field removed by minimization is dropped and counted. If minimization removes a required field, or a value fails its pattern, the event is rejected. Dropped values are never retained.

## 6. Routes and trust

Trusted routes follow the existing `/agencies/{agency_id}/...` convention. Trust ranks: public browser 1; webhook and trusted server 2.

| Route | Authorization and behavior |
|---|---|
| `POST /agencies/{a}/clients/{c}/events` | Bearer key of kind `ingest`, live under the existing rules, with a grant for exactly this agency and client. Rank 2. |
| `POST /agencies/{a}/clients/{c}/consent` | The same ingest key records consent with source `api` and the notice digest the sender attests (section 7). |
| `POST /collect/v1/{public_key}/events` | Public key selects one active browser source of an active client. Origin must exactly match the source's allowlist. No cookies or Authorization header are read. Rank 1. |
| `POST /collect/v1/{public_key}/consent` | Explicit consent choices; creates the subject on the first grant (section 7). |
| `POST /collect/v1/{public_key}/erasure` | The token holder erases that pseudonymous subject (section 10). |
| `POST /webhooks/v1/{source_id}/events` | `X-Tracking-Signature: t=<unix>,v1=<hex>`, an HMAC-SHA256 over `t + "." + raw body` with the source secret, checked in constant time before JSON parsing. The timestamp must be within 5 minutes. Every secret version is accepted until its own `retires_at`: the current version, and each rotated-out version for 24 hours after the rotation that replaced it, however many rotations fall in that period (R004-03). Rank 2. |
| `POST/GET/PATCH /agencies/{a}/clients/{c}/ingestion-sources[/{id}]`, `POST .../ingestion-sources/{id}/secret` | Owner/Admin; audited. Create a browser source (returns a non-secret `pk_` key) or a webhook source (returns its secret once); disable, re-enable, edit origins or notice digest; rotate a webhook secret. |
| `PUT/GET /agencies/{a}/clients/{c}/collection-forms[/{form_key}]` | Owner/Admin; audited. Field descriptors, classes and option lists. |
| `POST /agencies/{a}/service-credentials` | Existing route with a new `kind`: `read` (default, unchanged behavior) or `ingest`. Requesting financial visibility for an ingest key is rejected. |
| `GET /agencies/{a}/clients/{c}/event-diagnostics?from=&to=` | `client:read`; daily counters, range at most 31 days. |
| `GET /agencies/{a}/clients/{c}/events/{event_id}` | `client:read`; metadata only (type, channel, trust, revision, times, traffic label, conflict count). No payload or subject. |
| `POST/GET /agencies/{a}/clients/{c}/deletion-requests[/{id}]` | Owner/Admin; audited; by subject token or event ID (section 10). |

Public responses: accepted, duplicate, conflict, consent-suppressed, unknown or deleted subject, and replay-blocked all return the same `202 {"status":"received"}`. Structural failures (unknown or disabled key 404, Origin 403, body 413, schema 422, rate 429) disclose no stored state. Browser access (R004-01): the public routes accept only `text/plain` (no preflight) and `application/json` (preflighted) bodies. Any other or missing media type returns 415. A preflight is answered with 204 only for an Origin registered for that public key's active browser source, method POST, and no requested header other than Content-Type. That answer allows POST and Content-Type for 600 seconds, without credentials. Every other preflight receives 403 without CORS headers. Once a route accepts the Origin, its responses carry `Access-Control-Allow-Origin` for that origin, with `Vary: Origin` and never `Access-Control-Allow-Credentials`. The page can therefore read the consent token and error codes. Unknown keys and rejected Origins stay unreadable. The credentialed platform CORS policy is not applied to public routes, and customer origins are never added to it, so platform cookies and CSRF keep their boundaries. A public key and a valid Origin are routing and abuse controls, not authentication.

## 7. Subjects and consent

- **Issuance only with consent.** A public or API consent request without a token that grants at least one purpose creates a `collection_subjects` row (token `sbj_` plus 32 random bytes, stored as a SHA-256 digest) and one `consent_records` row per choice. The response returns the token once, the record IDs as receipts, and the resulting states. It is meant to be read by the registered page, which needs the token for later events (section 6). A request that grants nothing creates no subject and stores nothing. Under J1, the tracker (005) sets no identifier before this point.
- **Changes.** A request with a valid token appends records (granted, denied or withdrawn) under the client lock. The latest record by database receipt time wins (`consent.current_state`).
- **Record contents.** These follow `ConsentRecord`: purpose, state, source (`tracker_banner` for public, `api` for trusted), profile J1, policy version, the `subject_ref` (see below), and a notice digest. For browser sources the server copies the digest from the source configuration; the browser cannot choose it. Trusted API senders attest it. `captured_at` is stored but never used for ordering. A grant expires 12 months after receipt (packet D7). GPC may only deny, as the contract enforces.
- **`subject_ref` for random tokens.** The token digest is the 64-hex `subject_ref`, with key ID `sha256-token`. A digest of a 256-bit random token cannot be enumerated, so no key is needed. Keyed subject references for email and phone remain with 006.
- **Consent basis.** Admission evaluates `require_all` over the event type's purposes using the current records, and stores the IDs of the deciding records in `collected_events.consent_basis`. The client never supplies a receipt, so a receipt cannot be copied between subjects or clients.
- **Field-level consent.** The URL parameter split in section 5 is the field-level enforcement required by acceptance criterion 5.

Trust boundary: a public browser can create subjects for itself and record its own choices. It cannot act for another subject without that subject's bearer token. A subject token proves possession, not identity or legal compliance.

## 8. Admission transaction and concurrency

Order inside one database transaction:

1. Bound and parse the body (16 KiB, strict schema). For webhooks, verify the signature over the raw body before parsing.
2. Resolve the source or ingest key (no row locks) and apply the rate limit.
3. Set `lock_timeout` (2 s) and take `pg_advisory_xact_lock(4004, int4(client_id))` (packet D10).
4. Re-resolve live scope: client, agency, source or key, creator membership and user. A disabled or archived item rejects the event. Then check the occurred time against the receipt time, a public `internal` flag, and the payload schema.
5. Look up the subject by token digest. An unknown token is rejected (`unknown_subject`, or `subject_deleted` when a subject tombstone matches).
6. Check event replay tombstones with `deletion.admission`. A matching key rejects the event (`replay_before_deletion`).
7. Evaluate consent with `require_all` under J1. Denial suppresses the event, stores nothing and increments a counter.
8. Minimize and validate (section 5). Compute the canonical fingerprint: SHA-256 of sorted-key JSON over the schema version, type, occurred time (UTC, microseconds), subject ID, payload and internal flag.
9. `INSERT ... ON CONFLICT (client_id, event_id) DO NOTHING`, then resolve the outcome (section 9). Update the subject's `last_activity_at` and the daily counter, then commit.

Receipt times (`first_received_at`, consent `received_at`, tombstone `effective_at`) are read with `clock_timestamp()` after the lock is held, not from the transaction start, so receipt order is lock order even when a later-starting transaction acquires the lock first.

Every consent change and deletion takes the same client lock before reading privacy state. A withdrawal or deletion therefore either commits before the event's privacy check, and the event observes it, or waits for the event to commit and then removes or supersedes it. No interleaving lets an event pass a stale check. The lock key's 32-bit hash may make two clients share a lock; that costs throughput, never authorization.

Lock order: an agency lock (deletion requests are audited under the agency write lock) comes before the client privacy lock. Holding the client lock, code takes only row locks on 004 tables and the foreign-key share locks of inserts. It never takes agency, user or session locks. A lock timeout returns `503` with `Retry-After`.

Revocation window: scope is re-resolved after the lock, but a credential revoked between that check and the commit can still complete the in-flight event. This matches the existing read semantics. The window is bounded by the statement timeout. Subsequent requests are denied.

## 9. Deduplication, conflicts and upgrades

The unique identity is `(client_id, event_id)`. An existing row is read `FOR UPDATE` after the conflicting insert.

1. **New:** one row; trusted response `201`.
2. **Same fingerprint:** `duplicate`; nothing changes except `last_received_at`. Trusted response `200`.
3. **Different fingerprint, same or lower trust:** `conflict`. The accepted row keeps its content; `conflict_count` and `last_conflict_at` change, and a counter is incremented. Trusted response `409`.
4. **Higher trust (public to server/webhook), same event type and subject:** `upgraded`. Consent and minimization are applied to the trusted copy first. It replaces the payload, occurred time, source and trust, increments `revision`, and keeps `first_received_at`. Trusted response `200`.
5. A different type or subject, or equal-trust disagreement, is a conflict. Public input never overwrites anything. Arrival order never selects financial truth.

Late arrivals keep both clocks. Reports (later specifications) count rows by `(client_id, event_id)` at their current revision, so a late or upgraded copy is never counted twice.

## 10. Deletion and replay

- **Admin request:** Owner/Admin of the agency for that client, identifying the subject by token or by an event ID whose row names the subject. Audited `deletion.requested`. Executed synchronously under the agency write lock and then the client lock. Statuses follow `deletion.transition` (received, verifying, accepted, in progress, completed or partially completed).
- **Self-erasure:** the token holder, through the public erasure route, with requester kind `data_subject`. This is an additive value in the 003 `RequesterKind` contract. The response is a generic `202`.
- **Effects in one transaction:** insert a subject tombstone (`match_type subject_token`, keyed over the token digest) and one replay tombstone per deleted event ID (`event_id`). Then delete the subject's events, consent records and subject row, and record target outcomes: `collected_events`, `consent_records` and `collection_subjects` done; `event_diagnostics` not applicable (aggregate counters with no subject). An optional objection flag marks the subject tombstone.
- **After deletion:** the old token is unknown, so its events are rejected. Re-delivered event IDs match replay tombstones from any source. New collection requires a new consent action, which creates a new unlinked subject. This satisfies D-025: consent recorded after deletion, and no linkage. An objection blocks reuse of the old subject outright.
- **Journal:** tombstones and requests are append-only for the runtime, so specification 019 can backfill the independent journal. 004 creates no journal outbox (packet D11).

## 11. Proposed schema (migration `0007_event_collection`)

All new tables carry `agency_id` and `client_id` with a composite foreign key to `client_workspaces (agency_id, id)`. Times are `timestamptz`, and server times come from the database clock.

| Table | Key columns and constraints | Indexes |
|---|---|---|
| `ingestion_sources` | id; kind `browser`/`webhook`; name; status `active`/`disabled`; `public_key` (browser, unique, `pk_` plus 32 random bytes, non-secret); `allowed_origins` text[] (1-10 exact origins, browser only); `notice_sha256` (browser); creator membership (composite FK). Checks tie columns to kind. | unique `public_key`; (agency, client) |
| `ingestion_source_secrets` | source FK; version; sealed AES-GCM fields from `token_secrets` (kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext); `retires_at`. Every version stays live until its own `retires_at`. The number of live versions is bounded by the rotations within one 24-hour overlap. | (source, version) unique |
| `collection_forms` | client; `form_key` (`[a-z0-9_-]{1,100}`); version; `fields` jsonb (at most 32 descriptors: name, input type, autocomplete, label, class, options); status. | unique (client, form_key) |
| `collection_subjects` | id; `token_digest` (unique, 64 hex); created_at; `last_activity_at`. | unique digest; (client, last_activity_at) |
| `consent_records` | id; subject FK (same client); purpose, state, source, profile, policy_version, notice digest (checks mirror `ConsentRecord`); `received_at` default now(); `captured_at`; `expires_at`; `supersedes_id`. | (subject, purpose, received_at desc, id) |
| `collected_events` | id; `event_id` uuid; event_type; subject FK; channel `browser`/`server`/`webhook`; `source_id` or `credential_id` (exactly one; composite FKs); trust_rank; occurred_at; first/last_received_at; revision; payload jsonb; fingerprint; consent_basis uuid[]; traffic_label `unclassified`/`bot_suspected`/`internal`; policy_version; conflict_count; last_conflict_at; `expires_at`. | unique (client, event_id); (client, first_received_at, id); (subject); (expires_at) |
| `event_diagnostics` | (client, day, channel, outcome, reason) primary key; count bigint. Closed outcome and reason codes. | primary key |
| `deletion_requests` | id; requester kind; requesting user (nullable, member FK); status (003 values); objected; received/completed times; `target_outcomes` jsonb (target to 003 `TargetStatus`). | (client, received_at, id) |
| `deletion_tombstones` | id; scope_kind `subject`; match_type `subject_token`/`event_id`; `match_key` bytea(32); `match_key_id`; request FK; `effective_at`; objected. | (client, match_type, match_key) |

Changes to existing tables: `service_credentials.kind` (`read`/`ingest`, not null, default `read`, so existing keys stay read-only), and extended `audit_events` action and resource checks (`source.created`, `source.updated`, `source.secret_rotated`, `form.updated`, `deletion.requested`; resources `source`, `form`, `deletion_request`). The downgrade refuses populated 004 state, following 0006.

Privileges (no schema privileges for either role):

| Role | Grants |
|---|---|
| `tracking_app` | Sources/forms: SELECT, INSERT, column-limited UPDATE. Source secrets: SELECT, INSERT, UPDATE (`retires_at`). Subjects: SELECT, INSERT, UPDATE (`last_activity_at`), DELETE. Consent records: SELECT, INSERT, DELETE (erasure only; no UPDATE). Events: SELECT, INSERT, column-limited UPDATE, DELETE. Diagnostics: SELECT, INSERT, UPDATE (`count`). Deletion requests: SELECT, INSERT, UPDATE (status, completion, outcomes). Tombstones: SELECT, INSERT only. |
| `tracking_lifecycle` | SELECT, DELETE on events, diagnostics, subjects, consent records and source secrets. No access to tombstones, deletion requests, sources or forms. |

Every new column is registered in `data_policy.py`. Proposed new classes: `collection.subject`, `consent.record`, `event.content`, `event.delivery_state`, `event.diagnostic_count`, `deletion.request`, `deletion.tombstone` and `credential.sealed_secret`. Their end-of-life rules cite the approving decision.

## 12. Retention and lifecycle (values in packet D7)

| Data | Proposed end of life | Executor |
|---|---|---|
| Event rows (payload and receipt) | 13 months after `first_received_at` | lifecycle runner |
| Diagnostic counters | 30 days after their day | lifecycle runner |
| Subjects and their consent records | 13 months after `last_activity_at` (never before their events expire), or on erasure | lifecycle runner; erasure |
| Consent grant validity | 12 months after receipt, then evaluated as expired | evaluation |
| Previous webhook secret | 24 hours after rotation | verification ignores it; lifecycle deletes it |
| Tombstones and deletion requests | Workspace lifetime (D-025 for subject tombstones; proposed for replay tombstones and requests) | 017 offboarding |
| Sources and forms | Until client offboarding | 017 |

Why expired rows need no receipt: an honest retry repeats the original `occurred_at`, and the lateness bound (7 days) is far shorter than row retention (13 months). A retry after expiry is therefore rejected as late before identity is checked. A sender that invents a new time or ID creates a new claim, which no receipt could prevent. Lifecycle serialization (corrected after review finding R004-02): expiry of events, consent records and subjects runs one client at a time. A transaction first takes that client's privacy lock (waiting at most 100 ms), then re-evaluates eligibility and deletes bounded batches of all three. A subject is deleted only after all its consent records. An admission, consent change or erasure in flight therefore either commits first and is observed, or waits until the batch commits. A busy client is skipped and finished by the next run. Admission also locks the subject row it uses. Because each batch commits and releases the lock, the deletion order must also keep consent semantics at every committed boundary (review finding R004-04). A consent record is eligible only when a newer record of the same subject and purpose exists, which leaves the effective record in place, or when no older one exists, which leaves the purpose unknown, a denial. Newer and older follow the evaluator's `(received_at, id)` order. So a withdrawal or denial is never removed while an older grant of that purpose remains. A client's batches continue until one deletes nothing, so an unbounded run also removes the effective records and the subject once their history is gone. The rare case of an expired conflicting row deleted between the insert and its read returns a retryable 503.

## 13. Key custody and rotation (packet D9)

| Material | Arrangement | Rotation |
|---|---|---|
| Webhook signing secrets | Sealed with `token_secrets` under the D-025 local token keyring (`TRACKING_TOKEN_KEYRING`, `TRACKING_TOKEN_KEYRING_ACTIVE`) in ignored `.env`, with AAD bound to agency, client, source and version. `SecretContext.kind` gains `webhook_signing` (additive contract change). | Per-source secret rotation with a 24-hour overlap; KEK rotation by `rewrap`. |
| Tombstone keys | Independent keyring `TRACKING_TOMBSTONE_KEYRING` (ID to at least 32 hex bytes) and its active ID; must differ from every other key. Each tombstone stores its key ID. | Add-only: new tombstones use the active key; lookups compute keys under every retained ID. A key cannot be retired without the original values, so retained keys live as long as their tombstones. |
| Subject tokens, ingest keys | SHA-256 digests of high-entropy random tokens. | Re-issue. |
| Public source keys | Non-secret identifiers. | Replace by creating a new source. |

Development only, as D-025 requires: production configuration is already refused, and managed custody follows 020. Per-client keys for crypto-shredding remain with 017 (D5).

## 14. Limits, outcomes, diagnostics and traffic labels

- Limits (packet D6): 16 KiB body, one event, 32 form fields, 2,048 characters per string and URL, +5 minutes future skew, 7 days lateness, 5-minute webhook window. Rate limits use the existing keyed `auth_rate_limits` buckets: 60/min per browser source and peer address, 600/min per ingest key, and 600/min per webhook source. Each returns `429` with `Retry-After`. The peer address is the direct connection; forwarded headers are ignored. A reverse proxy needs its own configuration in 020.
- Public outcomes: the generic 202 for every admitted, duplicate, conflicting, suppressed or rejected event; 404 unknown or inactive key; 403 Origin; 413; 415 media type; 422 schema; 429. Responses are readable only by a registered origin that the route accepted (section 6).
- Trusted outcomes: 201 accepted, 200 duplicate or upgraded, 409 conflict, 401/403 credential or scope, 413, 422 (including consent suppression with a closed reason code, to trusted callers only), 429, 503 retryable. Clients retry 429, 503 and network ambiguity with the same event ID and bounded backoff. A pre-commit failure creates nothing.
- No quarantine or dead-letter store: invalid, denied and suppressed inputs are discarded and counted by reason only, and nothing is queued.
- Diagnostics: daily counters by channel, outcome (`accepted`, `duplicate`, `conflict`, `upgraded`, `rejected`, `suppressed`) and closed reason codes. No subject, event ID, payload or fingerprint.
- Traffic labels: code-versioned user-agent heuristics (`bots-v1`) on public events, plus the trusted `internal` flag. Labeled events are stored with their label for reports to exclude. A rule version change never rewrites earlier rows. Unknown traffic stays `unclassified`; no client network rules in 004.

## 15. Verification plan

Tests assert database rows and their absence, not helper calls. They use synthetic fixtures, the project `.venv` and fresh disposable PostgreSQL `tracking_foundation_test` on port 55433.

- **Isolation:** two agencies with two clients each; a forged agency or client path; a read key writing; an ingest key reading; revoked or expired keys; a disabled creator membership; an archived client; a disabled source; diagnostics and event lookup across clients.
- **Deduplication:** concurrent identical retries (one row); browser then server upgrade; server then browser (no overwrite); the same ID in two clients; changed content (conflict counter, unchanged payload); a type or subject mismatch.
- **Validation:** bad or old webhook signature; signature verified before parsing; 16 KiB bound; future or late times; unknown fields; a public `internal` flag; batches rejected; 429 with Retry-After; no side effects on rejection.
- **Privacy (C1, M5, E2):** unknown, denied, withdrawn and expired consent store nothing; click IDs dropped without attribution; password, `cc-*`, one-time-code, unmapped and free-text fields and a Luhn-valid code value absent from the database and logs; email or card in a URL path rejected.
- **Deletion and replay (D2):** admin and self-erasure remove every 004 store; replays via browser, server and webhook rejected; a new consent creates an unlinked subject; objection; target outcomes.
- **Concurrency:** ingestion blocked behind a held client lock while withdrawal or deletion commits, then suppressed; lock timeout returns 503; lifecycle expiry against an in-flight admission in both orders, with shortened and default retention (R004-02); bounded runs with withdrawn or denied latest consent over histories spanning batches (batch sizes 1 and 500), requests between committed batches, multiple purposes and receipt-time ties (R004-04).
- **Browser access:** a registered origin reads the consent token and sends text/plain and preflighted JSON requests in a real Chromium browser; an unregistered origin is blocked (R004-01).
- **Lifecycle:** row expiry, then a late retry rejected; counter, subject and secret expiry; lifecycle grants cannot touch tombstones.
- **Schema:** migration up and down on empty and populated state (refused); grant matrix; data-policy registry; OpenAPI snapshot.

Baseline before 004 changes: `bab3a33`, 380 passed in 72.11 s on 2026-11-10 (Compose project `tracking-spec004-test-20261110`, synthetic credentials, no `.env`). Implementation results are in the [evidence](evidence.md).

## 16. Rollout and recovery

A source exists only once fully configured (origins and notice digest, or a sealed secret), and existing keys stay `read`. Disabling a source or revoking a key stops intake without deleting data. The migration is additive and tested only on disposable storage. Rolling back populated state means disabling intake and keeping the schema, never dropping tables with data. Native migration, real customer intake and production deployment each need their own approval (Q-004 and Q-012 stay open). The independent restore journal and its custody remain with 019/020.
