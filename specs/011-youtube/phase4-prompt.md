# Spec 011 Phase 4: F3, the stability probe, the live disconnect check, F12, F13 and clean-up

Prepared 2026-11-25 under D-062. Communicate with the owner in Arabic and write project files in formal English. Save this handoff as `specs/011-youtube/phase4-prompt.md` on the branch below.

## Where to work

1. Fetch `origin`.
2. From the current `origin/main` (expected `81977a3` or later; verify it), create the branch `codex/spec-011-youtube-phase4`. Use a fresh worktree, `C:\Code\Tracking-system\.worktrees\spec-011-phase4`. Do not reuse the merged `codex/spec-011-youtube` branch.
3. Verify a clean working tree, and preserve any later owner change.

Read the following before the first step:
- `AGENTS.md`, `README.md`, and D-056 to D-062 in `docs/planning/decisions.md`.
- In `specs/011-youtube/`: the [feasibility checklist](feasibility-checklist.md), the access rule and Phase 4 of the [completion prompt](completion-prompt.md), and the [evidence](evidence.md). In the evidence, the sections "011-B first run", "011-B Phase 1 steps", "Live check with the owner's test channel" and the D-062 review matter most.
- The "YouTube providers" section of `docs/engineering/connectors.md`.

## Authority and limits

- **Authority.** D-062 makes the F8 probe and Phase 4 follow-ups after the merge of PR 11. They are recorded on a fresh branch from the merged `main` and pushed under D-051. A pull request for them and its merge remain owner decisions: do not open one.
- **Scope.** No code, migration, dependency or setting change is expected.
  - **A defect in the tool or the adapter:** stop and present it to the owner with a proposed correction.
  - **A result that contradicts any of D1-D14:** present the proposed amendment to the owner before changing anything (as D-054 did). This applies in particular to D4, D5, D6 and D9.
- **Data.** Never run anything against native `tracking_sys`. Make no call to Meta, Instagram or any other provider.

## Facts in force

- **Slot a.** Its consent was given at 2026-11-17 23:57 UTC with `refresh_token_expires_in` 604,799. It should therefore have expired at about 2026-11-24 23:57 UTC. Every later consent used slot b.
- **Slot b.** It was last stored by the PKCE consent of 2026-11-18 11:45 UTC, so it has expired since about 2026-11-25 11:45 UTC.
- **No product connection.** The database of the 2026-11-18 live check was removed. Its grant at Google, from the consent at 19:26 UTC, lapses at about 2026-11-25 19:26 UTC unless something revokes it first.
- **Account-wide revocation (G-1).** Revoking any token of the account, or removing its access, ends every token of that account in `connectapp`. D-057 placed the test channel on a Google account other than the Gmail sender's.

## Rules for every step

