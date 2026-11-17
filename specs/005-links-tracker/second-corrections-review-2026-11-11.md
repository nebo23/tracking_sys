# Independent review of tracker 0.5.2 on PR 4

**Request changes before merge.** The seven previously reported scenarios have passing regressions. Additional checks found one identifying request that starts after a host denial, one ordering error that can disable collection after a successful grant, and two cases where Global Privacy Control (GPC) leaves a grant active at the collector.

Reviewed on 2026-11-11 at published head `f90b5272d9693955ec1d7ca7da6657f9a7403ae2` against the preceding review at `9c49d89`. The head worktree was clean. D-036 defines the scope. The implementation changes affect the tracker and its example. [PR 4](https://github.com/nebo23/tracking_sys/pull/4) · [Preceding review](corrections-review-2026-11-11.md)

## R005-19 · P1 · A queued resume transmits the subject token after a newer denial

In `packages/tracker-js/src/tracker.js:624-637`, the host choices are checked when resume is called. The serialized task can start later. It reads the token and takes a new state epoch when it starts, which lets an obsolete task issue its HTTP request after a newer host decision.

The independent loopback test exercised the published tracker in both Chromium and Firefox. Grant analytics and confirm a full withdrawal. Start a host-confirmed resume and hold its state response. Queue another resume. In a later browser turn, supply analytics denied and observe the returned blocked status. Record the HTTP request count at that point, then release the held response. **Each browser started one additional consent-state request carrying the subject token after the denial.** Each sent zero events. The transport issue is the token-bearing read itself.

Capture the applicable consent intent when enqueuing the operation. Recheck it immediately before accessing storage or sending a state request. Regression acceptance requires zero new token-bearing reads after denial while earlier work drains, plus a working explicit erasure and a later valid resume.

## R005-20 · P2 · An overlapping read can hide a successfully committed grant

At `packages/tracker-js/src/tracker.js:448`, an answer from a request with a lower start sequence is discarded. Request start order can differ from the order in which the collector observes changes.

After a confirmed withdrawal, hold the next explicit grant before the collector applies it. Start a refresh, which legitimately returns the older withdrawn state. Then let the grant commit and deliver its successful answer. In Chromium and Firefox the synthetic collector held analytics granted, while the tracker returned `nothing_granted` and blocked the next page view. With the deterministic clock, this divergence persisted beyond 65 seconds with zero pending timers. The same ordering arose with a page restoration triggering the read.

Coordinate authoritative writes and concurrent reads. One option is to serialize consent-state reads with writes and revalidate the caller's intent at execution time. Another is to perform a fresh read after a confirmed write when overlapping snapshots are ambiguous. A late response must still respect any newer local withdrawal. Test both processing orders, final server/local state and actual event delivery.

## R005-21 · P2 · A GPC-only choice can skip server withdrawal entirely

At `packages/tracker-js/src/tracker.js:557`, grant returns early when GPC filters out every requested grant. This path omits reconciliation of an existing subject's previously granted purpose. With sale/share as the only purpose, the host set also becomes empty and subsequent background refreshes cannot perform the reconciliation.

In the synthetic transport harness, grant sale/share, turn GPC on, then supply the sale/share choice again. The result was `nothing_sent`. After three minutes on the simulated clock, local permissions were empty, the server still held sale/share granted, and there had been zero further consent requests. This measures consent state and control traffic. No advertising integration was used.

Handle known, currently prohibited server grants on the all-filtered path, using the existing bounded withdrawal mechanism. Preserve the behavior for a new visitor with no known subject. Test both the previously granted sole-purpose case and an initially unknown visitor.

## R005-22 · P2 · A new grant inherits the previous grant's exhausted GPC retry budget

At `packages/tracker-js/src/tracker.js:480-487`, the round state uses subject and purpose as its key. An exhausted entry survives a subsequently confirmed withdrawal and a separate explicit grant on the same subject.

Exhaust three reconciliation rounds during a temporary outage. Once the collector recovers, turn GPC off, explicitly withdraw sale/share and verify the server reports withdrawn, then explicitly grant it again. Turn GPC back on, refresh, and advance the synthetic clock two minutes. The tracker disabled sale/share locally. The collector still reported granted and received zero withdrawal attempts for the new grant.

Keep the cap for consecutive failures of one grant, and give a genuinely new grant its own bounded reconciliation budget. Regression coverage should assert a real intervening server withdrawal, the distinct regrant, and the subsequent reconciliation request and final server state.

## Scope of verification

The previous R005-12 through R005-18 scenarios were exercised by running the published regression tests. They cover failed/stale reads after withdrawal, delayed replies past expiry, background reads after full withdrawal, GPC recovery and regrant, invalidating in-flight retries, queue TTL during stalled refresh, and example behavior when session storage is unavailable. The additional sequences above extend those checks to queued work and successive consent cycles.

The independent browser checks used the actual tracker and two loopback HTTP origins. The consent collector used scripted synthetic state and timing. The GPC and elapsed-time checks used the project's deterministic transport and clock. The full backend suite additionally exercises real PostgreSQL and the browser-to-API journey.

| Independent check on the published tree | Result |
|---|---|
| Backend pytest with database and browser journey enabled | 616 passed in 268.68 seconds. One Pydantic `UnsupportedFieldAttributeWarning` appeared in the concurrent invitation acceptance test. |
| Node unit suite | 47 passed |
| Browser suite with Chromium and Firefox | 30 passed, including the shipped example with storage available, blocked and unwritable |
| Ruff lint and formatting | Passed, 100 files already formatted |
| pip check and correction diff whitespace check | Passed |

The disposable PostgreSQL container, network and volume were removed after verification. Live domain operations and production rollout were outside this review.
