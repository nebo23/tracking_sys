# 014-ad-spend-capi — Advertising spend and conversion delivery
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
PDF-058,059,062. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Select an initial advertising platform; ingest spend and campaign/ad identifiers, deliver conversions through an outbox, and reconcile deduplication, consent, and errors.

## Out of scope
Supporting every advertising platform simultaneously, editing budgets, syncing audiences, or guaranteeing improved ROAS.

## Acceptance criteria
1. Rerunning spend ingestion does not duplicate totals and handles revisions, timezones, and currencies.
2. Only verified conversions with required consent enter the delivery outbox; a browser signal alone does not prove payment.
3. Retries do not create a semantically duplicate conversion; provider rejections have recorded resolution paths without endless retry loops.
4. ROAS identifies its model, period, and currency; zero spend does not produce a misleading infinite value.

## Required design contracts
AdAccount, SpendFact, ConversionDelivery, and ProviderAcknowledgement; separate read and write permissions.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md), [008-attribution-engine](../008-attribution-engine/spec.md)

Specification 003 obligations (D-025): check consent and tombstones at enqueue and again at the delivery claim (E4, E5) with the Meta, LinkedIn, and Google Ads rows re-verified; verify 003 cases C2, C3, C5, and outbound replay blocking end to end.

Open decisions: Q-001, Q-004, Q-010, Q-012; initial advertising provider. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
