# 010-instagram — Instagram analytics
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER Instagram; PDF-024,041 context. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Connect supported accounts and retrieve profile/content insights under verified permissions; define metric catalogs, history, freshness, and a proposed read-only launch scope.

## Out of scope
Assuming personal accounts, messaging, and advertising share permissions, or promising to identify every viewer.

## Acceptance criteria
1. An authorized test-account feasibility check proves account type, OAuth scopes, and actual fields before the final contract is designed.
2. Account/media metrics match verified reference fixtures with period, source, and version; unsupported metrics are not displayed as zero.
3. Access failure, content deletion, and disconnection are explicit and apply the retention policy.
4. The interface makes no metric or historical-coverage claim unsupported by documentation and API responses.

## Required design contracts
A provider capability matrix is mandatory; do not invent final metric names.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md)

Open decisions: Q-001; exact Meta Insights metrics, access, and history require verification. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
