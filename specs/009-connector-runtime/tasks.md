# Tasks: 009-connector-runtime
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for connector runtime and oauth.
- [ ] Resolve Q-001, Q-004, Q-009, Q-010 and record the owner decision.
- [ ] Verify dependencies: 003-privacy-data-policy, 004-event-collection.
- [x] Prepare applicable contracts and synthetic data/permission examples: [entry review](entry-review.md), 2026-11-15.
- [x] Define independently reviewable local changes: slices 009-A to 009-D in the [plan](plan.md).
- [ ] Record the owner decision on entry-review decisions D1-D10 for 009-A.
- [ ] Implement 009-A: migration 0009, OAuth connect and reconnect, status, single-page synthetic sync, `401` handling, disconnect teardown, disposable PostgreSQL concurrency and isolation tests.
- [ ] Verify 003 case D3: revocation at the mock provider, destroyed secret material, scoped purge before `purge_due_at`, honest `failed` or `unsupported` outcomes; the other client keeps syncing.
- [ ] Prepare and approve 009-B (synchronization), 009-C (coverage and provenance) and 009-D (provider webhooks).
- [ ] Verify: OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow.
- [ ] Verify: Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients.
- [ ] Verify: 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records.
- [ ] Verify: Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
