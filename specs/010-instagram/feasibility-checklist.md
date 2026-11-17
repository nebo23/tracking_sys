# Spec 010-B feasibility checklist

Prepared: 2026-11-17. Authority: D-053 decision D10. This is the owner-operated check of acceptance criterion 1: before the Instagram adapter (010-C) is designed against real data, one owner-controlled professional test account shows what the Instagram API with Instagram Login actually returns. Live Meta calls happen only when the owner runs the tool below after finishing parts A and B.

## What the check must answer

| ID | Question | How the tool answers it |
|---|---|---|
| F1 | Which scopes are granted and in what shape does the code exchange answer? | `authorize` records the granted permission names and the answer shape |
| F2 | What is the token's real lifetime, and does refresh work after 24 hours? | `authorize` records `expires_in`; `refresh`, at least 24 hours later, records the outcome |
| F3 | Is PKCE accepted, and is it enforced? | Optional `authorize --pkce` and `authorize --pkce-wrong-verifier` |
| F4 | Which profile fields exist (`user_id`, `username`, `account_type`, counts)? | `probe` requests them together, then one by one if refused |
| F5 | Which D2 account metrics return data, return empty data, or are refused, and is `impressions` refused? | `probe`, one request per metric for the last two days |
| F6 | How far back do account insights go? | `probe` reads one day of `reach` at 7, 30, 90, 365 and 730 days back |
| **F7** | **Is `media_product_type` available with Instagram Login?** The media reference documents it for Facebook Login only, while D7 assumes FEED, REELS and STORY. | `probe` requests it with the media list and records whether it is returned or refused |
| F8 | Which D2 media and story metrics return data for each media type? | `probe`, one request per metric for one item of each type, and the stories edge |
| F9 | Does the 100-follower threshold apply to this account, and what does a withheld metric look like? | `probe` records the follower bucket and empty or refused answers |
| F10 | Which rate-limit headers and values appear? | `probe` keeps the usage headers with numbers only |
| F11 | What happens to the token when the owner removes the app's access? | `check-access` after the removal in part D |

Not covered, because each needs a public HTTPS endpoint that is not approved: webhooks, the `story_insights` notification, and Meta's deauthorize and data deletion callbacks. Facebook Login, customer accounts, App Review and Business Verification are also out of scope.

## Part A: Meta app in development mode (owner)

Follow Meta's [create an Instagram app](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app) and [Business Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login) pages; dashboard labels can change.

1. In the Meta App Dashboard, create an app of type **Business** with the use case **Other**, and add the **Instagram** product (**API setup with Instagram login** is added automatically).
2. Under **Set up Instagram business login**, open **Business login settings** and add the OAuth redirect URI `https://localhost/instagram-feasibility/callback` exactly; check whether the dashboard added a trailing slash and use the same value in part B. If the dashboard refuses it, use an HTTPS address on a website you control and tell Claude, so the check uses that value.
3. If the dashboard requires a deauthorize callback URL or a data deletion request URL, enter `https://localhost/instagram-feasibility/deauthorize` and `https://localhost/instagram-feasibility/data-deletion`. They are not called during this check.
4. Note the **Instagram App ID** and **Instagram app secret** shown in the business login settings (not the Meta app ID).
5. Keep the app in development mode. Do not submit App Review or Business Verification.

## Part B: test account and local settings (owner)

1. Use an Instagram account you control that is a **professional** account (business or creator). Meta's setup page states that the test account must be **public**. Note whether it has fewer than 100 followers; both cases are useful.
2. Add it to the app for testing (**App Roles > Roles**, or **Instagram > API setup with Instagram login**) and accept the invitation from that Instagram account.
3. Add these lines to `C:\Code\Tracking-system\.env` (the ignored file; never paste the values into the chat, Git, or screenshots):

```
TRACKING_INSTAGRAM_APP_ID=<Instagram App ID>
TRACKING_INSTAGRAM_APP_SECRET=<Instagram app secret>
TRACKING_INSTAGRAM_REDIRECT_URI=https://localhost/instagram-feasibility/callback
```

4. Tell Claude that parts A and B are done, without any value.

## Part C: run the check (owner, with Claude)

Run from `C:\Code\Tracking-system\.worktrees\spec-010-instagram\backend` with the project environment. Claude can start each command in the Terminal panel; the owner completes the browser step and the paste.

```powershell
C:\Code\Tracking-system\.venv\Scripts\python.exe -m app.instagram_feasibility --env-file C:\Code\Tracking-system\.env authorize
```

1. The browser opens Instagram's consent page. Sign in with the test account and approve read-only access (`instagram_business_basic`, `instagram_business_manage_insights`).
2. The browser then goes to the redirect address, which does not load. That is expected.
3. Copy the full address from the address bar and paste it at the hidden prompt in the terminal. The code is valid for one hour and only once.
4. The tool exchanges the code, stores the long-lived token in `.env` without showing it, reads the account, and writes redacted evidence to `C:\Code\Tracking-system\local-data\instagram-feasibility\`.

`probe` repeats the read at any time with the stored token. `--max-calls` (default 150) bounds the number of reads; the tool also stops when Meta throttles.

## Part D: follow-up steps

1. **At least 24 hours later**, refresh the token (F2): `... -m app.instagram_feasibility --env-file C:\Code\Tracking-system\.env refresh`
2. **Optional PKCE check** (F3), two more consents: `authorize --pkce`, then `authorize --pkce-wrong-verifier`. If the second exchange succeeds, PKCE is not enforced.
3. **Removal check** (F11): remove the app's access from the test account (Instagram settings for apps and websites), then run `check-access`.
4. **Clean-up**: run `forget` to delete the stored token from `.env`. Keep or delete the Meta app as you prefer.

## What enters the repository

Only Claude's dated summary of the redacted evidence files, in the [010 evidence](evidence.md), followed by any owner decision the results require (for example on F7) and the re-verified `meta.platform_data` and `instagram.login_api` rows. The evidence files hold metric and field names, availability, value types, error codes, counts, ages in days and rate-limit percentages. They hold no token, code, secret, account or media ID, username, caption, URL or metric value, and they stay in the ignored `local-data` folder.

## The tool

`backend/app/instagram_feasibility.py` uses only the standard library and python-dotenv, already a dependency. It is read-only: one consent with the two scopes above, the documented code exchange, long-lived exchange and refresh, and GET reads of the profile, insights, media and stories. It never publishes, comments, messages or changes anything. Its offline tests are `backend/tests/test_instagram_feasibility.py`.
