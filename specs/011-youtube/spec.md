# 011-youtube — YouTube analytics
Status: The [entry review](entry-review.md) (D-056, 2026-11-18) is decided: D15 by D-057 and D1-D14, D16 and D17 as recommended by D-058. D-059 corrected the 011-B tool (R011-01 to R011-09), and D-060 amended D9 and set the completion order: the short 011-B steps, then 011-A and 011-C, with a pull request against `main`. 011-B has run partly (F4, F5, F6, F9, F10 and F14 answered, F1, F3 and F8 in part; see the [evidence](evidence.md)); F3, F12 and F13 end after 2026-11-24 23:57 UTC. 011-D remains a separate decision. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

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

Specification 003 obligations (D-025): re-verify and test the YouTube rows in `app.privacy.providers` and mark them current before the features they govern run.

The [entry review](entry-review.md#45-re-verification-of-the-policy-rows) (section 4.5) found the `youtube.authorized_analytics` and `youtube.other_data` rows consistent with the policies read on 2026-11-18. They stay stale until the live adapter slice (011-C) re-verifies them and marks them current.

Open decisions: Q-001, Q-004; provider use-case and policy approval. See the [decision register](../../docs/planning/decisions.md). The entry review places each: Q-001 (YouTube part) through D1, D7 and D8, Q-004 through D10 and D17, Q-012 through D11, and the use case and policies through D5, D6 and D11 to D13.

## Owner approval
D-056 (2026-11-18) authorized preparation. D-057 decided D15 (the existing Google Cloud project `connectapp`), and D-058 (2026-11-18) approved D1-D14, D16 and D17 as recommended. It authorizes 011-B (the [feasibility checklist](feasibility-checklist.md), the read-only tool and owner-operated calls) and then 011-A after the 011-B evidence. 011-C, 011-D, customer channels, native migration, pull request, merge and deployment remain separate decisions.
