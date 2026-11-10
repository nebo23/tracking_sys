# 005-links-tracker — Links, UTM parameters, and website tracker
Status: Draft; entry review refreshed against merged specification 004 on 2026-11-10 under D-032. Implementation is not approved. Level: L2. Prepared: 2026-10-28. See the [entry review](entry-review.md) for the implemented baseline, inherited contracts and next decisions.

## Sources
PDF-003,015,016,024; PDF-001,008. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Define per-content links, a URL registry, UTM templates, a branded-domain plan, redirects, a JavaScript tracker for client websites, and a form-field allowlist.

## Out of scope
Automatic social content publication or editing, and a complete WhatsApp forwarding tree.

## Acceptance criteria
1. A test link reaches its destination and preserves content/campaign provenance without exposing personal information in the URL.
2. Disallowed destinations, unsafe protocols, and redirect loops are rejected; link management requires client permission.
3. Analytics failure does not break redirects; bots and prefetch requests are not automatically counted as qualified human clicks.
4. Custom domains require ownership verification; implementation verifies TLS and slug conflicts.

## Required design contracts
Link, ContentReference, Campaign, and DomainVerification; the browser tracker is separate from the React application.

## Dependencies and open decisions
Dependencies: [004-event-collection](../004-event-collection/spec.md)

Specification 003 obligations (D-025): apply the never-collect form rules and URL minimization (`app.privacy.collection`) in the tracker before any identifying request (E1), under J1 strict opt-in; verify 003 cases C4 and M4 end to end.

Open decisions: Q-001, Q-002, Q-003. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
