# Every screen of Connect, A to Z

Status: prepared on 2026-11-27 for the owner's review of the whole interface, at the owner's request to see every screen from the sign-in page to the last one. It records what is on the "A to Z" page of the design canvas "Connect App Screens" and adds no decision. The canvas is a review copy; this repository (`docs/design/` and `frontend/`) stays the source of truth. Updated on 2026-11-28 in P5: the screens built in the completion round (D-106) are marked Built.

## 1. How the page was made
| State | Meaning | How it was drawn |
|---|---|---|
| Built | The screen exists in the application on `codex/spec-018-workspace-screens` (slices 018-A to 018-G). | A picture of the running application at 1440 pixels (390 for a phone), taken on the disposable stack with made-up data on 2026-11-27, in Chromium. The screens built on 2026-11-28 (A03, B13 to B15, C01 to C10, E03 to E08) were captured the same day from the corrected application (`d29ac00`), on a disposable stack of their own. |
| Design | The API exists, the screen is drawn, and it is not built. | A reference page in `docs/design/preview/screens/`, drawn on the API contract. |
| Concept | Neither an API nor a decision exists yet. | A reference page marked "Design concept" on the page itself. |

The pictures of built screens were changed in four ways, and only these: keys, callback addresses and the DNS record shown once by the disposable stack were replaced with examples (`tsk_example-1`, `isk_example-1`, `ppk_example-1`, `pk_example-1`, `tracking-verification=example-record`); the local addresses became `links.connect.example`, `api.connect.example` and `app.connect.example`; the random endings of the link slugs were removed; and the stand-in providers of the development build were renamed to the providers they stand for, while the four test-only choices of the connect dialog were taken out. A03 is drawn from A01 with the message the sign-in shows after the API refuses outdated terms.

## 2. The screens
| Code | Screen | State | Source |
|---|---|---|---|
| A01 | Sign in | Built | `/sign-in` |
| A02 | Sign in, with what is missing | Built | `/sign-in`, sent empty |
| A03 | Sign in, the terms changed | Built | `/sign-in`, answered `agreement_required` (017-A) |
| A04 | Sign in, Arabic | Built | `/sign-in` |
| A05 | Create an account | Built | `/register` |
| A06 | Confirm the email address | Built | `/verify-email` |
| A07 | Forgotten password | Built | `/forgot-password` |
| A08 | Choose a new password | Built | `/auth/reset-password` |
| A09 | An invitation, signed out | Built | `/auth/accept-invitation` |
| A10 | The first agency | Built | `/welcome` |
| B01 to B03 | Clients, archived clients, adding a client | Built | `/agencies/{a}/clients` |
| B04 to B07 | Members, a member's access, invitations, inviting | Built | `/agencies/{a}/team` |
| B08 to B10 | API keys, creating one, the key shown once | Built | `/agencies/{a}/keys` |
| B11 | Audit log | Built | `/agencies/{a}/audit` |
| B12 | Privacy and data | Concept | `privacy-and-data.html` |
| B13 to B15 | Agency settings, closing the agency, the closing state | Built | `/agencies/{a}/settings`, `/agencies/{a}/closing` (017-A, 016-C) |
| C01 to C04 | Overview in light, dark, Arabic and on a phone | Built | `/agencies/{a}/clients/{c}` (016-A) |
| C05, C06 | Content, Revenue | Built | `/agencies/{a}/clients/{c}/content`, `.../revenue` (016-A) |
| C07 | Ad spend | Built | `/agencies/{a}/clients/{c}/ad-spend` (016-A spend report) |
| C08 to C10 | Attribution: credit, funnel, return on ad spend | Built | `/agencies/{a}/clients/{c}/attribution` and its tabs (016-B) |
| C11 | Attribution, first concept with one journey | Concept | `journey.html` |
| D01 to D08 | Links and their six tabs, a new link, a DNS record shown once | Built | `/agencies/{a}/clients/{c}/links` |
| D09 to D12 | Website tracking, a new source, the install code, erasing a visitor | Built | `/agencies/{a}/clients/{c}/tracking` |
| D13 to D16 | Integrations: payments, bookings and CRM, WhatsApp, Meta conversions | Built | `/agencies/{a}/clients/{c}/integrations` |
| E01, E02 | Connections, connecting an account | Built | `/agencies/{a}/clients/{c}/connections` |
| E03, E04 | Reports: exports and schedules | Built | `/agencies/{a}/clients/{c}/reports`, with `?tab=schedules` (016-C) |
| E05 | Saving a report as an export | Built | "Save as export" on every report page (016-C) |
| E06 | A new schedule | Built | Reports, "New schedule" or "Edit" (016-C) |
| E07 | The export a report email opens | Built | `/agencies/{a}/clients/{c}/reports/exports/{id}` (016-C) |
| E08 | An export that is gone | Built | the same address, for a revoked or expired export (016-C) |
| F01, F02 | Account, closing the account | Built | `/account` |
| F03, F04 | A page that does not exist, the server cannot be reached | Built | any address |
| F05 | Search | Concept | `search.html` |
| G01 to G03 | Clients, Links and Website tracking on a phone | Built | 390 pixels |
| G04 to G06 | Clients, Links and Integrations in Arabic and dark | Built | Arabic, dark theme |

