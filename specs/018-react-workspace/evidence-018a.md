# 018-A evidence

Status: implemented and checked as described here on 2026-11-26, pushed to `codex/spec-018-react-workspace` (D-051) and presented in a pull request against `main` (D-086) for the owner's review. Slice 018-A is not accepted until the owner has reviewed it. The merge and any deployment are the owner's decisions. Section 7 lists what was not run and section 8 what is open.

The slice follows the [018-A plan](plan-018a.md) (D-084). How to run the application and its checks is in the [frontend guide](../../frontend/README.md).

## 1. Installation on 2026-11-26
Environment: Windows 11, Node.js 24.17.0, npm 11.13.0. The install ran inside `frontend/` from `package.json`, in which every version is exact, and created `package-lock.json`.

| Check | Result |
|---|---|
| Packages | 404 installed; the lockfile has 435 entries, which include optional packages for other platforms. |
| Direct versions | All thirty match section 4 of the plan (`npm ls --depth=0`). |
| Size | `node_modules` is 294 MB. Free space on drive C went from 3.7 GB to 3.0 GB, which includes npm's own cache. |
| Browsers | None downloaded. |

### 1.1 Security audit
`npm audit` reports no critical and no high finding, and seven of moderate severity. All seven are one advisory: `minimatch` can be made slow by a crafted pattern. It is reached only through `typescript-eslint` 8.72.2 and its `@typescript-eslint` packages, which are used for static checks during development. The patterns it reads come from this project's own configuration, and the package is not part of the application that a browser loads. Removing the finding means another version of `typescript-eslint`, which needs a decision (D-084).

### 1.2 Notice from the registry
npm marks `eslint` 9.39.5 as no longer supported by its maintainers. ESLint 9 was chosen because `eslint-plugin-jsx-a11y` 6.10.2, which carries the accessibility rules, accepts ESLint up to 9 (plan, section 4.3). The tool runs only during development.

### 1.3 Licences of the full tree
Read from the lockfile, 435 entries:

| Licence | Entries |
|---|---|
| MIT | 348 |
| Apache-2.0 | 34 |
| MPL-2.0 | 14 |
| ISC | 14 |
| BSD-2-Clause | 9 |
| BSD-3-Clause | 5 |
| OFL-1.1 | 3 |
| BlueOak-1.0.0 | 2 |
| Python-2.0, CC-BY-4.0, Unlicense, CC0-1.0, 0BSD, "MIT OR CC0-1.0" | 1 each |

### 1.4 Licences outside the approved list
Section 4.5 of the plan approves MIT, Apache-2.0, BSD, ISC, OFL-1.1 and MPL-2.0. Eight packages carry another licence. None was chosen directly; each comes with an approved package.

| Package | Licence | Part of the application | Comes with |
|---|---|---|---|
| `tslib` 2.9.1 | 0BSD | Yes | `react-aria-components` |
| `isbot` 5.2.4 | Unlicense | Yes | `@tanstack/react-router` |
| `minimatch` 10.2.6 | BlueOak-1.0.0 | No, development only | `typescript-eslint` |
| `lru-cache` 11.5.3 | BlueOak-1.0.0 | No, development only | `jsdom` |
| `argparse` 2.0.1 | Python-2.0 | No, development only | `eslint` |
| `caniuse-lite` 1.0.30001828 | CC-BY-4.0 | No, development only | `eslint-plugin-react-hooks` |
| `language-subtag-registry` 0.3.23 | CC0-1.0 | No, development only | `eslint-plugin-jsx-a11y` |
| `type-fest` 4.41.0 | MIT OR CC0-1.0 | No, development only | `openapi-typescript` |

Assessment: all eight are permissive. None requires publishing source code and none restricts commercial use. 0BSD, the Unlicense and CC0-1.0 ask for nothing at all; BlueOak-1.0.0 and Python-2.0 ask to keep the licence text; CC-BY-4.0 covers a data file used by a development tool and asks for attribution if that data is redistributed, which the application does not do. This is an engineering reading, not legal advice.

Gate: section 4.5 sends such a finding to the owner before any code is written. The owner accepted the eight packages at their locked versions on 2026-11-26 (D-085).

### 1.5 A second copy of one package
The lockfile holds `playwright-core` twice: 1.64.1 inside `@playwright/test`, which runs the journeys, and 1.65.1 as the peer package that npm adds for `@axe-core/playwright`. Only its type definitions are read from the second copy; no browser of 1.65.1 is downloaded or started. Both were part of the install that sections 1.1 to 1.4 describe.

