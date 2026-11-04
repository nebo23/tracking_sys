# Tasks: 014-ad-spend-capi
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for advertising spend and conversion delivery.
- [ ] Resolve Q-001, Q-004, Q-010, Q-012; initial advertising provider and record the owner decision.
- [ ] Verify dependencies: 009-connector-runtime, 007-revenue-ledger, 008-attribution-engine.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: Rerunning spend ingestion does not duplicate totals and handles revisions, timezones, and currencies.
- [ ] Verify: Only verified conversions with required consent enter the delivery outbox; a browser signal alone does not prove payment.
- [ ] Verify: Retries do not create a semantically duplicate conversion; provider rejections have recorded resolution paths without endless retry loops.
- [ ] Verify: ROAS identifies its model, period, and currency; zero spend does not produce a misleading infinite value.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
