# Tasks: 011-youtube
Status: Not completed; this is a review checklist, not an implementation instruction. Preparation under D-056.

- [x] Prepare the [entry review](entry-review.md) from the official Google documentation read on 2026-11-18, with the 009 contract gaps, the policy constraints, decisions D1-D17 and slices 011-A to 011-D.
- [x] Approve the scope and sources for youtube analytics: D15 by D-057 (existing project `connectapp`), D1-D14, D16 and D17 as recommended by D-058, with 011-B before 011-A.
- [x] Google Cloud console steps (owner, 2026-11-18), as adjusted for `connectapp` in [entry review section 10](entry-review.md#10-owner-decisions).
- [x] Prepare the 011-B [feasibility checklist](feasibility-checklist.md) and the read-only tool `app.youtube_feasibility` with offline tests ([evidence](evidence.md)).
- [x] Correct review findings R011-01 to R011-09 of the 011-B tool and documents, each with a regression that fails at `bb3263e` (D-059, [corrections](evidence.md#011-b-review-corrections-2026-11-18)).
- [ ] 011-B feasibility check: the owner's run and answers to F1-F14 with redacted evidence. Answered so far: F1 (a first consent with a scope cleared waits for Phase 4), F2, F3 (without the 7-day check), F4, F5, F6, F7, F8 (without the next-day check), F9, F10, F11 and F14. F3, F12 and F13 follow after 2026-11-24 23:57 UTC under the access rule of the [completion prompt](completion-prompt.md).
- [x] Owner decision on the proposed D9 completeness amendment ([consequences for 011-A](evidence.md#consequences-for-011-a)): approved as D-060.
- [ ] After 011-B: delete `local-data\youtube-feasibility` once the summary is recorded (R011-08, D-010).
- [x] 011-A: YouTube-shaped synthetic adapter, runtime extensions and migration 0015 ([design](design-011a.md), [evidence](evidence.md#011-a-youtube-shaped-synthetic-adapter-2026-11-18)). Started before the next-day probe (F8) at the owner's request of 2026-11-18.
- [x] 011-C: the live adapter, its settings, the operator purge and migration 0016, with fixture tests ([evidence](evidence.md#011-c-live-youtube-adapter-2026-11-18)).
- [x] 011-C read-only live check with the owner's test channel (2026-11-18): the browser connect and one sync of each stream. It found and corrected the `video_totals` report ([evidence](evidence.md#live-check-with-the-owners-test-channel-2026-11-18)).
- [ ] 011-C live disconnect check after F3 (Phase 4).
- [ ] Follow-up: rotate the client secret shared in the conversation before any use beyond owner test channels. Requested on 2026-11-18 (completion prompt, Phase 3 step 7) and deferred by the owner.
- [x] Re-verify the `youtube.authorized_analytics` and `youtube.other_data` rows and mark them current before the live adapter runs (011-C, D-025): verified 2026-11-18, review due 2027-11-18 ([evidence](evidence.md#policy-rows-re-verified-2026-11-18)).
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