## 2. What was built
| Part | Where | What it does |
|---|---|---|
| Project | `frontend/` | React 19, TypeScript, Vite; exact versions; scripts for development, build, checks, journeys and a sandbox. |
| Stylesheet | `frontend/src/styles/` | Imports `docs/design/tokens/tokens.css`, `docs/design/ui/connect-icons.css` and `docs/design/ui/connect-ui.css` from where they are, without a copy, IBM Plex from local files, and one file of rules that only a running application needs (prefix `a-`). |
| API client | `frontend/src/api/` | Types generated from `contracts/openapi.json` (141 operations after the merge of main) with a drift check; the session cookie on every request; the request-forgery token in memory and on every mutation; one table from API error codes to sentences. |
| Language and theme | `frontend/src/app/preferences.ts`, `frontend/src/i18n/` | English and Arabic messages (ICU), `lang` and `dir` on the root element, Western digits and the Gregorian calendar in Arabic (`ar-u-ca-gregory-nu-latn`), device, light or dark theme. |
| Screens before the workspace | `frontend/src/features/auth/`, `frontend/src/features/agency/WelcomePage.tsx` | Sign in, register, verify the code, forgotten and reset password, accept an invitation, Google completion, first agency. |
| Workspace | `frontend/src/app/shell/`, `frontend/src/features/agency/HomePage.tsx`, `frontend/src/features/account/` | Sidebar, top bar, phone tab bar, agency switcher, account menu with language and theme, overview, account page with password change, sign-out, Google link and account closure. |
| Disposable stack | `frontend/tests/browser/support/` | Starts a PostgreSQL container of its own, applies the migrations, runs the real API and serves the built application, each on a port nothing else in the project uses; removes all of it afterwards. Backs the journeys and `npm run sandbox`. |

## 3. Checks on 2026-11-26
The checks below ran on the branch after it was brought up to date with main (section 3.5), except the removed protections, which ran just before on frontend sources that the merge did not change.

| Check | Command | Result |
|---|---|---|
| Types | `npm run typecheck` | No error (strict mode, with unchecked index access reported). |
| Static rules | `npm run lint` | No finding. ESLint 9.39.5 with the recommended rules of `typescript-eslint`, the recommended accessibility rules of `eslint-plugin-jsx-a11y` and the two rules of hooks. |
| Contract types | `npm run api:check` | `src/api/schema.d.ts` (19,464 lines) equals what `contracts/openapi.json` generates. |
| Unit and component tests | `npm test` | 199 tests in 14 files pass (about 11 seconds). |
| Removed protections | scratch tool, not in the repository | Each of 29 protections was removed in turn; every time at least one unit test failed, and the file was restored byte for byte. Section 3.1. |
| Production build | `npm run build` | 95 files, 2,134 KiB. One script of 641 kB (196 kB compressed) and one stylesheet of 149 kB (34 kB compressed); the rest are font files. |
| Bundle search | `npm run build:check` | No secret, key, token or backend setting. A control file that names a backend setting fails the check. Section 3.4. |
| Journeys in Chromium | `npm run test:browser -- --project=chromium` | 38 of 38 pass in 3.0 minutes. Chromium 156.0.8078.4 (Playwright 1.64.1, build 1248). |
| Journeys in Firefox | `npm run test:browser -- --project=firefox` | 38 of 38 pass in 4.6 minutes. Firefox 157.0 (build 1555). |

The journeys ran with one worker and no retry.

### 3.1 Protections whose removal a unit test catches
The token on mutations only, and not on reads; the cookie on every request; a wrong password not treated as an ended session; `/auth/me` answering 401 not treated as an ended session; the token forgotten at sign-out; sign-in, registration and the Google start refused without the agreement; the link token removed from the address bar; a malformed link token refused; a link pasted into an open tab shown; the return path limited to this application (four variants); the cache emptied when a session starts and when it ends; the agency choice forgotten at the end of a session; data of an agency dropped on a move to another agency; the sentence for a wrong password; the password minimum equal to the contract; the text direction following the language; Western digits in Arabic; an address from the API followed only when it is https; no empty password sent on account closure; the countdown following the clock; the return path never carrying a fragment; the workspace start page not opened without an agency.

### 3.2 Journeys
All of them use the real API on the disposable stack, with mail captured as files and read by the journey as a person reads their mail. Each journey creates its own synthetic people.

