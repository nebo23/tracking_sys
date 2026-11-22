# Plan: 015-business-integrations
Status: Completed for review under D-066, D-067 and D-068: slices 015-A to 015-E are implemented against synthetic senders and fixtures, with migrations `0020` to `0025` tested on disposable PostgreSQL only; see the [evidence](evidence.md).

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
- [x] Payment webhook signatures are verified; duplicates and out-of-order delivery are safe and reconcile with the revenue ledger (first round, Paymob, synthetic fixtures).
- [x] Booking creation, cancellation, and rescheduling do not count as multiple sales; links to leads require identifier evidence (second round, Cal.com and the signed webhook).
- [x] A CRM stage transition does not become a paid transaction without an approved rule and supporting evidence (second round).
- [x] WhatsApp/ManyChat referral metadata is used when available; missing data remains unknown, and comment/DM correlation requires a valid grant (second round, WhatsApp Cloud API; ManyChat is a follow-up).
- [x] CSV imports include a preview, schema validation, row-level errors, and client authorization (first round).

## Follow-ups after the first round
- Outside the acceptance criteria (D-068 E1), each with its own decision: Stripe, Paymob transaction reads and backfill, third-party form tools, ManyChat and a named CRM connector.
- Live checks with owner Cal.com and WhatsApp accounts.
- A live Paymob check with an owner sandbox account and an HTTPS-hosted API (020), separately approved; it confirms the null text form in the signature, the references of refunds after captures and the retry behavior.
- 007-B: persisted postings and movements, finance write permissions, audited corrections, reconciliation workflows and the approval of declarations.
- 006: linking payments to people and journeys.
- The legal review (Q-012) of callbacks that carry the last four digits of a card, before live intake.
- Native `tracking_sys` migration of `0020` to `0025`, and deployment.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
