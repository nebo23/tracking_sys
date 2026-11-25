# Identity journey and persisted revenue ledger

Specifications 006 and 007-B/C, implemented under D-075 on `codex/spec-006-007-identity-ledger` (migrations `0026_identity_journey`, `0027_ledger_persistence` and `0028_revenue_identity`). Design: [joint addendum](../../specs/006-identity-journey/joint-design.md) over [design revision 4](../../specs/006-identity-journey/design.md). Evidence: [joint evidence](../../specs/006-identity-journey/joint-evidence.md). Every example below is synthetic.

## Identity (006)

### Sending identity evidence

The client's own backend, never the browser, asserts that a visitor proved control of an identifier. Two proof routes exist, decided by the collection subject's immutable issuance channel:

| Subject | Proof | Flow |
|---|---|---|
| Created by the public consent route (`browser`) | One-time browser handoff | The backend creates a challenge (at least 128 random bits, 22-128 base64url characters) for one verified form or login transaction. The page calls `tracker.identityHandoff(challenge)` and posts the returned `code` to its backend, which sends `{handoff, challenge}`. The code lasts 10 minutes and works once. |
| Created by the trusted consent API (`server`) | Direct token | The backend sends `{subject_token, identity_consent_receipt_id}`; the receipt is the current `identity_link` grant receipt from its consent response (receipts follow the sorted purpose order). |
| Created before 0026 (`unknown`) | None | Never linkable; a new explicit grant creates a new subject. |

`POST /agencies/{a}/clients/{c}/identity-assertions` with a client-granted ingest key:

```json
{
  "assertion_id": "00000000-0000-4000-8000-000000000401",
  "handoff": "ihc_...", "challenge": "...",
  "identifiers": [
    {"kind": "email", "value": "mona@example.test", "method": "email_code", "verified_at": "2026-11-02T09:05:09Z"}
  ]
}
```

Rules: 1-3 identifiers, one per kind; methods `email_code`, `email_link`, `account_verified_email` (email), `phone_code`, `account_verified_phone` (phone), `account_login` (`customer_ref`); `verified_at` at most 30 days old and 5 minutes ahead. Phones must be international ASCII (`+20 10 0000 0101` or `0020...`); national input is `phone_country_required`. `staff_verified` is refused until a client attestation setting exists. Answers: `201 accepted` for every well-formed, fresh and proven request (linked, ambiguous, contested or suppressed alike), `200 duplicate` or `409 conflict` inside the 24-hour retry window, `422 rejected` with `request_invalid`, `identifier_invalid`, `phone_country_required`, `method_invalid`, `verification_stale` or `proof_invalid`. Nothing in an answer reveals an owner, a contest, an erasure or an objection.

Raw values are used only to compute HMAC keys under a per-client matching key (sealed with the development token keyring) and are never stored or logged.

### Matching, segments and consent

Matching follows R1-R5 (`app.identity.matching`): keys join only when asserted together; the engine never merges existing persons; a `customer_ref` decides between owners; a phone never pulls a new email or account into an existing person; conflicts are ambiguous. A collection subject's segments (`app.identity.segments`) assign an event only when both its receipt time and its claimed time lie inside the same owner's segment; boundary instants are unassigned. The first assertion of an uninterrupted `identity_link` grant on a never-shared subject adopts the events received since that grant (the provisional prefix); a second owner, an ambiguous or a suppressed assertion marks the subject shared and retracts it.

Withdrawing or denying `identity_link` (W1) deletes the subject's segments, assertions and handoffs in the consent transaction and removes persons left without independent evidence, closing an active merge edge first. Expiry stops new links and keeps earlier assignments.

### Reading persons

| Route (below `/agencies/{a}/clients/{c}/identity`) | Who |
|---|---|
| `GET /subjects`, `GET /subjects/{id}`, `GET /subjects/{id}/timeline`, `GET /leads` | Owner/Admin; Analyst or ClientViewer with `can_view_identities` on the client grant (default false). No service key. |
| `GET /subjects/{id}/revenue` | Both `identity:read` and `finance:read`. |
| `GET /review`, `POST /merges`, `POST /merges/{id}/reversal`, `POST /erasures`, `POST /erasures/{request_id}/resolution` | Owner/Admin sessions. |

Grant writes keep an omitted `can_view_identities`; invitations carry it. Profiles show key kinds, normalizers and methods, never values or masks. Purchase claims and customer qualification appear only for readers who also hold `finance:read`; otherwise `customer_qualification` is `permission_unavailable`. While the published ledger cannot be read it is `ledger_unavailable` with the flag `customer_status_unavailable`, never `not_customer`; a subject list filtered by `stage` then answers the retryable `503 ledger_projection_unavailable`, and lead items carry the qualification next to the stage (D-076, R0607-09). Every read is rechecked against current scope before release, and a response built with finance access rechecks `finance:read` too (R0607-14).

Merges are disjoint pairs with expected versions and closed reason codes; an exact retry returns the recorded result. A reversal re-evaluates every key and link that recorded the merge and sends items anchored on both sides to review.

A subject records the shared marker when it gets a second original owner, a merge-dependent owner set included, or an ambiguous segment, a reversal's included, so erasure never treats another person's device as exclusive (R0607-02). Removing a person (W1, erasure or expiry) takes it out of every candidate and original-owner list; an ambiguous segment left without candidates becomes neutral, and a key that no surviving assertion presents is deleted, owned or contested, so a withdrawn identifier never links a later subject to the old person (R0607-01, R0607-07, R0607-19).

