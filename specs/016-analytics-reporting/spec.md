# 016-analytics-reporting — Analytics queries and client reporting
Status: D-072 approved D1-D12; slice 016-A is implemented and verified (see the [evidence](evidence.md)); 016-B, attribution reports, is approved in its [entry review](entry-review-016b.md) (D-089) and ready to implement under its [implementation handoff](implementation-prompt-016b.md); 016-C remains open. Level: L5. Prepared: 2026-10-28. Updated: 2026-11-26.

The [entry review and decision packet](entry-review.md) proposes 016-A over existing stored facts, then 016-B attribution reporting and 016-C retained/scheduled reports. Read the [design](design.md), [verification matrix](verification-matrix.md) and [conditional handoff](implementation-prompt.md). D-072 approved D1-D12 as recommended on 2026-11-22, and the [reporting guide](../../docs/engineering/reporting.md) describes the implemented 016-A routes. This progression does not change the multi-agency social analytics and attribution launch requirement.

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
Dependencies: [006-identity-journey](../006-identity-journey/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md), [008-attribution-engine](../008-attribution-engine/spec.md), [010-instagram](../010-instagram/spec.md), [011-youtube](../011-youtube/spec.md), [012-linkedin](../012-linkedin/spec.md), [013-x](../013-x/spec.md), [014-ad-spend-capi](../014-ad-spend-capi/spec.md), [015-business-integrations](../015-business-integrations/spec.md). Specs 012/013 remain deferred under D-063. The proposed 016-A uses stored 010/011/014/015 facts; real journey/attributed-revenue reporting waits for 006 implementation, 007-B/C and persisted 008 integration. Retained/scheduled reports require their own lifecycle and delivery decisions, with 017/018/020 dependencies as applicable.

Specification 003 obligations (D-025): invalidate caches and revoke exports covered by deletion requests, and verify the cache and export part of 003 acceptance criterion 3.

Open decisions: Q-001, Q-004, Q-006, Q-007, Q-011 and Q-012. See the [decision register](../../docs/planning/decisions.md). The packet proposes bounded development behavior only; it does not settle unrelated production scope, budgets, attribution defaults or retention.

## Owner approval
D-071 records the owner's request to begin Spec 016 as preparation under the existing review workflow. D-072 (2026-11-22) approves D1-D12 as recommended and authorizes 016-A only; a pull request and merge need separate owner authorization. Direct CSV in 016-A does not satisfy all of acceptance criterion 5: retained download URLs and deletion-driven revocation remain open in 016-C.
