# Tasks: 017-saas-lifecycle
Status: 017-A is implemented under D-092 ([evidence](evidence-017a.md)) and merged in PR 19 after Claude's [merge review](merge-review-017a.md) (D-093); 017-B, approved under D-098 ([entry review](entry-review-017b.md)), is implemented and merged in PR 21 ([evidence](evidence-017b.md), [merge review](merge-review-017b.md), D-099); 017-C, approved as recommended under D-103 ([entry review](entry-review-017c.md)), is implemented and open for review ([evidence](evidence-017c.md)). This is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for saas subscriptions and usage lifecycle.
- [ ] Resolve Q-003, Q-004, Q-005, Q-008 and record the owner decision.
- [ ] Verify dependencies: 002-tenancy-access, 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [x] Implement the first approved slice (017-A, D-092).
- [x] Implement the offboarding slice (017-B, D-098).
- [x] Implement the billing slice (017-C, D-103).
- [x] Verify: Concurrent account creation does not duplicate agencies or subscriptions; ownership transfer and offboarding follow explicit policies (017-A D9; 017-B OV01-OV20; 017-C BL05, BL16).
- [x] Verify: Usage limits are enforced server-side, not only in React, and do not affect unrelated clients (SV02-SV05, SV19).
- [x] Verify: Duplicate or delayed billing webhooks are idempotent; SaaS subscription billing remains separate from agency-client revenue (017-C BL07, BL16, BL17, BL19).
- [x] Verify: Exceeding quotas or budgets has documented behavior that protects data and does not break critical redirects without an agreed policy (SV04-SV06).
- [x] Verify: Closing an agency stops its jobs and applies export, deletion, and retention policies (017-A SV11, SV13; 017-B OV01-OV20).
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
