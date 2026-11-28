# 017-saas-lifecycle — SaaS subscriptions and usage lifecycle
Status: 017-A (plans, limits, agency closure and the agreement record, without payment) is approved in its [entry review](entry-review-017a.md) (D-092) and implemented on `codex/spec-017a-saas-plans` under its [implementation handoff](implementation-prompt-017a.md) and [design note](design-017a.md); see the [evidence](evidence-017a.md). It merged through PR 19 at `06d6a19` after Claude's [merge review](merge-review-017a.md) (D-093). 017-B (the offboarding export, provider disconnection and purge of closed agencies), approved as recommended in its [entry review](entry-review-017b.md) (D-098), is implemented on `codex/spec-017b-agency-offboarding` under its [design note](design-017b.md) with the additive migration `0033_agency_offboarding`; see the [evidence](evidence-017b.md). It merged through PR 21 at `04dc323` after Claude's [merge review](merge-review-017b.md) (D-099); 017-C (subscription billing: the payment provider, prices and the trial) is prepared under D-102 in its [entry review](entry-review-017c.md) and [implementation handoff](implementation-prompt-017c.md), with Paddle Billing in USD and a 14-day trial; the owner approved D1-D14 as recommended (D-103), and it is implemented on `codex/spec-017c-saas-billing` under its [design note](design-017c.md) with the additive migration `0034_saas_billing` and open for review; see the [evidence](evidence-017c.md). Level: L5. Prepared: 2026-10-28. English revision: 2026-10-29. Updated: 2026-11-28.

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