## 3. Points for the owner's review
1. **The Analyze group (C01 to C10) waits for the decision on 018-C**, which needs Recharts (D-100). The ad spend and attribution designs follow the 016-A and 016-B contracts: date ranges end on the last complete day, each model is shown on its own, credit is checked against the ledger, and unknown or unmeasured values are named instead of shown as zero. Settled: D-106 approved `recharts` 3.10.1 and `react-is` 19.3.1, and P1 and P2 built C01 to C10.
2. **Names of campaigns, ad sets and ads.** The 016-A spend report and the 016-B ROAS report return object IDs only. C07 and C10 show the names that the 014 ad-spend read (`/ad-spend`) returns for the same account, joined in the browser; no API change is assumed.
3. **Agreement to the terms.** Main now has 017-A: signing in, registering and Google sign-in must send the current versions from `GET /auth/agreements`. The interface branches were made before 017-A and do not send them yet, so this must be added when they are brought up to date with main; A03 shows the refused state. Done in P0: the versions are sent, and A03 is built.
4. **Agency settings (B13 to B15)** need a place in the navigation; the design adds "Agency settings" to the agency group. The API (plan, closure) exists on main. Done in P3 (018-F).
5. **Concepts B12, C11 and F05** need a decision each before anything is built. The Reports concept E03 was drawn again on the 016-C contract on 2026-11-28 as E03 to E08 (D9 of the [completion entry review](entry-review-completion.md)); they replace the concept on the canvas and keep the other codes. The owner approved them (D-107), and P4 built them; B12, C11 and F05 stay concepts (D10).
6. **Not on the page:** the Google sign-in return page, the return page of a provider connection, the terms and privacy pages (their texts are not written), and the operator's verification of a WhatsApp number, which is a command, not a screen.
7. **After 017-B and 017-C.** An Owner's copy of the agency's data while it closes (017-B) and the subscription, trial and hold of 017-C have their API on `main` and no screen yet; their actions appear in the audit log. Screens for them need drawings and a decision.

## 4. Checks
On 2026-11-28 every board was rendered again with IBM Plex at its own size, at the owner's request: the sign-in layout of A01 to A10 and F04 stopped at about 644 of its 900 pixels, because its height is a share of a parent that has none on a board. Those eleven boards now fill their height and show the redrawn sign-in picture (the Arabic one mirrored); no other board leaves space at the bottom. The ten new reference pages were rendered at 1440 pixels and checked at 390, 768, 1024 and 1440 pixels, light and dark, for horizontal overflow and console errors, with none found; five were reviewed as screenshots. The built screens are the application as its journeys and accessibility scans checked it ([018-D evidence](evidence-018d.md)). The canvas itself was not rendered or checked after the upload.

On 2026-11-28, after P5, the drawings of A03, B13 to B15, C01 to C10 and E03 to E08 on the canvas were replaced by captures of the running application, with made-up data, in the same states the drawings showed. The boards B01, B03, G01 and G04, whose client links led to the drawn overview, now lead to the captured one. Those captures showed four display defects of the application, which were corrected the same day (section 5 of the [completion evidence](evidence-018-completion.md)); the boards above, and D09 to D12 and G03, were then captured again from the corrected application.
