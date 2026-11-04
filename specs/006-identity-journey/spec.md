# 006-identity-journey — Lead identity and customer journey
Status: Draft; implementation is not approved. Level: L2. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-027,028,029,030; PDF-050(partial). See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Represent anonymous visitors, leads, and customers; support deterministic identity linking, sourced event timelines, and auditable merge/unmerge actions.

## Out of scope
Fingerprinting, IP-based identity merging, and claims to identify every viewer.

## Acceptance criteria
1. Anonymous visits link to a verified identity only within the same client and under applicable consent.
2. Shared or conflicting email addresses and phone numbers do not automatically merge people without an established policy.
3. Switching users on a shared device does not silently transfer one person's visits to another.
4. Merge/unmerge preserves provenance and recalculates attribution without losing the original evidence.

## Required design contracts
IdentityKey, Subject, IdentityLink, and Touchpoint; define normalization, versioning, and ambiguity policies.

## Dependencies and open decisions
Dependencies: [005-links-tracker](../005-links-tracker/spec.md)

Specification 003 obligations (D-025): build subject keys from `app.privacy.deletion` (canonical identifiers, per-client keys), require the identity_link purpose (E3), and verify that deletion and unmerge remove identity links; review the candidate phone trunk-zero rule.

Open decisions: Q-002, Q-008, Q-012. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
