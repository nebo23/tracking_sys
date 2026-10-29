# 013-x — X analytics
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER X/Twitter. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Retrieve account/post metrics under verified paid access; distinguish public and private metrics, historical windows, and per-client budgets.

## Out of scope
Assuming a free unlimited API or applying an owned-read discount to every agency client.

## Acceptance criteria
1. Credit and usage budgets cap collection and explain any stop to the user, preventing uncontrolled spending.
2. Private-metric permissions and history are verified on an authorized account; data outside the permitted window is unavailable.
3. Synchronization uses verified checkpoints and retry behavior without retrieving the entire history on every cycle.
4. Recheck pricing definitions and access entitlements before release.

## Required design contracts
Public/private metric distinction, provider cost ledger, and rate-limit metadata.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md)

Open decisions: Q-001, Q-004; X budget and entitlement. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
