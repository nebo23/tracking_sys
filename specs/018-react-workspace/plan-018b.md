# 018-B plan: clients, team and access, connections

Prepared: 2026-11-26, after D-090. Status: in implementation under D-090 on `codex/spec-018-workspace-screens`, with the thirty packages of the [018-A plan](plan-018a.md) and no other. Section 3 lists what the API cannot supply for the approved screens; the parts of the slice that depend on it wait for the owner's decision on section 3.2. Results go into the 018-B evidence file when the slice is checked.

## 1. Goal and boundaries
018-B is the second slice of [specification 018](spec.md) (D14 of the [entry review](entry-review.md)). After it, a person can move between the agency and one client, manage the clients of the agency, invite people, issue keys, and connect, watch and remove the accounts of a client, in English and Arabic and in both themes, on the reference styles the owner approved.

In scope:

- The agency and the client in the address, and the two levels of navigation (D11) with one switcher.
- Clients: the list with the state of each client's connections, add and rename.
- Team and access: invitations with client and financial grants; members when the API can name them (section 3).
- API keys: list, issue once, revoke.
- Connections of one client: status, freshness, coverage per stream, cost, connect, synchronize, reconnect and disconnect, and the return from a provider.

Not in scope:

- Overview, content, revenue and ad spend (018-C); links, tracking and integrations, with Paymob, Cal.com, WhatsApp and the conversion destinations (018-D); attribution (after 016-B).
- Any change to the API, the contract or the schema. Section 3.2 proposes one; it needs its own decision (D-090).
- A new package. The slice needs none.
- Subscription and usage screens (017), and the stored record of agreement to the terms (D15).

## 2. What the API already provides
Read from the repository at `1c4ee9e`: the [contract](../../contracts/openapi.json) (147 operations), `backend/app/api/tenancy.py`, `backend/app/services/tenancy.py`, `backend/app/services/access.py` and the [connector guide](../../docs/engineering/connectors.md).

| Fact | Consequence for the interface |
|---|---|
| `GET /agencies` lists the person's agencies with the role in each. `GET /agencies/{a}` gives the name and is refused to a client viewer. | The role decides which destinations are shown. A client viewer sees client names and no agency name. |
| `GET /agencies/{a}/clients` returns the active clients the person may read, 100 a page: all of them for an owner or admin, the granted ones for an analyst or client viewer. Archived clients are never listed. | The list is read page by page. The interface filters and counts on what it has read. It cannot show archived clients (section 3). |
| `POST /agencies/{a}/clients` and `PATCH .../clients/{c}` (name, or status `active` or `archived`) are for owners and admins. A name has 1 to 200 characters. | Add and rename are offered to owners and admins only. |
| `GET /agencies/{a}/members` returns the membership identifier, the user identifier, the role and the status, to owners and admins. `PATCH` changes the role or disables a member; an admin cannot change an owner, and the last active owner cannot be removed (`409 state_conflict`). | Roles and status can be changed, but a member cannot be named (section 3). |
| `PUT` and `DELETE .../members/{m}/clients/{c}` set or remove one grant, with `can_view_financials`. No operation reads the grants. | A grant can be written but not shown (section 3). |
| Invitations: `POST` (email, role, up to 100 client grants), `GET` (email, role, status, creation and expiry time), `DELETE` for a pending one. Only an owner invites or revokes an owner. An existing member or a pending invitation for the address answers `409 state_conflict`. | The invitations tab is complete with the present API. The mail is captured locally in the journeys. |
| Service keys: `POST` (name of 1 to 100 characters, `read` or `ingest`, at least one client grant, 1 to 90 days) returns the key once; `GET` lists name, kind, status and dates; `DELETE` revokes. An ingest key never carries financial access. | The key is shown once, in a dialog that says so, and is kept nowhere by the interface. |
| `GET /agencies/{a}/audit` returns the newest 100 events with an action code, a resource type and identifiers only. | The actor cannot be named (section 3). |
| Connections: `GET` list and one, with provider, account label, status (`active`, `reconnect_required`, `disconnecting`, `disconnected`), reason, last successful synchronization, the `actions` the caller may take and the disconnect outcome. Readable by every member who may read the client. | One card per connection. Actions follow the `actions` flags and the role; nothing is offered that the API will refuse. |
| `GET .../coverage` gives freshness (`fresh`, `stale`, `never_synced`), the state of the latest run, each stream's covered range and state, each metric's availability and the cost of the day. | Freshness and coverage use the data-state language of the design (D9). A missing value is never drawn as zero. |
| `POST .../connections` returns an address at the provider and binds the browser with a cookie; the provider returns to the API, which redirects to `/connections/complete` with `result=connected&connection_id=` or one fixed `error`. | The application remembers which client the person was connecting, leaves for the provider, and on return shows the result in that client's connections. |
| A provider may need more than a click: an ad account or dataset number (`account`), or an approval of the agency and the client's members as agents of the account holder (`agent_approval`, Spec 011 D13). | The connect dialog asks for what the chosen provider needs. The wording of the approval is provisional until the owner supplies it. |
| `POST .../sync` queues a run (`409 sync_in_progress`, `409 connection_not_active`); `POST .../reconnect` and `POST .../disconnect` follow the connector guide. | Each action reports its outcome in the card; a refusal is a sentence, not a code. |
| No operation lists the providers a server has enabled. An unavailable provider answers `404 provider_unavailable`. | The dialog lists the product's providers and reports an unavailable one when it is chosen. The synthetic providers are listed only in a build that enables them, for local use and the journeys. |

