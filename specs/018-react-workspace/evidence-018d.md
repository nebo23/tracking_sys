# 018-D evidence

Status: slice 018-D is implemented and checked as described here on 2026-11-27, under D-093 and the [018-D plan](plan-018d.md), and pushed to `codex/spec-018-workspace-screens` (D-051). The slice is not accepted until the owner has reviewed it. A pull request for it, the merge and any deployment are the owner's decisions. Section 7 lists what was not run and section 8 what stays open.

How to run the application and its checks is in the [frontend guide](../../frontend/README.md).

## 1. What did not change
| Area | State |
|---|---|
| Packages | None added and none changed: `frontend/package.json` and `package-lock.json` are those of 018-A (the thirty packages of D-084). |
| API, contract, schema | Nothing in `backend/` or `contracts/` changed. `npm run api:check` still matches the contract. |
| Reference styles | Nothing in `docs/design/` changed. The new screens use the existing classes and glyphs; `frontend/src/styles/app.css` gains rules of the running application only (prefix `a-`). |
| Build settings | One public setting was added, `VITE_SHORT_LINK_ORIGIN` (plan section 2). It is not a secret and defaults to the API origin. |

## 2. What was built
| Part | Where | What it does |
|---|---|---|
| Collect group | `frontend/src/app/shell/` | The client level gains Links, Website tracking and Integrations above Manage (D11). The phone tab bar holds five destinations; at the client level the account stays in the top bar's menu. |
| Links | `frontend/src/features/links/` | Six tabs kept in the address. The links with search, a campaign filter and active, paused and expired views; copy of the short address and of the issued address; pause after asking, resume, and a new end. A panel beside the list creates a link and checks the slug, the destination site, the query names and the UTM values with the rules of `backend/app/links/policy.py` before sending; afterwards it shows the address the API issued. Campaigns, content references, UTM templates and destination sites with their own dialogs; custom domains whose DNS record is shown once and kept nowhere, with each check result and failure code in words. |
| Website tracking | `frontend/src/features/tracking/` | Website sources for exact sites, written the way a browser sends its Origin, with the SHA-256 fingerprint of the consent notice calculated in the browser (only the fingerprint is sent) and the install code of the tracker package; webhook sources whose signing secret is shown once with the webhook address, and replaced with a 24-hour overlap; forms registered field by field; the daily counters of the last 7 or 30 UTC days with each channel, outcome and reason in words; erasure of a visitor by token or event identifier, asked as an alert. |
| Integrations | `frontend/src/features/integrations/` | Four tabs kept in the address. Paymob sources with the callback address, the declared live integration IDs and a write-only HMAC secret; Cal.com and signed webhook sources with the booking totals, the deal totals and the stage rules; WhatsApp numbers registered as claims for the Connect operator to verify, and the conversations that ads started; Meta datasets connected with the connect dialog of 018-B, their destinations, created off, and the deliveries with what Meta answered. |
| Shared parts | `frontend/src/components/` | A field to copy a value, a dialog for values shown once, a confirmation dialog, the states of a list, a choice in a card header, and a text area. |
| Address settings | `frontend/src/app/router.tsx` | `/agencies/{a}/clients/{c}/links`, `/tracking` and `/integrations`, each tab in `?tab=`, and the return from a dataset connection to the integrations. |

## 3. Checks on 2026-11-27
| Check | Result |
|---|---|
| Types, static rules, contract types | `tsc --noEmit`, ESLint with the accessibility rules and `npm run api:check` pass. |
| Unit tests | 517 pass in 26 files, 147 more than at the end of 018-B (section 3.1 lists those that read the repository). |
| Removed protections | 25 protections of the slice were removed one at a time, and each made a unit test fail: the rules of a link, the reader's view of each page, the values shown once and kept nowhere, the exact origins and the notice fingerprint, the settled answers, the Paymob numbers, one destination per dataset, the switch of a verified number only, the last counted day, the return of a dataset connection, the phone tab bar and the first link's panel. Two of them first escaped: the first-link check removed nothing that mattered, and the lowercase event identifier was tested with digits only. Both checks were corrected and now fail as they should. |
| Build and bundle search | One script of 1,044 kB (284 kB compressed), up from 816 kB (238 kB) at the end of 018-B. The bundle search of `npm run build:check` finds no secret, key, token or backend setting. |
| Journeys | 54 of 54 pass in Chromium (8.1 minutes) and in Firefox (12.3 minutes) on the disposable stack: the 47 journeys of 018-A and 018-B, the three new journeys and the new accessibility tests of section 3.2. |
| Accessibility | axe-core scans 95 more states in each browser (23 in each of the four looks and 3 at 390 pixels), 264 in all. No finding remains in either browser, and nothing spills past the edge at 390 pixels. |

### 3.1 Unit tests that read the repository
| Test | What it compares |
|---|---|
| `tests/unit/lib/linkRules.test.ts` | The reserved slugs and the slug rule with `backend/app/links/policy.py`; the UTM names and click identifiers with `backend/app/privacy/collection.py`; every failure code of a domain check in `backend/app/links/verification.py` and `services/links.py` has its own sentence. |
| `tests/unit/lib/trackingRules.test.ts` | The channels and outcomes of the counters with `backend/app/models/collection.py`; the states, requesters and targets of an erasure with `backend/app/privacy/deletion.py` and `services/collection.py`; the tracker version of the install code with `packages/tracker-js/package.json`; the notice fingerprint with Node's own SHA-256. |

