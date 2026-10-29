# Plan: 005-links-tracker
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Define per-content links, a URL registry, UTM templates, a branded-domain plan, redirects, a JavaScript tracker for client websites, and a form-field allowlist.

## Design before implementation
- Link, ContentReference, Campaign, and DomainVerification; the browser tracker is separate from the React application.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-002, Q-003.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] A test link reaches its destination and preserves content/campaign provenance without exposing personal information in the URL.
- [ ] Disallowed destinations, unsafe protocols, and redirect loops are rejected; link management requires client permission.
- [ ] Analytics failure does not break redirects; bots and prefetch requests are not automatically counted as qualified human clicks.
- [ ] Custom domains require ownership verification; implementation verifies TLS and slug conflicts.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
