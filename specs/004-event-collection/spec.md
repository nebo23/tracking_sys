# 004-event-collection — Event collection and contracts
Status: Draft; implementation is not approved. Level: L2. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-001,002,004,005,006,007,008,009,013,014,082,084. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define a versioned event envelope, limited-trust public ingestion, authenticated server ingestion, webhooks, deduplication, UTM/click IDs, bot/internal traffic filtering, and backend event diagnostics.

## Out of scope
Native mobile SDKs, unlimited automatic capture, or treating a browser purchase event as proof of payment.

## Acceptance criteria
1. The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
2. An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
3. Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
4. Late arrivals retain occurred_at and received_at and update reports without double counting.
5. Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.

## Required design contracts
EventEnvelope v1, idempotency scope, public/trusted credentials, and quarantine, retry, and dead-letter contracts.

## Dependencies and open decisions
Dependencies: [003-privacy-data-policy](../003-privacy-data-policy/spec.md)

Specification 003 obligations (D-025): call the consent evaluation (`app.privacy.consent`), collection minimization (`app.privacy.collection`), and tombstone admission (`app.privacy.deletion`) at ingestion (E2); add the consent, deletion-request, and tombstone tables through this specification's reviewed schema; verify 003 acceptance criteria 1 and 3 (replay blocking, cases C1, D2, M5) end to end.

Open decisions: Q-002, Q-004, Q-012. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
