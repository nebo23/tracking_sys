# Independent review of the Spec 005 corrections

**Request changes before merge.** All eleven original regression scenarios pass on the corrected branch. Additional checks identified three privacy blockers and four other defects in the tracker and its installation example.

Reviewed on 2026-11-11. The open [pull request](https://github.com/nebo23/tracking_sys/pull/4) and clean local worktree both pointed to `9c49d89af8ffb4568139f3b66f37a14dea455fa1`. The correction range starts at `14e8288`. References below use line numbers at the reviewed head. The earlier [review](pull-request-review-2026-11-11.md) records the original behaviors.

## R005-12 · P1 · An unavailable resume re-enables withdrawn consent

`packages/tracker-js/src/tracker.js:520` widens the host's allowed purposes before the asynchronous state read succeeds. At line 616 a confirmed withdrawal leaves the old server grant in the in-memory permission map. Together these allow an event through while the collector's recorded state is withdrawn.

In both Chromium and Firefox, grant analytics, withdraw analytics and wait for confirmation. On the same tracker, call resume with a host-reported analytics grant and return 503 from the consent-state read. Resume reports `unavailable`. A subsequent page view reports `queued` and the loopback collector receives one HTTP event request. Its consent record still says `withdrawn`. The synthetic grant response included a valid server time and expiry. A separate deterministic Node check produced the same result. This proves transmission from the browser. Production database persistence was outside this diagnostic.

Invalidate a purpose's cached server approval when it is withdrawn. Keep newly widened permissions suspended until a current, successful consent response confirms them. Test pending, failed and superseded reads on an already active tracker and assert on outgoing HTTP requests.

## R005-13 · P1 · Response latency extends the server's consent deadline

`packages/tracker-js/src/tracker.js:387` adds the remaining grant lifetime measured at the server to the **arrival time** on the client. Delivery time is consequently added to the period during which capture and sends are allowed.

With the injected clock, the collector prepared a valid consent-state response with one second left on the analytics grant. Delivering it 2.5 seconds later still allowed a page-view request, 1.5 seconds after the authoritative expiry. The committed expiry tests deliver the server snapshot immediately.

Carry a conservative request-start time through grant, resume and refresh, accounting for elapsed transport time while translating the server deadline. Never widen permission on invalid deadline data. Check both event capture and retries for analytics and attribution when the response arrives close to or after expiry.

## R005-14 · P1 · Page restoration sends the subject token after full withdrawal

The persisted `pageshow` listener at `packages/tracker-js/src/tracker.js:919` calls `refresh()` when a token is present. The guard at line 557 checks the token and local lifetime. A successful withdrawal of all purposes clears the host permissions and session record but retains the in-memory token.

In the page-lifecycle harness, grant analytics, confirm a full withdrawal, then dispatch a persisted page restore. With zero enabled purposes, the tracker made one background consent-state request containing the subject token. No explicit grant, resume or erasure was requested.

Require current host permission before background state reads. Keep access needed for explicit erasure separate from permission for automatic traffic. Assert that page restore after full withdrawal produces zero identifying requests and that explicit erasure still works.

## R005-15 · P2 · GPC reconciliation can permanently stop after a transient failure

At `packages/tracker-js/src/tracker.js:402`, the tracker marks a purpose as reconciled before the server confirms the withdrawal. The set also spans later grants and subjects in the same tracker instance.

Start with a granted sale/share purpose, enable GPC and let the three withdrawal attempts receive 503. After recovery, a successful state refresh returned the still-granted purpose. The tracker sent zero further withdrawals, even though local permissions excluded sale/share. A second test confirmed the same divergence after a successful GPC cycle, an explicit regrant with GPC off, and a second activation of GPC. No advertising provider was contacted.

Track pending and confirmed reconciliation for the current subject and grant. When a subsequent authoritative response still reports a prohibited grant, allow bounded reconciliation after recovery. Test temporary failures and two distinct grant cycles.

## R005-16 · P2 · An in-flight event can be retried across a withdrawal

At `packages/tracker-js/src/tracker.js:311`, queue purging skips in-flight items entirely. When a purpose is subsequently regranted before the request finishes, its old item passes the current-permission check.

Hold a page-view request containing a synthetic click identifier, withdraw attribution and confirm, then explicitly regrant it. Return 503 for the held request. The tracker transmitted the original ID and bytes again. Permission was active again at retry time, but the earlier withdrawal was supposed to invalidate that item's retry eligibility permanently.

Mark affected in-flight items as ineligible for future attempts when a purpose narrows. The already-issued request can finish. Assert that fresh post-grant events work and the pre-withdrawal request gets no retry.

## R005-17 · P2 · A pending consent-state refresh can retain expired queue entries

The event fetch now has an abort deadline. The queue pump can also wait at `packages/tracker-js/src/tracker.js:844` for a control fetch with no deadline.

Queue an event 57 seconds after confirmation. Have its first attempt return 503 with a five-second retry delay. At retry time a fresh state read is required. Hold that read. At 65 seconds after enqueue the item was still retained. After a successful separate grant and a fresh capture the queue contained two items and only the first HTTP event request had been issued.

Bound the wait for state refresh, release the pump after timeout, and expire retained payloads within the configured lifetime. Preserve normal navigation and permission checks. Test recovery with a fresh event when a stale state read is still outstanding.

## R005-18 · P2 · The installation example fails when session storage is blocked

The same-origin initializer fixes the previous CSP issue. At `packages/tracker-js/examples/install.js:26`, the example banner directly reads sessionStorage. Its consent, withdrawal and erasure handlers also use storage directly.

With the repository's blocked-session-storage browser fixture, the exact shipped page raised `SecurityError` and the consent banner stayed hidden in both Chromium and Firefox. This happens before the user can reach the tracker's supported in-memory fallback.

Make the example's own choice storage tolerate access and write failures. Ensure that an optional persistence failure cannot prevent withdrawal or erasure. Exercise the shipped files in both browsers with storage access denied and with writes failing.

## Verification

| Check | Independent result |
|---|---|
| Full backend suite with PostgreSQL integration and browser journey enabled | 616 passed in 221.96 seconds, no skips or warnings reported in this run |
| Tracker Node suite | 36 passed |
| Chromium and Firefox browser suite | 24 passed, including the normal installation example |
| Ruff lint and formatting | Passed, 100 files already formatted |
| pip check and correction diff whitespace check | Passed |

The original fixes for SPA link provenance, event-fetch timeout, CSP, DNS/TLS deadline sharing and service-target canonicalization passed their direct tests. The other original tests also pass, including the expired-local-token erasure case and the partial-withdrawal race. The additional sequences above identify where the broader consent, retry and integration requirements still fail.

Verification used the project virtual environment, synthetic credentials, local browsers and a dedicated disposable PostgreSQL database on loopback port 55433. The test runner removed its container, volume and network. The independent browser diagnostics used a synthetic collector, and the expiry and retry timing diagnostics used the repository's injectable clock. Live customer infrastructure and native database rollout remain outside the review.
