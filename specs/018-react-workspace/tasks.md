# Tasks: 018-react-workspace
Status: Not completed; this is a review checklist, not an implementation instruction.

- [ ] Approve the scope and sources for react workspace and user experience.
- [x] Resolve Q-006, Q-009; approve user flows and design before implementation and record the owner decision. (D-082 and D-083. The currency and FX part of Q-006 stays open with specification 007, and D-084 approves the package list of the [018-A plan](plan-018a.md).)
- [ ] Verify dependencies: 016-analytics-reporting, 017-saas-lifecycle.
- [ ] Prepare applicable contracts and synthetic data/permission examples.
- [x] Define independently reviewable local changes for the approved specification. (D14 in D-083: slices 018-A to 018-D; the first is planned in the [018-A plan](plan-018a.md).)
- [x] Implement the first approved slice. (018-A under D-084; see the [018-A evidence](evidence-018a.md). The owner's review is pending.)
- [ ] Verify: A user connects an account, sees its status, and accesses clearly sourced social analytics and attribution workflows.
- [ ] Verify: Switching clients clears state/cache that could expose the previous client's data; deep links cannot bypass API authorization.
- [ ] Verify: Approved RTL/LTR layouts, keyboard navigation, and loading, empty, error, stale, and partial states work correctly. (Checked for the screens of 018-A, see the [018-A evidence](evidence-018a.md); stale and partial states arrive with the data screens of later slices.)
- [ ] Verify: Budgets, financial data, and permissions match backend rules; mobile layouts retain essential actions.
- [ ] Verify: Production secrets are absent from browser bundles, and potentially dangerous content is rendered safely. (Checked for 018-A by the bundle search of the [018-A evidence](evidence-018a.md); every later slice repeats it.)
- [ ] Update documentation, limitations, and untested assumptions.
- [ ] Present a reviewable result to the owner. (018-A was pushed to the specification branch under D-051 on 2026-11-26; the later slices are not started.)
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012). (018-A: pushed under D-051 and opened as a pull request under D-086; the review and the merge are pending.)
- [ ] Record owner acceptance before progressing to dependent work.
