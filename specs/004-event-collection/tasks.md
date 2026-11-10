# Tasks: 004-event-collection
Status: Implemented and verified locally on disposable storage under D-027, 2026-11-10 ([evidence](evidence.md)). Not pushed or merged; native rollout and real intake remain gated.

- [x] Prepare the [entry review](entry-review.md) and [predecessor closure matrix](../../docs/planning/spec-004-readiness.md), 2026-11-10. This is design preparation, not implementation approval.
- [x] Prepare [design](design.md), [decision packet](decision-packet.md), synthetic acceptance examples and the 004-A to 004-F delivery plan.
- [x] Verify dependencies: 003 merged in PR 2 (`bab3a33`); create `codex/spec-004-event-collection` from it; full suite 380 passed with PostgreSQL enabled on disposable storage, 2026-11-10.
- [x] Compare the design with the merged code and prepare revision 2 with decisions D1-D11, 2026-11-10.

- [x] Record the owner's D1-D11 decisions as D-027, 2026-11-10.
- [x] Keep Q-002, Q-004 and Q-012 open for real intake; D-027 values apply to development and synthetic use only.
- [x] 004-B: migration 0007, models, registry rules, settings and grants.
- [x] 004-C: ingest keys, trusted consent and trusted intake (smallest complete path).
- [x] 004-D: public browser and generic webhook paths.
- [x] 004-E: deletion, lifecycle expiry, diagnostics and traffic labels.
- [x] Verify server-derived consent basis, subject issuance only with consent, withdrawal/deletion serialization, tombstone replay and no prohibited storage side channels.
- [x] Verify generic webhook raw-body signature, time window, secret rotation, source disablement and public-to-trusted isolation.
- [x] Verify row expiry followed by a rejected late retry, metadata cleanup and safe deletion outcomes. Tombstone keyring rotation is unit-tested; the token keyring KEK rewrap reuses the 003 contract and was not exercised end to end.
- [x] Verify metadata-only diagnostics, traffic labels and bounded date ranges. No 004 route returns financial values, so no financial read path exists yet.
- [x] Verify: The same event_id delivered through browser and server paths is counted once within a client, using an explicit policy for preferring the more trusted source.
- [x] Verify: An identical event_id in another client does not suppress that client's data; conflicting payloads for the same scoped ID are recorded as conflicts.
- [x] Verify: Invalid signatures, oversized payloads, and invalid timestamps are rejected; duplicates are safe and 429 responses support retry.
- [x] Verify: Late arrivals retain occurred_at and received_at without double counting at ingestion. Report updates belong to the later reporting specifications.
- [x] Verify: Denied consent blocks disallowed field collection, and personally identifiable information does not appear in logs.
- [x] Update documentation, limitations, and untested assumptions.
- [x] Present a reviewable result to the owner, 2026-11-10.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
- [ ] Native migration 0007 and lifecycle grants on tracking_sys: separate owner-approved rollout.
