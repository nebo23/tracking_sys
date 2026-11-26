# Plan: 008-attribution-engine
Status: Slice 008-A implemented under D-046 with no new dependencies, corrected under D-047 and merged in PR 7 at `3f6dc06`; see the [evidence](evidence.md). Slice 008-B (persisted attribution) implemented under D-079 in phases P0-P5 with no new dependency and the additive migration `0029`; see its [design note](design-008b.md) and [evidence](evidence-008b.md).

## Expected outcome
Propose First Click, Last Click, and Linear models with configurable lookback windows, direct/unknown rules, model versions, reprocessing, and refund handling.

## Design before implementation
- AttributionRun, ModelVersion, CreditAllocation, and EvidenceClass; distinguish lead credit from revenue credit.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-007.

## Proposed review slices
1. Review contracts, schema proposals, synthetic fixtures, and approved acceptance cases.
2. Implement the smallest approved end-to-end slice with appropriate observability.
3. Verify failure, permission, and recovery behavior; update documentation and review evidence.

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [x] For touchpoints A then B and revenue of 100, the approved models produce First: A=100; Last: B=100; Linear: A=50 and B=50.
- [x] With no eligible touchpoint, unknown receives 100; total allocated credit equals eligible net revenue exactly after rounding.
- [x] Fixtures define expected results for window boundaries, timezones, timestamp ties, refunds, and late events.
- [x] Recalculating identical inputs with the same model version produces identical results; model changes preserve history.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage. For 008-B: migration `0029` refuses a downgrade while attribution rows or its audit values exist; a client's attribution is rebuilt from the published ledger and the identity journey by the worker (a new model set, ledger generation or pruned feed rebuilds it), and the native `tracking_sys` rollout of 0005 to 0029 needs its own decision.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