## 3. What the approved screens show that the API cannot supply
The reference screens ([clients](../../docs/design/preview/screens/clients.html), [team](../../docs/design/preview/screens/team.html), [connections](../../docs/design/preview/screens/connections.html)) were drawn before the interface was built against the API. These parts have no source today.

### 3.1 Gaps
| Screen | Shown in the design | State of the API | In this slice without a change |
|---|---|---|---|
| Team, members | Name and email of each member | Identifiers only; the projection leaves out the profile on purpose (specification 002) | The members tab is not built. An interface that lists people as identifiers helps nobody. |
| Team, members | Clients and financial access per member | Grants can be written, never read | Not built. |
| Team, members | "Last active" | Not recorded for display | Left out; it needs its own privacy decision. |
| Clients | "Archived" view and "1 archived" | Archived clients are not listed | Archive is not offered, because the interface could not show or restore what it archived. |
| Clients | "People with access" per client | No grants read | Column left out. |
| Clients | A line of business under the name ("Restaurant") | No such field | Left out; the date the client was added is shown. |
| Clients | "All fresh", "Meta ads stale" per client | Freshness is part of each connection's coverage; reading it for every connection of every client is one request per connection | The list shows what the connection list gives: reconnect needed, disconnecting, connected, or nothing connected, with the last synchronization. Freshness is on the client's connections page. |
| Audit log | Who did what | The actor is an identifier | Not built until members can be named. |
| Connections | Paymob, Cal.com, WhatsApp and Meta conversions on the same page | They are integrations with their own operations | They arrive with 018-D, on the same page or beside it. |
| Sign-in (018-A) | Seconds to wait after too many attempts | `Retry-After` is not readable across origins | Unchanged: the sentence has no number. |

### 3.2 Proposed amendment to the API (needs the owner's decision)
Recommended, as one small amendment to specification 002 with its own tests, without a migration and without a new table:

| ID | Change | Who may read it | Why |
|---|---|---|---|
| B1 | `GET /agencies/{a}/members` adds `display_name`, `email_normalized`, `created_at` and the member's client grants (`client_id`, `can_view_financials`, `can_view_identities`). | Owners and admins of that agency, as today. | The members tab, the grants of a member, and the name of the actor in the audit log. Managers already see an invited person's address in the invitation list. |
| B2 | `GET /agencies/{a}/clients` accepts `status=archived` for owners and admins. | Owners and admins. | An archived view with restore, so archiving can be offered. |
| B3 | The API lets the browser read `Retry-After` (one entry in its cross-origin settings). | Every caller. | The rate-limit sentence can say how long to wait (018-A evidence, section 8.1). |

Alternative: keep the API as it is. The slice then ends with the parts of section 3.1 left out. Not recommended: the team screen the owner approved cannot be built.

Until the owner decides, nothing in `backend/` or `contracts/` changes.

## 4. How it is built
### 4.1 Addresses
The agency and the client are part of the address, so a link names its tenant and a reload returns to the same place (carried from the 018-A evidence, section 8.2).

| Address | Screen |
|---|---|
| `/` | Goes to the clients of the agency the person last worked in, or to the first agency. |
| `/agencies/{agency}/clients` | Clients |
| `/agencies/{agency}/team` | Team and access (owners and admins) |
| `/agencies/{agency}/keys` | API keys (owners and admins) |
| `/agencies/{agency}/clients/{client}` | Goes to the client's first page: Connections in this slice, Overview from 018-C. |
| `/agencies/{agency}/clients/{client}/connections` | Connections |
| `/connections/complete` | The return from a provider. |

An address that names an agency the person does not belong to, or a client the person may not read, shows the "not found" page. The API decides; the interface never treats an address as permission (acceptance criterion 2).

### 4.2 Navigation
- The sidebar shows the agency level (Clients; Team and access and API keys for owners and admins) or the client level (Manage: Connections), as in the reference screens. Destinations of later slices are absent, not disabled.
- One switcher at the top of the sidebar names where the person is: the agency with "All clients", or the client with its agency. Its menu lists "All clients", the clients, and the person's other agencies.
- The overview page of 018-A showed the agency and the person. The agency level now starts at Clients, as designed, and the first page of 018-A is removed.
- The phone tab bar carries the destinations of the current level and the account.

