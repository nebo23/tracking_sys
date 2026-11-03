# Tasks: 018-react-workspace
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for react workspace and user experience.
- [ ] Resolve Q-006, Q-009; approve user flows and design before implementation and record the owner decision.
- [ ] Verify dependencies: 016-analytics-reporting, 017-saas-lifecycle.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [ ] Define independently reviewable local changes for the approved specification.
- [ ] Implement the first approved slice.
- [ ] Verify: A user connects an account, sees its status, and accesses clearly sourced social analytics and attribution workflows.
- [ ] Verify: Switching clients clears state/cache that could expose the previous client's data; deep links cannot bypass API authorization.
- [ ] Verify: Approved RTL/LTR layouts, keyboard navigation, and loading, empty, error, stale, and partial states work correctly.
- [ ] Verify: Budgets, financial data, and permissions match backend rules; mobile layouts retain essential actions.
- [ ] Verify: Production secrets are absent from browser bundles, and potentially dangerous content is rendered safely.
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
