# Spec 011 merge review: corrections R011-13 to R011-17, published to PR 11

Work in `C:\Code\Tracking-system\.worktrees\spec-011-youtube` on `codex/spec-011-youtube`. The reviewed head is `d8b6b5d` (Spec 011-C: Record the live check and read video totals as two reports); the review itself ran on `cd307d7`, and each finding was re-checked at `d8b6b5d`. Before editing, verify the branch, the working tree and the head. Preserve any later commit, in particular the F8 next-day probe if it has been recorded in the meantime. Read `AGENTS.md`, `README.md`, D-056 to D-060 in `docs/planning/decisions.md`, and every file in `specs/011-youtube/`, in particular the [completion prompt](completion-prompt.md) and the [evidence](evidence.md). Communicate with the owner in Arabic and write project files in formal English. Save this handoff as `specs/011-youtube/merge-review-prompt.md`.

## Authority

On 2026-11-18 the owner approved this handoff. Record it as D-061 in `docs/planning/decisions.md` and `AGENTS.md`. D-061 does three things:

1. It authorizes correcting R011-13 to R011-17 below on `codex/spec-011-youtube`, each with a regression, and adopts the recommended options for Q1 and Q2.
2. After successful verification, it authorizes committing, pushing the branch and updating the open PR 11 without a further upload request. Do not open a second pull request.
3. The merge waits for Claude's review of the corrections and for Phase 4 (D-060). It remains the owner's decision.

011-D, customer channels, native `tracking_sys` migration and deployment remain separate decisions. The access rule of the completion prompt stays in force until F3 is recorded after 2026-11-24 23:57 UTC. Nothing in this work may revoke a token of the test account, make a live Google call, or disconnect a live connection. All checks run against fixtures and the disposable PostgreSQL service only.

## Review result

Claude's independent review of the whole branch ran on Linux with Python 3.12.3. It used the pinned `postgres:18.6-bookworm` image as the disposable service of `backend/tests/README.md` and never touched the owner's `tracking_sys`.

| Check at `cd307d7` | Result |
|---|---|
| `ruff check` and `ruff format --check` | All checks passed (152 files) |
| `pytest -m "not integration"` | 593 passed, 342 deselected |
| `pytest -m integration` (full suite) | 339 passed, 3 skipped (browser journeys) |
| Alembic | One head, `0016_youtube_provider`; no conflict with `main` at `5d05153` |
| R011-10 regression | Fails at `c2a2cd4`, passes at the head, on Linux |
| Mutation spot checks | The D5 shared-teardown rule and the `not_returned` day marking were each disabled; both were caught, and the sources were restored byte for byte |
| Credentials | Only synthetic test values; no tracked `.env` or local-data file |

The review flagged that the `video_totals` request shape (`video,creatorContentType` with the whole catalog) had never been sent in 011-B. The live check confirmed the refusal, and `d8b6b5d` corrected it by reading two reports. The design, the D5 account-wide grant rules, the D10 quota buckets, the D9 completeness rule as amended, the operator purge and both migrations hold.

`developers.google.com` was not reachable from the review environment. The evidence's own limit therefore stands: Developer Policies III.E was confirmed from a summary, and a word-for-word reading belongs to 011-D.

## Findings to correct

Each code correction needs a regression that fails at `d8b6b5d` and passes after the change. Record the platform of each regression run.

