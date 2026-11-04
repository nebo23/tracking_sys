# 016-analytics-reporting — Analytics queries and client reporting
Status: Draft; implementation is not approved. Level: L5. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-038,065,067,068,069,070,071,073,097; USER combined dashboard. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Provide query APIs that clearly present social metrics alongside journey/revenue data, filters, leaderboards, freshness, exports, and proposed basic reports.

## Out of scope
A complete custom dashboard builder, unsourced benchmarks, or treating reach summed across platforms as unique people.

## Acceptance criteria
1. Every report enforces tenant, client, and field permissions, including exports and background generation.
2. Social metrics show platform definitions, ranges, and freshness; revenue shows currency, model, attribution window, and evidence.
3. Pagination, filters, date boundaries, timezones, and comparisons match reference fixtures.
4. Partial synchronization, unsupported metrics, and currency mismatches are not displayed as zero or complete totals.
5. Export URLs are short-lived and authorized; client deletion invalidates accessible reports according to policy.

## Required design contracts
Read models, aggregation provenance, and report snapshot schemas; identify non-additive metrics explicitly.

## Dependencies and open decisions
Dependencies: [008-attribution-engine](../008-attribution-engine/spec.md), [010-instagram](../010-instagram/spec.md), [011-youtube](../011-youtube/spec.md), [012-linkedin](../012-linkedin/spec.md), [013-x](../013-x/spec.md), [014-ad-spend-capi](../014-ad-spend-capi/spec.md), [015-business-integrations](../015-business-integrations/spec.md)

Specification 003 obligations (D-025): invalidate caches and revoke exports covered by deletion requests, and verify the cache and export part of 003 acceptance criterion 3.

Open decisions: Q-001, Q-006, Q-007, Q-011. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
