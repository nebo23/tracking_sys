# 014-ad-spend-capi — Advertising spend and conversion delivery
Status: Implemented for review under D-063 and D-064: 014-A (spend ingestion), 014-B (conversion delivery), 014-C (ROAS contract) and 014-D (live Meta adapters, off by default) against synthetic Meta-shaped providers and fixture tests, with no live Meta call; see the [evidence](evidence.md), the [design note](design-014.md) and the [advertising guide](../../docs/engineering/advertising.md). The merge is the owner's decision. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

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

## Acceptance evidence
1. **AC1** (re-reads, revisions, time zones, currencies): T-01 to T-10 in `backend/tests/integration/test_ad_spend.py` and the pure cases in `backend/tests/test_advertising_spend.py`. The unique fact key, exact parsing, per-currency totals and `finance:read` are each backed by a caught mutation check.
2. **AC2** (only verified conversions with consent): T-20 to T-25 and T-35 in `backend/tests/integration/test_conversion_delivery.py`, with 003 C2, C3, C5 and outbound replay blocking end to end. Purchase signals and manual declarations never post in the ledger and are never enqueued; consent and tombstones are checked at enqueue (E4) and again at the claim (E5).
3. **AC3** (no duplicates, recorded resolution paths): T-26 to T-33 in the same file. Deterministic event IDs, the attempt cap and deadline, the requeue limit and dismissal, lease fencing and acknowledgements per attempt.
4. **AC4** (ROAS labels, zero spend): T-40 to T-47 in `backend/tests/test_advertising_roas.py` and `backend/tests/integration/test_roas.py`. Rows name their model, version, window, period, currency and basis; zero spend gives no value (`zero_spend`), and a currency mismatch none either.

## Required design contracts
AdAccount, SpendFact, ConversionDelivery, and ProviderAcknowledgement; separate read and write permissions.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md), [007-revenue-ledger](../007-revenue-ledger/spec.md), [008-attribution-engine](../008-attribution-engine/spec.md)

Specification 003 obligations (D-025): check consent and tombstones at enqueue and again at the delivery claim (E4, E5) with the Meta, LinkedIn, and Google Ads rows re-verified; verify 003 cases C2, C3, C5, and outbound replay blocking end to end. Under D-063 only the Meta row is re-verified; the LinkedIn and Google Ads rows stay stale and block their features until those providers are built.

Open decisions: Q-001, Q-004, Q-010, Q-012. The initial advertising provider is Meta (D-063). See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-063 (2026-11-20) chose Meta as the initial provider and a completion against synthetic providers and fixtures; D-064 (2026-11-20) approved decisions D1-D14 of the [entry review](entry-review.md) and authorized the implementation. Live checks (014-E, 014-F), Meta review and verification (014-G), the browser-field decision of D8, native migration, merge and deployment remain separate decisions.
