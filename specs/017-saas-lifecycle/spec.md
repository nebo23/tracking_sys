# 017-saas-lifecycle — SaaS subscriptions and usage lifecycle
Status: Draft; implementation is not approved. Level: L5. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER multi-agency SaaS; PDF-096,098,101. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define agency registration, invitations, onboarding, plans, entitlements, metering, approved trial/subscription flows, limits, offboarding, and support.

## Out of scope
Setting prices, selecting a billing provider, or imposing an unapproved trial.

## Acceptance criteria
1. Concurrent account creation does not duplicate agencies or subscriptions; ownership transfer and offboarding follow explicit policies.
2. Usage limits are enforced server-side, not only in React, and do not affect unrelated clients.
3. Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue.
4. Exceeding quotas or budgets has documented behavior that protects data and does not break critical redirects without an agreed policy.
5. Closing an agency stops its jobs and applies export, deletion, and retention policies.

## Required design contracts
Plan, Entitlement, UsageMeter, Subscription, and BillingEvent; pricing and provider selection remain open.

## Dependencies and open decisions
Dependencies: [002-tenancy-access](../002-tenancy-access/spec.md), [009-connector-runtime](../009-connector-runtime/spec.md)

Open decisions: Q-003, Q-004, Q-005, Q-008. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
