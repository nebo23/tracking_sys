# Plan: 011-youtube
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Retrieve authorized channel/video statistics and permitted analytics; distinguish the Data API from the Analytics API and review derived-metric policies before combining data.

## Design before implementation
- Channel/Video references and typed metric records with mandatory source version, interval, and deletion policy.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004; provider use-case and policy approval.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Prove scopes, channel authorization, Analytics access, and actual project quotas before connector release.
- [ ] Completeness markers account for incomplete days, reporting delays, and historical coverage.
- [ ] Storage, display, and retention follow an applicable provider policy and permitted use case; unrestricted cross-source scoring is excluded.
- [ ] Tagged-link attribution is displayed as separate evidence; combining or deriving metrics with YouTube data requires policy review.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
