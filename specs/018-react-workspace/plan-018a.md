# 018-A plan: toolchain, application shell, sign-in and account flows

Prepared: 2026-11-26, after D-076. Status: waiting for the owner's approval of the package list in section 4. Until that approval nothing is installed and no application code is written (D-011).

## 1. Goal and boundaries
018-A is the first slice of [specification 018](spec.md) (D14 of the [entry review](entry-review.md)). It delivers a running application in `frontend/` that a person can open, sign in to and manage an account in, in English and Arabic and in both themes, built on the reference styles the owner approved.

In scope:

- The toolchain and the project skeleton in `frontend/`.
- The stylesheet, fonts, themes and text direction of the [design language](../../docs/design/README.md).
- A typed API client generated from `contracts/openapi.json`, with the session, the request-forgery token and one mapping of API errors to messages.
- The screens of section 5: sign in, register, verify the email code, forgotten and reset password, accept an invitation, Google sign-in completion, the first agency, the application shell and the account page.

Not in scope:

- Clients, team and access, connections (018-B); reports (018-C); links, tracking and integrations (018-D); attribution (after 016-B).
- The stored record of agreement to the terms (D15). It needs an amendment to specification 002 with its own schema review. 018-A builds the box of the approved sign-in screen and refuses a sign-in without the tick, but until that amendment exists the tick is not evidence of anything. No real user may be given the application before then.
- Containers, hosting and the production origin layout (020).

## 2. What the API already provides
Read from the merged repository; see the [authentication guide](../../docs/engineering/authentication.md) and the [contract](../../contracts/openapi.json) (124 operations).

| Fact | Consequence for the interface |
|---|---|
| The session is an opaque cookie (`HttpOnly`, `SameSite=Lax`, host-only). `POST /auth/login` and `GET /auth/me` return the user and a `csrf_token`. | The interface never sees or stores a session secret. It keeps the token in memory only and reads it again from `/auth/me` after a reload. |
| Every browser mutation needs an allowed `Origin` and `X-CSRF-Token`. The allowed origins already include `http://127.0.0.1:5173` and `http://localhost:5173`. | The development server runs on `127.0.0.1:5173` with a fixed port. The client sends the cookie with each request and adds the token to every mutation. |
| Errors are `{"error": "<code>"}` with 400, 401, 403, 409, 422, 429 (with `Retry-After`) and 503. | One table maps codes to messages in both languages. A 401 ends the session in the interface. |
| Registration, resend and forgotten password answer 202 with a generic acknowledgement. | The interface never says whether an address exists. |
| Passwords are 15 to 128 characters. The verification code is six digits, valid for ten minutes, with five tries per code. | Field rules and messages match these limits; the code field uses the one-time-code component. |
| Mail links point to `/auth/reset-password#token=…` and `/auth/accept-invitation#token=…` on the frontend origin. | Two routes read the token from the fragment once and remove it from the address bar. |
| Google sign-in is off unless enabled. It ends at `/auth/google/complete` with `?result=signed_in` or `?error=<code>`. A new Google account has no agency. | A completion route, a build setting that shows or hides the Google button, and a first-agency screen. |
| Sessions end after 12 hours, or 30 minutes without use. Changing or resetting a password ends every session. | The interface returns to sign-in on 401 and says why when it can. |
| Closing an account needs the password, or a Google session younger than ten minutes; 409 when an agency would lose its last owner. | The account page explains both cases before the action. |

## 3. How it is built
### 3.1 Layout of `frontend/`
```
frontend/
  package.json, package-lock.json     exact versions, private, Node 24.15 or later
  vite.config.ts, tsconfig.json, eslint.config.js, playwright.config.ts
  index.html
  src/
    main.tsx, app/                    providers, router, guards, shell
    api/                              generated schema, client, session, errors
    components/                       thin wrappers over the reference markup
    features/auth/, features/account/, features/agency/
    i18n/                             messages in en.json and ar.json
    styles/                           one entry that imports the design files
  tests/
    unit/                             Vitest and Testing Library
    browser/                          Playwright journeys and accessibility checks
```

### 3.2 Styles
The application imports `docs/design/tokens/tokens.css`, `docs/design/ui/connect-icons.css` and `docs/design/ui/connect-ui.css` through one alias. `docs/design/` stays the single source: the reference pages, the token audit and the application read the same files, so the application cannot drift from what the owner reviewed. Components use the existing class names (`l-`, `c-`, `u-`, `is-`). No utility framework and no second styling vocabulary is added.

React Aria Components supplies the behavior of controls that need it (menus, dialogs, selects, tabs, the language and theme choices) and is styled with the same classes through its `className` functions. Plain elements stay plain: a link is an `<a>`, a button a `<button>`.

### 3.3 Language, direction and numbers
- Messages are ICU messages in `src/i18n/en.json` and `ar.json`, read through `react-intl`. No text is written in a component.
- The chosen language sets `lang` and `dir` on the root element and the locale of React Aria. The choice is kept in `localStorage`; it is not sensitive.
- Arabic formats numbers and dates with the locale `ar-u-ca-gregory-nu-latn`: Western digits and the Gregorian calendar (D3).

