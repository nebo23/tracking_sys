# Combined identity and revenue design addendum

Status: proposed, 2026-11-23, baseline `81977a3`. Decisions: [J1-J12](joint-entry-review.md). This addendum takes precedence over conflicting implementation details in the historical [006 revision 4](design.md) and [007 entry review](../007-revenue-ledger/entry-review.md) only if the owner approves it. Unchanged identity semantics and API shapes remain in revision 4. No implementation or test result is claimed here.

## 1. Boundaries

`revenue_evidence` remains the append-only source of financial truth. Identity evidence is a separate, erasable store. A financial transaction's key is `(agency_id, client_id, source_account_id, operation_id)`; it is never a merge root or an email. An identity association is evidence about that transaction, never proof of its amount or payment status.

Existing 015 intake, stored rows, verified/manual separation, D-070 order checks and 016-A effective-date reporting survive this work. No customer field is added to Paymob payload storage. Bookings and won CRM stages remain non-financial signals. WhatsApp referral rows remain anonymous: there is no retained sender identifier from which to reconstruct a person.

`identity_link` is required for identity association. Sale-to-person association and attribution handoffs additionally require `attribution` on their collection subject. Withdrawal of either permission detaches the financial association. Money stays in the client ledger. A booking's existing attribution grant does not by itself establish identity.

## 2. Deferred 006 design corrections

These are proposed resolutions, not completed bug fixes. Each requires the matching real database or browser case in the joint matrix.

| Finding | Required design amendment |
|---|---|
| R006-23 scoped event FK | Add a unique key on `collected_events(agency_id, client_id, id)` before adding the erasure-hold FK to those exact columns. Keep the non-cascading FK and settle every hold before an event delete. The global `id` primary key alone is not the named composite target. |
| R006-24 trusted event upgrade | Add a write-once nullable `collected_events.identity_excluded_at`. Set it in the same transaction whenever an unresolved event enters an erasure hold or is retained anonymously. An upgrade may replace allowed payload/provenance but cannot clear this field, change `first_received_at`, or recover identity through a new subject/time. Every identity and attribution adapter excludes marked events, even after the hold rows expire. Ordinary event retention still removes them. |
| R006-25 independent merge evidence | Decide whether a participant survives after filtering out every key/link whose `merge_id` is the edge under examination. An assertion counts only through its surviving, independently owned keys or links, not a candidate reference or a merge-dependent anchor. Expire/delete a participant with no independent evidence, close the edge first, and re-evaluate dependent items without treating loss as evidence for the survivor. A financial association never supplies independent identity evidence. |
| R006-26 expired receipts | Under the client lock and one database clock, use a live receipt for retry detection. If expired, validate new proof/consent first, then replace its fingerprint and window atomically when the request is accepted, including a suppressed application. Do not insert against the existing unique key, extend an unexpired window, or delete an expired row on failed proof. Concurrent retries observe either the old accepted state or the new accepted state. A receipt remains usable for its exact retry window even if its handoff was removed early; normal handoff expiry and early removal have separate test cases. |
| R006-27 retrospective interval | Split revision 4's broad unassigned category into `provisionally_linkable` and `permanently_unassigned`. The former is only the uninterrupted current identity-grant interval before the first assertion, on a never-shared subject with no closure/floor barrier. The first valid assertion may adopt it. Consent gaps, neutral/ambiguous segments, shared-device pre-identification time and closed/erased intervals are permanent. A switch retracts only the provisional prefix and never transfers it to the next person. The event exclusion marker has priority over either interval. |
| R006-28 rebuild publication | Capture `(generation, checkpoint)` before rebuild. Publish the staged generation and snapshot watermark only through a compare-and-swap on both captured values, not generation alone. A concurrent replay that advances the checkpoint makes publication fail. All staged rows remain invisible until the atomic switch. Failed staging is discarded without changing current rows. |

For any consumer retaining person-derived data, a successful compare-and-swap is necessary but insufficient for release. An erasure or consent change after the source snapshot makes the published snapshot stale. Compare the consumer checkpoint with the current source watermark and recheck current scope, consent and tombstones before returning person data. While catching up or rebuilding, return an explicit unavailable/stale result, never the older person association. Deletion cannot report the financial-association target complete until its links are detached.

## 3. Schema inventory

Use additive revisions `0026_identity_journey`, `0027_ledger_persistence` and `0028_revenue_identity`, chained from `0025_whatsapp`. Confirm these numbers are still free before implementation; if main moves, rebase and update the documented numbering without modifying earlier migrations. Tests use disposable PostgreSQL, never native `tracking_sys`.

### Identity, migration 0026

Retain the eleven tables from revision 4 section 12.1: `identity_key_secrets`, `identity_subjects`, `identity_keys`, `identity_assertions`, `identity_assertion_receipts`, `identity_links`, `identity_handoffs`, `identity_merges`, `identity_changes`, `identity_feed_state` and `identity_erasure_holds`. Retain their scoped FKs, unique keys, interval checks and merge dependency indexes. Arrays/JSON containing scoped references require explicit same-client validation; they do not substitute for FKs.

Existing-table changes:

