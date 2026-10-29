# 012-linkedin — LinkedIn analytics
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER LinkedIn. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Support organization or member analytics according to verified program access, with pagination, account grants, API version headers, and deprecation tracking.

## Out of scope
Assuming personal analytics is always prohibited or available to every application; publishing and messaging are outside this specification.

## Acceptance criteria
1. Record the organization/member scope decision and verify Community Management access before launch.
2. Do not collect from unauthorized accounts; revoked grants prompt reconnection and stop affected collection.
3. API version changes do not silently change metric semantics; contract fixtures cover unavailable and empty responses.
4. Document tier, role, and historical-coverage limits using an authorized test connection.

## Required design contracts
Separate member and organization capability types; complete field mappings after the access feasibility check.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md)

Open decisions: Q-001; account type and program approval. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
