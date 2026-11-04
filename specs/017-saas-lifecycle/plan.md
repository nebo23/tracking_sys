# Plan: 017-saas-lifecycle
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Define agency registration, invitations, onboarding, plans, entitlements, metering, approved trial/subscription flows, limits, offboarding, and support.

## Design before implementation
- Plan, Entitlement, UsageMeter, Subscription, and BillingEvent; pricing and provider selection remain open.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-003, Q-004, Q-005, Q-008.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Concurrent account creation does not duplicate agencies or subscriptions; ownership transfer and offboarding follow explicit policies.
- [ ] Usage limits are enforced server-side, not only in React, and do not affect unrelated clients.
- [ ] Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue.
- [ ] Exceeding quotas or budgets has documented behavior that protects data and does not break critical redirects without an agreed policy.
- [ ] Closing an agency stops its jobs and applies export, deletion, and retention policies.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