- `collection_subjects`: immutable `issuance_channel`, monotonic `identity_floor_at`, write-once `identity_shared_at`; old rows receive `unknown`.
- `collected_events`: the scoped unique key and write-once exclusion timestamp from R006-23/24.
- `client_grants` and `invitation_client_grants`: `can_view_identities`, default false, preserved when an older caller omits it. Do not add identity access to service read grants.
- Extend the closed audit, diagnostic and tombstone kinds and deletion targets listed in revision 4. Validate current column widths and constraints rather than copying old migration SQL.
- Restricted `tracking_lifecycle` permissions for expiry, hold settlement, edge closure and change emission. No runtime/lifecycle access to unwrapped matching secrets through an API, and no lifecycle deletion of workspace matching keys or replay tombstones.

### Financial persistence, migration 0027

Every new table includes agency/client scope and a matching client FK. UUID references use scoped composite FKs backed by matching uniqueness. JSON materializations have a versioned, closed shape containing only existing non-contact ledger fields.

| Table | Stored fields and key | Mutation and purpose |
|---|---|---|
| `ledger_projection_state` | One row per client: current generation, algorithm version, last processed evidence sequence, per-client receipt ordinal, last movement sequence, receipt digest, financial revision and status (`building`, `ready`, `failed`). | Updated under the revenue lock, atomically with projection rows. The global evidence sequence is a cursor, not a contiguous per-client ordinal. |
| `ledger_receipts` | Unique `(client_id, generation, receipt_ordinal)` and `(client_id, generation, evidence_id)`; scoped evidence FK; input digest, preceding digest, receipt digest, outcome and closing transaction states. | Append-only within a generation. Every stored evidence row, including held, conflicting or unverified evidence, receives a position; exact duplicate deliveries insert neither evidence nor a receipt. |
| `ledger_movements` | Unique `(client_id, generation, movement_sequence)`; receipt FK; transaction key, operation key, kind, post/release direction, signed minor units, currency/exponent, effective time, trigger evidence ID and closed reason. | Append-only within a generation. No person, contact value or identity key. Releases preserve the original operation/effective-time provenance. |
| `ledger_transactions` | Unique `(client_id, generation, source_account_id, operation_id)`; current financial revision; current posting/adjustment state, exact currency totals and evidence references. | A replaceable current projection, updated with receipts/movements. Current effective-date reports read this state, not a sum of historically superseded posting rows. |
| `ledger_reconciliation_actions` | Unique `(client_id, operation_id)` for request idempotency; issue fingerprint/version, evidence references, action (`acknowledge`, `reopen`), actor, closed reason and time. | Append-only audit. Does not remove an issue from unresolved financial counts or change evidence classification/amounts. Original evidence remains visible. |

Add scoped uniqueness on `revenue_evidence(agency_id, client_id, id)` for receipt and action references. Preserve its existing immutability, uniqueness and intake provenance. Do not add a person column there.

### Financial association, migration 0028

`revenue_identity_bindings` is the sixth new table outside identity. It holds association revisions keyed by `(client_id, association_id, revision)` and idempotent request IDs. Each revision names a source-account/sale-operation key, originating credential, verified identity assertion, collection subject, original identity owner/key evidence, server receipt time, state and expected prior revision. It stores no raw identifier, subject token, browser handoff or merge-root ownership. All identity/evidence references must resolve within the same client.

Association correction appends a revision and closes the previous one. An active merge is resolved only when reading the original owner; unmerge recomputes ownership from the original evidence. A conflicting assertion never transfers a sale automatically. An Owner/Admin may detach a mistaken association; replacement still needs qualifying trusted evidence.

F1 applies to the complete association history: withdrawal/erasure/expiry deletes or clears every identifying pointer and keyed proof that would recover the person, including closed revisions and retry material. Keep only a non-identifying financial audit of detachment; do not copy identity assertion IDs into immutable financial journal rows. A replay with consumed, erased or withdrawn proof cannot restore a binding. Any permitted new association needs a new request, new proof and current consent. The original financial evidence and amounts remain unchanged.

Downgrades refuse populated new business stores or non-default existing fields; financial data must never be silently dropped. Backfill/rollout tooling is operator-controlled and idempotent. No native rollout is authorized by J7.

## 4. Posting, replay and recovery

