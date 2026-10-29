# 011-youtube — YouTube analytics
Status: Draft; implementation is not approved. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER YouTube; PDF-024,041 context. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Retrieve authorized channel/video statistics and permitted analytics; distinguish the Data API from the Analytics API and review derived-metric policies before combining data.

## Out of scope
Identifying individual viewers or calculating a causal revenue contribution for each video minute.

## Acceptance criteria
1. Prove scopes, channel authorization, Analytics access, and actual project quotas before connector release.
2. Completeness markers account for incomplete days, reporting delays, and historical coverage.
3. Storage, display, and retention follow an applicable provider policy and permitted use case; unrestricted cross-source scoring is excluded.
4. Tagged-link attribution is displayed as separate evidence; combining or deriving metrics with YouTube data requires policy review.

## Required design contracts
Channel/Video references and typed metric records with mandatory source version, interval, and deletion policy.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md)

Open decisions: Q-001, Q-004; provider use-case and policy approval. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