| File | What a person does | What it proves |
|---|---|---|
| `01-first-visit` | Registers, enters a wrong code and then the mailed code, signs in, creates an agency, reloads, signs out. | The first use from start to end. Sign-in and registration send nothing without the agreement. The session cookie is `HttpOnly` and `SameSite=Lax`; the token, the cookie value and the password are in no storage and in no address. After sign-out the Back button and a direct address lead to sign-in, and the cookie is gone. Focus moves to the heading of each new page. |
| `02-password-reset` | Asks for a link, opens it from the mail, saves a new password, tries the old one, opens the link again. | The acknowledgement is the same for every address. The token leaves the address bar at once, is in no storage and in no request address, and works once. A link pasted into a tab that already shows the page is taken as well. |
| `03-limits` | Types a wrong password until the API refuses. | After more than five attempts the API answers 429 and the screen says to wait. No number of seconds is shown; see section 8.1. |
| `04-arabic` | Switches to Arabic, reloads, signs in. | `lang` and `dir` change, the brand side and the sidebar move to the right, the choice is remembered, an email address stays left to right, the date reads `26 نوفمبر 2026` with Western digits, and nothing overflows the page. A browser set to Arabic starts in Arabic. |
| `05-theme` | Chooses dark from the account menu, reloads, returns to the device setting. | The theme is applied and remembered, the logo changes to its light version, and a device set to dark gets the dark theme without a choice. |
| `06-keyboard` | Signs in, opens menus, opens and leaves the closure dialog and signs out with the keyboard alone. | Every step is reachable by Tab, Enter, Space, arrows and Escape; focus is visible (an outline of at least two pixels), stays inside the dialog and returns to the control that opened it; a skip link is the first stop of the workspace. |
| `07-motion` | Looks at the picture, pauses it; then the same with a device that asks for less motion. | Nine travellers move and stop on request. With reduced motion nothing is animated, each traveller rests at the place the reference styles give it, and the pause control is absent. |
| `08-session` | Opens a deep address while signed out; loses the session in the middle of work; changes the password; signs out everywhere with a second browser open; closes an account. | The wanted page is reached after sign-in. An ended session leads to sign-in with a sentence that says why, and back to the page afterwards. A password change and "sign out everywhere" end the sessions of other browsers. Closing an account asks twice, refuses a wrong password, and afterwards the person cannot sign in. The only owner of an agency is told why the account cannot be closed. |
| `09-invitation` | Opens an invitation link while signed out, signs in, accepts; another person tries the same link. | The token stays out of every address and every request address while the person signs in, the agency opens with the invited role, the link works once, and a person with another address is refused. |
| `10-accessibility` | (automatic) | Section 3.3. |
| `11-design` | (automatic) | Seventeen parts of the built sign-in screen are within one pixel of their place and size on the approved page `docs/design/preview/screens/sign-in.html`, at 1440 and at 390 pixels. Both pages are measured without web fonts, and the approved page without its Google button, because this build has Google sign-in switched off. IBM Plex Sans and IBM Plex Sans Arabic load from the application's own files, and the page makes no request to any other host. |
| `12-unreachable` | Opens the application while the API cannot be reached; loses the API in the middle of a form. | The page says that the server could not be reached, in the frame of the entry screens and in either language, and recovers on "Try again". A request that fails in the middle of work is reported in its form, and what was typed stays. |

### 3.3 Accessibility checks
axe-core 4.14.1 through `@axe-core/playwright` 4.14.0, with the rules tagged WCAG 2.0, 2.1 and 2.2 at levels A and AA (D12).

- Screens: sign-in, sign-in with errors, register with errors, verify, forgotten password, reset without a token, the reset form, invitation without a token, invitation while signed out, Google failure, terms, not found, the API unreachable, overview, account menu open, agency menu open, account, account with errors, the closure dialog, first agency, and the account page of a person without an agency. Twenty-one states.
- Looks: English light, English dark, Arabic light, Arabic dark. Plus sign-in, overview and account at 390 pixels in English light.
- Result: 87 scans in each browser, and no finding of any impact in either browser.

The first run found one rule on one control: the account button was named by an `aria-label` that did not contain its visible text, the monogram (rule `label-content-name-mismatch`, WCAG 2.5.3). The button now takes its name from its content: the monogram is marked as decoration and the name is text for assistive technology. The monogram is treated as a symbol of the name, which the understanding document of 2.5.3 allows; a person who speaks to their device says "account", not the two letters.

axe-core finds what a machine can find, which is a part of WCAG 2.2 AA. It does not replace the checks of section 7.

### 3.4 Bundle search
`scripts/check-bundle.mjs` reads every file of `dist/` and fails on: a backend setting name (`TRACKING_...`), a private key, a database address, a Google client secret, API key or client id, an AWS access key, a signed token, a key of this project's kinds (service, webhook, ingest, integration), a payment provider key, a session cookie value, or a source map. It found none.

