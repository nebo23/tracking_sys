# Plan: 014-ad-spend-capi
Status: Completed for review. The [implementation handoff](implementation-prompt.md) governed the approved implementation (D-064): Phase 0 sources ([entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0)), the [design note](design-014.md), slices 014-A to 014-D, and the verification recorded in the [evidence](evidence.md). D-063 starts the work with Meta as the initial provider; the [entry review](entry-review.md) proposed slices 014-A to 014-D and decisions D1-D14, which D-064 approved as recommended.

## Expected outcome
Select an initial advertising platform (Meta, D-063); ingest spend and campaign/ad identifiers, deliver conversions through an outbox, and reconcile deduplication, consent and errors. Achieved against synthetic Meta-shaped providers and fixture tests; live use is a follow-up.

## Design before implementation
- [x] AdAccount, SpendFact, ConversionDelivery and ProviderAcknowledgement (`ad_accounts`, `ad_spend_facts`, `conversion_deliveries`, `conversion_acknowledgements`); separate spend and delivery connections (D2).
- [x] Agency and client authorization across every route, job and storage (`finance:read` for amounts, Owner or Admin for writes, composite tenant keys).
- [x] Data classes, consent, retention and field provenance registered before the migrations (`app.data_policy`; D7, D13).
- [x] Success, error, retry, limits, backfill and disconnection behavior (design sections 3 to 5).
- [x] Confirmed decisions kept distinct from proposals: D1-D14 (D-064); Q-001, Q-004, Q-010 and Q-012 stay open.

## Review slices
1. 014-A spend ingestion (migration `0017`).
2. 014-B conversion delivery (migration `0018`).
3. 014-C ROAS contract.
4. 014-D live adapters with fixture tests (migration `0019`), off by default.

Each slice was verified, recorded and pushed (D-051); one pull request against `main` covers the specification (D-063).

## Validation
- [x] Rerunning spend ingestion does not duplicate totals and handles revisions, time zones and currencies.
- [x] Only verified conversions with required consent enter the delivery outbox; a browser signal alone does not prove payment.
- [x] Retries do not create a semantically duplicate conversion; provider rejections have recorded resolution paths without endless retry loops.
- [x] ROAS identifies its model, period and currency; zero spend does not produce a misleading infinite value.

## Rollout and recovery
Migrations `0017` to `0019` are additive, and each downgrade refuses populated state (use a forward fix). The live adapters stay off unless explicitly enabled and registered only with current provider rules; disabling a destination stops its deliveries and destroys their payloads. Native migration and deployment require separate approval.

## Follow-ups
See the [tasks](tasks.md) and the [evidence](evidence.md): 014-E, 014-F, 014-G, the browser-field decision, 007-B, 016, 018, 020, later providers and native rollout.
