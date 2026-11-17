# Specification 004: ingestion design for review

Prepared: 2026-11-10. Status: proposed, not implemented or approved. Authority: owner request to prepare specification 004. Read [spec](spec.md), [decision packet](decision-packet.md), [entry review](entry-review.md), and [predecessor evidence](../../docs/planning/spec-004-readiness.md). Proposed names and numeric limits below require a recorded owner decision before schema or application changes.

## 1. Baseline and boundaries

The baseline is the corrected specification 003 branch, pending PR 2 merge. FastAPI, PostgreSQL, SQLAlchemy and Alembic already exist. Current service credentials authorize `client:read`/`finance:read`; they do not implicitly authorize ingestion. The proposal adds an explicit write permission, not a reinterpretation of read access.

Both social analytics and attribution remain launch capabilities. This slice builds their shared ingestion foundation, not attribution models, revenue truth, connectors, browser SDKs, or React. No new broker, paid service or dependency is proposed. Initial processing is synchronous and transactional; receiving a request does not imply accepting or persisting it.

## 2. Requirement traceability

| Source | 004 deliverable | Boundary |
|---|---|---|
| PDF-001/002/005 | Public and authenticated event APIs with one envelope | Actual pixel/SDK delivery belongs to 005; native SDKs remain 021. |
| PDF-004/008 | Registered event schemas and mapped form fields only | No automatic arbitrary DOM capture or pre-submit keystrokes. |
| PDF-006/007 | Minimized URLs, allowlisted campaign/click fields | Consent and field retention apply; no indefinite raw URL history. |
| PDF-009 | Authenticated generic webhook with raw-body signature and replay rules | Provider-specific adapters need named provider contracts in their specs. |
| PDF-013 | Scoped backend diagnostics with closed reason codes | No frontend debugger in 004. |
| PDF-014 | Atomic scoped deduplication/conflict policy | Never global uniqueness of event ID alone. |
| PDF-082/084 | Versioned, auditable bot/internal rules and exclusion counters | Heuristic labels, not a claim of complete bot detection. |

## 3. EventEnvelope v1

Proposed input, with unknown fields rejected:

| Field | Rule |
|---|---|
| `schema_version` | Literal `1`; unknown versions rejected, no silent coercion. |
| `event_id` | UUID generated once and reused for retries and browser/server copies. |
| `event_type` | Registered code: proposed initial `page_view`, `link_click`, `form_submit`, `lead_signal`, `purchase_signal`; custom codes need a registered bounded schema. |
| `occurred_at` | UTC-aware event time within the approved skew/lateness window; never consent/deletion ordering evidence. |
| `subject_token` | Optional opaque client-bound subject token; required when the schema needs subject consent or identity. No raw email/phone in routing fields. |
| `consent_receipt` | Reference to a server record bound to the same client and subject; a copied receipt from another subject/client is rejected. |
| `payload` | Event-specific approved fields. Form descriptors/mapping come from stored client configuration, not arbitrary descriptors supplied by the sender. |

Server output/storage adds agency/client resolved from credentials, `received_at` from the database clock, source trust class, schema/policy/rule versions, safe payload, revision and outcome. The sender cannot set those fields. Public routes reject attempts to set trusted source or overwrite tenancy. Purchase signals remain unverified claims; only specification 007 can recognize financial evidence.

Proposed payload examples: page path plus minimized campaign parameters for `page_view`; registered link reference for `link_click`; registered form ID and mapped permitted values for `form_submit`; explicit lead action code for `lead_signal`; external reference and currency/amount claim for `purchase_signal`. Every monetary field remains subject to financial diagnostics authorization. Final per-field classes/purposes are part of schema review; no unrestricted JSON catch-all.

## 4. Routes and trust

Proposed routes; none exists yet:

| Route | Authorization and behavior |
|---|---|
| `POST /collect/v1/{public_key}` | Limited-trust public intake; key selects one enabled client/source and allowed origins. No cookie authentication. Origin checks reduce browser misuse but are not authentication. Never expose stored event content or existence through responses. |
| `POST /clients/{client_id}/events` | Live service credential with explicit `events:write`, matching agency and client grant; inactive issuer, membership, workspace or credential denies access. |
| `POST /webhooks/v1/{source_id}` | Source-specific secret, versioned timestamp plus exact raw-body HMAC, constant-time comparison, bounded replay window; source determines client and event schema. |
| `POST /collect/v1/{public_key}/consent` | Explicit consent action for a server-issued opaque subject token, client/subject bound; records only approved source/purpose/state values. An arbitrary event cannot grant consent. |
| `GET /clients/{client_id}/event-diagnostics` | Live scoped read authorization, bounded cursor pagination and redacted metadata only; financial metadata additionally requires financial access. |
| `POST /clients/{client_id}/deletion-requests` | Verified Owner/Admin request restricted to that client; identity verification and scope resolution precede execution. No public arbitrary-subject deletion. |