### 4.3 Data and the cache
- Every query key of tenant data starts with the agency, and every key of client data also carries the client: `['tenant', agency, 'client', client, ...]`.
- Moving to another agency removes everything under the previous agency, as in 018-A. Leaving a client removes everything under that client, so nothing of the previous client can be drawn for the next one (acceptance criterion 2).
- Lists that the API pages are read to the end, 100 at a time.
- A mutation refreshes what it changed. No value is shown before the API has confirmed it.

### 4.4 Roles
| | Owner | Admin | Analyst | Client viewer |
|---|---|---|---|---|
| See clients | All | All | Granted | Granted |
| Add or rename a client | Yes | Yes | No | No |
| Team and access, API keys | Yes | Yes | No | No |
| Invite or revoke an owner | Yes | No | No | No |
| See a client's connections | Yes | Yes | Granted clients | Granted clients |
| Connect, synchronize, reconnect, disconnect | Yes | Yes | No | No |

The interface hides what a role cannot do, and the API refuses it in any case. The entry review left open whether a client viewer sees the Manage group (section 6 there). In this slice a client viewer reads the connections of their client and changes nothing, which is what the API allows; the question returns with 018-C, when the client has an overview.

### 4.5 States
Every screen has a loading, an empty and an error state from the design language, and no screen shows sample data. For a connection:

| What the API reports | Shown as |
|---|---|
| `active`, fresh | "Connected" and the last synchronization |
| `active`, stale | "Stale" (clock) with the last synchronization |
| `active`, never synchronized | "Not synced" (cloud off) |
| `reconnect_required` | A danger banner with the reason and one action, "Reconnect" |
| `disconnecting` | "Disconnecting", with the date by which stored data is removed |
| `disconnected` | Listed under past connections with the outcome of the removal |
| Latest run `queued`, `running`, `delayed`, `budget_stopped`, `failed` | One line with the state, the reason and the next attempt |
| Stream `not_synced`, `partial`, `complete` | The coverage bar and its sentence |
| Cost `exhausted` | The meter in the danger tone and the reason |

## 5. Screens of the slice
| Route | Screen | API operations |
|---|---|---|
| `/agencies/{a}/clients` | Summary tiles, search, the table of clients with their connections, "Add client", rename. | `GET`, `POST /agencies/{a}/clients`, `PATCH .../clients/{c}`, `GET .../clients/{c}/connections` |
| `/agencies/{a}/team` | Invitations: list, invite with role and grants, revoke. What each role can do. Members when section 3.2 is decided. | `GET`, `POST`, `DELETE /agencies/{a}/invitations` |
| `/agencies/{a}/keys` | Keys: list, issue with kind, clients and lifetime, the key shown once, revoke. | `GET`, `POST`, `DELETE /agencies/{a}/service-credentials` |
| `/agencies/{a}/clients/{c}/connections` | A card per connection with status, freshness, coverage, cost and actions; "Connect account"; past connections. | `GET`, `POST .../connections`, `GET .../coverage`, `POST .../sync`, `.../reconnect`, `.../disconnect` |
| `/connections/complete` | Says what happened at the provider and returns to the client's connections. | none |

## 6. Checks that close the slice
| Check | What it proves |
|---|---|
| `tsc --noEmit`, ESLint with the accessibility rules, the contract drift check | As in 018-A. |
| Unit and component tests | Each role sees only its destinations and actions; a client's data is removed from the cache when the person leaves it; lists are read to the end; every error code of these operations has a sentence; the key is shown once and stored nowhere; the connect dialog sends what each provider needs; each connection state of section 4.5 is drawn as stated. |
| Browser journeys in Chromium and Firefox against the real API on the disposable stack, with the synthetic provider | Add a client; invite an analyst with one client and see only that client as the analyst; issue and revoke a key; connect a synthetic account, see it synchronized by the worker, disconnect it; a provider that refuses; a deep link to another agency's client; Arabic and the dark theme on the new screens; the keyboard alone. |
| axe-core on every new screen, both languages and both themes, and at 390 pixels | No finding. |
| The bundle search | No secret, key, token or backend setting (acceptance criterion 5). |
| Removed protections | Each protection of the unit tests fails a test when it is removed. |

Not covered: a real provider (Instagram, YouTube and Meta need their own approvals and an HTTPS address), screen readers, Safari, real phones, and usability with Arabic-speaking users.

The journeys never use the owner's `tracking_sys` database (D-015).

## 7. Order of work
Each step ends with its checks and a commit pushed to `codex/spec-018-workspace-screens` (D-051).

1. Addresses, the two levels of the shell and the switcher.
2. Clients.
3. Connections and the return from a provider.
4. Invitations and API keys.
5. Journeys, accessibility checks, the evidence file and the records.
6. After the owner's decision on section 3.2: the amendment with its tests, then members, grants, archive and the audit log.
