# Evidence: Agency settings (018-F, phase P3)

Status: slice 018-F, Agency settings, is implemented and checked as described here on 2026-11-28, under D-099 and the [plan](plan-018f.md), on `codex/spec-018-workspace-screens`. It is not accepted until the owner has reviewed it. A pull request follows at the end of the round (D11).

## 1. What was built

| Code | Screen | Address | Built on |
|---|---|---|---|
| B13 | Plan and usage | `/agencies/{a}/settings` | `GET /agencies/{a}/plan` |
| B14 | Branding | `/agencies/{a}/settings?tab=branding` | `GET` and `PUT .../branding`; `PUT`, `GET` and `DELETE .../branding/logo` |
| B14 | Close the agency | `/agencies/{a}/settings?tab=closure` | `POST .../closure` |
| B15 | The closing page | `/agencies/{a}/closing` | `GET` and `DELETE .../closure` |

- **Destination.** Agency settings is the last item of the agency group of the navigation for Owners, Admins and Analysts. For a client viewer it is not in the navigation and its address does not exist. Close the agency is a tab for Owners only; a tab that a role does not have falls back to Plan and usage.
- **Plan and usage.** The plan, the time of the reading, the four limits with their use, their share as the meter of the design, and their state ("1 of 5", "Within the plan", "At the limit", "No limit"), and the tracked events of the UTC month with the allowance and its meter, "More than N" when the count is capped, and "Over the allowance" without anything being refused.
- **Branding.** The display name and the accent color, checked before sending with the API's rules, then shown as the API kept them. A PNG logo is checked before it is sent (type, size up to 256 KiB, the signature, IHDR, up to 1024 pixels each way) and sent as the raw `image/png` body; an SVG file is refused before anything is sent, and the API's own refusals have sentences. A logo can be added once the profile is saved. The preview shows the name, the color and the logo the API keeps, on this page only (D8).
- **Closure.** The exact name, compared before sending, and the password; an empty password is left out, so that an account without one gets the API's `reauthentication_required` and is asked to sign in with Google again. Each refusal is said in words. The closing page says when the closure was asked for and when the agency closes for good, and lets an Owner keep the agency during the 30 days; every other page of a closing agency leads there.
- **Plan limits elsewhere.** The sentence of `plan_limit_reached` links Owners and Admins to Plan and usage; Analysts and client viewers get the sentence without the link.
- **Messages.** 91 messages of Agency settings and the closing page in each language.
- **Found by the journey and fixed.** The preview kept drawing a removed logo, and the "saved" notice vanished when the profile was read again. The preview now draws only an address made from the logo the API keeps, and the form no longer starts over after a save; a unit test fails for each without its fix.

## 2. Checks

| Check | Result |
|---|---|
| `npm run typecheck`, `npm run lint`, `npm run api:check` | Passed; no finding; "The contract types match contracts/openapi.json." |
| `npm test` | 31 files, 587 tests passed (564 after P2). |
| `npm run build`, then `npm run build:check` | Built; the settings page is a chunk of 14.85 kB (4.34 kB compressed) and the closing page one of 1.89 kB (0.88 kB). "No secret, key, token or backend setting was found." The first page loads six script files, 735.35 kB (seven, 719.89 kB, after P2): the entry script grew from 506.52 kB to 521.30 kB with the messages of both languages. |
| Journeys, Chromium | 63 journeys in four groups, all passed: files 01 to 09, 22 (1.4 minutes); 10 to 12, 27 (6.2 minutes); 13 to 16, 8 (1.4 minutes); 17 to 22, 6 (1.1 minutes). |
| Journeys, Firefox | 63 journeys, all passed: 22 (1.6 minutes), 27 (8.3 minutes, run in the background), 8 (1.6 minutes) and 6 (1.2 minutes). |
| After the last changes | The meters of Plan and usage, the navigation's use of the shared manager rule and the removal of a blank line at the end of the stylesheet came after the first runs. Journey 22 and the accessibility tests of the workspace and the phone then ran again: 6 passed in Chromium (2.5 minutes) and, with groups 13 to 16 and 17 to 22 run on the final code, 5 passed in Firefox (3.1 minutes). |
| Accessibility | The 22 axe tests of journey 10 in each browser report 0 serious or critical and 0 moderate or minor findings. The workspace tests now also open Plan and usage, Branding with an error, Close the agency and its dialog with an error, and the closing page after a real closure request, in the four looks; the phone test opens the three tabs at 390 pixels, none wider than the screen. |
| `git diff --check` | Clean. |