Person erasure resolves the target first (an active merge or a contested identifier pauses the request; with an objection, its identifier tombstones are written at once, and a paused request whose person another path removed completes on resolution, R0607-08), records the exact unresolved events of shared subjects as holds (marking them excluded from every journey for good), deletes confirmed events with tombstones, tombstones the person's keys and assertions, unlinks its sale associations, erases subjects exclusive to it whole and completes, or waits `on_hold` until an Owner/Admin decides `erase` or `retain` for exactly that held set.

### Change feed

Every transaction that changes a visible journey increments the person's `journey_revision` once and appends a contiguous per-client change record. Consumers use `app.services.identity_feed` inside one REPEATABLE READ transaction: `read_batch` and `verify` reject pruned or gapped batches, and publication must compare-and-swap both the consumer generation and its checkpoint. Before releasing person data, a consumer compares its checkpoint with `current_watermark` and answers stale while behind.

### Retention (development, D-075 J6)

The lifecycle runner (role `tracking_lifecycle`) handles identity data per client under the privacy lock: holds of expiring events settle as `expired` first; an expiring subject loses its identity evidence before it is deleted; links and assertions expire after 395 days, their sale associations unlinked first (F1, R0607-03), persons 395 days after their last evidence, contested keys 395 days after their last verification, handoffs 1 day after use or expiry, retry receipts at their window, change records after 30 days (advancing `pruned_through_seq`), settled holds 30 days after their request completed, and ended merge entries after 2 years.

## Persisted ledger (007-B)

`revenue_evidence` stays the source of truth. Each stored row receives an immutable receipt in the transaction that stores it, under the client revenue lock, with the D-070 hold rule evaluated at that receipt: a held refund keeps its position without a movement and takes effect at a later receipt that proves its order; no earlier receipt or movement changes. Receipt digests follow the `ledger_feed` chain, and for logs without held refunds the stored movements and journal equal `calculate()` and `ledger_feed()`.

Reads (`client_ledger`, the 015 revenue route, CRM deals, 016-A reports) check the published state against the latest stored sequence in one statement (`ledger_store.published_state`), then load the evidence once, derive the current view in one pass and use the stored movements, every query bounded by the published cursors, so a receipt committed meanwhile never fails or leaks into a read (R0607-12). They fail closed with `503 ledger_projection_unavailable` while no ready generation covers every stored row. A receipt time behind the client's last receipt is refused on every intake path with the retryable `503 receipt_clock_behind`, and nothing is stored (R0607-13).

A CSV commit projects its receipts inline only while rows x (stored history + rows) stays within 40,000 (`INLINE_RECEIPT_WORK`). A larger commit stores its evidence only and returns; `ledger_store.catch_up` then applies the receipts after the response, outside the agency lock, in batches of about half a second under the client revenue lock, within a 120-second budget (D-076, R0607-11). The intake routes (CSV commit, declaration, Paymob callback) schedule it whenever the projection is behind; a failure logs `ledger_catch_up_failed`, reads keep failing closed, and the next intake or the operator backfill continues.

| Route (below `/agencies/{a}/clients/{c}/revenue`) | Who |
|---|---|
| `GET /movements?after=&generation=&limit=` | `finance:read`; a changed generation answers `409 ledger_generation_changed`. |
| `GET /reconciliation` | `finance:read`: open reconciliation, pending and held items with stable issue IDs (anchored on each item's first evidence record, so conflicting deliveries of one operation are distinct, R0607-17) and their latest review. |
| `POST /reconciliation/{issue_id}/actions` | Owner/Admin: `acknowledge` or `reopen` with `expected_financial_revision`, an idempotent `operation_id` and a closed reason code. It changes no evidence, amount or unresolved count. |

### Operator backfill

A client whose evidence predates the projection, or one whose catch-up stopped (failure or budget), needs:

```
python -m app.ledger_backfill --agency <uuid> --client <uuid> [--batch 200] [--restart]
```

It runs with the migration role, refuses (`refused`, exit 1, nothing changed) an agency that does not own the client (R0607-18), writes a staging generation in resumable batches, catches up under the revenue lock and publishes only if the published and staging generations are unchanged. Readers never see staging rows. Cost grows quadratically with history (200 rows about 1.2 s on the development workstation); this is the open A3 limitation.

## Sale association (007-C)

`POST /revenue/identity-associations` with the ingest key that submitted the identity assertion:

```json
{"request_id": "...", "source_account_id": "shop", "sale_operation_id": "S1", "assertion_id": "...", "expected_revision": null}
```

It links only while the assertion's owned segment is unambiguous, `identity_link` and `attribution` are both granted, and the assertion was received within the current attribution grant (R0607-05). A segment that ended normally, for example when another person signed in on the same device, keeps its owner (D-076, R0607-10). An unknown sale stays pending until the ledger verifies it; a different owner yields an ambiguous revision, which no request can turn into its own until a review action (R0607-04); ambiguous associations are listed under `ambiguous_associations` in `GET /identity/review`. A reversal moves live associations with their recomputed segment owner, or makes them ambiguous with it (R0607-15). The answer is generic: `201 accepted` for every refused proof as well, `200 duplicate`, `409 conflict` for a reused request ID, and `409 revision_conflict` only against a live association (R0607-06). Owner/Admin may `POST /revenue/identity-associations/{association_id}/detach`. Withdrawal of either permission, erasure and expiry clear every identifying pointer of every revision (F1); amounts never change.

`app.services.attribution_inputs` turns a person's persisted journey and current associations into 008-A `Touchpoint`, `Conversion` and `SaleState` values for the existing in-memory engine. Persisted attribution runs, 016-B/C, native rollout and deployment are not implemented.
