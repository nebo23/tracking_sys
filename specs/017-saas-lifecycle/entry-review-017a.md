# Spec 017-A entry review: plans, limits and agency closure

Prepared: 2026-11-26 under D-091.
- **Baseline:** merged `main` at `633ea9a` (PR 18: Spec 016-B, attribution reports).
- **Status:** proposals for the owner. Decisions D1-D14 are not approved until the owner approves them, which will be recorded as D-092.
- **Handoff:** the [implementation handoff](implementation-prompt-017a.md) executes this packet after approval.

## 1. Intended result

The platform runs as a multi-agency SaaS with plans and limits before any payment is collected:
- Every agency has a plan whose limits the server enforces.
- An agency's Owner or Admin can see the plan, the limits and the current usage.
- The platform operator defines plans and assigns them from the command line.
- An agency's Owner can close the agency, with a grace period in which the closure can be cancelled.
- The sole Owner of a closed agency can then close their own account.
- Every account records which version of the Terms of Service and the Privacy Policy it agreed to, and when (D15 of the 018 entry review, approved by the owner).

D-091 records the owner's choices for finishing the backend: 017-A without a payment provider first, then 016-C in the same round. LinkedIn (012) and X (013) stay deferred under D-063.

The remaining work of Spec 017 stays open:
- **017-B:** the purge of a closed agency's data, and an agency data export.
- **017-C:** subscription billing with a payment provider, prices and any trial (Q-005).

## 2. Baseline on `main`

