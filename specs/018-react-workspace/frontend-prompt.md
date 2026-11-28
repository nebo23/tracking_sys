# Prompt: build the Connect web application with its approved design

Status: prepared on 2026-11-28 at the owner's request, for the implementing model (Claude Code or Codex) working in this repository. It describes the whole frontend of specification 018 as the owner approved it on the design canvas: the screens A01 to G06 and E03 to E08 of [screens-a-to-z.md](screens-a-to-z.md). It records no new decision. Use it to build the frontend from nothing with the same design, or to check an existing build against the design; the build on `codex/spec-018-workspace-screens` follows it and is the reference for behavior.

---

## 0. Start here: the first message
Paste this as the first message of a new session. It says where the work starts; the rest of this prompt is the brief it points to.

```text
You are continuing Spec 018, the Connect web application, in this repository.
Work with the owner in Arabic; write files, code, comments and commits in formal English.

1. Read AGENTS.md, then specs/018-react-workspace/frontend-prompt.md: it is the full brief
   (sources of truth, design, screens, rules and checks).
2. Find where the work stands before you change anything:
   - Fetch, then work on codex/spec-018-workspace-screens unless the owner names another branch.
     Read its latest commits, its open pull request and the latest plan and evidence files in
     specs/018-react-workspace/.
   - If frontend/ does not exist, start with step 1 of section 8 of the brief: the toolchain,
     the design styles and the screens before signing in (A01 to A10).
   - If it exists, run npm ci, npm run typecheck, npm run lint and npm test in frontend/,
     compare the built screens with specs/018-react-workspace/screens-a-to-z.md, and continue
     with the first screen or check that is not done.
3. Plan the next slice (plan-018x.md), build it, run its checks, write its evidence
   (evidence-018x.md), commit and push the branch. Ask the owner first about anything that needs
   a decision: a new package, a new screen, a change of an approved design, or anything the API
   cannot give.
```

## 1. Your task
Build the web application of Connect in `frontend/` so that every screen looks and behaves as the owner approved it, against the real API, in English and Arabic, light and dark, on a desktop and on a phone. Keep the addresses, the texts, the rules and the checks of this prompt. Where a screen already exists, keep its behavior and its tests unless this prompt says otherwise.

Connect is a multi-agency product (D-004): an agency connects its clients' social, advertising and business accounts, tracks visits through managed links and website tracking, and sees which content brings visits, leads and paid sales. Every screen serves one agency, and inside it one client.

Work with the owner in Arabic; write files, code, comments and commit messages in formal English (AGENTS.md).

## 2. Read first
1. `README.md`, `AGENTS.md` and `docs/planning/decisions.md` (above all D-082, D-083, D-084, D-105, D-106 and D-107, and the numbering notes at its top).
2. `specs/018-react-workspace/`: [spec.md](spec.md), [entry-review.md](entry-review.md), [entry-review-completion.md](entry-review-completion.md), [screens-a-to-z.md](screens-a-to-z.md), and the plans and evidence of each slice (018-A to 018-G).
3. The design: [docs/design/README.md](../../docs/design/README.md), `docs/design/tokens/tokens.css`, `docs/design/ui/connect-ui.css`, `docs/design/ui/connect-icons.css`, `docs/design/brand/`, and the reference pages in `docs/design/preview/screens/` (their list is `docs/design/preview/screens.html`).
4. The API: `contracts/openapi.json`, and the services under `backend/app/` whose rules the screens repeat (each section below names them).
5. The frontend guide `frontend/README.md`, and the code under `frontend/src` and `frontend/tests` when it exists.

The repository is the source of truth. The design canvas "Connect App Screens" is a review copy of it.

