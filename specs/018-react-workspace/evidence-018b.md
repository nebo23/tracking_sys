# 018-B evidence

Status: the parts of slice 018-B that the present API can back are implemented and checked as described here on 2026-11-26, and pushed to `codex/spec-018-workspace-screens` (D-051, D-093). The members tab, the grants of a member, archived clients and the audit log are not built: they wait for the owner's decision on the API amendment of the [018-B plan](plan-018b.md), section 3.2. The slice is not accepted until the owner has reviewed it. A pull request for it, the merge and any deployment are the owner's decisions. Section 7 lists what was not run and section 8 what is open.

How to run the application and its checks is in the [frontend guide](../../frontend/README.md).

## 1. What did not change
| Area | State |
|---|---|
| Packages | None added and none changed: `frontend/package.json` and `package-lock.json` are those of 018-A (the thirty packages of D-084). |
| API, contract, schema | Nothing in `backend/` or `contracts/` changed. `npm run api:check` still matches the contract of 147 operations. |
| Reference styles | Nothing in `docs/design/` changed. The new screens use the existing classes; `frontend/src/styles/app.css` gains rules of the running application only (prefix `a-`). |
| Pull request 17 | Untouched. This work is on a branch stacked on the 018-A branch (D-093). |

## 2. What was built
| Part | Where | What it does |
|---|---|---|
| Addresses | `frontend/src/app/router.tsx` | The agency and the client are part of the address: `/agencies/{agency}/clients`, `/team`, `/keys` and `/agencies/{agency}/clients/{client}/connections`. `/` leads to the clients of the agency the person last worked in. An agency the person does not belong to, a client the API refuses, something that is not an identifier, and a page of the managers opened by another role all show "not found". |
| Shell | `frontend/src/app/shell/` | The two levels of D11: the agency level (Clients; Team and access and API keys for owners and admins) and the client level (Manage: Connections). One switcher names where the person is and moves between clients and agencies. The breadcrumb leads from a client back to its agency. The phone tab bar follows the level. |
| Tenant data | `frontend/src/app/agency.ts`, `tenant.ts`, `frontend/src/api/clients.ts` | Every key of client data carries the agency and the client. What was loaded for a client is removed when the person leaves it, and what was loaded for an agency when they move to another (acceptance criterion 2). |
| Clients | `frontend/src/features/clients/` | The list, in the order of the names, with each client's connected providers, last synchronization and state; three summary figures; search; add and rename for owners and admins. A long list is read to its end, 100 at a time. |
| Connections | `frontend/src/features/connections/` | A card per account: provider, account, status, freshness, the latest run with its reason and next attempt, the covered range and state of each stream, and the allowance of the day per limit. Connect with what the provider needs (the number of an ad account, or the account holder's approval), synchronize, reconnect, disconnect after a second question, past connections with the outcome of their removal, and the return from a provider. |
| Team and access | `frontend/src/features/team/` | Invitations: the list with pending, accepted, expired and withdrawn; invite with a role and, for an analyst or client viewer, the clients they may open with financial data per client; withdraw. What each role can do. |
| API keys | `frontend/src/features/keys/` | The list with active, expired and revoked; create with kind, clients and lifetime; the key shown once; revoke after asking. |
| Stand-in providers | `frontend/tests/browser/support/stack.ts`, `tenants.ts`, `frontend/src/features/connections/providers.ts` | The disposable stack registers the synthetic providers of specifications 009 to 014, which keep made-up accounts in files and contact nobody. A build setting, off by default, lists them in the connect dialog. The journeys stand in for a provider's consent page and for the connector worker. |
| Sandbox | `frontend/tests/browser/support/sandbox.ts` | `npm run sandbox` now prepares an agency with three clients, three connected sample accounts and an invitation, prints a sign-in for it, and runs the connector worker beside the mail delivery. |

## 3. Checks on 2026-11-26
Environment: Windows 11, Node.js 24.17.0. All of them ran on the final code.

| Check | Command | Result |
|---|---|---|
| Types | `npm run typecheck` | No error. |
| Static rules | `npm run lint` | No finding. |
| Contract types | `npm run api:check` | `src/api/schema.d.ts` equals what `contracts/openapi.json` generates. |
| Unit and component tests | `npm test` | 335 tests in 18 files pass (about 15 seconds). 018-A had 199 in 14. |
| Removed protections | scratch tool, not in the repository | Each of 41 protections of this slice was removed in turn; every time at least one unit test failed, and the file was restored byte for byte. Section 3.1. |
| Production build | `npm run build` | 94 files, 2,505 KiB. One script of 769 kB (227 kB compressed) and one stylesheet of 150 kB (34 kB compressed); the rest are font files. |
| Bundle search | `npm run build:check` | No secret, key, token or backend setting. |
| Journeys in Chromium | `npm run test:browser -- --project=chromium` | 46 of 46 pass in 4.5 minutes. Chromium 156.0.8078.4 (Playwright 1.64.1, build 1248). |
| Journeys in Firefox | `npm run test:browser -- --project=firefox` | 46 of 46 pass in 5.9 minutes. Firefox 157.0 (build 1555). |

The journeys ran with one worker and no retry.

### 3.1 Protections whose removal a unit test catches
- **Addresses.** An agency the person does not belong to shows "not found"; so does a page of the managers for another role, and a client the API refuses. Only an identifier is sent to the API as a client, by the route and by the shell. The start address follows the agency last worked in.
- **Tenant data.** The data of a client is removed when the person leaves it, and the data of an agency when they move to another; only the data of other agencies is dropped.
- **Roles.** A client viewer is not asked for the agency profile, in the shell and in the switcher. Team and keys, "Add client", "Rename", "Connect account" and "Sync now" are offered to managers only. Only an owner is offered the owner role, and only an owner withdraws an owner invitation.
- **Lists.** Clients are listed in the order of their names. A paged list is read to its end. A removed connection is not counted. No figure is drawn while a client could not be read.
- **Connections.** The application follows only an https address. The record of a started connection must hold two identifiers and serves one return. The account holder's approval is needed before connecting and again before reconnecting; the ad account number is checked. Disconnecting needs the tick. The outcome of a return is said once, and only the fixed outcomes are read from either address. No second sync is offered while one is under way. A lasting state is not announced as news.
- **Invitations and keys.** A manager role carries no client grants, and a restricted role needs at least one client. Financial data is granted only with the client. A pending invitation and an active key past their time are expired. A key that only sends events never carries financial access. The new key is not kept by the request.

### 3.2 Unit tests that read the API source
As in 018-A, some tests compare the interface with the repository, so a change of the API fails a test instead of drifting:

- the outcomes of a return from a provider equal `CALLBACK_ERRORS` in `backend/app/services/connectors.py`;
- every code that the connection operations can raise has a sentence;
- every stream an adapter declares, and every reason for which the API stops or removes a connection, has a name;
- the approval version, the pattern of an ad account number and the longest key name equal those of the API and the contract.

### 3.3 Journeys
All of them use the real API on the disposable stack. Each journey creates its own synthetic people, agencies and clients.

| File | What a person does | What it proves |
|---|---|---|
| `01` to `12` | The journeys of 018-A, brought to the new first page. | A new agency opens on its list of clients. The Arabic journey now checks the mirrored table, the day `26 نوفمبر 2026` with Western digits and the address typed left to right. The keyboard journey reaches the top bar by going back from the content. |
| `06-keyboard` (third case) | Adds a client, opens another and returns to the list with the keyboard alone. | A dialog opens from its button, keeps focus inside and gives it back on Escape; Enter in the field adds the client and focus lands on the heading of the new page; the switcher is a menu the arrow keys move through. |
| `13-clients` | An owner adds two clients, opens them from the list, the breadcrumb and the switcher, renames one, searches, reloads. | The whole path from an empty agency. A reload stays on the page the address names. |
| `13-clients` (second case) | An owner opens addresses of another agency and of its client. | An address is not permission: every one of them shows "not found", and nothing of the other agency is drawn. |
| `13-clients` (third case) | An analyst who was given one of two clients signs in. | The API lists only the granted client; the analyst has no way to add, rename, connect, invite or create a key; the other client and the managers' pages do not exist for them. |
| `14-connections` | An owner connects a sample account, sees it synchronize, asks for a sync, is refused at the provider, tries the same account twice, and disconnects. | The browser leaves for the provider and returns connected; the code and the state of the authorization never travel through the application and are in no storage; the outcome leaves the address and a reload does not repeat it. Before the first read nothing is called fresh. The card follows the worker without a reload. A refusal at the provider and an account that is already connected are each a sentence. Disconnecting is asked twice, and after the worker's pass the account is listed as past with its data removed. |
| `14-connections` (second case) | An owner connects a sample YouTube channel. | The approval of the account holder is asked for and refused without the tick; the channel's four streams and two daily limits are each shown by name. |
| `15-team-keys` | An owner invites an analyst with one client and its financial data, is refused a second invitation to the same person, invites a client viewer and withdraws that invitation. | The invitation mail is captured and its link works: the analyst signs in, accepts and sees only the granted client. The list shows waiting, accepted and withdrawn. A withdrawn link lets nobody in. |
| `15-team-keys` (second case) | An owner creates a key for one client, uses it, revokes it. | The key is shown once and is in no storage, in no address and, after the dialog, nowhere on the page. Used from outside the browser it reads exactly the client it was given; after a revoke the API answers 401. |

### 3.4 Accessibility checks
axe-core 4.14.1, with the rules tagged WCAG 2.0, 2.1 and 2.2 at levels A and AA (D12).

- Screens added in this slice: the list of clients, the client and agency menu, the add-client dialog with an error, the connections of a client, the connect dialog with an error, the disconnect dialog with an error, team and access, the invite dialog with errors, the role list, the keys page empty and with a key, the key dialog, the key shown once, and "not found" inside the workspace.
- Looks: English light, English dark, Arabic light, Arabic dark, plus the list of clients, the connections and the connect dialog at 390 pixels.
- Result: 137 scans in each browser, and no finding of any impact in either browser. At 390 pixels nothing spills past the edge of the page.

axe-core finds what a machine can find. It does not replace the checks of section 7.

### 3.5 Looking at the screens
The screens were also reviewed as pictures on the disposable stack: every new screen in English, and the list of clients, the connections and the team page in Arabic, in the dark theme and at 390 pixels. Section 5 lists what that review changed.

## 4. Isolation of the checks
- The journeys and the sandbox use the Compose project `tracking-e2e-frontend` only, as in 018-A. Before anything connects, the stack now also confirms that the stand-in providers are the only ones registered: the live Instagram, YouTube and Meta adapters are off, and the provider callback and return address are those of the stack.
- The stand-in providers are files inside the stack's own folder, removed with it. Their authorization addresses are under the reserved `.invalid` domain, which resolves nowhere. No provider was contacted and no message left the workstation.
- The owner's database `tracking_sys` was not used (D-015). Another disposable container of another session, `tracking-test-016b-database-1`, was running throughout and was not touched.

## 5. Corrections found by tests and by looking
1. Removing the data of an agency or a client before the next page was drawn only had it loaded again, because the page being left asked once more. It is now removed after the new page is drawn. A unit test found it.
2. The shell asked the API for a client whose place in the address did not hold an identifier. The address now counts only when it holds identifiers. A unit test found it.
3. The notice after a return from a provider was repeated on every reload. The outcome is now said once and removed from the address.
4. A select showed the meaning of the chosen option twice. The button now shows the name of the choice only.
5. The initials of "Olive & Thyme" were "O&". A word that does not start with a letter or a digit is passed over.
6. A day written in digits alone read ambiguously beside Arabic text. A day is now written with its month as a word in both languages and is not broken across two lines.
7. Three items of the journeys' own support: each stand-in provider has an address of its own; an account may sign in only a few times a minute, so a journey that prepares several things signs in once; and Firefox does not wrap from the last control of a page to its first, so the keyboard journey goes back as a person would.
8. Carried from the 018-A evidence, section 8.2: a request of the journeys that meets a connection the API has just closed is sent once more.

## 6. Differences from the plan
| Plan | What was done | Why |
|---|---|---|
| Section 5: the clients page shows summary tiles. | Three figures: clients, connections that need a reconnect, and clients with nothing connected. | "Stale" is not counted there; freshness is part of each connection's coverage (plan, section 3.1). |
| Section 4.5: a connection's state from the API. | As planned, and the allowance of a provider with several limits is one meter per limit. | The YouTube adapters report two. |
| Not in the plan. | The sandbox prepares an agency with clients and sample accounts. | So the owner can look at the screens with something in them. A new sample account cannot be connected by hand there, because its provider's consent page exists only in the journeys. |
| Not in the plan. | `VITE_SYNTHETIC_PROVIDERS`, a third public build setting, off by default. | The stand-in providers must be listed for the journeys and never in an ordinary build. A unit test checks the ordinary list. |
| 018-A evidence, section 8.2: split the script by route. | Not done. The script is 227 kB compressed, 31 kB more than in 018-A. | Carried to 018-C, where the chart library makes the split worth its cost. |

## 7. Not run
- A real provider. Instagram, YouTube and Meta need their own approvals, test accounts and an HTTPS address (010-D, 011-D, 014, 020). The connect and reconnect screens for them are covered by unit tests with a stand-in API.
- A reconnect through a browser. The screens are covered by unit tests; the journeys do not make a stand-in account stop working.
- A history request for older days. The API offers it; no control of this slice asks for it.
- A list of more than 100 clients, a person with two agencies, and a client viewer, in a browser. Unit tests cover them.
- Screen readers, voice control, Safari and real phones; usability with Arabic-speaking users; a native editor's review of the Arabic copy, which a model wrote.
- Load time and performance.
- Anything over HTTPS, and a content security policy (specification 020). The coverage bar and the allowance meter set their widths as inline styles, which such a policy must allow or which must then move to classes.

## 8. Open
### 8.1 For the owner to decide
1. **The API amendment of the plan, section 3.2.** Until it is decided, the team page lists invitations only, a client cannot be archived, and there is no audit log page.
2. **The wording of the account holder's approval** (specification 011, D13). The sentence in the connect dialog is provisional in both languages; the version the API records stays `dev-agent-approval-1` until the owner supplies the text.
3. **Whether a client viewer sees the connections** (entry review, section 6). In this slice they read them and change nothing, as the API allows.
4. **Which providers a server offers.** No operation lists them, so the dialog offers Instagram, YouTube and Meta ads and reports an unavailable one only after it is chosen.
5. **The package list of 018-C.** D-083 approved Recharts as a family. By the rule of the 018-A plan the version would be 3.10.1, with its peer `react-is`, and `@internationalized/date` 3.12.4 for the date range, which is already installed as part of React Aria Components. The 018-C plan will name them for approval.
6. A pull request for these slices, and the merge of pull request 17.

### 8.2 Carried to later slices
- Overview, content, revenue and ad spend (018-C); links, tracking and integrations, with Paymob, Cal.com, WhatsApp and the conversion destinations (018-D).
- Splitting the script by route (section 6).
- The open items of the 018-A evidence, section 8.1, which this slice does not change.