1. Existing intake authenticates and validates under its existing trust protocol. New evidence is written to the existing receipt table with the established client revenue lock. Keep `received_at` stable; the ordering key is `(received_at, sequence)` and must not go backwards. Detect a backwards clock before accepting a new receipt, rather than rewriting earlier timestamps or reordering published positions.
2. A ready projection applies each new stored row under the same revenue lock. Calculate its eligible current financial state with the approved 007-A and D-070 rules. Compare that current state to the previously persisted state, append the necessary signed releases/posts, and persist a closing-state receipt even when there is no monetary change.
3. All evidence, receipts, movements, current state and cursors commit together. If publication fails, nothing advances. For bounded multi-row CSV commits, preserve input receipt order and transaction atomicity; do not expose an intermediate prefix as a complete import.
4. A mismatched-parent refund always occupies its raw receipt position, even while held. If later evidence proves a matching signed order, its effect starts at that later receipt. Conversely, later evidence that makes a prior provisional effect ineligible produces a release then. No earlier receipt digest or movement is replaced. The adapter's journal version is explicit; the historical filtered `ledger_feed(records)` position is not a durable cursor.
5. For inputs without provider-specific holds, the materialized movements, closing states and transport adapter must match the established 007-A/008-A reference output. For hold transitions, use explicit new persisted-receipt fixtures and retain all D-070 financial exclusions. Never weaken the existing in-memory engine's journal-mismatch checks to accept renumbered history.
6. Backfill uses the original evidence order and reconstructs state as known after each receipt, not a final held-filter applied to every earlier prefix. Build a staging generation, catch up under the revenue lock, and atomically publish it only if the captured state/cursor still match. Readers fail closed with a retryable `ledger_projection_unavailable` result while no current generation is ready. An existing ready generation must not be served as current if receipts have advanced beyond it.
7. An interrupted rebuild does not expose staging rows. A calculation-rule change needs a new explicit algorithm/generation and consumer reset; it cannot reinterpret an existing receipt position silently. Administrative rebuilding/retirement is not a runtime permission to update immutable financial journal rows.

The pure calculation remains the reference, not an unmeasured performance promise. Read requests must not rebuild every historical receipt prefix. Initial writes/backfill may still need bounded recomputation; measure and retain the A3 limitation explicitly. Keep the current 016-A 200-evidence cap until a separately reviewed limit amendment. Large clients and imports retain their existing intake behavior; they may remain unavailable to the bounded report API.

## 5. Association and authorization

Proposed additional API operations, all below `/agencies/{a}/clients/{c}`:

| Operation | Policy |
|---|---|
| `GET /revenue/movements` | `finance:read`; revision/generation-bound keyset pagination; include receipt provenance, omit person data. |
| `GET /revenue/reconciliation` | `finance:read`; unresolved state and review action shown separately; no claim that acknowledgement resolved the amount discrepancy. |
| `POST /revenue/reconciliation/{issue_id}/actions` | Owner/Admin; expected financial revision, idempotent operation ID, closed action/reason; stale state is 409. |
| `POST /revenue/identity-associations` | Existing client-granted ingest credential; same live credential must own the submitted 006 assertion. Body names source account, sale operation, assertion ID, request ID and expected association revision. Proof of sale matching is a trusted backend claim; it does not independently verify identity. Generic acknowledgement reveals no person or payment-match history. |
| `POST /revenue/identity-associations/{id}/detach` | Owner/Admin; audited, idempotent, expected revision. No arbitrary reassignment to a profile. |
| `GET /identity/subjects/{id}/revenue` | Both `identity:read` and `finance:read`; current consent, ownership and financial generation checked before release. No read-key access. |

Revision 4's eleven identity operations remain proposed. New permission fields are additive and legacy grant updates preserve omitted flags. Financial-derived customer status is itself a financial disclosure: without finance access return an explicit permission-unavailable customer qualification, while non-financial lead information remains available. No person amount or sale-existence flag may leak through a lead list, count, profile, error or export.

A trusted sale-association assertion links only when the matching sale is verified, the originating assertion still has an unambiguous eligible segment, and both current permissions are granted. Match all four parts of the transaction key. `operation_id` alone is insufficient across payment sources. An absent sale stays pending without a customer stage; a later verified sale may resolve it only after proof and consent are rechecked. Conflicting ownership requires review. Do not infer a link from a payment reference in browser data, shared campaign tags, booking contact fields or a CRM amount.

For combined operations, extend the existing lock conventions with this order: authentication/administrative agency locks first when needed, then client privacy lock, then client revenue lock, then deterministically ordered rows. No code holding the revenue lock may acquire the privacy/agency lock. Pure financial callbacks keep their current lock path; recheck association on a later authorized read instead of acquiring privacy locks inside a financial callback. No new job queue is proposed. Audit actual integration, lifecycle and delivery paths for this order before enabling them. Grant lifecycle only the additional association detachment and history cleanup privileges needed by J6, with tests proving that it cannot modify financial amounts or receipt history.

## 6. Consumer handoff and meaning of completion

007-C provides a snapshot of current, authorized transaction state plus its original identity owner, journey revision, ledger generation and receipt watermark. It supplies actual persisted synthetic journeys to the existing 008 in-memory engine and exercises model recalculation after late events, refunds, merge/unmerge and erasure. An old attribution result is discarded/rebuilt when identity ownership changes; do not mutate the immutable identity of an existing 008 conversion in place.

Test the R006-28 consumer protocol with persisted reference-consumer state and two workers. The operational v1 sale/person read can resolve current bindings directly and need not persist another consumer cache. Any introduced production projection must use the same checkpoint/generation checks and deletion release barrier.

The result can close 007-C's implemented identity/financial handoff and its consumer-contract tests. It cannot claim production end-to-end attribution, persisted 008 runs, full 006 AC4 attribution operation, 016-B reports, 016-C retained exports or production privacy compliance. Record those remaining consumer obligations explicitly, with evidence links rather than checking them off prematurely.
