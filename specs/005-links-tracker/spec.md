# 005-links-tracker — Links, UTM parameters, and website tracker
Status: Approved for local implementation by D-033 (2026-11-10): the recommended D1-D10 options and design revision 1 prepared at `a909990`. Slices 005-B to 005-E are implemented and verified locally on `codex/spec-005-links-tracker`; see the [evidence](evidence.md) for the tested tree, results and limitations. Published for review under D-034 (pull request against `main`); not merged. Level: L2. Prepared: 2026-10-28. The entry review was refreshed against merged specification 004 on 2026-11-10 under D-032.

Design revision 1, the [D1-D10 decision packet](decision-packet.md), and the [verification matrix](verification-matrix.md) are approved by D-033 for local and disposable environments. Publication, merge, native rollout, live intake, domain purchases, DNS changes, certificate issuance and deployment remain separately gated.

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
D-033 (2026-11-10): the owner approved the recommended D1-D10 options and design revision 1 prepared at `a909990`, and authorized implementation of 005-B to 005-E with local and disposable environments only. D-032 remains the record of the preparation-only phase; its restriction is superseded for this scope only.