Consent receipt and subject token design must include issuance, digest-only storage, expiry, revocation, purpose separation, and rejection of cross-subject substitution. They convey a recorded assertion, not proof of a human or legal compliance. Public clients may make false claims about themselves; they must not obtain authority over another subject. A raw `consent=true` flag, Origin, or public key is insufficient to authorize processing.

Webhook trust means possession of that configured source secret, not verified revenue. Signature verification precedes JSON parsing and any record creation. Never log signed bodies, signatures, tokens or URL path keys; reuse the existing log allowlist. No provider-specific signature standard is assumed.

## 5. Privacy and admission transaction

Use `app.privacy.consent.current_state` and `require_all` for all purposes selected by the server-side event schema. Query records by exact agency/client/subject, use database receipt time, and reject missing, denied, withdrawn or expired purposes under J1. The client cannot choose `necessary` to reclassify telemetry.

Use `sanitize_submission` for mapped fields and `minimize_url` for URLs, then validate the resulting payload against the event schema. If minimization removes an event-required field, reject that event; optional unsafe fields are dropped and counted by reason only. Do not save a raw copy in conflicts, diagnostics, quarantine or dead letters. Do not compute persistent raw-content fingerprints before minimization; sensitive inputs must not leave retained side channels.

Match `subject_key` and `tombstone_key` using independent approved key material and key IDs. Load the relevant subject AND replay tombstones and call `app.privacy.deletion.admission`. Preserve D-025: known replay keys always deny; objection always denies; otherwise new collection requires consent received after deletion. A new event ID cannot override a subject objection. No cross-client identity matching is introduced.

Proposed concurrency strategy for the initial low-load slice: all ingestion, consent change, and deletion operations for a client acquire the same transaction-scoped advisory lock before loading privacy state. Then re-read live scope and privacy state, check the event receipt and persist atomically. The lock is derived deterministically from the client ID; collisions may serialize unrelated clients but cannot authorize them. Document order relative to existing user/session/agency locks and test it before implementation. Bounded lock/statement timeouts return retryable sanitized errors. More granular locking needs evidence and a separate design revision, not an early optimization.

This prevents deletion/withdrawal from committing between the privacy check and event insertion. A writer that acquired the lock first may commit before withdrawal; subsequent intake observes the new state. A deletion request installs replay/subject tombstones and removes covered payloads atomically under that lock. All retries re-evaluate privacy before deduplication, so an old accepted receipt cannot authorize a prohibited replay.

## 6. Scoped deduplication and conflict policy

Unique identity is `(client_id, event_id_key)`, where the event ID key is a purpose-separated HMAC. A composite agency/client foreign key prevents mismatched ownership. Canonical safe-payload fingerprints include schema version, event type, occurred time, approved subject reference and sanitized payload, but exclude transport arrival time/signature. Specify canonical JSON rules and key rotation before implementation.

Proposed outcomes:

1. New identity: create one receipt and one event payload in the same transaction.
2. Same safe fingerprint: `duplicate`; do not create another event or refresh the original receipt time or payload expiry.
3. Different safe fingerprint, same/lower trust: `conflict`; retain the accepted event and record only a bounded reason/fingerprint in conflict metadata.
4. Higher-trust server copy after public copy: allow `upgraded` only when event type, subject and approved identity fields agree. Replace the single canonical safe payload, increment its revision and retain first_received_at. Re-evaluate consent/minimization first. Disagreeing identity fields remain conflicts, not automatic overrides.
5. No rule lets public input overwrite trusted data. Two equally trusted disagreeing sources conflict; arrival order alone does not select financial truth.

Lifetime digest-only receipts are proposed to prevent recounting when raw payload retention expires. A receipt with no payload returns duplicate/conflict but never reconstructs the expired payload. Subject deletion removes payloads and installs replay tombstones; no fingerprint or subject link survives merely because it was called metadata unless its retention has been approved. Receipt/tombstone key custody and rotation must preserve replay lookup across retained key IDs. The metadata retention choice is explicitly pending in the decision packet.

## 7. Proposed schema inventory

All tables are proposals for one reviewed additive migration after 0006. No migration is created during preparation.