The addresses the build names are `http://127.0.0.1:8000` (the default API origin, a public build setting), `http://localhost` and `http://www.w3.org` (constants inside libraries), and `https://react.dev` and `https://formatjs.github.io` (links in library error messages). The application's two settings, `VITE_API_ORIGIN` and `VITE_GOOGLE_SIGN_IN`, are public by design (acceptance criterion 5).

### 3.5 Bringing the branch up to date with main
Before the pull request was opened, main had moved: PR 15 merged specifications 006 and 007-B/C (main at `3187c70`), with the migrations `0026` to `0028` and seventeen new API operations.

- Main was merged into the branch (`9a1cfdf`). `AGENTS.md` and the decision register had one conflict each, because both sides had added decisions at the same place; both sets were kept.
- Both workstreams had numbered their decisions from D-074. The 018 decisions became D-078 to D-082 in every file that names them (`42d1e58`); they were renumbered once more afterwards (section 3.6), and the decision register carries a note.
- The drift check failed on the merged contract, as it should: the contract had grown from 124 to 141 operations. The types were generated again, and no call of this slice changed.
- The type check, the static rules, the unit tests, the build, the bundle search and all 38 journeys in both browsers were run again on the merged branch, with the API at migration `0028`. The results are the ones in the table above.

### 3.6 Bringing the branch up to date a second time (D-087)
PR 16 then merged Spec 008-B into main (`f15b6e4`), with migration `0029` and six new API operations. Claude brought the branch up to date on the owner's instruction (D-087).

- **Decision numbers.** Main holds D-078 to D-080 for Spec 008-B, so the six 018 decisions moved from D-078 to D-083 to D-081 to D-086 in every file that names them (`60b0619`). The note in the decision register explains both renumberings.
- **Merge.** Main was merged with the D-080 records of its own merge (`587e429`). `AGENTS.md` and the decision register conflicted again where both sides had added decisions, and the register also on two neighbouring rows of its open questions; both sides were kept.
- **Contract types.** The drift check failed on the merged contract, which had grown from 141 to 147 operations. The types were generated again: 979 lines were added and none removed, and no call of this slice changed. `src/api/schema.d.ts` now has 20,443 lines.

The checks ran again on the merged branch in Claude's review environment (Linux, Node.js 24.22.3), with the API at migration `0029`.

| Check | Result |
|---|---|
| `npm ci` | 404 packages, as locked. |
| `npm run typecheck`, `npm run lint`, `npm run api:check` | No error, no finding, and the types match the contract. |
| `npm test` | 199 of 199 pass. |
| `npm run build`, `npm run build:check` | Built; no secret, key, token or backend setting was found. |
| Journeys in Chromium | Every one of the 38 cases passed: 35 in the full run, and the other 3 when they were run again on their own (see below). The browser was Chrome for Testing 158.0.8127.36, the build installed in that environment, in place of Playwright's own build 1248. |

Not run again: the journeys in Firefox, which that environment does not have, and the removed protections of section 3.1, whose sources the merge did not change.

**An intermittent failure of the journeys' own requests.** In the full run, three of the four variants of "the first-agency screen has no serious accessibility finding" stopped at their first statement with `fetch failed` (`other side closed`), before any page was opened. A second run of that file stopped one variant in the same way, and all four variants passed when they were run on their own. The cause is in the test support, not in the application or the API:
- the request that a test itself sends to the API (`tests/browser/support/people.ts`) reuses an idle connection;
- the API closes an idle connection after five seconds;
- the test before this one spends about five seconds in the browser without such a request.

Making these requests open a new connection, or try once more, is carried to the next slice (section 8.2).

## 4. Isolation of the checks
- The journeys and the sandbox use the Compose project `tracking-e2e-frontend`: database `tracking_e2e_frontend` on `127.0.0.1:56434`, the API on `127.0.0.1:8010` and the application on `127.0.0.1:5183`. The container, its volume, the captured mail and the build are removed when a run ends.
- Before anything connects to a database, the stack asks the backend which settings it will use and stops unless they name that database, local mail capture, Google sign-in off and the application's origin. Inherited `TRACKING_`, `PG`, `PYTHON` and `VITE_` variables are dropped, and every secret is random for one run.
- The owner's database `tracking_sys` on port 5432 was not used (D-015). Another disposable container that was running on the workstation, `tracking-test-008b-database-1` on port 55433, was not touched.
- No message left the workstation and no provider was contacted. Google sign-in was not exercised against Google.