### 3.4 Themes
The theme follows the system setting unless the person chooses light or dark; the choice sets `data-theme` on the root element and is kept in `localStorage`.

### 3.5 Routing and data
- Routes are defined in code with TanStack Router. A guard loads the session before any signed-in route; without a session it sends the person to sign in and remembers where they wanted to go, limited to paths of this application.
- TanStack Query holds server state. Every key of client data carries the agency and client identifiers. Signing out, a 401 and switching the agency clear the cache, so one tenant's data cannot be shown to another (acceptance criterion 2). The same rule extends to clients in 018-B.

### 3.6 Security rules of the slice
- The bundle holds no secret. Its only settings are the API origin and whether the Google button is shown.
- No `dangerouslySetInnerHTML`. Text from the API is rendered as text.
- A token from a link is read from the fragment, sent once in a request body and removed from the address bar. Tokens, codes and passwords never enter a query string, the cache, storage or a log.
- A redirect after sign-in accepts only a path inside the application.

## 4. Packages to approve
Rule used for every version: the newest release that was at least 14 days old on 2026-11-26 and that the other packages accept. Versions are exact, with no ranges. The lockfile is committed and installs use `npm ci` inside `frontend/` only (D-011). Versions, dates, licences and peer requirements were read from the npm registry on 2026-11-26.

### 4.1 In the application
| Package | Version | Licence | Why it is needed |
|---|---|---|---|
| `react`, `react-dom` | 19.3.1 | MIT | The interface library (D-001, D13). |
| `react-aria-components` | 1.22.1 | Apache-2.0 | Accessible behavior for menus, dialogs, selects and tabs, with its own right-to-left handling and Arabic strings (D13). |
| `@tanstack/react-query` | 5.107.1 | MIT | Server state with a cache that can be scoped and cleared per tenant (D13). |
| `@tanstack/react-router` | 1.170.46 | MIT | Routes and guards with typed parameters. Date ranges and filters of later slices live in typed, validated address parameters. |
| `react-intl` | 12.1.7 | BSD-3-Clause | ICU messages, with the six plural forms Arabic needs (D2, D13). |
| `openapi-fetch` | 0.17.0 | MIT | A small typed `fetch` client over the generated contract types (D13). |
| `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-sans-arabic`, `@fontsource/ibm-plex-mono` | 5.3.0 | OFL-1.1 | The three typefaces as local files, with no request to a font service (D7, D13). |

### 4.2 For building and checking only
| Package | Version | Licence | Why it is needed |
|---|---|---|---|
| `vite`, `@vitejs/plugin-react` | 8.3.8, 6.3.0 | MIT | Development server and production build (D13). |
| `typescript` | 5.9.3 | Apache-2.0 | Type checking (D13). |
| `openapi-typescript` | 7.13.0 | MIT | Generates the contract types from `contracts/openapi.json`. |
| `vitest`, `jsdom` | 5.1.0, 31.0.0 | MIT | Unit and component tests (D13). |
| `@testing-library/react`, `@testing-library/dom`, `@testing-library/user-event`, `@testing-library/jest-dom` | 16.3.3, 10.4.2, 14.6.9, 7.0.1 | MIT | Tests that use the interface as a person does: by role, label and keyboard. |
| `@playwright/test` | 1.64.1 | Apache-2.0 | Browser journeys (D13). The same release as the tracker package (D-033), so the browsers already on the workstation are used again. |
| `@axe-core/playwright` | 4.14.0 | MPL-2.0 | Automatic accessibility checks in the browser journeys (D12). |
| `eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y` | 9.39.5, 9.39.5, 8.72.2, 7.1.1, 6.10.2 | MIT | Static checks, with the accessibility rules for markup (D12) and the rules of hooks. |
| `@types/react`, `@types/react-dom`, `@types/node` | 19.3.0, 19.3.0, 24.19.2 | MIT | Type definitions. |

Thirty direct packages: ten in the application and twenty for building and checking.

### 4.3 Why some versions are not the newest
- TypeScript 5.9.3, not 7.0.2: `openapi-typescript` 7.13.0 accepts only TypeScript 5, and `typescript-eslint` 8.72.2 accepts versions below 6.1.
- ESLint 9.39.5, not 10: `eslint-plugin-jsx-a11y` 6.10.2 accepts ESLint up to 9.
- Playwright 1.64.1, not 1.65.1: it matches `packages/tracker-js` and its downloaded browsers.
- Nine packages have a newer release that is less than 14 days old: `@tanstack/react-query`, `react-intl`, `vitest`, `jsdom`, `@testing-library/user-event`, `@testing-library/jest-dom`, `@axe-core/playwright`, `typescript-eslint` and `@types/react`. The rule keeps the older one.
- Node.js 24.15 or later is required (`jsdom` 31). The workstation has 24.17.0, and `@types/node` follows the Node.js 24 line.

