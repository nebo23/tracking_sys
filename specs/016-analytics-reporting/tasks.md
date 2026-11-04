# Tasks: 016-analytics-reporting
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for analytics queries and client reporting.
- [ ] Resolve Q-001, Q-006, Q-007, Q-011 and record the owner decision.
- [ ] Verify dependencies: 008-attribution-engine, 010-instagram, 011-youtube, 012-linkedin, 013-x, 014-ad-spend-capi, 015-business-integrations.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: Every report enforces tenant, client, and field permissions, including exports and background generation.
- [ ] Verify: Social metrics show platform definitions, ranges, and freshness; revenue shows currency, model, attribution window, and evidence.
- [ ] Verify: Pagination, filters, date boundaries, timezones, and comparisons match reference fixtures.
- [ ] Verify: Partial synchronization, unsupported metrics, and currency mismatches are not displayed as zero or complete totals.
- [ ] Verify: Export URLs are short-lived and authorized; client deletion invalidates accessible reports according to policy.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