## 5. Corrections found by running against the real API
1. A wrong password is answered with `401 invalid_credentials`, not with `authentication_required` as the plan's table of facts implies. The interface now decides by code: a 401 that is not a wrong password makes it ask `/auth/me` whether the session ended, and only then does it return to sign-in. The sentences for a wrong password on sign-in, password change and account closure follow that code.
2. A person who belongs to no agency could not reach the account page, and so could not close the account. The account page no longer depends on an agency; the first-agency screen links to it.
3. A mail link is folded by the mail format (quoted-printable). The journeys and the sandbox decode a captured message before reading it.
4. The icons of the pause control took the pointer above the checkbox they belong to. Corrected in the reference styles.
5. The Arabic label of the language switch was one pixel smaller than on the approved page, because its language was set on an inner element. It is now set on the control.
6. A scan of the API source found a Google code without a sentence (`google_unavailable`). It and `google_sign_in_conflict` now use the general Google sentence. A unit test repeats that scan, so a new authentication code without a sentence fails the tests.
7. With the API unreachable, the message that replaces a page was drawn as a second main region inside the frame of the entry screens. Every page now has exactly one main region, and the state is part of the accessibility checks.

## 6. Differences from the plan
| Plan | What was done | Why |
|---|---|---|
| Section 5: the top bar has the search pill. | No search control in the top bar. | It opens the command palette, which has no design and no function yet (plan, section 7). A control that does nothing was left out; the owner decides whether to show it earlier. |
| Section 5: the account page is part of the shell. | It is, and it is also reachable without an agency. | Correction 2 of section 5. |
| Section 8, step 3: the first screenshot comparison after the styles. | The comparison runs as journey `11-design`, with the other journeys. | It needs the built screen. |
| Section 2: "A 401 ends the session in the interface." | Correction 1 of section 5. | The API uses 401 for a wrong password as well. |
| Reference styles used unchanged. | Three small changes in `docs/design/ui/connect-ui.css`: the icons of the pause control do not take the pointer, a menu row shows keyboard focus, and one comment follows the new logo. | Found by the journeys and by keyboard use. The two published design pages were not refreshed for these changes; nothing in a still picture differs. |
| Not in the plan. | `/terms` and `/privacy` exist and say that the text is not published yet. | The agreement box links to them (D-082); the texts need their own decision. |
| Not in the plan. | `npm run sandbox` starts the disposable stack for trying the application by hand. | It is the stack of the journeys with a loop that prints captured mail. |

## 7. Not run
- Screen readers (NVDA, JAWS, VoiceOver, TalkBack) and voice control.
- Safari and any WebKit browser; real phones and tablets. The phone layout was checked at 390 pixels in desktop browsers only.
- Usability with Arabic-speaking users, and a native editor's review of the Arabic copy, which a model wrote.
- Google sign-in against Google. The screens around it are covered by unit tests with a stand-in API, including a build with the button enabled.
- An invitation for a person who has no account yet, as a journey; the resend of a code after its 60-second wait in a browser; switching between two agencies in a browser. Unit tests cover the wait and the switch.
- An API that answers 5xx, in a browser. An unreachable API is a journey; the sentences for 503 and other answers are covered by unit tests.
- A session that ends by time (12 hours, or 30 minutes without use). The journey ends it by removing the cookie.
- Load time, bundle budgets and performance on slow devices. The script is one file of 196 kB compressed and was not split.
- Anything over HTTPS, the `__Host-` cookie, a content security policy and the production origin layout (specification 020).

## 8. Open
### 8.1 For the owner to decide
1. The API does not let a browser on another origin read `Retry-After`, so the rate-limit sentence cannot say how long to wait. Exposing that header is one line in the API's cross-origin settings and belongs to the backend, outside this slice.
2. The agreement box is enforced and stored nowhere (D15). No real user may be given the application before the 002 amendment and the legal texts exist.
3. The approved sign-in design hides the brand side below 900 pixels, so the sign-in screen on a phone shows no logo.
4. The search pill of the top bar (section 6).
5. The only owner of an agency cannot close their account, by the API's rule, and the interface has no way to hand over or delete an agency yet (018-B).
6. The moderate `minimatch` advisory and the ESLint 9 notice of section 1 stay open (D-085).
7. The merge of the pull request that D-086 opened.

### 8.2 Carried to later slices
- Clients, team and access, connections (018-B); reports with charts (018-C); links, tracking and integrations (018-D).
- The agency and the client in the address, so a deep link names its tenant. In this slice the chosen agency is remembered by its identifier in the browser and forgotten at sign-out.
- Splitting the script by route, once there is more than the first two pages of the workspace.
- The journeys' own requests to the API can meet a connection that the API has just closed (section 3.6); they should open a new connection or try once more.
