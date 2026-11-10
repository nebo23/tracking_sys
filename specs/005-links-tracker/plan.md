# Plan: 005-links-tracker
Status: Detailed design prepared for review on 2026-11-10. This plan does not authorize implementation or dependency selection. Read [design revision 1](design.md), the [decision packet](decision-packet.md) and [verification matrix](verification-matrix.md).

Entry review: [merged baseline and preparation sequence](entry-review.md), refreshed on 2026-11-10 from `main` at `e8ef587` under D-032. Prepare the detailed design and decision packet before application changes.

## Expected outcome
Define per-content links, a URL registry, UTM templates, a branded-domain plan, redirects, a JavaScript tracker for client websites, and a form-field allowlist.

## Design before implementation
- Link, ContentReference, Campaign, and DomainVerification; the browser tracker is separate from the React application.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals. Resolve D1-D10 and only the open Q-001/Q-002/Q-003/Q-004/Q-009/Q-012 questions needed for the next slice; do not silently resolve real customer or infrastructure policy.

## Proposed review slices
1. **005-A:** approve D1-D10 or record the approved subset; review the six-table/additive-column schema and contract compatibility before coding.
2. **005-B:** implement approved link resources, permissions, UTM rules and safe redirects; verify scoped grants, concurrent slugs, host conflicts and telemetry independence on disposable storage.
3. **005-C:** implement the approved optional event link reference and non-mutating consent-state route; preserve old deduplication fingerprints, public CORS boundaries, erasure and lifecycle behavior.
4. **005-D:** implement the self-hostable JavaScript tracker and explicit form bindings; verify outgoing bytes and storage behavior with native Node tests and real browsers.
5. **005-E:** implement the reviewed DNS/TLS verifier and synthetic test adapters, installation example and full end-to-end matrix. Live DNS/certificates/deployment remain separately gated and must not be reported as tested.
6. Record the exact tested tree, checks and limitations; present the local result before upload. Stop dependent work if a required packet option remains undecided, while continuing independent approved work.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] A test link reaches its destination and preserves content/campaign provenance without exposing personal information in the URL.
- [ ] Disallowed destinations, unsafe protocols, and redirect loops are rejected; link management requires client permission.
- [ ] Analytics failure does not break redirects; bots and prefetch requests are not automatically counted as qualified human clicks.
- [ ] Custom domains require ownership verification; implementation verifies TLS and slug conflicts.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
