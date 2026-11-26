# 008-attribution-engine — Lead and revenue attribution engine
Status: 008-A, the synthetic calculation slice, is implemented under D-046 with the Q-007 choices of the [entry review](entry-review.md), corrected under D-047 and merged in PR 7 at `3f6dc06`; see the [evidence](evidence.md). 008-B, persisted attribution with the identity integration and the Q-007 production defaults of the [008-B entry review](entry-review-008b.md), is implemented under D-079 and merged in PR 16 at `f15b6e4` after Claude's [merge review](merge-review-008b.md); see the [design note](design-008b.md) and the [008-B evidence](evidence-008b.md). Level: L3.

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
D-046 (2026-11-15) approves the 008-A synthetic slice and its Q-007 rules. D-078 (2026-11-25) prepares 008-B, and D-079 (2026-11-25) approves its decisions D1-D14 as recommended, with Linear as each client's default, and its implementation and pull request. Merge, 016-B/C, native rollout, live providers and deployment need their own decisions.
