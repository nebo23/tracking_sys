# First-party website tracker

A self-hosted native JavaScript module (ES2022, no runtime dependency, no bundler) that connects a client website to the specification 004 public collection routes under J1 strict opt-in. It is separate from the React dashboard. Specification 005 (D-033) defines its behavior; the backend applies every rule again, so the tracker never widens what the server accepts.

## What it does and does not do

- **Before an explicit consent action** it reads no storage, URL, referrer, cookie or form value, generates no identifier, sends no request and keeps no event backlog. Loading the module and registering DOM bindings is all that happens.
- `grant(choices)` sends the visitor's explicit choices once (`POST /collect/v1/{public_key}/consent`). Only purposes the response reports as granted are enabled.
- `resume(choices)` is for a decision your banner or consent platform already holds. It reads the stored token and asks `POST /collect/v1/{public_key}/consent-state`. It never grants, renews or recreates consent; unknown, withdrawn, expired or missing state stays blocked until a new explicit grant.
- `withdraw(purposes)` and `erase()` stop local collection immediately, discard affected queued events, and run after any pending consent request, so a late response can never re-enable capture. A failed withdrawal is retried in memory and reported as `confirmed: false`.
- A browser Global Privacy Control signal refuses `sale_or_share`, `ads.measurement` and `ads.personalization` grants before anything is sent. It never grants analytics or attribution. No jurisdiction profile beyond J1 is introduced.
- After permission, `sessionStorage` (key `ts:v1:<public key>`) holds only the subject token, the granted-purpose snapshot and a fixed local expiry at most 24 hours after first storage, never extended. If storage is unavailable the tracker keeps the token in memory only. It uses no `localStorage`, cookie, fingerprint or cross-site identifier. `sessionStorage` survives reloads and may be copied into a window opened from the page; open links with `rel="noopener"`. Tabs do not share consent, and a remote withdrawal reaches an open tab at its next state read (at most 60 seconds while collecting).
- Built-in capture: `trackPageView()`, `trackLinkClick(anchor)` and `trackForm(formKey, form)`, plus optional click and submit bindings. URLs are minimized in the browser with the same rules as the server (campaign parameters with analytics, click identifiers only with attribution, email-like and card-number values removed). A managed link's `ts_link` is moved from the URL into the envelope `link_id`; it is a link reference, never a visitor identifier.
- Forms: only configured fields of the classes `form.option`, `form.code` and `form.quantity` are considered. Password, hidden, payment (`cc-*`), one-time-code, email, telephone, textarea and unconfigured controls are excluded from their descriptors before any value is read. The tracker never uses `FormData` on a whole form. Email, phone, name and free text wait for specification 006.
- Transport: one event per `fetch` request with `credentials: "omit"`, no referrer and `text/plain` JSON (a CORS simple request). The in-memory queue holds at most 20 events and 128 KiB for 60 seconds; each event gets at most three attempts with jittered delays of about 1 and 4 seconds, or a readable `Retry-After` within the queue lifetime. A `202` is a generic acknowledgement, not proof of storage. Navigation and form submission never wait for telemetry, and tracking errors never reach the page.

This is not general personal-data detection, not a guarantee of delivery, and not legal compliance advice.

## Installation

1. Register a browser ingestion source for the client (exact site origins and the notice digest) and register each form with `PUT .../collection-forms/{form_key}`. The page configuration below must not exceed the registered form.
2. Copy `src/tracker.js` and `src/minimize.js` to your own site's static assets. No CDN is selected; serve the files from your origin with a version in the path.
3. Allow the collector origin in `connect-src` if your site uses a Content Security Policy.
4. Connect your consent banner to `grant`, `resume`, `withdraw` and `erase` (see [examples/install.html](examples/install.html)).

```js
import { createTracker } from "/assets/tracker-0.5.0/tracker.js";

const tracker = createTracker({
  collector: "https://collect.example.test", // exact origin of the Tracking System API
  publicKey: "pk_...", // public source key; never an ingest or read service key
  forms: { lead: { fields: [{ name: "plan", data_class: "form.option", options: ["basic", "pro"] }] } },
  bindings: { links: "a[data-track]", forms: { lead: "#lead-form" } },
});
```

Single-page applications call `trackPageView()` after each route change; the History API is not patched.

## Development and tests

Dependencies are project-local (D-011): Playwright 1.64.1 is the only development dependency, locked in `package-lock.json`. Browsers install into this package's `node_modules` (never a global cache):

```powershell
npm ci
npm run install:browsers
npm test                 # Node built-in test runner: state machine, storage, transport, parity
npm run test:browser     # real Chromium and Firefox through Playwright
```

`test/fixtures/parity.json` holds shared minimization fixtures whose expected values come from the Python contracts; `backend/tests/test_tracker_parity.py` asserts the same file. The backend journey test (`backend/tests/integration/test_tracker_journey.py`, enabled with `TRACKING_RUN_BROWSER_TESTS=1`) runs `test/e2e/journey.js` and `test/e2e/parity-page.js` against the real API on loopback and a disposable database.