### 3.2 Journeys on the disposable stack
The stack switches on, for one run and with random secrets, what these screens need: the API as a platform host of the short links, the tombstone keyring of erasure, and the Paymob, Cal.com, signed webhook and WhatsApp settings (their provider rules are current until 2027-11-21). Nothing calls Paymob, Cal.com or Meta: the journeys sign their own synthetic callbacks, and the Meta dataset belongs to the stand-in provider. Domain checks stay off.

| Journey | What it does |
|---|---|
| `17-links` | Adds a site, a campaign and a template; sees two rules refused before sending; creates a link and reads the issued address; follows the short address to it (302); pauses the link and sees the short address refused (404), then resumes it; claims a domain, sees its DNS record once and nowhere afterwards, and is told that checks are not available on this server. |
| `18-tracking` | Creates a website source and reads its install code and public key; a webhook source whose secret is shown once; registers a form; records a synthetic consent and page view and sees them counted, and a forged webhook refused; erases the visitor by token and sees the token read as unknown afterwards. |
| `19-integrations` | Adds a Paymob source; a signed webhook source whose secret is shown once, delivers a signed booking and sees it counted, and sees a forged one refused; adds a stage rule and sees a deal counted as won without a matching payment; registers a WhatsApp number as a claim; connects a stand-in Meta dataset through the provider and back, adds its destination, off, and turns it on. |
| `10-accessibility` | A new test in each of the four looks scans the six tabs of Links with the row menu, the panel with its errors, the site dialog and the DNS record; Website tracking with the source, install, form and erasure dialogs; and the four tabs of Integrations with their dialogs. The phone test scans the three pages at 390 pixels and checks that nothing spills past the edge. |

### 3.3 Looking at the screens
The three pages, their tabs and dialogs were drawn in English and light, Arabic and dark, and at 390 pixels, and looked at. Two corrections of section 5 came from this.

## 4. Isolation of the checks
The journeys use the disposable stack of 018-A: a PostgreSQL container of its own (`tracking-e2e-frontend`, 56434), the API on 8010 and the built application on 5183, removed after each run. The owner's `tracking_sys` database was not used (D-015), and no other session's container was touched.

## 5. Corrections found by tests and by looking
1. After the first link of a client was created, the panel beside the list was drawn again from the start and lost the address the API had issued, because the list replaced the empty state around it. The panel now keeps its place; a unit test and the links journey create a first link.
2. The UTM values of the panel were shown while closed: the class of the field set overrode the `hidden` attribute. A rule hides a closed field set.
3. The numbers of the installation steps were missing, because the reference styles take them off lists. The steps keep theirs.
4. The conversations of WhatsApp ended one day late: the API counts up to its `until` day without it. The range now ends on the day before, with a unit test.
5. A feature the server has switched off (`collection_not_configured`, `payments_unavailable`, `integration_unavailable`, `whatsapp_unavailable`, `verification_unavailable`) was asked for twice more before its sentence appeared. Such answers are no longer asked again.
6. The DNS record of a domain stayed in the memory of its request while the page was open. The request is cleared when the dialog closes; a unit test checks the cache.
7. The connect dialog said that Connect would read the account; for a Meta dataset it now says that Connect sends the verified sales to it.

## 6. Differences from the plan
| Plan | What was done | Why |
|---|---|---|
| Section 4.2: the phone tab bar carries the four client destinations and the account. | Clients and the four client destinations; the account is in the top bar's menu at the client level. | Six tabs do not fit 390 pixels; the menu shows the account at every width. |
| Section 5: the integrations as cards on one page. | Four tabs, with Payments for owners and admins only. | The page was long, and a reader has nothing to see under Payments. |
| Not in the plan. | The type and autocomplete of a form field are left to the API's defaults. | The tracker reads the real ones from the page and refuses the kinds it never collects. |
| Not in the plan. | The deliveries show the newest page of 100 without paging. | The page is for watching what Meta answers; older deliveries stay in the API. |

## 7. Not run
- Live providers: no call to Paymob, Cal.com or Meta, no DNS check, and no real visitor. Their callbacks need the API's HTTPS address (specification 020).
- The tracker package on a real website. The install code is checked as text; the tracker has its own tests in `packages/tracker-js`.
- Screen readers, Safari, real phones and usability with Arabic-speaking users, as in the earlier slices.
- The backend tests: nothing in `backend/` changed.

## 8. Open
1. **The owner's review of the screens that had no reference drawing**: the tabs of Links after the first, Website tracking and Integrations follow the design language only.
2. **018-C** waits for the owner's decision on its packages (Recharts).
3. **Pull requests**: none was opened for 018-B or 018-D (D-093). Pull request 17 (018-A) is still open, and Spec 017-A will bring the agreement record at sign-in, the operator as an actor in the audit log, and the plan limits (018-B evidence, section 9.6).
4. A WhatsApp number is verified by the Connect operator with `python -m app.whatsapp_binding`; there is no screen for the operator, who acts outside the agency roles.
5. The application is one script of 1,044 kB. Loading each page's code when it is first opened would shorten the first load; it needs no new package (the router loads routes lazily) and can follow when the owner wants it.
