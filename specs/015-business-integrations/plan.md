# Plan: 015-business-integrations
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Select one integration for each approved workflow; map booking, payment, CRM, and WhatsApp events, with a defined import/manual fallback.

## Design before implementation
- Provider-specific subcontracts; each provider becomes an independently reviewable specification or PR slice.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-002, Q-003, Q-010; select providers before implementation.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger.
- [ ] Booking creation, cancellation, and rescheduling do not count as multiple sales; links to leads require identifier evidence.
- [ ] A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence.
- [ ] WhatsApp/ManyChat referral metadata is used when available; missing data remains unknown, and comment/DM correlation requires a valid grant.
- [ ] CSV imports include a preview, schema validation, row-level errors, and client authorization.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