## 3. Stack and boundaries
- **Packages (D-084, D-106).** React 19.3.1 and React DOM, TanStack Router 1.170.46 and TanStack Query 5.107.1, React Aria Components 1.22.1, react-intl 12.1.7, openapi-fetch 0.17.0 with types generated from the contract (`npm run api:types`, checked by `npm run api:check`), Recharts 3.10.1 with react-is 19.3.1, and the IBM Plex fonts from `@fontsource` (Sans, Sans Arabic, Mono). Development: Vite, TypeScript, ESLint, Vitest with Testing Library and jsdom, Playwright 1.64.1 with axe-core. Exact versions, from `frontend/package.json` and its lockfile. No other package, no CSS framework and no CSS-in-JS without a recorded decision.
- **No change to the API, the contract or the schema.** What the API cannot give is a decision for the owner, never a workaround in the browser.
- **Data and environments.** Synthetic data and the disposable stack only (`frontend/tests/browser/support/stack.ts`: Docker Compose project `tracking-e2e-frontend`); never the owner's database `tracking_sys` (D-015). No live provider, no external email (local `.eml` capture), no deployment.
- **Secrets.** Nothing secret in the bundle (`npm run build:check` fails otherwise). The session is the API's cookie; the CSRF token lives in memory only; tokens of mail links are read once and removed from the address; signed or one-time values are never stored or logged.

## 4. The design language
Use the reference styles as they are; do not restyle components.

