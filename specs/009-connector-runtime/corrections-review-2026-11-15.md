# Spec 009-A correction review

Reviewed `2d0ac21` on `codex/spec-009-connector-runtime` against D-048 and the [first independent review](pre-pr-review-2026-11-15.md). The seven regression tests introduced by that correction passed. Three additional synthetic cases failed. The owner's request made publication and merge conditional on a successful review.

## Findings

| Finding | Observed on the reviewed commit | Acceptance criterion for the correction |
|---|---|---|
| R009-08 · High · Two valid reconnects can leave an active connection unusable | Two authorizations initiated by the same Owner targeted the same connection generation. One completed while the other was between its generation check and its secret lookup. The successful callback installed a new grant. The delayed callback revoked that grant and returned `connection_changed`. The connection still reported `active` and its stored credentials were unusable at the mock provider. In `_settle_previous`, the connection check and the selection of live secret rows are separate reads. | Capture the connection generation and the exact eligible secret version IDs consistently. An outdated callback must never revoke versions installed by its successor. Exercise overlapping callbacks with independent sessions and verify both the public connection state and a fresh provider read using the installed grant. Retain cleanup of the discarded callback's own grant. |
| R009-09 · High · A rejected reconnect can revoke the original account's grant | A valid Owner selected a different synthetic account. The callback returned `account_mismatch` and disposed of the new grant, but the previously usable grant for the original account was also revoked. `complete_authorization` calls `_settle_previous` before `_install` checks the external account, current session, manager membership and client status. The existing mismatch test checks only grants created after the request began. | Validate the selected account, current authority, tenant and expected generation before revoking a retained grant. Preserve the install-time recheck. Verify that a rejected account choice leaves the previous grant and its recorded revocation outcome intact, and add equivalent denial assertions for loss of authority or client eligibility. |
| R009-10 · Medium · A late database purge can still report that it met its deadline | The provider completed before the deadline. In the controlled-clock test, deletion of the provider records finished after the deadline. The records were gone, but the public response still returned `deadline_met=true`. `run_teardowns` samples time before calling `_finalize`, before lock acquisition and deletion. | Measure completion after the purge work succeeds, in the transaction recording the outcome. Keep the original deadline stable. Cover a delay during provider revocation and a delay during database cleanup, including an accurately reported late completion. |

The affected implementation is in [the connector service](../../backend/app/services/connectors.py). At the reviewed commit the live versions are selected at line 573, previous-grant settlement is called at line 612, and the timestamp is passed into finalization at line 1228.

## Verification

- The full backend command `python -m pytest -q` passed 802 tests, including all 19 connector integration cases. Three opt-in Spec 005 browser journeys were skipped.
- Ruff lint and format checks passed for the backend. `git diff --check origin/main..HEAD` passed.
- Three additional review checks using the synthetic provider and a fresh disposable PostgreSQL 18.6 database failed independently as described above. The concurrency check controlled scheduling between the generation read and the version read. The timing check advanced an injected clock when the provider-record deletion completed.

Correct the three findings on this branch, include maintained regression tests for the expected outcomes and rerun the existing connector and backend suites before requesting publication verification. These findings concern the current synthetic 009-A scope.