### 2.1 The journey `22-agency-settings`
On the disposable stack: an owner with an agency, a client and an admin who accepted an invitation. The journey checks that:
- Plan and usage shows 1 of 5 clients, 2 of 10 seats, 0 of 10 connections and 0 of 500 managed links, each within the plan, and the tracked events of the month out of 100,000;
- the profile cannot take a logo before it is saved; saved with "  Lumen  " and `#1f6feb`, it shows "Lumen" and `#1F6FEB` as the API kept them;
- an SVG file is refused with its sentence and no upload request leaves the browser; a 48 by 32 PNG is uploaded once, described as "A PNG of 48 by 32 pixels, 1 KiB.", and drawn in the preview at its own width; removing it leaves no logo in the preview;
- the admin can edit the profile and has the tabs Plan and usage and Branding only, also when the address asks for the closure tab;
- the closure refuses a name in other letters before sending, says when the password is wrong, and then opens "Lumen Studio is closing" with the day it closes for good;
- while the agency is closing, the admin's list no longer has it ("Create your agency"), and the owner's other pages of it lead to "This agency is closing";
- "Keep the agency" opens its clients again, for the owner and for the admin.

### 2.2 Removed protections
Each protection was removed alone with a scratch script, the named unit test failed, and the file was restored byte for byte (SHA-256 compared):

| Protection | Failing test |
|---|---|
| The Owner-only closure tab | "show settings to every member but a client viewer, and closing to Owners only"; "lets an analyst read the plan and the branding, but neither edit it nor close the agency" |
| The client viewer's absence from settings (the page and the navigation, which share one rule) | "does not exist for a client viewer"; "offers a client viewer the clients only"; "show settings to every member but a client viewer, and closing to Owners only" |
| The PNG type check | "check a logo as the API does, with the same bounds"; "saves the branding profile, refuses an SVG before sending it, and uploads a PNG as its raw body" |
| The PNG size bound | "check a logo as the API does, with the same bounds" |
| The PNG signature check | "check a logo as the API does, with the same bounds" |
| The IHDR check | "check a logo as the API does, with the same bounds" |
| The PNG dimension bound | "check a logo as the API does, with the same bounds" |
| The check before the upload is sent | "saves the branding profile, refuses an SVG before sending it, and uploads a PNG as its raw body" |

Unit tests also read `backend/app/models/report_delivery.py`, `backend/app/services/branding.py`, `backend/app/api/schemas.py`, `backend/app/api/plans.py` and `backend/app/services/agency_closure.py`, and fail when the bounds, the name and color rules, the limit states or the closure refusals of the interface differ from them.

## 3. Limits
- Plans are changed by the Connect team for now (the operator command of 017-A); prices, payment and a plan change on the page wait for 017-C.
- The branding profile is previewed on this page only; the screens keep the Connect brand and report emails use the profile (D8, 016-C).
- The offboarding export of the closing period (017-B) is not on the closing page: `main` gained it at `04dc323` after this branch was updated in P0, and P5 merges `main` again.
- The journey uses a password account; the fresh Google sign-in that `reauthentication_required` asks for is covered by a unit test only, because the stack has no Google sign-in.
- The Arabic copy is written by a model and marked for review by a native editor (D12).