| Area | Available | Consequence for 017-A |
|---|---|---|
| Agencies (002) | `agencies.status` is `active` or `suspended`. A suspended agency is refused by every member route, the public intake (collection, links, payments, integrations, WhatsApp), the connector and delivery workers and the attribution worker. No route or command sets it. | Suspension already stops everything. Closure reuses that behavior, and the operator command sets it. |
| Ownership (002) | An Owner can make another member an Owner (`PATCH /agencies/{a}/members/{m}`), and the last active Owner cannot be removed or demoted. An account cannot be closed while it is the sole active Owner of an agency. | Handing over an agency already works. The gap is the sole Owner who wants to leave without a successor: closing the agency must lift the account-closure rule. |
| Creation points | Clients (`create_client`), memberships and invitations (`add_member`, `invite`), connector connections (`begin`), managed links (`create_link`), ingestion sources, service keys and the 014 and 015 sources. Every agency mutation takes the agency row lock. | Limits are checked under the same lock, so concurrent creations cannot exceed them. |
| Usage sources | `collected_events` has an index by client and receipt time. Clients, memberships, invitations, connections and links have status columns. | The current usage can be computed from stored data, without a counter table. |
| Operator commands | `python -m app.whatsapp_binding` and `python -m app.connector_purge` run outside the agency roles, print JSON and refuse without `--confirm`. | The plan command follows the same pattern. |
| Account closure (003-A5, D-024) | Closure scrubs the account and revokes its sessions. The lifecycle deletes the credential state of closed accounts. | Agency closure is a separate state machine and does not reuse account closure. |
| Terms (018 D15) | The 018-A sign-in and registration screens require a tick that nothing stores. The API has no field for it, and the legal texts do not exist. | 017-A stores the record. The owner supplies the texts and their version labels. |
| CORS | Platform CORS exposes no response header, so a browser on the application origin cannot read `Retry-After` (018-A evidence, open item 1). | One setting. |

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product and policy choices, not legal advice, and they leave Q-003, Q-004, Q-005 and Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 017-A has seven parts: plans and their limits; enforcement at creation; the usage view; the operator command; agency closure with a grace period; the agreement record; and the `Retry-After` header. Phases P0-P5 run on one branch, `codex/spec-017a-saas-plans`. Verified commits are pushed after each phase (D-051), and a pull request opens for review at the end; merge is a separate decision. Payment, prices, trials, the data purge, the agency export and the React UI stay outside. | Include the purge of closed agencies in 017-A: one review, but the slice grows by every table of the product and needs the retention decisions of 017-B first. |
| D2 Plans | A plan is immutable data that the platform operator creates: an internal key and name, and limits for clients, seats, connections, managed links and tracked events per month. A missing limit means unlimited. To change a plan, the operator creates a new plan and assigns it. Plans carry no price and no currency until 017-C. | Editable plans: simpler for the operator, but past assignments would silently change meaning and the audit trail would lose what an agency had. |
| D3 Default plan and development limits | Every agency always has exactly one current plan. A new agency gets the default plan; the migration assigns it to existing agencies. The migration seeds one plan, `development`, as the default, with these values: 5 clients, 10 seats, 10 connections, 500 active managed links and 100,000 tracked events per month. The operator can create other plans and change the default without code. | No default (each new agency waits for the operator): stricter, but self-registration stops working. Other default values: the owner may change any of them here. |
| D4 Hard limits on creation only | A limit refuses only the creation that would exceed it: `409 plan_limit_reached` with the limit's name, its value and the current use. Counted: active clients; seats (active memberships plus pending invitations); live connector connections; active managed links. Nothing that exists is disabled, deleted or hidden when an agency moves to a smaller plan; the agency just cannot add more. Reads, syncs, redirects, collection, erasure and deletion are never refused by a limit. | Enforce limits on existing resources after a downgrade (disable the extra clients or links): stricter, but a plan change could break live links and stop data. |
| D5 Tracked events | The monthly event allowance is a soft limit. Events beyond it are still accepted and counted, the usage view shows the agency as `over_allowance`, and the operator command lists such agencies. No event is dropped, and no redirect or collection request changes (Spec 017 acceptance 4). A month is a UTC calendar month. | A hard cap that refuses events: protects platform cost, but loses customer data and breaks tracking without warning. It needs a cost policy (Q-004) first. |
| D6 Usage view | `GET /agencies/{a}/plan` (Owner, Admin and Analyst; never a client viewer or a service key) returns the plan, each limit with its current use, and the month's tracked events with their state. Use is computed on read from stored data, in one snapshot, and never names a client, person or event. There is no usage history table until 017-C. | A daily usage snapshot table now: history for billing, but a schema and a worker step before any billing exists. |
| D7 Operator command | `python -m app.agency_plans` with `plans` (list), `create-plan`, `set-default`, `assign` (agency and plan), `agencies` (plans, use and over-allowance), `suspend` and `reactivate`. Every change needs `--confirm` and writes an audit event in the agency's audit log with the actor `platform_operator`. No platform-admin web interface. | A platform-admin web interface: easier to use, but it needs a new privileged role, a separate authentication policy and its own review. |
| D8 Agency closure | An Owner requests closure (`POST /agencies/{a}/closure`) with the agency's exact name and a password check or a recent session, as account closure does. The agency becomes `closing`, with a closing time 30 days later. While closing, the agency stops exactly as a suspended agency does: no member route, intake, sync, delivery or attribution pass. Its Owners can only read the closure state and cancel it (`DELETE /agencies/{a}/closure`), which returns the agency to `active`. At the closing time, the lifecycle runner marks the agency `closed`. A closed agency cannot be reopened through the API, and its data stays stored, unreachable, until the 017-B purge exists. Connections are not revoked at the start of the closure, so that a cancellation needs no reconnection; 017-B revokes them. | Revoke every connection and delete data at once: no grace period, so a mistaken closure cannot be undone. A shorter or longer grace period (for example 14 or 90 days): the owner may choose another value. |
| D9 Leaving an agency | The account-closure rule becomes: an account cannot be closed while it is the sole active Owner of an `active` or `suspended` agency. A `closing` or `closed` agency does not block it. Handing over ownership stays as today: an Owner makes another member an Owner, then leaves. | A dedicated transfer endpoint: one call instead of two, but the existing role change already covers it. |
| D10 Agreement record (018 D15) | One record per account, document and version: Terms of Service or Privacy Policy, the version label, the time and the channel (registration, password sign-in or Google sign-in). Registration and every sign-in send the versions that the person accepted. They must equal the current versions, otherwise the answer is `422 agreement_required`, and a record is written only when the account has none for that version. The current versions are settings. Until the owner supplies the texts, the development values are `draft-1`, and every response that needs them says that the texts are not published. | The lighter form of 018 D15: ask only at registration and again when a version changes. Fewer prompts, but the approved 018-A screens ask at every sign-in. |
| D11 `Retry-After` | Platform CORS exposes `Retry-After`, so the interface can say how long to wait after a rate limit. Nothing else is exposed. | Leave it: the interface keeps a generic sentence. |
| D12 Schema | One additive migration, `0031_saas_plans`, adds `saas_plans`, `agency_plan_assignments` (history; the current plan is the latest), `agency_closures` and `user_agreements`. `agencies.status` gains `closing` and `closed`. The migration seeds the `development` plan and assigns it to every existing agency. Scoped keys, closed checks, data policy rows and restricted grants follow 0026-0030. It is tested on disposable PostgreSQL only, and the downgrade refuses stored rows. | Plans as configuration files instead of tables: no migration, but no assignment history or audit, and every deployment would carry the plan list. |
| D13 Boundaries | Backend only, synthetic data, disposable PostgreSQL, no new dependency and no live provider. No price, currency, payment provider, trial or invoice (017-C). No purge, export or provider token revocation for closed agencies (017-B). Existing behavior stays unchanged for an agency within its limits. | Start the payment provider research in the same branch: it needs its own decision first (D-091). |
| D14 Completion evidence | The [verification matrix](#5-verification-matrix) SV01-SV20 is executed with the existing suites, and every command and count is recorded. Each new safeguard is shown to fail its test when disabled. The completed branch is presented for independent review in its pull request. | Unit tests only: fast, but they would miss the lock, the concurrency and the stop behavior of closure. |

## 4. Design for implementation after approval

The implementing model writes the exact statements, answer shapes, error codes and grants in a design note (`design-017a.md`) before any code. This section is its source.

### 4.1 Schema (`0031_saas_plans`, after `0030_reporting_indexes`)

| Table | Content | Mutation |
|---|---|---|
| `saas_plans` | Key (unique), internal name, the five limits (each nullable: unlimited), `is_default` (one by partial unique index), `created_at`, the operator's reason. | Insert; update only `is_default`. |
| `agency_plan_assignments` | Agency, plan, `assigned_at`, `assigned_by` (`platform_operator` or `default`), a closed reason code. The current plan is the latest row per agency. | Insert only. |
| `agency_closures` | Agency, `requested_by` (membership), `requested_at`, `closes_at`, `cancelled_at`, `cancelled_by`, `completed_at`. At most one open closure per agency. | Insert; update only the cancel and completion columns. |
| `user_agreements` | User, document (`terms`, `privacy`), version label, `accepted_at`, channel (`registration`, `password_sign_in`, `google_sign_in`). Unique per user, document and version. | Insert only. |

`agencies.status` allows `active`, `suspended`, `closing` and `closed`. The data policy classifies every new column; `user_agreements` follows the account lifecycle of D-024 (deleted with a closed account's credential state, unless the owner's legal advice requires keeping proof of agreement; Q-012 stays open).

### 4.2 Enforcement

- **Lock.** Each creation point counts the agency's use under the agency row lock it already takes, then compares it with the current plan's limit.
- **Refusal.** `409 plan_limit_reached` with `{limit: "clients" | "seats" | "connections" | "managed_links", value, used}`. A missing limit never refuses.
- **What counts:**
  - clients: active client workspaces;
  - seats: active memberships plus pending invitations;
  - connections: connector connections whose status is live (`active`, `reconnect_required`);
  - managed links: active managed links of all clients.
- **Never refused:** reads, syncs, redirects, collection, erasure, deletion, archival, revocation and any status change that lowers use.

### 4.3 Usage view

`GET /agencies/{agency_id}/plan` answers, in one REPEATABLE READ snapshot:
- the plan (key, name, limits, `assigned_at`);
- for each limit, its value, its use and a state (`within`, `at_limit` or `unlimited`);
- the tracked events of the current UTC month: the count, the allowance and a state (`within`, `over_allowance` or `unlimited`).

Tracked events are the client events received in the month across the agency's clients, counted with a bound and the existing index. The answer names no client, person or event.

### 4.4 Closure

- **Request.** `POST /agencies/{agency_id}/closure` with `{confirm_name, password?}`, Owner only. It takes the agency write lock and checks the name and the password or the recent session (`closure_reauthentication_seconds`). It writes the closure row and sets `status = 'closing'`, audited.
- **Read.** `GET /agencies/{agency_id}/closure` is for Owners only and stays readable while the agency is closing.
- **Cancel.** `DELETE /agencies/{agency_id}/closure` sets `status = 'active'`, audited.
- **While closing:**
  - every other member route, all public intake and every worker refuse the agency exactly as for `suspended`;
  - every existing check of `status == 'active'` keeps working unchanged;
  - `GET /agencies` lists a closing agency for its Owners with its state.
- **Completion.** A lifecycle step marks closures whose `closes_at` has passed: it sets `completed_at`, then `status = 'closed'`. A closed agency is refused everywhere, also for Owners.
- **Account closure.** `close_account` ignores `closing` and `closed` agencies when it looks for a sole Owner.

### 4.5 Agreement record

- **Settings.** `terms_version` and `privacy_version`, both `draft-1` in development.
- **Requests.** `POST /auth/register` and `POST /auth/login` accept `agreements: {terms, privacy}`. The Google completion carries them in the stored transaction.
- **Missing or outdated versions.** The answer is `422 agreement_required` with the current versions. The check comes before the credential check on login, so it reveals nothing about the account.
- **Records.** One insert per new version, in the same transaction as the account creation or the session creation.
- **Discovery.** `GET /auth/agreements` (public) returns the current versions and whether the texts are published.

### 4.6 Operator command

`python -m app.agency_plans` runs as `tracking_app` with the application settings and prints JSON. The subcommands are those of D7. Each change takes the agency write lock where it touches an agency, needs `--confirm` and writes an audit event:
- `agency.plan_assigned`;
- `agency.suspended`;
- `agency.reactivated`;
- `plan.created`;
- `plan.default_set`.

`reactivate` refuses a closing or closed agency.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| SV01 Default plan | A new agency and every agency existing at migration have the `development` plan; a changed default applies to new agencies only. |
| SV02 Limits | Each of the four limits refuses exactly the creation beyond it, with the closed code, the value and the use; a missing limit never refuses. |
| SV03 Concurrency | Two concurrent creations at the limit, under real PostgreSQL: exactly one succeeds, for clients, invitations, connections and links. |
| SV04 Downgrade | Moving to a smaller plan disables, deletes and hides nothing; only new creations are refused. |
| SV05 Never refused | Reads, syncs, redirects, collection, erasure, archival and revocation work at and beyond every limit. |
| SV06 Tracked events | Events beyond the allowance are accepted and counted; the state is `over_allowance`; months are UTC calendar months. |
| SV07 Usage view | Owner, Admin and Analyst read it; a client viewer, a service key, another agency and an ingest key are refused; the answer names no client, person or event. |
| SV08 Operator command | Every subcommand, `--confirm`, the audit events, refusals for unknown agencies and plans, and JSON output without secrets. |
| SV09 Suspension | A suspended agency stops as today, and reactivation restores it. |
| SV10 Closure request | Owner only; the name and the reauthentication checked; an Admin, an Analyst or a wrong name is refused; audited. |
| SV11 Closing stops everything | While closing: member routes, collection, redirects, payments, integrations, WhatsApp, the connector, delivery and attribution workers all refuse or skip the agency, as for `suspended`. |
| SV12 Cancel | An Owner cancels within the grace period, the agency is active again, and connections still work without reconnecting. |
| SV13 Completion | The lifecycle closes the agency at `closes_at`, idempotently and with a bound; a closed agency is refused for everyone and cannot be reopened through the API. |
| SV14 Sole Owner | The sole Owner of a closing or closed agency can close the account; of an active or suspended agency, cannot. |
| SV15 Agreement at registration | Registration without the current versions is refused with `agreement_required`; with them, it stores one record per document. |
| SV16 Agreement at sign-in | Password and Google sign-in record a new version once, never twice; outdated versions are refused before the credential check; no account information leaks. |
| SV17 `Retry-After` | A rate-limited response's `Retry-After` is readable from the application origin, and nothing else is exposed. |
| SV18 Migration | Upgrade from a populated `0030` seeds and assigns the plan; the downgrade refuses stored rows; grants are as D12 states. |
| SV19 Isolation and logs | Two agencies never see each other's plan, use or closure; no person, token or secret appears in a log line or in the command output. |
| SV20 Existing behavior | Every existing suite passes unchanged for agencies within their limits; the OpenAPI snapshot has additions only, apart from the documented agency status values and the agreement fields of the authentication requests. |
