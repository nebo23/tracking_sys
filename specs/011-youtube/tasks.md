# Tasks: 011-youtube
Status: Not completed; this is a review checklist, not an implementation instruction. Preparation under D-056.

- [x] Prepare the [entry review](entry-review.md) from the official Google documentation read on 2026-11-18, with the 009 contract gaps, the policy constraints, decisions D1-D17 and slices 011-A to 011-D.
- [ ] Approve the scope and sources for youtube analytics: the owner's choices on D1-D17.
- [ ] Google Cloud console steps of [entry review section 8](entry-review.md#8-owner-steps-in-the-google-cloud-console-before-011-b-after-d15-and-d16-are-approved) (owner, after D15 and D16).
- [ ] 011-B feasibility check: answers to F1-F14 with redacted evidence.
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
