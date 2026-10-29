# Tasks: 009-connector-runtime
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for connector runtime and oauth.
- [ ] Resolve Q-001, Q-004, Q-009, Q-010 and record the owner decision.
- [ ] Verify dependencies: 003-privacy-data-policy, 004-event-collection.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow.
- [ ] Verify: Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients.
- [ ] Verify: 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records.
- [ ] Verify: Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
