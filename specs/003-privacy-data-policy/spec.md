# 003-privacy-data-policy — Consent, data protection, and lifecycle
Status: Draft; detailed approval is pending. Level: L1. Prepared: 2026-10-28. English revision: 2026-10-29. Continuation authorized under D-023 on 2026-11-04: the [design](design.md) is reconciled with merged specification 002. Completed at contract level under D-025 ([evidence](evidence.md)) and under owner review in [PR 2](https://github.com/nebo23/tracking_sys/pull/2), which is open and not merged. The PR review findings R003-01 to R003-03 were corrected under D-026 on 2026-11-09 ([correction evidence](review-corrections-evidence.md)). Slice 003-A is implemented. The 003-B to 003-D contracts are tested libraries without tables, and end-to-end verification of acceptance criteria 1, 3, and 4 (and the form half of 2) is transferred to the consuming specifications listed in the evidence.

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
D-023 (2026-11-04) authorized continuation; D-024 approved the 003-A decisions; D-025 approved contract-level completion with the J1 consent default, tombstone policy, and local key custody. D-026 (2026-11-08) authorized the scoped review corrections and their publication to PR 2. Owner review of the corrected work, formal acceptance, and merge remain pending.
