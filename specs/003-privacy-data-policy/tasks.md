# Tasks: 003-privacy-data-policy
Status: Not completed; this is a review checklist, not an implementation instruction.

Continuation authorized under D-023 on 2026-11-04. Work on `codex/spec-003-privacy-data-policy`; use the [Claude handoff](implementation-prompt.md). Detailed policy and schema choices remain subject to review.

- [x] Create the dedicated local branch from merged main (PR 1, `98747a2`) and prepare the Claude handoff.
- [x] Reconcile the design inventory and historical amendments with `0004_identity` and the merged authentication corrections before proposing implementation changes. See the [design](design.md) and [evidence](evidence.md).
- [x] Prepare the [003-A decision packet](decision-packet-003a.md): slice boundaries, retention, closure and erasure, privileges, and mail cleanup.
- [x] Re-verify the primary sources behind the decision packet ([sources](../../research_notes/privacy-data-policy/sources.md), 2026-11-04).
- [x] Implement 003-A1, the data-class registry, as independent work under D-023 (no schema, dependency, retention, deletion, or privilege change).
- [x] Implement 003-A2, the log allowlist and library logger routing, as independent work under D-023 (M1-M3, M6).
- [x] Record the owner's decisions on packet items 1-5 (D-024, 2026-11-04: every recommended option).
- [ ] Owner review of 003-A1/003-A2.
- [x] Implement 003-A3 (lifecycle runner, migration 0005, tracking_lifecycle role) and 003-A4 (reset and invitation mail expiry) under D-024 with disposable-database tests (L3, L4, L7).
- [ ] Implement 003-A5, account closure and erasure, under D-024 (L6, L7, L8).

- [ ] Approve the scope and sources for consent, data protection, and lifecycle.
- [x] Review the owner-requested [Google/Gmail continuation amendments](review-amendments.md) under D-021. Their schema, dependency, identity, and provider choices were resolved by D-022 and merged in PR 1; the file is kept as a historical record. This did not approve the proposed privacy and retention rules.
- [ ] Resolve Q-003, Q-012 and record the owner decision. Q-003 is not needed for 003-A; Q-012 is partly addressed by packet decision 2.
- [x] Verify dependencies: 002-tenancy-access (merged in PR 1; baseline 196 passed on the disposable database).
- [ ] Prepare applicable contracts and synthetic data/permission examples. DataClassPolicy is implemented; ConsentRecord, DeletionRequest, TokenSecretReference, and connector rows are proposed for 003-B/003-C.
- [x] Define independently reviewable local changes for the approved specification (design section 16).
- [x] Implement the first slice (003-A1/003-A2, pending owner review).
- [ ] Verify: Events that violate the approved consent policy enter neither prohibited storage nor an outbound delivery queue.
- [ ] Verify: Password and sensitive payment fields are excluded from form telemetry and logs. Logs are verified; form telemetry waits for 004/005.
- [ ] Verify: Subject or connector deletion covers applicable raw data, derived data, caches, and exports, and prevents reintroduction through old event replay under the approved policy.
- [ ] Verify: Backup restoration reapplies deletion tombstones before making the service available.
- [x] Update documentation, limitations, and untested assumptions for 003-A1/003-A2.
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
