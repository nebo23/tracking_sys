# Plan of P3: Agency settings (018-F)

Status: phase P3 of the [completion handoff](implementation-prompt-completion.md), approved with D1-D12 of the [completion entry review](entry-review-completion.md) by D-106 (2026-11-28). Done on 2026-11-28: see the [evidence](evidence-018f.md). This plan was written down after the code, from the notes of the phase. It follows D7 and D8 of the packet; section 6 lists the two points that the packet left open and how they were settled.

## 1. The destination
Agency settings is a page of the agency at `/agencies/{a}/settings`, the last item of the agency group of the navigation, for everyone of the agency except its client viewers; for a client viewer the address does not exist. Its tabs are kept in the address (`tab`, the default left out):

| Tab | Code | Who sees it | Built on |
|---|---|---|---|
| Plan and usage (default) | B13 | Owners, Admins and Analysts | `GET /agencies/{a}/plan` |
| Branding (`tab=branding`) | B14 | Owners and Admins edit it; Analysts read it | `GET` and `PUT .../branding`; `PUT`, `GET` and `DELETE .../branding/logo` |
| Close the agency (`tab=closure`) | B14 | Owners | `POST .../closure` |

A tab that a role does not have falls back to Plan and usage. The closing page B15 is `/agencies/{a}/closing`.

## 2. Plan and usage
The plan's name and the time of the reading; each of the four limits (clients, seats, connections, managed links) with what it counts, its use as "used of value" or "used, without a limit", its share as the meter of the design, and its state (within the plan, at the limit, no limit); the tracked events of the current UTC month with the allowance, its meter and its state, "More than N" when the API capped the count, and the sentence that going over the soft allowance stops nothing (017-A, D5). Plans are changed by the Connect team for now; the page says so.

## 3. Branding
- **Profile.** The display name (1 to 100 characters, no control character) and the accent color (`#RRGGBB`), checked before sending with the rules of `backend/app/services/branding.py`; the form then shows what the API kept (the trimmed name, the color in upper case). `invalid_branding` has its own sentence.
- **Logo.** A PNG of 67 bytes to 256 KiB and of 1 to 1024 pixels each way. Before anything is sent, the file's type, its size, the PNG signature and the IHDR chunk with its width and height are checked; an SVG file is refused at once. The file is sent as the raw `image/png` body. The API's refusals `unsupported_media_type`, `invalid_png`, `request_too_large` and `branding_profile_required` are said in words. A logo can be added once the profile is saved, because the API keeps a logo only with a profile.
- **Preview (D8).** A preview of how a report email names the agency (display name, accent color, logo) on this page only; the screens of the workspace keep the Connect brand.

## 4. Closure and the closing page
- **Request.** The dialog asks for the agency's exact name, compared before sending as the API compares it, and the password. An empty password is left out, so that an account without a password is asked by the API for a fresh Google sign-in (`reauthentication_required`). The refusals `confirmation_mismatch`, `invalid_credentials`, `reauthentication_required`, `closure_in_progress` and `access_denied` are said in words. On success the list of agencies is read again and the closing page opens.
- **Closing page (B15).** When the closure was asked for, the day the agency closes for good, and "Keep the agency" during the 30 days (`DELETE .../closure`), with `closure_not_open`, `grace_period_ended` and `access_denied` in words. The API lists a closing agency only to its Owners and refuses its other routes, so every other page of a closing agency leads to the closing page, and its name is shown only when it was read before the closure. Other members no longer see the agency.

## 5. Plan limits elsewhere
The sentence of `plan_limit_reached` names the limit, its value and its use (P0) and, for Owners and Admins, links to Plan and usage.

## 6. Points settled in this phase
- **The link from a plan limit.** The handoff asks for a link for Owners and Admins. Analysts can read Plan and usage too, but they create nothing that a limit counts, so the link is shown to Owners and Admins only, as written.
- **A logo needs a profile.** The packet did not say what happens to a logo without a profile; the API answers `409 branding_profile_required`, so the page asks for the profile first.

## 7. Tests
Unit tests for the limit states (compared with `backend/app/api/schemas.py`), the PNG rules (compared with `backend/app/models/report_delivery.py` and `backend/app/services/branding.py`), the display name and color, the closure refusals (compared with `backend/app/services/agency_closure.py`), the tabs of each role and the plan link; journey `22-agency-settings`; the tabs, the closure dialog and the closing page in the accessibility scans of the four looks, and the three tabs at 390 pixels; the removed protections of the handoff.
