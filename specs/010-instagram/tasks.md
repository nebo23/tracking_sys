# Tasks: 010-instagram
Status: D1-D10 approved by D-053, the story catalog amended by D-054, and 010-C completed under D-055 ([evidence](evidence.md)). 010-D (access for customer accounts) and the follow-ups below remain. This is a review checklist, not an implementation instruction.

- [x] Prepare the [entry review](entry-review.md) from the official Meta documentation read on 2026-11-17, with the 009 contract gaps and decisions D1-D10.
- [x] Approve the scope and sources for instagram analytics: D-053.
- [x] Implement 010-A: the Instagram-shaped synthetic adapter, runtime extensions and migration 0013 ([evidence](evidence.md)).
- [x] Prepare the 010-B [feasibility checklist](feasibility-checklist.md) and the read-only tool `app.instagram_feasibility` with offline tests (no live call).
- [x] Amend the D2 story catalog from the 010-B evidence (D-054) and apply it to the synthetic adapter.
- [x] 010-B: owner-operated feasibility check with an owner-created Meta app and professional test account (entry review section 6). Four reads on 2026-11-17 answered F1, F2 (lifetime), F4-F10 ([evidence](evidence.md#010-b-first-run-2026-11-17)); the F2 refresh, F3 and F11 checks are D-055 follow-ups.
- [x] Instagram part of Q-001: account kinds and the launch metric catalog decided by D-053 (D1, D2) and D-054. Q-001 stays open for 011-013.
- [x] Verify dependencies: 009-connector-runtime (merged in PR 8).
- [x] Prepare applicable contracts and synthetic data/permission examples (010-A synthetic provider; `backend/tests/instagram_graph.py` with the 010-B answer shapes).
- [x] Define independently reviewable local changes for the approved specification (slices 010-A to 010-D).
- [x] Implement the first approved slice (010-A).
- [x] Implement 010-C: the live Instagram Login adapter, its settings, rule-gated registration and migration 0014 (D-055).
- [x] Verify: An authorized test-account feasibility check proves account type, OAuth scopes, and actual fields before the final contract is designed (010-B).
- [x] Verify: Account/media metrics match verified reference fixtures with period, source, and version; unsupported metrics are not displayed as zero.
- [x] Verify: Access failure, content deletion, and disconnection are explicit and apply the retention policy.
- [x] Verify: The interface makes no metric or historical-coverage claim unsupported by documentation and API responses (API contract; no customer interface exists yet).
- [x] Update documentation, limitations, and untested assumptions.
- [x] Present the result and publish it: D-055 asked to complete, push and merge Spec 010.
- [ ] Follow-ups: F2 refresh after 2026-11-18 16:58 UTC, F3, F11 and `forget`, rotation of the app secret, and a product Meta app with the two read-only permissions only.
- [ ] 010-D: App Review, Advanced Access and Business Verification (owner business actions) and an HTTPS-hosted callback (020) before customer accounts.
- [ ] Record owner acceptance before progressing to dependent work.
