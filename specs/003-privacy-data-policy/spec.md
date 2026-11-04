# 003-privacy-data-policy — Consent, data protection, and lifecycle
Status: Draft; detailed approval is pending. Level: L1. Prepared: 2026-10-28. English revision: 2026-10-29. Continuation authorized under D-023 on 2026-11-04: the [design](design.md) is reconciled with merged specification 002. Slice 003-A (data-class registry, log allowlist, lifecycle runner, mail expiry, and account closure) is implemented locally for review under D-023/D-024 ([evidence](evidence.md)). 003-B to 003-D depend on later specifications. No acceptance criterion below is complete.

## Sources
PDF-104,105,106,107,108. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define consent contracts, data classes, masking before transmission, token encryption, retention, deletion, export, residency decisions, and integration authorization.

## Out of scope
Claims of certification or automatic legal compliance, and session replay implementation.

## Acceptance criteria
1. Events that violate the approved consent policy enter neither prohibited storage nor an outbound delivery queue.
2. Password and sensitive payment fields are excluded from form telemetry and logs.
3. Subject or connector deletion covers applicable raw data, derived data, caches, and exports, and prevents reintroduction through old event replay under the approved policy.
4. Backup restoration reapplies deletion tombstones before making the service available.

## Required design contracts
ConsentRecord, DataClassPolicy, DeletionRequest, TokenSecretReference, and a provider-specific policy table.

## Dependencies and open decisions
Dependencies: [002-tenancy-access](../002-tenancy-access/spec.md)

Open decisions: Q-003, Q-012. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
