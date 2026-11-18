# Plan: 011-youtube
Status: Draft. This plan does not authorize implementation or dependency selection. The [entry review](entry-review.md) (D-056) proposes slices 011-A (YouTube-shaped synthetic adapter and runtime extensions), 011-B (owner-operated feasibility check), 011-C (live adapter) and 011-D (Google verification and quota audit), D-057 and D-058 decided D1-D17; 011-B runs first (see the [feasibility checklist](feasibility-checklist.md) and [evidence](evidence.md)). D-060 ordered the completion; 011-A follows the [design note](design-011a.md).

## Expected outcome
Retrieve authorized channel/video statistics and permitted analytics; distinguish the Data API from the Analytics API and review derived-metric policies before combining data.

## Design before implementation
- Channel/Video references and typed metric records with mandatory source version, interval, and deletion policy.
- Map agency/client authorization across every relevant resource, job, cache, and export.
- Identify data classes, consent, retention, and field provenance before migrations.
- Define success, error, retry, limits, backfill, and disconnection behavior where applicable.
- Distinguish confirmed decisions from proposals and resolve: Q-001, Q-004; provider use-case and policy approval.

## Proposed review slices
These slices are defined in [entry review section 6](entry-review.md#6-proposed-slices) with the tests and evidence each needs. D-058 approves 011-B and then 011-A, in that order; 011-C and 011-D remain separate decisions.
1. 011-A: a YouTube-shaped synthetic adapter with the runtime extensions of D2 to D13 (refresh ahead of expiry, account-wide Google grants, authorization checks and grace purge, quota buckets per API on Pacific days, Pacific-day watermarks, record attributes with 30-day refresh, deleted-video purge, agent approval) and migration 0015 on disposable PostgreSQL. No live call.
2. 011-B: the owner-operated feasibility check in the existing Google Cloud project `connectapp` (D-057), in Testing, with a separate Web client for the connector and an owner test channel, answering F1-F14 with redacted evidence (acceptance criterion 1).
3. 011-C: the live adapter, off by default and registered only while the re-verified YouTube policy rows are current, with fixture tests and a local browser connect through the loopback callback.
4. 011-D: Google brand and sensitive-scope verification, the YouTube API compliance audit and quota extension, and optionally the additional derived-metrics terms (owner business actions; needs 020 hosting).

Prepare small, reviewable local changes. Complete the approved specification and relevant checks, then obtain owner review and upload approval before pushing or creating/updating a PR (D-012).

## Validation
- [ ] Prove scopes, channel authorization, Analytics access, and actual project quotas before connector release.
- [ ] Completeness markers account for incomplete days, reporting delays, and historical coverage.
- [ ] Storage, display, and retention follow an applicable provider policy and permitted use case; unrestricted cross-source scoring is excluded.
- [ ] Tagged-link attribution is displayed as separate evidence; combining or deriving metrics with YouTube data requires policy review.

## Rollout and recovery
Specify migrations and backfill where needed, feature flags or kill switches where appropriate, and rollback procedures that preserve financial and audit history. Deployment requires approval of the production stage.

## Progression gate
The specification is approved, dependencies are ready, required decisions are resolved, and evidence is attached. Estimate delivery only after sizing the work and confirming access.
