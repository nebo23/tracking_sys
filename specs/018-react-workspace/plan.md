# Plan: 018-react-workspace
Status: Draft. This plan does not authorize implementation or dependency selection.

## Expected outcome
Provide authentication flows, agency/client switching, connections, dashboards, journeys, links, reports, and settings with responsive and accessible interactions.

## Design before implementation
- A typed API client after toolchain approval; define route, permission, and state matrices before components.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-006, Q-009; approve user flows and design before implementation.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

After repository authorization, combine slices for small changes or separate providers into individual PRs. Every PR must contain a reviewable change; no push is authorized now.

## Validation
- [ ] A user connects an account, sees its status, and accesses clearly sourced social analytics and attribution workflows.
- [ ] Switching clients clears state/cache that could expose the previous client's data; deep links cannot bypass API authorization.
- [ ] Approved RTL/LTR layouts, keyboard navigation, and loading, empty, error, stale, and partial states work correctly.
- [ ] Budgets, financial data, and permissions match backend rules; mobile layouts retain essential actions.
- [ ] Production secrets are absent from browser bundles, and potentially dangerous content is rendered safely.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
