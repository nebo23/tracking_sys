# 011-youtube — YouTube analytics
Status: The [entry review](entry-review.md) (D-056, 2026-11-18) is decided: D15 by D-057 and D1-D14, D16 and D17 as recommended by D-058. D-059 corrected the 011-B tool (R011-01 to R011-09), and D-060 amended D9 and set the completion order: the short 011-B steps, then 011-A and 011-C, with a pull request against `main`. 011-B has run partly (F2, F4, F5, F6, F7, F9, F10, F11 and F14 answered, F1, F3 and F8 in part; see the [evidence](evidence.md)); F3, F12 and F13 end after 2026-11-24 23:57 UTC. 011-A (the YouTube-shaped synthetic adapter, the runtime extensions and migration `0015`) is implemented and verified on disposable PostgreSQL ([design](design-011a.md)). 011-C (the live adapter, the operator purge and migration `0016`, with the policy rows re-verified) is implemented and verified with fixtures ([evidence](evidence.md#011-c-live-youtube-adapter-2026-11-18)); the read-only live check with the owner's test channel is done ([live check](evidence.md#live-check-with-the-owners-test-channel-2026-11-18)), and the live disconnect check comes after F3. The branch is open for review in [PR 11](https://github.com/nebo23/tracking_sys/pull/11); Claude's merge review found R011-13 to R011-17, which D-061 corrected with regressions ([corrections](evidence.md#merge-review-corrections-d-061-2026-11-18)). Claude reviewed the corrections at `5ccb87a`, and D-062 merged PR 11 before Phase 4: the F8 next-day probe and Phase 4 (F3, the live disconnect check, F12, F13, `forget` and the closing records) are follow-ups after the merge. 011-D remains a separate decision. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

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
D-056 (2026-11-18) authorized preparation. D-057 decided D15 (the existing Google Cloud project `connectapp`), and D-058 (2026-11-18) approved D1-D14, D16 and D17 as recommended. It authorizes 011-B (the [feasibility checklist](feasibility-checklist.md), the read-only tool and owner-operated calls) and then 011-A after the 011-B evidence. D-060 (2026-11-18) amended D9 and authorized 011-C and a pull request against `main`. D-061 (2026-11-18) authorized the merge review corrections R011-13 to R011-17 and their publication to PR 11 ([merge review prompt](merge-review-prompt.md)). D-062 (2026-11-18) merged PR 11 before Phase 4, whose checks follow on a fresh branch. 011-D, customer channels, native migration and deployment remain separate decisions.