- **What the owner sends.** Guide the owner in Arabic, one step at a time, and wait for each result. The owner sends only the printed summaries or the redacted evidence files. They never send a value from `.env`, a token, a code, a channel or video ID, a title or a metric value.
- **How the tool runs.** From `<worktree>\backend`:

  ```powershell
  C:\Code\Tracking-system\.venv\Scripts\python.exe -m app.youtube_feasibility --env-file C:\Code\Tracking-system\.env <command>
  ```

  Evidence goes to `C:\Code\Tracking-system\local-data\youtube-feasibility\`, which keeps its `digest-key` until step 7. Stop any API server before an `authorize`, because the tool listens once on port 8000.
- **Recording.** Record each result in a dated section "Phase 4 (2026-11-25)" of `specs/011-youtube/evidence.md` as it happens, with redacted facts only. Commit and push after each step that ends with a recorded result.

## Step 0: preconditions

1. Confirm that the current UTC time is after 2026-11-24 23:57.
2. Run `python -m pytest -q tests/test_youtube_feasibility.py` (offline) on the new branch and record the count.
3. Ask the owner to confirm three things:
   - Nothing has revoked a token, removed the app's access or run `authorize` on slot a since 2026-11-17.
   - `connectapp` is still in Testing.
   - The test channel's account is not the Gmail sender's.

   If any answer differs, stop and present what it changes.

## Step 1: F3, the 7-day refresh check

The access rule of the completion prompt still applies until this result is recorded.

1. Run `refresh`, which uses slot a.
2. Expected: the tool prints "Refresh was refused". The new `refresh-*.json` shows status 400, error `invalid_grant` and a `token_age_hours` of at least 168.
3. Optionally, `refresh --slot b` adds a second expiry data point.
4. Record the following, and no token value:
   - the status;
   - the error code;
   - the category of the error description, for example "expired or revoked";
   - the token age.

If the refresh succeeds, stop: run no later step. Present the result to the owner with its consequence for D4 (the stored grant expiry) and for the access rule. A changed publishing status of `connectapp` would remove the 7-day limit.

After F3 is recorded, commit and push. **The access rule ends here.**

## Step 2: F8, the stability probe

Slot a has expired, so the probe follows a fresh consent.

1. Run `authorize` (slot a, both scopes, with its default probe). The owner chooses the test channel's account and grants both scopes.
2. The probe compares each day with the latest earlier probe through the keyed digests. Record:
   - the last day's offset;
   - the missing and zero-row days;
   - the number of compared days;
   - the offsets of the days whose digest changed.

The gap is about seven days rather than one, so state it. Relate the result to D9: the 72-hour bound, the 4-day re-read and the provisional marking. If a day older than four days changed, present the consequence for the re-read window to the owner before any change.

Keep this slot a token: step 3 uses it as a cross-check.

## Step 3: the 011-C live disconnect check

This is the first step that ends access.

**Setup.** Reproduce the setup of the 2026-11-18 live check (evidence section "Live check with the owner's test channel"):
- **Database.** A separate disposable database (Compose project `tracking-system-youtube-live`, database `tracking_youtube_live` on 127.0.0.1:55434), migrated to the head of `main` (`0025_whatsapp`). Never `tracking_sys`.
- **API.** The API in process, with `TRACKING_CONNECTOR_YOUTUBE_ENABLED=true` for this check only, and a synthetic agency, client and Owner.
- **Callback.** The loopback receiver on 127.0.0.1:8000. It passes Google's code and state to the API's callback with the session and binding cookies of the client that started the connect.
- **No revoke guard.** This time the disconnect must reach Google.
- **Temporary harness.** Keep any harness outside the repository, and delete it after the check (D-010).

**Sequence.**

1. **Connect.** Connect the test channel, including the D13 agent approval with the development disclosure `dev-agent-approval-1`. Expected: `connected`, an `active` connection with both scopes.
2. **Sync.** Run one worker pass, which makes one sync of each stream, so that the purge has stored records to remove. Record counts only.
3. **Disconnect.** As the Owner, call `POST /agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/disconnect`. Expected: 202 and `disconnecting`.
4. **Teardown.** Run `python -m app.connector_worker` until the teardown completes. Record:
   - The connection status, expected `disconnected`.
   - The `disconnect` state. Expected: `revocation` `done`, `secret_destruction` `done`, `data_purge` `done`, `completed_at` set and `deadline_met` true.
   - With counts only, that no stored record, attribute, label, coverage row or sealed token material of the connection remains in the database.
5. **Cross-check at Google (G-1).** Run the tool's `refresh` on slot a, a separate consent from step 2.
   - Expected: refused with `invalid_grant`.
   - If it still works, repeat it at least 30 minutes later before concluding, because a revocation may take time to take effect.
   - A token that survives bears on D5 (account-wide grants and the shared revocation rule). Present it to the owner before changing anything.
6. **Log scan.** Confirm that no token, code, channel or video ID appears in the API or worker output.
7. **Clean-up.** Remove the disposable database (`down -v`).

## Step 4: F12, the shared grant

This step ends access.

1. Store two fresh full consents: `authorize --no-probe`, then `authorize --slot b --no-probe`.
2. Run `revoke-test --confirm`, and record `b_before`, `revoke_a`, `a_after`, `b_after` and the conclusion.
3. If the conclusion is `provisional`, run `check-access --slot b` at least 30 minutes later and record the result.
4. Compare it with step 3.5. If F12 contradicts D5 or D6, present the amendment to the owner before the closing records.

## Step 5: F13, access removal in the Google Account

1. Run `authorize --no-probe` (slot a).
2. The owner removes the app's access in the Google Account, under Security, Third-party apps and services (myaccount.google.com/connections).
3. Run `check-access`. Expected: refused with `invalid_grant`. If it still works, repeat it at least 30 minutes later.
4. Record the result.

## Step 6: the rest of F1, a first consent with one scope cleared

After F13 the account holds no grant in `connectapp`.

1. Run `authorize --slot b --no-probe`, and the owner clears one scope on the consent screen.
2. Record:
   - whether the screen showed a checkbox per scope;
   - the granted scopes, from the `scope` field.

   D2 already refuses a grant without both scopes (`scopes_missing`, tested with fixtures), so no product run is needed. If the result contradicts D2, present it to the owner.
3. Remove the app's access again as in step 5, then run `check-access --slot b`, expecting a refusal, so that no grant remains.

## Step 7: clean-up

1. Run `forget`, then confirm with a script that prints names only that `.env` holds no `TRACKING_YOUTUBE_FEASIBILITY_*` key.
2. Record the evidence summary in `evidence.md` first.
3. The owner then deletes `C:\Code\Tracking-system\local-data\youtube-feasibility`, including `digest-key` (R011-08, D-010). Confirm that `Test-Path` returns `False`.

## Step 8: the client secret rotation

D-058 and D-062 plan the rotation for after Phase 4. Ask the owner whether to rotate the connector Web client's secret in `connectapp` now:

1. In the console, go to Credentials and open the connector's Web client. Add a new secret.
2. Replace `TRACKING_YOUTUBE_CLIENT_SECRET` in `.env`.
3. Disable or delete the old secret.

Optionally, the owner can prove the new secret with one `authorize --no-probe`, then remove the access again, run `check-access` and `forget`. If the owner defers, it stays an open follow-up. Never record either secret.

## Step 9: closing records

1. **`evidence.md`.** The complete Phase 4 section: F3, F8, the disconnect check, F12, F13, the rest of F1, the clean-up and the rotation status, together with any proposed amendment.
2. **`tasks.md`.** Close:
   - the 011-B feasibility item;
   - the folder deletion;
   - the live disconnect check;
   - the Spec 010 day-list follow-up, which PR 13 corrected as review finding R011.

   Keep the separately gated items open: 011-D, the D10 and D11 owner decisions, the secret rotation if deferred, customer channels, native migration and deployment.
3. **`feasibility-checklist.md`.** Mark it completed with the date.
4. **`spec.md`.** Map acceptance criteria 1 to 4 to their evidence.
5. **Status lines.** Update `README.md`, `specs/README.md`, `docs/planning/review-next.md` and `docs/planning/roadmap.md`.
6. **Checks.** Run `git diff --check` and a relative-link check of the changed Markdown files.
7. **Commit and push.** Commit, then push `codex/spec-011-youtube-phase4` (D-051). Open no pull request.
8. **Report.** Tell the owner in Arabic:
   - the head commit;
   - each result;
   - any owner decision that the results require.
