# Tasks: 009-connector-runtime
Status: 009-A implemented locally under D-048, with the findings of both reviews (R009-01 to R009-10) corrected; 009-B to 009-D are approved by D-049 (decisions D11-D20). This is a review checklist, not an implementation instruction.

- [x] Approve the scope and sources of the first slice: D-048 approves 009-A (2026-11-15). Later slices need their own approval.
- [ ] Resolve Q-001, Q-004, Q-009, Q-010 and record the owner decision. 009-A needed none of them (entry review section 8).
- [x] Verify dependencies for 009-A: the 003 TokenSecretReference contract and provider rules, and the 004 secret, webhook and deduplication code (entry review section 2).
- [x] Prepare applicable contracts and synthetic data/permission examples: [entry review](entry-review.md), 2026-11-15.
- [x] Define independently reviewable local changes: slices 009-A to 009-D in the [plan](plan.md).
- [x] Record the owner decision on entry-review decisions D1-D10 for 009-A: D-048, with the [follow-up](entry-review-follow-up.md) at `54f733c`.
- [x] Implement 009-A: migration 0009, OAuth connect and reconnect, status, single-page synthetic sync, `401` handling, disconnect teardown, disposable PostgreSQL concurrency and isolation tests ([evidence](evidence.md)).
- [x] Correct the pre-publication findings R009-01 to R009-07 and the correction review findings R009-08 to R009-10 with maintained regressions ([evidence](evidence.md#correction-review-corrections-2026-11-17)).
- [x] Verify 003 case D3 for the synthetic provider: revocation at the mock provider, destroyed secret material, scoped purge before `purge_due_at`, honest `failed` or `unsupported` outcomes; the other clients keep syncing.
- [x] Prepare and approve 009-B (synchronization), 009-C (coverage and provenance) and 009-D (provider webhooks): [decision packet](decision-packet-009bcd.md), D-049 (2026-11-17).
- [x] Verify (009-A): OAuth callbacks validate state and reject replay; tokens appear in neither the browser nor logs, and PKCE applies where required by the flow.
- [x] Verify (009-A): Expired or revoked tokens produce an explicit disconnected state and stop affected ingestion without disrupting other clients.
- [ ] Verify: 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records. The `401` part is verified in 009-A; backoff and crash recovery at the page/checkpoint boundary are 009-B.
- [ ] Verify: Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states. 009-A exposes status and last successful sync only; the rest is 009-C.
- [x] Update documentation, limitations, and untested assumptions for 009-A (entry review section 9, [connector guide](../../docs/engineering/connectors.md)).
- [ ] Present a reviewable result to the owner.
- [ ] Obtain owner review and upload approval, then push and create or update a PR (D-012).
- [ ] Record owner acceptance before progressing to dependent work.
