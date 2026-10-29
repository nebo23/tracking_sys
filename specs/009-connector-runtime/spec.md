# 009-connector-runtime — Connector runtime and OAuth
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
Foundation for USER social; PDF-058,059,090,100. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Manage OAuth connection lifecycles, encrypted credentials, synchronization scheduling/workers, cursors/checkpoints, quotas and cost budgets, backfill, retries, and webhook verification.

## Out of scope
Selecting a queue provider or assuming an application has platform approval.

## Acceptance criteria
1. OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow.
2. Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients.
3. 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records.
4. Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states.

## Required design contracts
Connection, SyncRun, Checkpoint, Capability, ProviderError, and UsageRecord; keep the runtime contract independent of individual platforms.

## Dependencies and open decisions
Dependencies: [003-privacy-data-policy](../003-privacy-data-policy/spec.md), [004-event-collection](../004-event-collection/spec.md)

Open decisions: Q-001, Q-004, Q-009, Q-010. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
