# Tasks: 011-youtube
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for youtube analytics.
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
