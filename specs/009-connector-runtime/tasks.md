# Tasks: 009-connector-runtime
Status: 009-A to 009-D implemented against the synthetic provider (D-048, D-049), with review findings R009-01 to R009-10 and verification finding R009-11 corrected; D-050 authorizes merging PR 8 after verification. This is a review checklist, not an implementation instruction.

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
- [x] Implement 009-B (D-049 decisions D11-D15, D20): migration 0010, run kinds and windows, attempt-fenced checkpoints, the provider error policy, usage reservation with daily limits, the scheduling step ([evidence](evidence.md#009-b-synchronization-2026-11-17)).
- [x] Verify: 429 responses respect provider backoff; 401 responses trigger reconnection; crash recovery resumes without duplicate records. `401` in 009-A; backoff, retry limits and restart at the page/checkpoint boundary in 009-B.
- [x] Implement 009-C (D-049 decisions D16, D17, D20): migration 0011, coverage and record reads with explicit metric states and provenance ([evidence](evidence.md#009-c-coverage-and-provenance-2026-11-17)).
- [x] Verify: Every connection exposes explicit metric availability, last synchronization, historical coverage, and cost states (009-C).
- [x] Implement 009-D (D-049 decisions D18-D20): migration 0012, signed provider webhooks with deduplicated, scoped effects and 7-day delivery records ([evidence](evidence.md#009-d-provider-webhooks-2026-11-17)).
- [x] Update documentation, limitations, and untested assumptions for 009-A to 009-D (entry review section 9, [decision packet section 6](decision-packet-009bcd.md#6-implementation-reconciliation), [connector guide](../../docs/engineering/connectors.md)).
- [x] Present a reviewable result to the owner: [PR 8](https://github.com/nebo23/tracking_sys/pull/8), 2026-11-17.
- [x] Obtain upload approval, then push and create the PR: D-049 authorized the push and pull request after verification; [PR 8](https://github.com/nebo23/tracking_sys/pull/8).
- [x] Verify the complete branch before merge and correct verification finding R009-11 (each synchronization step reads the clock when it happens) with a maintained regression (D-050, [evidence](evidence.md#verification-before-merge-and-correction-r009-11-2026-11-17)).
- [x] Record owner acceptance before progressing to dependent work: PR 8 merged at `4abcbc6` under D-050 (2026-11-17). This is repository acceptance, not production sign-off.
