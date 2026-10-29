# Plan: 002-tenancy-access
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Define agency tenants, client workspaces, membership, sign-in, invitations, roles, service/API credentials, and auditing of sensitive changes.

## Design before implementation
- Agency, ClientWorkspace, User, Membership, RolePolicy, and AuditEvent; define an authorization matrix before routes.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-008.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] With two agencies and two clients per agency, every read, mutation, export, and job enforces the relevant access boundary.
- [ ] A client viewer cannot access another client in the same agency or financial fields excluded by their permissions.
- [ ] Expired or reused invitations grant no new access; disabling a member revokes access.
- [ ] Background jobs and cache keys carry tenant/client scope; a user-supplied tenant_id is insufficient authorization.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
