# Tasks: 005-links-tracker
Status: Implemented and verified locally under D-033 (2026-11-10); awaiting independent review. See the [evidence](evidence.md).

- [x] Approve the scope and sources for links, utm parameters, and website tracker (D-033).
- [x] Record owner choices for [D1-D10](decision-packet.md) (D-033: all recommended options); Q-001 to Q-004 and Q-012 stay open for real intake.
- [x] Verify the merged code dependency: 004-event-collection, PR 3 at `e8ef587`; 481 suite tests and two independent reproduction checks recorded before merge. Native rollout remains separate.
- [x] Prepare the [entry review](entry-review.md) on the fresh `codex/spec-005-links-tracker` branch (D-032).
- [x] Prepare [design revision 1](design.md) and the [decision packet](decision-packet.md), including schema, tracker consent/storage, tooling and domain-verification boundaries (approved by D-033).
- [x] Prepare proposed contracts, synthetic journey/permission examples and the [verification matrix](verification-matrix.md) (executed; see the evidence).
- [x] Define independently reviewable proposed slices 005-A to 005-E in the [plan](plan.md).
- [x] Review and approve the six-table schema, event-link column and grants before migration implementation (D-033, D3).
- [x] Select exact compatible dependency versions for approved tools; pin in local manifests/locks and install only in the isolated project environments: dnspython 2.9.1 (existing hashes) and Playwright 1.64.1 (package-local lockfile and browsers).
- [x] 005-B: implement approved resources, safe redirects and tenant/host isolation (`5d2c13b`, fix `ed1f245`).
- [x] 005-C: implement approved consent-state and event-link contracts with 004 compatibility tests (`cb580fd`).
- [x] 005-D: implement approved tracker state machine, storage and browser-side minimization with real-browser tests (`2418720`).
- [x] 005-E: implement approved domain verification and complete acceptance evidence; label live operational checks separately (`c9bcb2c`, regressions `0c846a9`).
- [x] Implement the first approved slice.
- [x] Verify: A test link reaches its destination and preserves content/campaign provenance without exposing personal information in the URL (synthetic).
- [x] Verify: Disallowed destinations, unsafe protocols, and redirect loops are rejected; link management requires client permission.
- [x] Verify: Analytics failure does not break redirects; bots and prefetch requests are not automatically counted as qualified human clicks.
- [x] Verify: Custom domains require ownership verification; implementation verifies TLS and slug conflicts (synthetic DNS/TLS; live operation not performed).
- [x] Update documentation, limitations, and untested assumptions.
- [x] Present a reviewable result to the owner (local commits on `codex/spec-005-links-tracker`).
- [ ] Independent review of the local commits.
- [x] Obtain owner upload approval, then push and create a PR (D-012): D-034 on 2026-11-11. Merge, native rollout and deployment remain separate decisions.
- [ ] Owner-authorized live custom-domain smoke test, if wanted (separately gated).
- [ ] Record owner acceptance before progressing to dependent work.
