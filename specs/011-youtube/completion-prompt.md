# Spec 011 completion: corrections, the rest of 011-B, 011-A, 011-C and the pull request

Work in `C:\Code\Tracking-system\.worktrees\spec-011-youtube` on `codex/spec-011-youtube`. The reviewed head is `c2a2cd4` (Spec 011-B: Record the corrected probe). Verify the branch, the working tree and that `c2a2cd4` is still the head before editing, and preserve any later owner change. Read `AGENTS.md`, `README.md`, D-056 to D-059 in `docs/planning/decisions.md`, and every file in `specs/011-youtube/`, in particular the [entry review](entry-review.md) sections 2 to 6 and 10, the [evidence](evidence.md) with its "Consequences for 011-A" table, and the [first handoff](review-corrections-prompt.md). Use the Spec 009 runtime and the Spec 010 work as the pattern: `backend/app/connectors/` (`contracts.py`, `synthetic_instagram.py`, `instagram.py`), migrations `0013_connector_streams` and `0014_instagram_provider`, the Instagram settings in `backend/app/config.py`, `backend/tests/instagram_graph.py`, `backend/tests/integration/test_connector_instagram*.py` and `specs/010-instagram/evidence.md`. Communicate with the owner in Arabic and write project files in formal English. Save this handoff as `specs/011-youtube/completion-prompt.md`.

## Authority

Record the owner's decisions of 2026-11-18 as D-060 in `docs/planning/decisions.md` and `AGENTS.md`:

