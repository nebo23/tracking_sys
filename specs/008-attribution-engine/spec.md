# 008-attribution-engine — Lead and revenue attribution engine
Status: 008-A, the synthetic calculation slice, is implemented locally under D-046 with the Q-007 choices of the [entry review](entry-review.md); see the [evidence](evidence.md). Production defaults, persistence and identity integration remain open. Level: L3.

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
D-046 (2026-11-15) approves the 008-A synthetic slice and its Q-007 rules. Production defaults, persistence, identity integration, publication and later slices need their own decisions.
