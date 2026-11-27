# Tasks: 017-saas-lifecycle
Status: 017-A is implemented under D-092 ([evidence](evidence-017a.md)) and merged in PR 19 after Claude's [merge review](merge-review-017a.md) (D-093); 017-B and 017-C are not started. This is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for saas subscriptions and usage lifecycle.
- [ ] Resolve Q-003, Q-004, Q-005, Q-008 and record the owner decision.
- [ ] Verify dependencies: 002-tenancy-access, 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [x] Implement the first approved slice (017-A, D-092).
- [ ] Verify: Concurrent account creation does not duplicate agencies or subscriptions; ownership transfer and offboarding follow explicit policies.
- [x] Verify: Usage limits are enforced server-side, not only in React, and do not affect unrelated clients (SV02-SV05, SV19).
- [ ] Verify: Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue.
- [x] Verify: Exceeding quotas or budgets has documented behavior that protects data and does not break critical redirects without an agreed policy (SV04-SV06).
- [ ] Verify: Closing an agency stops its jobs and applies export, deletion, and retention policies.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
