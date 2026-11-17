# Independent review of Spec 005 and PR 4

**Request changes before merge.** The tracker can transmit data after permission has been narrowed or has expired. The installation example also fails to start in both tested browsers.

Reviewed on 2026-11-11. GitHub PR 4 was open at `14e8288c1a140cdc6de52535d5540c66a26ab3c9`, targeting `main` at `e8ef587eb4df39f9f0bf1b31421d0a672388e9dd`. The local clean worktree, published branch and PR head matched. The implementation is governed by D-033 and the D1–D10 packet at `a909990`. [Pull request](https://github.com/nebo23/tracking_sys/pull/4)

Locations below are relative to the reviewed head. The review covered managed-link policy, administrative scope and redirects, migration and grants, event provenance, consent-state, tracker behavior, domain verification, installation, and the agreed test matrix. Findings describe the observable behavior of this revision.

## Consent and outbound requests

**R005-01 · P1 · A retry transmits a click identifier after attribution withdrawal.** In `packages/tracker-js/src/tracker.js:576`, the queue records the event's primary purpose. A page view requires analytics, but its serialized URL can also depend on attribution. With both granted, a page view containing a synthetic `gclid` received a retryable 503. After confirmed withdrawal of attribution, its retry still contained that identifier. Only analytics remained in local permissions. The diagnostic observed request bytes at the tracker transport boundary. Server-side filtering happens after transmission. Record all permissions needed by the serialized content, and discard affected items on withdrawal, refresh or resume. A retry must retain its original ID and bytes or be dropped. Add a test for queued and retrying page/link URLs following partial withdrawal.

**R005-02 · P1 · The host can deny analytics and still get a new outgoing event.** At `packages/tracker-js/src/tracker.js:405`, calling `resume` with only denied choices returns immediately. On an already active tracker it reported `blocked`, then `trackPageView()` returned `queued` and made one event request. Suspend permissions excluded by the host synchronously, invalidate relevant pending results and purge affected queue entries. A failed or pending server read must also respect the latest local permission ceiling. Test an active tracker that transitions from granted to denied or to a narrower set, including an unavailable state read.

**R005-03 · P1 · Per-purpose server expiry is ignored before capture.** At `packages/tracker-js/src/tracker.js:428` and in `refresh()`, the tracker consumes the granted states but uses the local session deadline for permission checks. A synthetic consent-state response reported a grant expiring in one second. Two seconds later, before the next refresh, a new page view was queued and sent. Apply each server deadline to capture and retries using the returned server time, including optional fields that require attribution. Ensure fresh-grant initialization can establish any relevant earlier deadline. Test analytics expiry and attribution expiry independently and assert on outgoing bytes.

**R005-04 · P2 · An expired local token continues to be sent for state refreshes.** At `packages/tracker-js/src/tracker.js:438` and `:808`, refresh can send the token after its fixed 24-hour local lifetime. With a hidden tab advanced beyond expiry and then made visible, the tracker reported `collecting: false` but sent a consent-state request containing the expired local token. Successful refresh can persist the expired record again and schedule further refreshes. Enforce the deadline before background reads, clear expired tracking state and cancel scheduled refreshes. Test visibility changes and page restoration after the deadline, while preserving explicit user-requested erasure handling.

**R005-05 · P2 · A partial withdrawal can revoke unrelated analytics permission.** At `packages/tracker-js/src/tracker.js:369`, a superseded grant compensates by withdrawing every purpose reported as granted. Start with analytics granted, request attribution, withdraw attribution while that request is pending, then deliver the grant response. The server fixture ended with analytics and attribution both withdrawn, while the tracker still listed analytics as granted. Reconcile against the latest intended choices and revoke only the affected purposes. Test the final server state, local state and a subsequent legitimately permitted analytics event.

**R005-06 · P2 · Previously granted purposes can survive a GPC refusal in local state.** At `packages/tracker-js/src/tracker.js:387`, the tracker adopts the full consent response. With an existing sale/share grant, enabling GPC and submitting analytics plus sale/share made the tracker report sale/share as both refused and enabled. The server fixture retained the grant. Intersect effective permissions with current GPC restrictions on each relevant transition. Reconcile the affected server choices according to the approved denial behavior. Test a change in the signal on an existing subject. This observation concerns consent state; the diagnostic did not involve an advertising provider.

## Provenance, transport and integration

**R005-07 · P2 · SPA navigation can attribute a page view to the preceding managed link.** At `packages/tracker-js/src/tracker.js:528`, the first `ts_link` is cached for the instance lifetime. Two explicit page views on different SPA routes, each with a distinct valid link UUID, both sent the first UUID. Derive the reference from the consent-permitted capture URL for each new event, or invalidate it when the route changes. Keep retries immutable. Test two link arrivals and a first route without a reference followed by a linked route.

**R005-08 · P2 · A stalled request blocks the event queue beyond its TTL.** At `packages/tracker-js/src/tracker.js:678` and `:736`, a fetch can remain pending while the only pump waits for it. With one pending request and another queued, after 61 seconds both remained and no TTL drop was recorded. A fresh capture grew the queue to three with only the first request sent. Bound the wait by the event's remaining lifetime, release the queue on timeout and preserve event IDs on eligible retries. Verify continued delivery of a fresh event after a stalled send, including cleanup of expired payloads. Existing tests cover the effect on navigation.

**R005-09 · P2 · The published installation example blocks its own initializer.** The policy at `packages/tracker-js/examples/install.html:13` disallows the inline module at line 40. Serving the exact committed example through an intercepted synthetic site produced a CSP diagnostic, zero module requests and a hidden consent banner in both Chromium and Firefox. Move the initializer into a same-origin module and retain the restrictive policy. Exercise the shipped example itself in browser tests and assert the banner opens, the module loads and an explicit grant can proceed.

## Domain verification

**R005-10 · P2 · The five-second total deadline is reused across blocking operations.** In `backend/app/links/verification.py:198`, A and AAAA each receive the full remaining timeout. With a simulated clock and injected DNS responses consuming four seconds per query, both queries received five seconds and the verifier reported failure after eight simulated seconds. At line 222, TCP connect and the following TLS handshake also reuse the original timeout. Pass one absolute monotonic deadline through the adapters and recalculate before each blocking operation. Verify elapsed budgets for both DNS subqueries and for connect plus handshake. The timing diagnostic used no external DNS/TLS operation.

**R005-11 · P3 · A valid mixed-case service target fails routing verification.** In `backend/app/config.py:229`, validation discards the canonical hostname, while `backend/app/links/verification.py:141` compares the normalized CNAME to the original setting. Identical synthetic answers verified for a lowercase target and returned `routing_mismatch` for its uppercase spelling. Store or compare the canonical target and test both configurations.

## Verification performed

| Check | Independent result |
|---|---|
| Backend suite, project virtual environment, PostgreSQL and browser journey enabled | 611 passed in 224.76 seconds, no skips reported |
| Tracker Node suite | 24 passed |
| Tracker browser suite | 20 passed across Chromium and Firefox |
| Ruff lint and formatting | Passed, 100 files already formatted |
| pip check and implementation diff whitespace check | Passed |
| Additional diagnostics | Observed each behavior above using the published code, synthetic inputs, the instrumented tracker transport, real browsers for the installation example, and injected clocks/resolvers for the domain checks |

The backend run used a fresh PostgreSQL Compose project on loopback port 55433, the database `tracking_foundation_test`, separate database roles and generated synthetic secrets. The worktree contained no .env file. The dedicated database container, network and volume were removed after the suite. Native tracking_sys was outside the verification environment. Browser journey results used loopback services and synthetic domain proofs. Live customer DNS, public certificate issuance, production deployment, external provider behavior and load capacity remain unverified.

For the next review, exercise the new consent cases against the actual transport, rerun the existing backend, Node and browser suites, and smoke-test the corrected installation page in both engines. The standalone diagnostics in this review used synthetic harnesses. Permanent regression coverage belongs with the implementation corrections.
