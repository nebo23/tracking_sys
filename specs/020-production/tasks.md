# Tasks: 020-production
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for deployment, operations, and recovery.
- [ ] Resolve Q-003, Q-004, Q-011, Q-012; hosting and production approval and record the owner decision.
- [ ] Verify dependencies: 019-quality-security.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: An actual restore in an isolated environment meets approved RPO/RTO targets and reapplies deletion controls.
- [ ] Verify: Deployment, rollback, and migration recovery exercises preserve event and payment data.
- [ ] Verify: Alerts cover worker lag, failed synchronization, rejected webhooks, quotas, cost, errors, and storage.
- [ ] Verify: Kill switches disable a specific connector, conversion delivery, or ingestion path while preserving tenant isolation.
- [ ] Verify: Launch requires provider approvals, budget, privacy decisions, and explicit owner sign-off.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
