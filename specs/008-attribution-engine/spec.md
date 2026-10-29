# 008-attribution-engine — Lead and revenue attribution engine
Status: Draft; implementation is not approved. Level: L3. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-032,034,035(partial),041,042,069. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Propose First Click, Last Click, and Linear models with configurable lookback windows, direct/unknown rules, model versions, reprocessing, and refund handling.

## Out of scope
Causal claims, AI attribution, or independent view-through attribution without verified access to supporting evidence.

## Acceptance criteria
1. For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
2. With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
3. Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
4. Recalculating identical inputs with the same model version produces identical results; model changes preserve history.

## Required design contracts
AttributionRun, ModelVersion, CreditAllocation, and EvidenceClass; distinguish lead credit from revenue credit.

## Dependencies and open decisions
Dependencies: [007-revenue-ledger](../007-revenue-ledger/spec.md)

Open decisions: Q-007. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
