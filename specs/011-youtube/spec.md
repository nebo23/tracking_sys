# 011-youtube — YouTube analytics
Status: The [entry review](entry-review.md) (D-056, 2026-11-18) is decided: D15 by D-057 and D1-D14, D16 and D17 as recommended by D-058. D-059 corrected the 011-B tool (R011-01 to R011-09), and D-060 amended D9 and set the completion order: the short 011-B steps, then 011-A and 011-C, with a pull request against `main`. 011-B answered F2, F4 to F7, F9 to F11 and F14 on 2026-11-18 and the rest in Phase 4 ([evidence](evidence.md)). 011-A (the YouTube-shaped synthetic adapter, the runtime extensions and migration `0015`) is implemented and verified on disposable PostgreSQL ([design](design-011a.md)). 011-C (the live adapter, the operator purge and migration `0016`, with the policy rows re-verified) is implemented and verified with fixtures ([evidence](evidence.md#011-c-live-youtube-adapter-2026-11-18)); the read-only live check with the owner's test channel is done ([live check](evidence.md#live-check-with-the-owners-test-channel-2026-11-18)). Claude's merge review of [PR 11](https://github.com/nebo23/tracking_sys/pull/11) found R011-13 to R011-17, which D-061 corrected with regressions ([corrections](evidence.md#merge-review-corrections-d-061-2026-11-18)). Claude reviewed the corrections at `5ccb87a`, and D-062 merged PR 11 before Phase 4. Phase 4 ran on 2026-11-25 on `codex/spec-011-youtube-phase4` ([evidence](evidence.md#phase-4-2026-11-25)): F3, the F8 probe, the live disconnect check, F12, F13, the rest of F1 and `forget`. No result contradicts D1-D14. The secret rotation (deferred by the owner), the D10 and D11 owner decisions and 011-D remain open. Level: L4. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER YouTube; PDF-024,041 context. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Retrieve authorized channel/video statistics and permitted analytics; distinguish the Data API from the Analytics API and review derived-metric policies before combining data.

## Out of scope
Identifying individual viewers or calculating a causal revenue contribution for each video minute.

## Acceptance criteria
1. Prove scopes, channel authorization, Analytics access, and actual project quotas before connector release.
   - **Evidence (met for the owner's test channel in Testing).** 011-B answered F1-F14: see the [first run](evidence.md#011-b-first-run-2026-11-18), the [Phase 1 steps](evidence.md#011-b-phase-1-steps-2026-11-18) and [Phase 4](evidence.md#phase-4-2026-11-25).
     - **Scopes:** F1, F6 and F14, with D2 installing only with both scopes.
     - **Channel authorization:** F2 (PKCE `S256` enforced), F4, and the browser connect through the API in the [live check](evidence.md#live-check-with-the-owners-test-channel-2026-11-18).
     - **The life of an authorization:** F3, F12, F13 and the [live disconnect check](evidence.md#step-3-the-011-c-live-disconnect-check).
     - **Analytics access:** F6, F8, F9 and F10.
     - **Project quotas:** F7 and F11, read from the `connectapp` console: 10,000 Data units and 100,000 Analytics queries a day, on the Pacific day.
   - **Not yet released.** Release beyond test users and the 7-day Testing tokens waits for 011-D.
2. Completeness markers account for incomplete days, reporting delays, and historical coverage.
   - **Evidence (met).** D9 as amended by D-060: `complete_through` at the 72-hour bound, days without a row `not_returned` and never 0, the 4-day re-read and provisional days for 193 hours. 011-A tests it across the 2026 daylight-saving change ([evidence](evidence.md#011-a-youtube-shaped-synthetic-adapter-2026-11-18)).
   - **Live answers.** F8 found that the last day returned had ended 40 to 52 hours before the read, and that no day changed over 7 days ([step 2](evidence.md#step-2-f8-the-stability-probe)). F10 found history beyond the 730-day backfill. Both live checks reported `complete_through` 3 days before the read, with 4 provisional days.
3. Storage, display, and retention follow an applicable provider policy and permitted use case; unrestricted cross-source scoring is excluded.
   - **Policy rows.** The `youtube.authorized_analytics` and `youtube.other_data` rows are current until 2027-11-18, and the live adapter registers only while they are ([policy rows](evidence.md#policy-rows-re-verified-2026-11-18)).
   - **Storage and retention.** D11 and D13 are implemented in 011-A and 011-C: allow-listed attributes with no titles, clearing after 30 days, 730-day retention, deleted videos purged, the operator purge and the agent approval.
   - **Lost access.** The live disconnect check revoked, destroyed and purged in 1.8 seconds, with nothing logged. Removed access leads to `reconnect_required` and the 14-day grace purge (F13, D6).
   - **Display and scoring.** D12 limits data to one channel inside the connecting client, with simple sums only. The 016-A social report reads one connection and totals only additive counts ([reporting guide](../../docs/engineering/reporting.md)). No aggregation across clients, ranking, score or derived metric exists.
4. Tagged-link attribution is displayed as separate evidence; combining or deriving metrics with YouTube data requires policy review.
   - **Decided, not yet verifiable.** D12 places tagged-link evidence in a separate section disclosed as not coming from YouTube, and derived metrics wait for the P-4 terms (D17, 011-D). No attribution display exists yet: 016-A keeps social, spend and recorded-revenue reports apart. The display is verified when 016-B and 018 build it.

## Required design contracts
Channel/Video references and typed metric records with mandatory source version, interval, and deletion policy.

## Dependencies and open decisions
Dependencies: [009-connector-runtime](../009-connector-runtime/spec.md)

Specification 003 obligations (D-025): re-verify and test the YouTube rows in `app.privacy.providers` and mark them current before the features they govern run.

The [entry review](entry-review.md#45-re-verification-of-the-policy-rows) (section 4.5) found the `youtube.authorized_analytics` and `youtube.other_data` rows consistent with the policies read on 2026-11-18. They stay stale until the live adapter slice (011-C) re-verifies them and marks them current.

Open decisions: Q-001, Q-004; provider use-case and policy approval. See the [decision register](../../docs/planning/decisions.md). The entry review places each: Q-001 (YouTube part) through D1, D7 and D8, Q-004 through D10 and D17, Q-012 through D11, and the use case and policies through D5, D6 and D11 to D13.

## Owner approval
D-056 (2026-11-18) authorized preparation. D-057 decided D15 (the existing Google Cloud project `connectapp`), and D-058 (2026-11-18) approved D1-D14, D16 and D17 as recommended. It authorizes 011-B (the [feasibility checklist](feasibility-checklist.md), the read-only tool and owner-operated calls) and then 011-A after the 011-B evidence. D-060 (2026-11-18) amended D9 and authorized 011-C and a pull request against `main`. D-061 (2026-11-18) authorized the merge review corrections R011-13 to R011-17 and their publication to PR 11 ([merge review prompt](merge-review-prompt.md)). D-062 (2026-11-18) merged PR 11 before Phase 4, whose checks ran on 2026-11-25 on a fresh branch pushed under D-051 ([handoff](phase4-prompt.md)). A pull request for that branch and its merge remain owner decisions. 011-D, customer channels, native migration and deployment remain separate decisions.
