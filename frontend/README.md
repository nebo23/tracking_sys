# Frontend
Connect, the web application of the Tracking System (specification 018), in English and Arabic and in both themes.

- Slice 018-A: the toolchain, the stylesheet, the typed API client, the screens before the workspace, the workspace shell and the account page. See the [018-A evidence](../specs/018-react-workspace/evidence-018a.md).
- Slice 018-B: the agency and the client in the address, the list of clients with archived clients, the connections of a client, the members of an agency with their client access, invitations, API keys and the audit log. See the [018-B evidence](../specs/018-react-workspace/evidence-018b.md).

Both are presented for the owner's review; each evidence file says what was checked and what was not. Slices 018-C and 018-D are not started.

The agreement box of the sign-in and registration screens is enforced in the interface and recorded nowhere yet (D15). No real user may be given the application before that record and the legal texts exist.

## Requirements
- Node.js 24.15 or later and npm. Every package is local to this folder and pinned to an exact version; nothing is installed globally (D-011). Another package or another version needs an owner decision (D-084).
- For the browser journeys and the sandbox only: Docker, the project's Python virtual environment with the backend requirements, and the Chromium and Firefox builds of Playwright 1.64.1.

```powershell
npm ci
```

## Try the whole application on throwaway data
```powershell
npm run sandbox
```

This starts a PostgreSQL container of its own, applies the migrations, runs the real API on `http://127.0.0.1:8010` and serves the built application on `http://127.0.0.1:5183`. It then prepares an agency with three clients, three connected sample accounts and one invitation, and prints an email address and a password to sign in with; the password is random and lasts as long as the sandbox.

Mail is captured, never sent: every few seconds the terminal prints new messages, so the six-digit code of a registration and the link of an invitation or a password reset can be read there. The connector worker runs in the same rhythm, so a requested sync or removal is carried out. The sample accounts belong to stand-in providers that keep made-up data in files and contact nobody. A new sample account cannot be connected by hand, because a stand-in provider has no consent page a browser can open; the browser journeys stand in for it. Ctrl+C removes the container, its data and the captured mail. The owner's database is never used (D-015): the stack sets every database setting itself and checks them before it connects.

The stack looks for the Python interpreter of the project's virtual environment in `.venv` at the repository root, and for a git worktree at the root of the main checkout. Set `TRACKING_E2E_PYTHON` to its path when it is somewhere else.

## Develop against a local API
```powershell
npm run dev
```

The development server listens on `http://127.0.0.1:5173`, an origin the API already allows. It expects the API on `http://127.0.0.1:8000`; start it as the [local environment guide](../docs/engineering/local-environment.md) describes. That API uses the database of its own configuration, so accounts created this way are rows in that database: use synthetic people only, and read codes and links from its captured mail as the [authentication guide](../docs/engineering/authentication.md) describes.

Three settings exist, all public because they are compiled into the bundle that every visitor downloads. Copy `.env.example` to `.env.local` to change them:

| Setting | Meaning |
|---|---|
| `VITE_API_ORIGIN` | Origin of the API. The API must list this application's origin among its allowed origins. |
| `VITE_GOOGLE_SIGN_IN` | `true` shows the Google sign-in controls. The API must have Google sign-in enabled as well. |
| `VITE_SYNTHETIC_PROVIDERS` | `true` lists the stand-in providers when connecting an account. For local development against an API that has `TRACKING_CONNECTOR_SYNTHETIC_STATE` set, and for the journeys. Never in a build for real users. |

Never put a secret in a `VITE_` setting.

## Checks
| Command | What it checks |
|---|---|
| `npm run typecheck` | Types, including every call against the API contract. |
| `npm run lint` | Static rules, with the accessibility rules for markup and the rules of hooks. |
| `npm run api:check` | `src/api/schema.d.ts` equals what `contracts/openapi.json` generates. Run `npm run api:types` after the contract changes. |
| `npm test` | Unit and component tests in jsdom, with a stand-in API. |
| `npm run build` | Type check and production build into `dist/`. |
| `npm run build:check` | Searches `dist/` for secrets, keys, tokens and backend settings. |
| `npm run test:browser` | The journeys in Chromium and Firefox against the real API on the disposable stack, with axe-core on every screen. Add `-- --project=chromium` for one browser. |

The journeys need to know where the Playwright browsers are. Where they were installed inside another package of this repository, point Playwright at them; otherwise install them (a download of about one gigabyte):

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "<folder that holds chromium-1248 and firefox-1555>"
```

```powershell
npx playwright install chromium firefox
```

A journey that fails leaves a trace and a screenshot in `test-results/`.

## Layout
```
index.html, vite.config.ts, tsconfig.json, eslint.config.js, playwright.config.ts
scripts/                    contract drift check, bundle search
src/
  main.tsx                  start: link token, preferences, router, session watch
  app/                      providers, routes and guards, session life cycle, the agency and client of a page, preferences, shell
  api/                      generated contract types, client, session, agencies, clients, connections, invitations, keys, error table
  components/               thin wrappers over the reference markup
  features/auth/            sign in, register, verify, forgotten and reset password, invitation, Google completion
  features/agency/          first agency
  features/account/         account page, account closure
  features/clients/         the list of clients, add and rename
  features/connections/     the accounts of a client, connect, the return from a provider
  features/team/            members, their client access, invitations and roles
  features/audit/           the audit log and the sentence of each action
  features/keys/            API keys
  i18n/                     en.json and ar.json with the same keys
  lib/                      small helpers: link tokens, safe return path, field rules
  styles/                   one entry that imports the design files, and app.css
tests/
  unit/                     Vitest and Testing Library
  browser/                  Playwright journeys; support/ holds the disposable stack
```

## Rules of this application
- **Styles.** The stylesheet is `docs/design/`: its tokens, icons and component rules are imported from there, so the application cannot drift from the design the owner reviewed. Components use those class names (`l-`, `c-`, `u-`, `is-`). `src/styles/app.css` holds only what a running application needs around them, with the prefix `a-`. No utility framework and no second styling vocabulary.
- **Text.** No sentence is written in a component. Every message has a key in `src/i18n/en.json` and `ar.json`; a key missing from Arabic is a type error and a test failure. Arabic uses Western digits and the Gregorian calendar (D3).
- **Session.** The session is an `HttpOnly` cookie this code never sees. The request-forgery token comes from sign-in and from `GET /auth/me`, lives in memory only, and goes on every mutation.
- **Secrets in transit.** A password, a code or a link token travels in a request body and nowhere else: not in an address, not in storage, not in the query cache, not in a log. The token of a mail link is taken out of the address bar before the router reads the address.
- **Tenants.** The address names the agency and the client of a page, and it is not permission: the API decides, and what it refuses is shown as "not found". Data that belongs to one agency is cached under a key that starts with that agency, and data of one client under a key that also carries the client. Leaving a client removes its data, a move to another agency removes the data of the first, and signing out or an ended session empties the cache.
- **Roles.** The interface shows a person what their role may do and hides the rest. The API refuses it in any case; hiding is not the protection.
- **Providers.** The application follows the address the API hands over for an authorization only when it is an https address. The code and the state of an authorization travel between the provider and the API and never through the application. A key the API issues is shown once and kept nowhere.
- **Redirects.** After sign-in the application goes only to a path of its own.
- **Markup.** No `dangerouslySetInnerHTML`. Text from the API is rendered as text.
- **Errors.** `src/api/errors.ts` maps every error code of the API to one sentence in both languages. A unit test reads the API source and fails when a code has no sentence.
- **Honest screens.** A destination appears when it works. No screen shows sample data.