- **Names.** `l-` for layout, `c-` for components, `u-` for utilities and `is-` for states come from `connect-ui.css`. Rules only the application needs live in `frontend/src/styles/app.css` with the prefix `a-`, and take every value from the tokens.
- **Color.** Every color is a token of `tokens.css`: the brand teal from `--brand-50` (#eefaf8) to `--brand-950` (#02282c), with `--brand-600` (#007a79) as the primary action; the neutrals; and success, warning, danger and info. The dark theme swaps the semantic tokens; components never pick colors of their own. The only exception is the sign-in picture, which uses the token values as hex inside its SVG.
- **Type.** IBM Plex Sans for Latin text, IBM Plex Sans Arabic for Arabic, IBM Plex Mono for codes and keys; sizes and lines from the `--type-*` tokens. Arabic numbers are written with Latin digits (`ar-u-ca-gregory-nu-latn`).
- **Space, radius, shadow.** From the tokens (`--space-*`, `--radius-*`, `--shadow-*`).
- **Icons.** The Lucide shapes of `connect-icons.css`, drawn by class (`c-icon c-icon--<name>`); decorative icons are hidden from assistive technology; icons that point a way are mirrored right to left.
- **Logo.** "Pure magnet" (D-082): the C drawn as a horseshoe magnet with teal pole tips; the Arabic lockup in Arabic; the reversed files on dark backgrounds.
- **Motion.** Rare and purposeful. The only loop is the sign-in picture; it rests under reduced motion and can be paused.

## 5. The two layouts

### 5.1 Before signing in (A01 to A10, F04)
- Two equal columns from 900 pixels wide; below that, the form alone. The layout fills the whole height of the window.
- **The brand side** (dark `--brand-950`, with a soft teal light behind the magnet): the reversed logo; the picture; the statement "Turn your content into a sales magnet." (36/44, semibold, two lines); two points with a check ("See which posts pull in visits, leads and paid sales." and "Put your time and budget where the sales come from."); and at the bottom the note "Read-only connections. Connect never posts or charges." with a control that pauses the picture.
- **The picture (D-105)** is the redrawn one of `docs/design/preview/screens/sign-in.html`, drawn by `frontend/src/components/PullPicture.tsx` with the `c-pull` rules of `connect-ui.css`:
  - the Connect C as a large steel magnet with teal pole tips;
  - its field drawn as loops of dotted "iron filings" that drift from pole to pole;
  - three tracks of people who turn into gold coins near the magnet;
  - a gold coin held in its mouth.
  The picture runs to the end edge of the brand side. In Arabic it is mirrored, so the magnet stands at the start of the line as in English. There is no example sale card. The loop lasts 7.2 seconds; under reduced motion the travellers rest at nine places; the pause control stops every part of it.
- **The form side.** The language switch sits in the top corner at the end of the reading direction. The form is centered, at most 440 pixels wide. "Forgot password?" sits under the password field in a quieter color. A box that starts unticked asks for agreement to the Terms of Service and the Privacy Policy, and the current agreement versions are sent at sign-in and registration (017-A).

### 5.2 The workspace (every other screen)
- **Sidebar:** the logo; the switcher of the agency and the client; the navigation; Account at the end.
  - At the agency level: Clients; then the group Agency with Team and access, API keys and Audit log for owners and admins, and Agency settings for everyone except client viewers.
  - Inside a client: Overview; Analyze (Content, Revenue, Ad spend, Attribution); Collect (Links, Website tracking, Integrations); Manage (Connections, Reports).
- **Top bar:** the breadcrumb (agency, client, page) and the account menu.
- **Page:** a page head (title, lead and actions), then cards, tables and tabs from the reference styles. Tabs and choices that change what a page shows are kept in its address.
- **On a phone:** a top bar with the mark and a compact switcher, and a bottom tab bar of five places. Inside a client these are Clients, Overview, Attribution, Links and More; More opens the rest of the client's menu and Account.

## 6. The screens
Codes, names and states follow [screens-a-to-z.md](screens-a-to-z.md); the reference page or the built screen of each code is its design.

| Codes | Screens | Address | Built on |
|---|---|---|---|
| A01 to A04 | Sign in; with what is missing; the terms changed; in Arabic | `/sign-in` | `POST /auth/login`, `GET /auth/agreements`, Google start |
| A05, A06 | Create an account; confirm the email address with its code | `/register`, `/verify-email` | `POST /auth/register`, `POST /auth/verify-email-code` |
| A07, A08 | Forgotten password; choose a new password | `/forgot-password`, `/auth/reset-password` | password reset routes |
| A09, A10 | An invitation while signed out; the first agency | `/auth/accept-invitation`, `/welcome` | invitations, `POST /agencies` |
| B01 to B03 | Clients, archived clients, adding a client | `/agencies/{a}/clients` | clients routes |
| B04 to B07 | Members, a member's access, invitations, inviting | `/agencies/{a}/team` | members and invitations (D-101) |
| B08 to B10 | API keys, creating one, the key shown once | `/agencies/{a}/keys` | service keys |
| B11 | Audit log | `/agencies/{a}/audit` | audit routes |
| B13, B14 | Agency settings: plan and usage, branding, closing the agency | `/agencies/{a}/settings` | 017-A plan and closure, 016-C branding |
| B15 | The agency is closing | `/agencies/{a}/closing` | closure routes |
| C01 to C04 | Overview (light, dark, Arabic, phone) | `/agencies/{a}/clients/{c}` | 016-A reports |
| C05 to C07 | Content, Revenue, Ad spend | `.../content`, `.../revenue`, `.../ad-spend` | 016-A social, revenue and spend reports; names from the 014 read |
| C08 to C10 | Attribution: credit, funnel, return on ad spend | `.../attribution` | 016-B reports |
| D01 to D08 | Links, their tabs, a new link, a DNS record shown once | `.../links` | 005 routes |
| D09 to D12 | Website tracking, a new source, the install code, erasing a visitor | `.../tracking` | 004 routes |
| D13 to D16 | Integrations: payments, bookings and CRM, WhatsApp, Meta conversions | `.../integrations` | 014 and 015 routes |
| E01, E02 | Connections, connecting an account | `.../connections` | 009 to 011 routes |
| E03 to E08 | Reports: exports, schedules, saving an export, the schedule form, the export a report email opens, an export that is gone | `.../reports`, `.../reports/exports/{id}` | 016-C routes |
| F01, F02 | Account, closing the account | `/account` | account routes |
| F03, F04 | A page that does not exist; the server cannot be reached | any address | |
| G01 to G06 | The same screens on a phone, in Arabic and dark | | |

Not to build without a decision: the concepts B12 (Privacy and data), C11 (the journey of one conversion) and F05 (Search), the agency's brand on the screens of client viewers, printable pages and PDF files.

## 7. Rules every screen keeps
- **Tenants.**
  - Every query is keyed under its agency, and under its client inside one; leaving a client or an agency drops what was loaded for it.
  - An address is not permission: what a person may not see answers "Page not found", the same as what does not exist.
- **Roles.** Owners, admins, analysts and client viewers see what 002 allows. The API decides; the interface hides only what it would refuse, and says so when it refuses anyway.
- **States in words.** A missing, unsupported, not synchronized, partial, unavailable, stale or provisional value is named, never shown as 0. The reason codes and states the interface knows are compared with `backend/app/reporting/` and the services by unit tests.
- **Days.**
  - A range is `from` and `to`, both included, in the address.
  - Default ranges end on the last complete UTC day and last at most 31 days.
  - The explicit "Last 30 days, up to today" marks today as provisional and never compares it.
  - A report holds its own days only; the previous period comes from its own report.
- **Money and shares.**
  - Amounts are the API's decimal text, formatted with `Intl.NumberFormat` in the currency of each amount; shares use their exact decimal.
  - A refused finance report shows "Needs financial access" and keeps everything that does not need it.
- **Errors.**
  - Every API code has its sentence.
  - A rate limit says how many seconds to wait.
  - A plan limit names the limit, its value and its use, and links owners and admins to Plan and usage.
  - A closing agency opens only its closing page.
- **Forms.** Values are checked before sending, with the API's own rules and bounds (unit tests read those rules in the backend). The first invalid field takes focus; problems are announced.
- **Reports and exports.**
  - The direct CSV of a report downloads through the API.
  - Retained exports and schedules follow 016-C: at most 50 unexpired exports and 10 active schedules per client, and 20 recipients per schedule.
  - Only members who may read the report can be recipients.
  - A gone export says why and when.
- **Languages.** Every text is a message in `frontend/src/i18n/en.json` and `ar.json`, under the same keys and with the same arguments. Arabic reads right to left; the layout mirrors, numbers stay Latin, and charts keep time running left to right.
- **Accessibility (WCAG 2.2 AA).**
  - Everything works by keyboard, with visible focus.
  - Every control and region has a name; dialogs keep focus and return it.
  - Wide tables scroll inside a focusable, named region on a phone.
  - Motion respects reduced motion.
  - Contrast comes from the tokens.
- **Loading by route (D4).** The entry screens load at once; every workspace page loads with its route. The first page must not load the charts or the workspace screens (`npm run build:check`).

## 8. How to work
- One slice at a time, each with a plan (`plan-018x.md`), its checks, its evidence (`evidence-018x.md`), one commit and a push of the branch (D-051). Pull requests, merges and deployment remain the owner's decisions.
- Order, when building from nothing:
  1. the toolchain, the design styles and the entry screens;
  2. the shell and the agency's screens;
  3. Collect;
  4. Analyze and Attribution;
  5. Agency settings and Reports;
  6. the final verification.
- Before a new screen, a new package, a change of a drawn design or anything the API cannot give, ask the owner in Arabic with a concrete proposal; record the answer as a decision with the next free number (check `main` and the other branches first).
- Unit tests read the backend's constants and codes instead of copying them. For every protection you add, remove it once, show that a named test fails, and restore the file byte for byte.

## 9. Done means
- `npm ci`, `npm run api:check`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build` and `npm run build:check` pass.
- The browser journeys of `frontend/tests/browser/` pass in Chromium and Firefox on the disposable stack, run in groups (`0*`, `10` to `12`, `13` to `16`, `17` onward). They cover sign-in and registration, Arabic, theme, keyboard, motion, the session, invitations, the clients, connections, team and keys, members and the audit log, links, tracking, integrations, Analyze, Attribution, Agency settings and Reports.
- Journey `10-accessibility` reports no axe finding on every screen and dialog, in the four looks (English and Arabic, light and dark) and at 390 pixels. Journey `11-design` measures the sign-in screen against its reference page.
- At 390, 768, 1024 and 1440 pixels no page is wider than the window.
- The evidence of each slice records every command with its counts, what could not be checked, and the limits.

## 10. Report
Tell the owner in Arabic:
- what was built, screen by screen with the A to Z codes;
- the checks actually run, with counts;
- what could not be checked;
- the limits, and what waits for a decision.
