# Spec 011-B feasibility checklist

Prepared: 2026-11-18. Authority: D-058 (entry review decision D16; D15 decided by D-057). This check is owner-operated and covers acceptance criterion 1. Before the YouTube-shaped synthetic adapter (011-A) and the live adapter (011-C) are built, one owner-controlled channel shows what Google's OAuth 2.0 web server flow, the YouTube Data API v3 and the YouTube Analytics API actually return. Live Google calls happen only when the owner runs the tool below.

## What the check must answer

The questions are those of [entry review section 7](entry-review.md#7-feasibility-questions-for-011-b).

| ID | Question | How it is answered |
|---|---|---|
| F1 | What does the token answer contain, and what happens when one scope is cleared on the consent screen? | `authorize` records the answer's field names, the granted scopes, `expires_in` and whether a refresh token came back. Part D step 1 clears a scope. |
| F2 | Does the Web client accept PKCE `S256`, and does it refuse a wrong verifier? | `authorize --pkce`, then `authorize --pkce-wrong-verifier` (Part D step 3). |
| F3 | Does refresh work, and does it fail after 7 days in Testing? | `refresh` at any time, then again more than 7 days after `authorize`. |
| F4 | What does `channels.list?mine=true` return, and how is a channel chosen? | `probe` records the item count, the statistics fields and their types, the hidden-subscriber flag and the uploads playlist. The owner notes which account or channel Google offered at consent. |
| F5 | Does the uploads playlist list private and unlisted videos? What is the ID limit? Does `fields` work, and how do hidden likes and disabled comments show? | `probe` records privacy counts of the uploads, the statistics present per video, and whether titles came back despite `fields`. It sends `videos.list` and `videos:batchGetStats` (with its required `part`) 50 and then 51 IDs, distinct where the uploads allow. Each records `ids_sent`, `distinct_ids` and `conclusive`: a refusal is conclusive, while an acceptance is conclusive only with 51 distinct IDs. |
| F6 | Does `reports.query` work with `yt-analytics.readonly` alone? | `authorize --scopes analytics-only --slot b` (Part D step 2). |
| F7 | How many units do calls record, where does `batchGetStats` count, and what do quota errors look like? | `probe` counts calls per API. The owner reads the console quota pages (Part E). |
| F8 | Which is the last day returned, are days without activity zero rows or missing, do recent days change, and is the whole catalog accepted? | `probe` records the first and last day offsets, missing days, zero-view days and the column headers. A second `probe` a day later compares keyed digests of each day (Part D step 4). |
| F9 | Does the `video` dimension work with a multi-ID filter and with `creatorContentType`, and how does the top-200 report behave? | `probe` records row counts and content-type values for each report. The filtered reports are sent with `sort=-views` and `maxResults=200`, and one unsorted variant shows whether those are required. |
| F10 | How far back does data go, and what does a start date before YouTube existed do? | `probe` reads 30-day windows ending 90 to 3,650 days back, a total from 2005-02-14, monthly totals since 2008-07-01 (first-of-month dates), and the days of the earliest month with views. |
| F11 | What Analytics API quota does the console show? | The owner reads it (Part E). |
| F12 | Does revoking one consent's token end another consent of the same account? | `revoke-test --confirm` with two stored consents (Part D step 6). It ends access. A slot b that still works after the wait is provisional until `check-access --slot b` at least 30 minutes later. |
| F13 | What does a refresh answer after the owner removes access in the Google account? | `check-access` after removal (Part D step 7). |
| F14 | What do an invalid token and insufficient scopes return? | `probe` sends one invalid-token request to each API. The analytics-only consent of F6 shows insufficient scopes. |

Out of scope: customer channels, content owner (CMS) reports, revenue metrics, the Reporting API, Cross-Account Protection, verification and the quota audit (011-D).

## Part A: Google Cloud project (done by the owner on 2026-11-18)

The project `connectapp` was prepared as recorded in [entry review section 10](entry-review.md#10-owner-decisions):

- Both APIs are enabled.
- The publishing status is Testing, with the owner's account as test user.
- `youtube.readonly` (sensitive) and `yt-analytics.readonly` (non-sensitive) are added under Data access.
- A separate Web application client uses the redirect URI `http://127.0.0.1:8000/connectors/oauth/callback`.

`TRACKING_YOUTUBE_CLIENT_ID` and `TRACKING_YOUTUBE_CLIENT_SECRET` are in the ignored `C:\Code\Tracking-system\.env`. Rotating the secret, which was shared in the conversation, is a follow-up (D-058).

## Part B: test channel (owner)

1. Use a channel the owner controls and uses only for testing. Its Google account must be listed under Audience, Test users.
2. Ideally it has at least one public long-form video, one Short, and one unlisted or private video, plus a few days of activity.
3. If this account is also the Gmail sender's account, leave Part D steps 6 and 7 until last, because they end every token of that account in `connectapp`, including the Gmail sender's (D-057).

## Part C: run the check (owner, with Claude)

Stop the API server if it is running, because the tool listens once on port 8000 for Google's answer. Run from `C:\Code\Tracking-system\.worktrees\spec-011-youtube\backend`:

```powershell
C:\Code\Tracking-system\.venv\Scripts\python.exe -m app.youtube_feasibility --env-file C:\Code\Tracking-system\.env authorize
```

1. The browser opens Google's consent page. Sign in with the test channel's account and choose the test channel if Google asks.
2. Google shows that the app is in testing and requests read-only access to the two scopes; continue and allow.
3. The browser shows "The YouTube feasibility check received the answer". There is nothing to paste.
4. The tool exchanges the code, stores the refresh token in `.env` without showing it, reads the channel and writes redacted evidence to `C:\Code\Tracking-system\local-data\youtube-feasibility\`.

`probe` repeats the reads at any time with the stored token. `--max-calls N` (default 120) bounds the number of reads. It can be given before the command name or after `authorize` and `probe`, for example `probe --max-calls 50`. The tool also stops at any quota or rate-limit answer. If Google stops answering, the probe stops with `no_answer` and still writes what it read.

## Part D: follow-up steps

1. **Partial consent (F1):** `authorize --slot b --no-probe`, and clear one of the two scopes on the consent screen.
2. **Analytics scope alone (F6):** `authorize --scopes analytics-only --slot b`.
3. **PKCE (F2):** `authorize --pkce --slot b --no-probe`, then `authorize --pkce-wrong-verifier --no-probe`. If the second exchange succeeds, PKCE is not enforced.
4. **Stability (F8):** run `probe` again at least one day later. The evidence compares the recent days with the earlier probe.
5. **Refresh (F3):** run `refresh` now, and again more than 7 days after `authorize`.
6. **Shared grant (F12, ends access):**
   1. Store two full consents with `authorize --no-probe` and `authorize --slot b --no-probe`.
   2. Run `revoke-test --confirm`, which revokes slot a and checks slot b after a short wait (`wait_seconds`).
   3. If slot b still works, the answer is provisional, because a revocation may take some time to take full effect. Run `check-access --slot b` again at least 30 minutes later before drawing a conclusion.
7. **Access removal (F13):**
   1. Run `authorize --no-probe` again.
   2. Remove the app's access in the Google Account under Security, Third-party apps and services (myaccount.google.com/connections, formerly /permissions).
   3. Run `check-access`.
8. **Clean-up:**
   1. Run `forget` to remove the stored tokens from `.env`.
   2. Once Claude's summary is recorded in [the 011 evidence](evidence.md), delete the folder `C:\Code\Tracking-system\local-data\youtube-feasibility` with its evidence files and `digest-key` (D-010).

## Part E: console readings (owner)

In `connectapp`, open APIs and Services, then **YouTube Data API v3**, then **Quotas and system limits**, and send the daily limits and current usage shown (F7). Do the same for **YouTube Analytics API** (F11). These are project figures, not secrets.

## What enters the repository

Only Claude's dated summary of the redacted evidence files enters the repository, in the [011 evidence](evidence.md), followed by any owner decision the results require.

- **What the evidence files hold:** field, metric and column names, value types, scopes, error codes and reasons, counts, day offsets and keyed digests of day rows.
- **What they never hold:** a token, code, secret, channel or video ID, title or metric value.
- **Where they stay:** the ignored `local-data` folder, together with the digest key.

## The tool

`backend/app/youtube_feasibility.py` uses only the standard library, python-dotenv and the already pinned `tzdata` (for Pacific days on Windows).

- **Read-only.** It makes consents with the two read-only scopes, the documented code exchange, refresh and revocation, and GET reads of the channel, its uploads, its videos and the Analytics reports. It never uploads, edits or comments.
- **Revocation.** `revoke-test` is the only command that ends access, and it refuses to run without `--confirm`.
- **Tests.** Its offline tests are in `backend/tests/test_youtube_feasibility.py`.
