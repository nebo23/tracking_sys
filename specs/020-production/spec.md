# 020-production — Deployment, operations, and recovery
Status: Draft; implementation is not approved. Level: L8. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER production; Operational proposals. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Prepare staging and then production after hosting approval, including secrets, TLS/DNS, migrations, backup/restore, monitoring, alerts, runbooks, rollback, and phased rollout.

## Out of scope
Purchasing or deploying services now, or automatically selecting Kubernetes or multiple regions.

## Acceptance criteria
1. An actual restore in an isolated environment meets approved RPO/RTO targets and reapplies deletion controls.
2. Deployment, rollback, and migration recovery exercises preserve event and payment data.
3. Alerts cover worker lag, failed synchronization, rejected webhooks, quotas, cost, errors, and storage.
4. Kill switches disable a specific connector, conversion delivery, or ingestion path while preserving tenant isolation.
5. Launch requires provider approvals, budget, privacy decisions, and explicit owner sign-off.

## Required design contracts
Runbooks, release manifest, rollback plan, and operational ownership; configure CI/CD only as part of approved implementation work.

## Dependencies and open decisions
Dependencies: [019-quality-security](../019-quality-security/spec.md)

Specification 003 obligations (D-025): implement the deletion journal store, restore epochs, and readiness gate from `app.privacy.restore`, run the restore drill for 003 acceptance criterion 4, and choose managed key custody to replace the local token keyring.

Open decisions: Q-003, Q-004, Q-011, Q-012; hosting and production approval. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