| ID | Severity | Location | Finding and observed result | Required correction |
|---|---|---|---|---|
| R011-13 | Medium (D6; P-1 III.D.2, III.E.4.b) | `app/services/connectors.py`: the check in `_execute`, the active-agency and active-client filters of `schedule_syncs`, and the `client_inactive` cancellation in `_claim`. Also design note section 2 and the "Tokens" row of `docs/engineering/connectors.md`. | D6 approves "Refresh at least every 7 days, even without a sync". The check runs only inside a sync run, and runs are queued and claimed only for an active agency and client. Reproduced: a `synthetic_youtube` connection in client A1 was synced, then A1 was archived, then the account's refresh was refused (the stand-in for a revocation in the Google settings). Worker passes with scheduling at +8, +31 and +45 days made no refresh call, and the connection stayed `active` with 99 records. A suspended agency is skipped by the same filter. A revocation is therefore never detected, and the data stay past the 30 days of P-1. The design note's sentence "The scheduler queues every stream at least daily, so the check holds for tokens of any lifetime" is not true in these cases. | Add a scheduling step, beside `expire_reconnects`, that checks authorization independently of syncs and of the agency and client status. For each live `active` connection of a provider with `authorization_check_days` whose access token was last refreshed longer ago than that period, it refreshes the access token without reading data, under the same fencing, sealing and usage rules as `_refresh`. `invalid_grant` then leads to `reconnect_required`, and to the 14-day grace purge, as today. Regressions: the archived-client case above, and a suspended agency. Correct the design note and the guide. |
| R011-14 | Low-medium | `app/connectors/youtube.py` `_token_error` (`refresh and (error == "invalid_grant" or reply.status == 401)`) | A refresh answered with HTTP 401 is mapped to `UNAUTHORIZED`, whatever the error. Google's token endpoint answers client errors such as `invalid_client` with 401, as the branch's own fixture `tests/youtube_api.py` models for a wrong secret. Reproduced: after a sync, the worker ran with a provider holding a secret that Google no longer accepts. The connection became `reconnect_required` with reason `credential_expired`. With every connection in that state, the grace purge would disconnect and purge them all 14 days later. The postponed secret rotation can cause exactly this if `.env` and the console disagree. | Only `invalid_grant` ends a user's authorization. Map the client errors (`invalid_client`, `unauthorized_client`, `deleted_client`, `disabled_client`) to `PERMANENT` with the closed code `client_rejected`. Runs then fail, and the connection stays `active`. Log a new field-less event `connector_client_rejected`: add it to `app.logging_config.EVENTS` and to its test. Regressions: the case above, and `invalid_grant` still leading to `reconnect_required`. |
| R011-15 | Low-medium (D9) | `app/connectors/youtube.py` `_daily_page`; the same pattern in `app/connectors/synthetic_youtube.py` `_page` for `channel_daily` | When `since` is None (the first read after a connect), the first day is computed from `complete_through(now)` on every page, while the cursor is only an offset into that list. When a run resumes (attempt > 0), the runtime keeps `window_since` as None and keeps the cursor. If the resumed page comes after the 72-hour bound has moved, the list shifts by one day and one day is skipped. That happens on any deferral across a Pacific midnight; a `budget_exhausted` deferral always resumes just after one. Reproduced with the live adapter and the fixture: the first page ended at 2026-09-15, and the page read one hour later, after the Pacific midnight, started at 2026-09-17. 2026-09-16 is never read and gets no `not_returned` record, and later incremental runs re-read only the last days. | A resumed read must continue the day list it started with. For example, carry the first day in the cursor (`<first-day>:<offset>`); still refuse a malformed cursor as `invalid_cursor`. Apply the same to the synthetic adapter. Regressions: the adapter case above, and an integration case in which the per-connection Analytics allocation defers the first `channel_daily` run between pages, with no day missing after it resumes. Record as a Spec 010 follow-up that `app/connectors/instagram.py` (`start = max(since or now - timedelta(days=RECENT_DAYS), oldest)` with `_account_page`) has the same pattern on UTC days. Do not change the Instagram adapter in this work. |
| R011-16 | Low (D11; P-1 III.E.4.b) | `app/connectors/youtube.py` `_channel_page` and `_uploads` (`channel_unavailable`) | When the channel is deleted but the Google account stays, every read fails as `PERMANENT` each day, and the connection stays `active`. The inventory sweep then never runs, so the records of the deleted videos stay for up to 730 days, against D11's purge of deleted videos. | When a read finds no channel for the connection's account, treat it as lost authorization: raise `UNAUTHORIZED` with the closed code `channel_gone`. The runtime then makes the connection `reconnect_required` after its one refresh, so the D6 grace purge applies. Keep a failed request (a 5xx or a network error) retryable. Regression with the fixture: set `channels = 0` after the connect. |
| R011-17 | Documentation | `README.md`; `docs/engineering/local-environment.md`; `.env.example`; `docs/engineering/connectors.md`; `specs/011-youtube/evidence.md` (011-A and 011-C limits) | (a) `README.md` and `local-environment.md` still say that the branch expects `0014_instagram_provider` (migrations 0005 to 0014). The head is `0016_youtube_provider`. (b) `.env.example` has the Instagram block but not `TRACKING_CONNECTOR_YOUTUBE_ENABLED=false`, `TRACKING_YOUTUBE_CLIENT_ID=` and `TRACKING_YOUTUBE_CLIENT_SECRET=`. (c) The large-channel limit is stated as about 1,450 videos. Since `d8b6b5d`, a `video_totals` page costs 2 Analytics requests and 2 Data units, and a `videos` page reserves 3 Data units. With the daily `channel_daily` request, the 30 Analytics requests of a connection cover a full daily cycle only up to 14 pages, about 700 videos (1 + 2 × 14 = 29). The Data allocation would stop at 19 pages, about 950 videos (measured at `cd307d7`: 950 videos complete in one day; at 1,000 videos one run is deferred, although only 63 Data API calls were made). D10 estimated about 2,000 videos. | Correct (a) to (c). State the capacity of the live adapter in the evidence and the guide: about 700 videos per day before the rest continues the next Pacific day. Reserving the actual page cost is not part of this work, because it changes D10's accounting; record it as a proposal for the owner. |