| Table | Purpose and key constraints |
|---|---|
| `ingestion_sources` | Client-bound public/server/webhook configuration, status, origin rules, schema version, creator and key references; raw secrets excluded. |
| `event_schemas` | Versioned event allowlists, required purposes, field classes, form mappings and limits; controlled writes by client managers. |
| `collection_subjects` | Opaque token digest, agency/client, keyed subject reference and key ID; no identity graph or global email mapping. |
| `consent_records` | Append-only persistence matching 003 `ConsentRecord`; subject/client/purpose receipt-order index; current state resolved server-side. |
| `event_receipts` | Unique scoped event HMAC, safe fingerprint, trust, first/last receipt metadata, canonical revision and payload status. |
| `collected_events` | One canonical sanitized payload per receipt, occurred/received times, subject reference, policy version and expiry. |
| `event_diagnostics` | Bounded safe outcome/reason metadata and rule version; no raw payload, signed request, URL key or identifier. |
| `deletion_requests` / `deletion_targets` | 003 request transitions and per-store outcomes; failed/unsupported is not completed. |
| `deletion_tombstones` | 003 keyed subject/replay matches, key IDs, effective_at and objection; workspace lifetime per D-025. |

Use existing tenancy IDs and audit conventions. Review composite keys/FKs, uniqueness, pagination indexes, runtime privileges and lifecycle deletion privileges explicitly. Register every new column/table in `data_policy.py` with approved end-of-life rules. Do not reuse the credential-state lifecycle role's privileges without reviewing the additional tables. No key-management technology or new encryption dependency is selected here; secrets and independent subject/tombstone key custody need the approved local development arrangement and later production custody.

## 8. Outcomes, retries and diagnostics

Trusted API proposal: 201 accepted; 200 duplicate/upgraded; 409 conflict; 400 malformed/signature/timestamp rejection; 401/403 credential/scope rejection; 413 oversized; 422 schema rejection; 429 with Retry-After; 503 transient database/lock failure. Public accepted, duplicate, conflict and privacy-suppressed submissions use one generic 202 response without revealing stored content/existence. Structural/abuse errors may still return bounded 4xx responses. Exact OpenAPI schemas are reviewed before implementation.

Clients retry 429/503 or network ambiguity with the same event ID and bounded backoff. Other 4xx errors require correction. No server job broker is proposed. Quarantine/dead-letter contracts contain safe reason metadata only; invalid or denied raw payloads are discarded, not queued. Test rollback after privacy admission and before final receipt commit. Diagnostics must distinguish acceptance, duplicate, conflict, suppression and retryable failure without leaking subjects.

Bot/internal rules are versioned client configuration applied before canonical storage: explicit internal-source flags from trusted senders, configured server-observed network rules where approved, and bounded heuristic user-agent rules. Do not trust arbitrary forwarded headers or retain IP/user-agent merely to explain a rule. Unknown remains unknown; do not label all automation as malicious. A rule change does not silently rewrite historical acceptance.

Late arrivals preserve both clocks and canonical revision; later report consumers use receipt identity and revision to avoid double counting. No report updates or outbound delivery are implemented in this slice.

## 9. Verification and rollout

Synthetic example for contract review (IDs and payload are illustrative; no request was sent):

```json
{
  "schema_version": 1,
  "event_id": "00000000-0000-4000-8000-000000000004",
  "event_type": "page_view",
  "occurred_at": "2030-01-01T12:00:00Z",
  "subject_token": "synthetic-subject-token",
  "consent_receipt": "00000000-0000-4000-8000-000000000005",
  "payload": {"url": "https://shop.example.test/offer?utm_source=demo"}
}
```

Set the test clock to 2030-01-01T12:00:01Z. Client A with a matching analytics grant admits the event; an identical retry remains one row. Client B using the same event ID creates its own row only with its own authorized source/subject/consent. Substituting A's receipt into B denies processing. A withdrawn analytics record suppresses a later retry even if the earlier receipt exists. Deleting A's subject installs subject and event replay tombstones; a fresh post-deletion consent cannot admit that old event ID, while a new event may be admitted only if there is no objection and the D-025 admission rules pass. None of these outcomes establishes a sale.

Implement the [entry acceptance matrix](entry-review.md#acceptance-matrix), plus deterministic concurrent ingestion/withdrawal/deletion, trust upgrades, expired-payload retries, key rotation and cross-client receipt substitution. Test actual database rows and absence of prohibited payloads, not only mocked helper calls. Use synthetic values, isolated `.venv`, fresh disposable PostgreSQL on port 55433, and full migration/role/registry/OpenAPI checks. No native migration or real provider call is implied.

Before rollout: owner approves schema/policies, tests pass, final diff excludes unrelated local work, publication is approved, and native/production rollout has its own backup/readiness/recovery plan. Downgrading a schema with customer data is not a rollback strategy. Specification 019/020 still owns independent journal storage, authoritative head custody, restore epochs and the operational restore drill.
