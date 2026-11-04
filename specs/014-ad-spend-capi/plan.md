# Plan: 014-ad-spend-capi
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Select an initial advertising platform; ingest spend and campaign/ad identifiers, deliver conversions through an outbox, and reconcile deduplication, consent, and errors.

## Design before implementation
- AdAccount, SpendFact, ConversionDelivery, and ProviderAcknowledgement; separate read and write permissions.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004, Q-010, Q-012; initial advertising provider.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Rerunning spend ingestion does not duplicate totals and handles revisions, timezones, and currencies.
- [ ] Only verified conversions with required consent enter the delivery outbox; a browser signal alone does not prove payment.
- [ ] Retries do not create a semantically duplicate conversion; provider rejections have recorded resolution paths without endless retry loops.
- [ ] ROAS identifies its model, period, and currency; zero spend does not produce a misleading infinite value.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