## Q1 and Q2 (recommended options, adopted by D-061)

- **Q1. The adapter is not registered.** When the setting is off (the kill switch), or a rule is past its review date (2027-11-18), the registry has no `youtube` provider. Its connections are then neither synced nor checked, and `expire_reconnects` skips them. Document in the connectors guide that the operator purge must follow within 30 days of switching the adapter off (P-1), and that the rule review must be renewed before 2027-11-18. Add the same point to the 020 follow-ups in `docs/planning/review-next.md`. No code change.
- **Q2. R011-14's trade-off.** With client errors mapped to `PERMANENT`, connections keep their data while the client is broken. The operator must repair the client or run the operator purge within the 30 days of P-1. Document this next to Q1.

## Records

- `evidence.md`: add a dated section "Merge review corrections (D-061)" with the finding IDs, the regression names, the platform, the commands and their counts.
- Update `tasks.md`, the design note, the connectors guide, `spec.md`, `specs/README.md` and `docs/planning/review-next.md` where the behavior or the status changes.

## Verification before the push

From `backend/` with the project `.venv`:

- `python -m pytest -m "not integration" -q`.
- The full suite, `python -m pytest -m integration -q`, on the disposable service, because R011-13 to R011-16 change shared runtime code.
- `python -m ruff check .` and `python -m ruff format --check .`.
- The OpenAPI snapshot, if an API field changes.
- The mutation check of each new safeguard: the independent authorization check, the `client_rejected` mapping, the pinned first day and the `channel_gone` mapping. Restore each source byte for byte.
- Each new regression, run against a temporary checkout of `d8b6b5d`, with the failure recorded.

Commit with a message that names R011-13 to R011-17 and D-061. Push `codex/spec-011-youtube` (D-051, D-061).

## Updating PR 11

Update the description of PR 11 with:

- the corrections and their regressions;
- the new verification counts;
- the corrected capacity;
- the remaining gates: the F8 next-day probe (if not yet recorded) and Phase 4 after 2026-11-24 23:57 UTC (F3, the disconnect check, F12, F13, `forget`, the deletion of `local-data\youtube-feasibility` and the closing records);
- the open follow-ups: the client secret rotation after Phase 4 (D-058), the Instagram cursor pattern (Spec 010), the actual-cost reservation proposal (D10), and 011-D.

Do not merge. Tell the owner in Arabic that the corrections are ready for Claude's review, with the head commit and the PR 11 link.