1. **D9 amendment (from the 011-B evidence).** Day reports are sparse, so the last row returned cannot show how far data is complete. `complete_through` is the end of the last Pacific day that ended at least 72 hours before the read. A day of a read window without a row is `missing` with reason `not_returned`, never 0. The 4-day re-read and the provisional marking stay.
2. **Order.** 011-A starts once the short 011-B steps (Phase 1) and this amendment are recorded. F3, F12 and F13 run in parallel with 011-A and 011-C, in the order of the access rule below, and are recorded before the pull request is offered for review.
3. **Complete Spec 011 under this handoff.** That covers R011-10 to R011-12, the rest of 011-B, 011-A, and 011-C (the live adapter, migration `0016`, the re-verified policy rows, fixture tests, a browser connect through the loopback API callback and a read-only adapter check with the owner's test channel). Push after each verified phase (D-051) and open a pull request against `main`.

The merge waits for Claude's independent review of the whole branch and for the owner's decision. Several things stay separate owner decisions: 011-D (brand and sensitive-scope verification, the YouTube API compliance audit and quota extension, and the optional derived-metrics terms, which need HTTPS hosting under 020), customer channels, native `tracking_sys` migration and deployment. A change to D1-D13 that any later evidence requires goes to the owner first, as D-054 did. The other rows of the "Consequences for 011-A" table are applied as recorded, within D7, D8, D10 and the error handling of D4 and D10.

## Access rule for the test account

Google revokes every token of an account in the project at once (entry review G-1). Before F3 is recorded, nothing may revoke a token or remove access for the test channel's Google account. F3 can be checked only after **2026-11-24 23:57 UTC (2026-11-25 01:57 Cairo time)**, when the refresh token of the first consent (slot a) should have expired. Until F3 is recorded, do none of the following:

- `authorize` on slot a;
- `revoke-test`, or access removal in the Google account;
- a product disconnect of a live YouTube connection;
- a refused-grant or partial-consent test through the product with the live channel.

After F3: the live disconnect check of 011-C, then F12, then F13, then `forget` and the deletion of `local-data\youtube-feasibility`.

## Phase 0: corrections R011-10 to R011-12

Each code correction needs a regression that fails at `c2a2cd4` and passes after the change.

| ID | Location at `c2a2cd4` | Finding and observed result | Required correction |
|---|---|---|---|
| R011-10 | `_probe_day_report` | When the combined day report gets no answer, the per-metric fallback runs first and consumes the `no_answer` label, so the evidence names the wrong call. Observed with `FakeGoogle(fail_at_get=9)`, where the combined day report is the 9th GET of the default fake: `day_report.combined` is `not_requested` and `day_report.per_metric.views` is `no_answer`. | Record the combined failure before the fallback, and skip the per-metric fallback when the probe has stopped. Regression: the combined record is `no_answer` and no per-metric read is sent. |
| R011-11 | `evidence.md`, 011-B review corrections | The section says the 9 regressions fail at `bb3263e` and `7d66822` without naming the platform. On Linux, `test_r011_09_the_receiver_refuses_a_port_that_is_in_use` passes at both revisions, because Linux refuses a second bind of a listening port even with `SO_REUSEADDR`. Claude's run gave 8 failed and 1 passed at each. | State that the run was on Windows, and add the Linux result with its reason. |
| R011-12 | `spec.md`, `specs/README.md`, `docs/planning/review-next.md` | Their status lines still describe 011-B as prepared and do not mention D-059 or the partial run. | Bring them up to date, and keep them current at the end of each phase. |

Verify, commit and push.

## Phase 1: the short 011-B steps (owner, before 011-A)

Guide the owner in Arabic, one step at a time, through the corrected checklist. The owner sends only the printed summaries or the redacted evidence files, never a value from `.env`.

1. **Partial consent (F1).** `authorize --slot b --no-probe`, clearing one scope on the consent screen.
2. **PKCE (F2).** `authorize --pkce --slot b --no-probe`, then `authorize --pkce-wrong-verifier --no-probe`. The second command stores nothing and leaves slot a untouched.
3. **Console quota readings (F7, F11).** The daily limits and current usage of both APIs from the `connectapp` console.
4. **Next-day stability (F8).** A `probe` on slot a at least 24 hours after the 2026-11-17 probe.
5. **Channel choice (F4).** Ask the owner which account or channel Google offered at consent.

Record each answer in `evidence.md`, with any proposed amendment, then commit and push. If the PKCE result shows that the Web client enforces `S256`, the adapter declares it (D3).

## Phase 2: 011-A, the YouTube-shaped synthetic adapter

1. **Design note.** Write `specs/011-youtube/design-011a.md`: the runtime extensions, migration `0015` (tables, columns, constraints, privileges, upgrade and downgrade), the error mapping, and how each item of entry review section 6 is tested. Then continue; this note is not a stopping point.
2. **Implementation.**
   - A `synthetic_youtube` adapter that reproduces the shapes observed in 011-B: lowerCamelCase `creatorContentType` values mapped to `SHORTS`, `VIDEO_ON_DEMAND` and `UNSPECIFIED` (values not yet observed map to `UNSPECIFIED`); 50 IDs per `videos.list` and `batchGetStats` call; private and unlisted uploads in the inventory with their privacy status; sparse day rows; and `refresh_token_expires_in` kept as the grant's expiry.
   - The runtime extensions of D2 to D13, with D9 as amended by D-060: refresh ahead of expiry; installation only with both scopes; the D5 rules for account-wide grants; the 7-day authorization check and the purge after 14 days in `reconnect_required` with reason `authorization_lost`; quota buckets per API on the Pacific day with deferral on `quotaExceeded`; Pacific-day watermarks with zone-correct boundaries; the widened product types; record attributes and labels with refresh times and deletion after 30 days without refresh; purge of deleted videos from every stream; retention per provider (730 days for YouTube); the non-additive marker and the rounded-count unit; and the D13 agent approval stored with its time and a disclosure version.
   - The customer-facing wording of D13 and any frontend work wait for the owner's brief (D-039). Use a development disclosure identifier and add no frontend change.
   - The error mapping: 401 `authError` gets one refresh, then `reconnect_required`; 403 `insufficientPermissions` is forbidden for the stream that needs the scope; 403 `quotaExceeded` defers to the next Pacific reset and is not counted as a failure; 400 is permanent.
3. **Tests.** `backend/tests/integration/test_connector_youtube.py` covers every case listed in entry review section 6, including tenant isolation, a daylight-saving change, no filling with zeros, and a mutation check of each safeguard (show that removing the safeguard makes its test fail). Add unit tests for the pure parts.
4. **Migration.** Test `0015` upgrade and downgrade on the disposable PostgreSQL 18 service of `backend/tests/README.md` only, never on the owner's `tracking_sys`.
5. **Verification.** The YouTube tests, the full unit suite, the full integration suite on the disposable service, the OpenAPI snapshot if the API changed, and ruff check and format. Record the commands and counts in `evidence.md`, then commit and push.

## Phase 3: 011-C, the live adapter

1. **Policy rows (D-025).** Re-read the official pages that support the `youtube.authorized_analytics` and `youtube.other_data` rows in `app.privacy.providers` (entry review section 1.5 and section 4.5). Update their texts where needed, and mark them current with the verification date and a review date one year later. Test that the live adapter is not registered while either row is stale or past its review date.
2. **Adapter.** `backend/app/connectors/youtube.py` for the Data API v3 and the Analytics API: the streams `channel`, `channel_daily`, `videos` and `video_totals` (D7), requesting only `youtube.readonly` and `yt-analytics.readonly` with offline access and `prompt=consent`, and reading no title, description, thumbnail, tag, comment or caption (`fields` as in the feasibility tool).
3. **Settings.** Off by default, following the Instagram settings: for example `connector_youtube_enabled`, `youtube_client_id` and `youtube_client_secret`, read from the existing `TRACKING_YOUTUBE_CLIENT_ID` and `TRACKING_YOUTUBE_CLIENT_SECRET`. When enabled, require a Web client ID ending in `.apps.googleusercontent.com` and a non-blank secret. Refuse a client ID equal to the Google sign-in client ID or the Gmail sender client ID (entry review section 10, safeguard 1).
4. **Operator purge.** A command that disconnects and purges every YouTube connection, for a loss of API access (entry review section 4.2). The setting is the kill switch.
5. **Migration.** `0016_youtube_provider` admits the provider. Test it on the disposable service only.
6. **Fixture tests.** Run them against an in-memory Google API built from the 011-B answers, in the way `backend/tests/instagram_graph.py` serves the Instagram tests.
7. **Secret rotation.** Before the live check, ask the owner to rotate the connector client's secret in `connectapp` and replace it in `.env` (D-058). If the owner defers, record it as an open follow-up.
8. **Live check (owner, read-only).** Run the API locally on `127.0.0.1:8000` against a Docker development or disposable database, never native `tracking_sys`. With the adapter enabled only for this check:
   1. Connect the owner's test channel in the browser through `http://127.0.0.1:8000/connectors/oauth/callback`.
   2. Run one sync of each stream.
   3. Record only redacted evidence: outcomes, counts, coverage states, `complete_through` offsets and errors, with no ID or metric value.
   4. Respect the access rule: the disconnect check (revocation and purge) comes only after F3 is recorded.
9. **Verification.** As in Phase 2, then record the results in `evidence.md`, commit and push.

## Phase 4: the access-ending checks and the pull request

1. **After 2026-11-24 23:57 UTC.**
   1. F3: `refresh` on slot a, expecting `invalid_grant`.
   2. The 011-C disconnect check.
   3. F12: two fresh consents, then `revoke-test --confirm`, with `check-access --slot b` at least 30 minutes later if slot b survives.
   4. F13: access removal in the Google account, then `check-access`.
   5. `forget`, then delete `local-data\youtube-feasibility` once the summary is recorded.

   If F12 or F13 contradicts D5 or D6, present the amendment to the owner before the review.
2. **Pull request.** When Phase 3 is verified, open a pull request from `codex/spec-011-youtube` against `main`, following `.github/pull_request_template.md` if it exists. Describe the slices, the decisions D-056 to D-060, the evidence, the verification counts and the open follow-ups. Update it as Phase 4 completes. Do not merge.
3. **Closing records.**
   - `tasks.md`: every item closed except the separately gated ones, which are listed as follow-ups.
   - `spec.md`: acceptance criteria 1 to 4, each mapped to its evidence.
   - Status lines updated.
   - Tell the owner in Arabic that the branch is ready for Claude's independent review, with the head commit and the pull request link.

## Follow-ups that stay open after Spec 011

- 011-D: brand and sensitive-scope verification for `youtube.readonly` (demo video, scope justification, privacy policy on a verified domain), the "In production" status, the compliance audit with a quota extension, and the optional derived-metrics terms (P-4). These are owner business actions after HTTPS hosting and legal pages exist (020).
- A review of the Google Cloud project used in production before 011-D (D-057, safeguard 4).
- Customer channels, native `tracking_sys` migration and deployment.
- The client secret rotation, if the owner deferred it.
