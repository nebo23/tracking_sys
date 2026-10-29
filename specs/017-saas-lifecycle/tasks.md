# Tasks: 017-saas-lifecycle
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for saas subscriptions and usage lifecycle.
- [ ] Resolve Q-003, Q-004, Q-005, Q-008 and record the owner decision.
- [ ] Verify dependencies: 002-tenancy-access, 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable PR slices once the repository is available.
- [ ] Implement the first approved slice.
- [ ] Verify: Concurrent account creation does not duplicate agencies or subscriptions; ownership transfer and offboarding follow explicit policies.
- [ ] Verify: Usage limits are enforced server-side, not only in React, and do not affect unrelated clients.
- [ ] Verify: Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue.
- [ ] Verify: Exceeding quotas or budgets has documented behavior that protects data and does not break critical redirects without an agreed policy.
- [ ] Verify: Closing an agency stops its jobs and applies export, deletion, and retention policies.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Create or update a PR and push only after repository authorization.
- [ ] Record owner acceptance before progressing to dependent work.
