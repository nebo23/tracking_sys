# Tasks: 011-youtube
Status: Not completed; this is a review checklist, not an implementation instruction. Preparation under D-056.

- [x] Prepare the [entry review](entry-review.md) from the official Google documentation read on 2026-11-18, with the 009 contract gaps, the policy constraints, decisions D1-D17 and slices 011-A to 011-D.
- [x] Approve the scope and sources for youtube analytics: D15 by D-057 (existing project `connectapp`), D1-D14, D16 and D17 as recommended by D-058, with 011-B before 011-A.
- [x] Google Cloud console steps (owner, 2026-11-18), as adjusted for `connectapp` in [entry review section 10](entry-review.md#10-owner-decisions).
- [x] Prepare the 011-B [feasibility checklist](feasibility-checklist.md) and the read-only tool `app.youtube_feasibility` with offline tests ([evidence](evidence.md)).
- [ ] 011-B feasibility check: the owner's run and answers to F1-F14 with redacted evidence.
- [ ] 011-A: YouTube-shaped synthetic adapter, runtime extensions and migration 0015, after the 011-B evidence.
- [ ] Follow-up: rotate the client secret shared in the conversation before any use beyond owner test channels.
- [ ] Re-verify the `youtube.authorized_analytics` and `youtube.other_data` rows and mark them current before the live adapter runs (011-C, D-025).
- [ ] Resolve Q-001, Q-004; provider use-case and policy approval and record the owner decision.
- [ ] Verify dependencies: 009-connector-runtime.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: Prove scopes, channel authorization, Analytics access, and actual project quotas before connector release.
- [ ] Verify: Completeness markers account for incomplete days, reporting delays, and historical coverage.
- [ ] Verify: Storage, display, and retention follow an applicable provider policy and permitted use case; unrestricted cross-source scoring is excluded.
- [ ] Verify: Tagged-link attribution is displayed as separate evidence; combining or deriving metrics with YouTube data requires policy review.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
