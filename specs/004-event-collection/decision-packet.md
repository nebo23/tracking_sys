# Specification 004 decisions for owner review

Prepared: 2026-11-10. Status: proposed; none of the options below is approved by preparing this packet. [Design](design.md) gives behavior and data implications. Record explicit decisions in the decision register before dependent implementation.

## Recommended package

| ID | Recommendation | Alternative and implication |
|---|---|---|
| C004-01: delivery slice | Browser + trusted server intake and generic signed webhook, with registered event schemas and metadata-only diagnostics. No paid provider, broker, SDK or React dependency. | A named provider adapter first requires its contract/configuration and review; silently omitting webhook acceptance is not allowed. |
| C004-02: permission | Add explicit client-scoped `events:write`; keep read/finance grants unchanged. Public keys only route limited-trust events. | Separate write credentials isolate risks further but require another credential model. Do not treat `client:read` as write authority. |
| C004-03: conflict policy | One scoped event identity; identical retries deduplicate; divergent equal/lower-trust payloads conflict; higher-trust copy upgrades only approved mutable fields after identity and privacy checks. | Reject every divergent copy: simpler and safer, but server enrichment cannot replace browser claims. Neither choice treats a purchase signal as revenue proof. |
| C004-04: local abuse bounds | Propose single-event requests, 64 KiB body, 32 fields, 2,048 characters per text field, 5-minute future skew, 7-day maximum lateness, 5-minute webhook signature window. Propose 60 public requests/minute per source+peer and 600/minute per trusted source, with Retry-After. | Different values need expected workload. These are review candidates, not established capacity or legal limits. Reject or explicitly negotiate batches; never accept unbounded arrays. |
| C004-05: event/diagnostic retention | Propose 30 days for sanitized payloads and 7 days for safe diagnostic/conflict metadata; digest-only scoped receipts for workspace lifetime, with deletion removing subject links/fingerprints and retaining approved replay tombstones. | Bounded receipts reduce retained metadata but make deduplication time-bounded; that would require narrowing the acceptance contract explicitly. No indefinite raw payload or guessed historical expiry. |
| C004-06: privacy persistence/schema | Review the proposed schema inventory, server-bound consent/subject receipts, independent key material, and client-level transaction lock. All non-necessary purposes remain strict opt-in under D-025. | More granular locks may improve throughput but require a complete tested concurrency design. No new market profile or inferred consent. |

The proposed limits and retention values are starting recommendations for review, not statements of owner workload or compliance. Q-004 remains open for agency/client counts, daily/burst event volume, concurrency and monthly budget. Q-012 remains open for lawful retention by class; approving a local synthetic pilot does not approve real customer intake.

## Decisions needed now versus later

For implementation: approve/revise C004-01 to C004-06 and the concrete migration/field-purpose matrix. For synthetic design work: no provider account or production workload is required. Before real intake: confirm source ownership, privacy notice/consent binding, jurisdiction requirements, abuse limits, key custody and retention. Before production: hosting, capacity, monitoring, delivery and operational restore retain their existing gates.

Separate predecessor actions: explicit PR 2 merge decision; optional native 0005/0006 rollout; legacy queued-mail T1/T2 policy. Native rollout and legacy mail are not requirements for writing the 004 design or exercising it on disposable data.

## Approval record

Pending. Record date, selected options or revisions, approved schema version, permitted environment, deferred source adapters and test expectations. Do not mark this packet accepted based solely on a request to prepare specification 004.