### 4.4 Deliberately left out of 018-A
Recharts (arrives with the charts of 018-C, pinned then), a form library, a state library, a mock server, an icon package (the icons are already CSS masks), Tailwind CSS and shadcn/ui (the alternative of D13, not chosen).

### 4.5 At installation
Packages that these thirty bring with them are fixed by the lockfile. The first install records the `npm audit` result, the licences of the full tree and the size on disk in the evidence file. A finding of high severity, or a licence other than MIT, Apache-2.0, BSD, ISC, OFL-1.1 and MPL-2.0, goes back to the owner before any code is written.

## 5. Screens of the slice
| Route | Screen | API operations |
|---|---|---|
| `/sign-in` | The approved sign-in screen: Google when enabled, email and password, "Forgot password?", the agreement box, the language switch, the moving picture with its pause control. | `POST /auth/login`, `GET /auth/google/start` |
| `/register` | Name, email, password with its length rule, the agreement box. | `POST /auth/register` |
| `/verify-email` | The six-digit code and "Send a new code", which waits 60 seconds. | `POST /auth/verify-email-code`, `POST /auth/resend-verification` |
| `/forgot-password` | One email field and the same acknowledgement for every address. | `POST /auth/forgot-password` |
| `/auth/reset-password` | A new password; the token comes from the link. | `POST /auth/reset-password` |
| `/auth/accept-invitation` | Sign in if needed, then accept. | `POST /invitations/accept` |
| `/auth/google/complete` | Continues after Google, or explains the error, including the case where an existing account must be linked first. | `GET /auth/me` |
| `/welcome` | A signed-in person without an agency creates one, or is told to wait for an invitation. | `GET /agencies`, `POST /agencies` |
| `/` | The shell: sidebar, top bar with the search pill, the agency in the switcher, the account menu with language and theme. Destinations of later slices are absent, not disabled. | `GET /auth/me`, `GET /agencies` |
| `/account` | Name and email, change password, sign out, sign out everywhere, link Google when enabled, close the account. | `POST /auth/change-password`, `/auth/logout`, `/auth/logout-all`, `/auth/google/link`, `/auth/close-account` |

Every screen has its loading, empty and error state from the design language. No screen shows sample data.

## 6. Checks that close the slice
| Check | What it proves |
|---|---|
| `tsc --noEmit` and ESLint with the accessibility rules | Types match the contract; markup rules hold. |
| The generated contract types are rebuilt and compared | The client cannot drift from `contracts/openapi.json`. |
| Unit and component tests | The token is sent on every mutation; a 401 clears the session and the cache; the error table covers every code of section 2; link tokens leave the address bar; language, direction and theme switch; field rules match the API limits. |
| Browser journeys in Chromium and Firefox against the real API on a disposable database, with local mail capture | Register, verify, sign in, create an agency, sign out; a wrong code; the rate-limit message; password reset through the captured link; Arabic from right to left; the dark theme; sign-in by keyboard only; the picture resting under reduced motion. |
| axe-core on every screen, both languages and both themes | No serious or critical finding. |
| Screenshots of the built sign-in beside the reference page at 1440 and 390 pixels | The built screen matches the approved design. |
| A search of the production build | No secret, key, token or backend setting in the bundle (acceptance criterion 5). |

Results go into `specs/018-react-workspace/evidence-018a.md`, with what was not run. Not covered by these checks: screen readers, Safari, real phones and usability with Arabic-speaking users. They stay listed as open.

The browser journeys never use the owner's `tracking_sys` database (D-015).

## 7. Prerequisites and risks
| Item | State | Handling |
|---|---|---|
| Disk space | 4.5 GB free on drive C on 2026-11-26. The install is estimated at 0.3 to 0.5 GB and is measured at the first install. | No browser is downloaded: the Chromium and Firefox of Playwright 1.64.1 already on the workstation (1.1 GB) are used through `PLAYWRIGHT_BROWSERS_PATH`. Nothing is deleted without the owner's word. |
| Safari | WebKit is not on the workstation. | Adding it is a download the owner decides separately. |
| Agreement to the terms | No record exists (D15). | The box is built and enforced in the interface; the limitation is stated in the evidence; the 002 amendment is a separate piece of work. |
| Controls without reference styles | The calendar of the date range and the command palette. | Neither is needed in 018-A. They are designed with the slices that use them. |
| Arabic copy | Written by a model. | Marked for review by a native editor before release (entry review, section 7). |

## 8. Order of work
Each step ends with its checks and a commit pushed to `codex/spec-018-react-workspace` (D-051). A pull request, a merge and any deployment remain the owner's decisions.

1. The owner approves section 4.
2. Skeleton: `package.json` with the exact versions, the lockfile, the configuration files and the scripts; the install evidence of section 4.5.
3. Styles, fonts, themes and direction; the shell without data; the first screenshot comparison.
4. The generated contract types, the client, the session and the error table, with their tests.
5. Sign in, register, verify, forgotten and reset password, Google completion, invitation.
6. First agency, the shell with real data, the account page.
7. Browser journeys, accessibility checks and the evidence file.
8. Documentation: how to run the application, and the records.
