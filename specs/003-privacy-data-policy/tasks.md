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
- [x] Implement 003-A5, account closure and erasure, under D-024 (migration 0006, `POST /auth/close-account`, closed-account deletion; L6, L7, L8).
- [ ] Owner review of 003-A3 to 003-A5, then a separately approved native rollout (lifecycle role, migrations 0005/0006).

- [x] Approve the scope and sources for consent, data protection, and lifecycle (D-023 to D-025; sources re-verified 2026-11-04 for the decisions taken).
- [x] Review the owner-requested [Google/Gmail continuation amendments](review-amendments.md) under D-021. Their schema, dependency, identity, and provider choices were resolved by D-022 and merged in PR 1; the file is kept as a historical record. This did not approve the proposed privacy and retention rules.
- [x] Resolve the parts of Q-003 and Q-012 this specification needs: J1 strict opt-in removes the market dependency (D-025); credential-state retention is decided (D-024). Market profiles, security/audit/invitation/unverified-account retention, and per-market client-data periods stay open for their specifications.
- [x] Verify dependencies: 002-tenancy-access (merged in PR 1; baseline 196 passed on the disposable database).
- [x] Prepare applicable contracts and synthetic data/permission examples: DataClassPolicy, ConsentRecord, DeletionRequest, TokenSecretReference, the provider policy table, and the restore journal (D-025).
- [x] Define independently reviewable local changes for the approved specification (design section 16).
- [x] Implement the first slice (003-A1/003-A2, pending owner review).
- [x] Verify (contract level; end to end in 004, 005, 014): Events that violate the approved consent policy enter neither prohibited storage nor an outbound delivery queue.
- [x] Verify: Password and sensitive payment fields are excluded from form telemetry and logs. Logs end to end; form rules at contract level, end to end in 005/004.
- [x] Verify (platform accounts end to end; subject and connector at contract level, end to end in 004, 006, 009, 014, 016): Subject or connector deletion covers applicable raw data, derived data, caches, and exports, and prevents reintroduction through old event replay under the approved policy.
- [x] Verify (contract level; restore drill in 019/020): Backup restoration reapplies deletion tombstones before making the service available.
- [x] Update documentation, limitations, and untested assumptions for 003-A1/003-A2.
- [x] Present a reviewable result to the owner (contract-level completion under D-025, with the transferred obligations recorded in each consuming spec.md).
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
