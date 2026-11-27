# Spec 017-B entry review: offboarding export, provider disconnection and the purge of closed agencies

Prepared: 2026-11-27 under D-097.
- **Baseline:** merged `main` at `e3b3005` (PR 20: Spec 016-C, report delivery).
- **Status:** approved. The owner approved D1-D14 as recommended, without amendment, on 2026-11-27 (D-098).
- **Handoff:** the [implementation handoff](implementation-prompt-017b.md) executes this packet after approval.

## 1. Intended result

017-B completes what happens when an agency leaves the platform:
- **Offboarding export.** During the 30-day closing period of 017-A, an Owner downloads the agency's data in one file, so that its clients' data is returned at the end of the service.
- **Provider disconnection.** When the closure completes, every connection is disconnected. The 009 teardown revokes each token at its provider and deletes the provider data.
- **Purge.** The closed agency's data is then deleted from every table. Only a minimal record stays: the agency's ID and closure dates, its plan history and a count of what was deleted.

This closes acceptance criterion 5 of the [017 spec](spec.md): "Closing an agency stops its jobs and applies export, deletion, and retention policies." 017-A stopped the jobs; 017-B applies export and deletion. In the 003 design, the platform is the processor for its agencies and their clients, with "end-of-service return or deletion" (section 15). The deletion scope of section 10 is "All clients and configuration after an export window".

D-091 set the order: the backend first, with 017-C (payment provider, prices and trials) after research and an owner decision. LinkedIn (012) and X (013) stay deferred under D-063.

## 2. Baseline on `main`

| Area | Available | Consequence for 017-B |
|---|---|---|
| Closure (017-A) | An Owner requests closure; the agency is `closing` for 30 days and stops like a suspended agency. Only the closure routes and the agency list read it, for its Owners. The lifecycle runner then marks it `closed` (`agency_closures.completed_at`). Nothing reopens it. | The closing period is the natural export window. The completion is the trigger of disconnection and purge. |
| Tables | 95 tables; 80 carry `agency_id` or `client_id`. No unscoped table references a tenant row. `agencies` is referenced by `agency_branding`, `agency_closures`, `agency_invitations`, `agency_memberships`, `agency_plan_assignments`, `audit_events`, `client_workspaces` and `service_credentials`. The data policy marks most tenant tables "kept with the workspace; offboarding is 017". | One purge must cover every tenant table, children first. The test cleanup order of `tests/integration/conftest.py` is already a valid children-first order. |
| Connector teardown (009) | `start_disconnect` moves a connection to `disconnecting`. The connector worker's teardown revokes each token at the provider, destroys the sealed material and purges the provider data within the teardown deadline (72 hours), whatever the agency's status. Disconnect reasons are a closed list. | A closed agency's connections are disconnected with a new reason, `agency_closed`, and the purge waits for their teardowns. |
| Other bindings | WhatsApp numbers are bound by the operator (015); custom link domains reserve their host name (005); service keys, invitations, payment and integration sources and CAPI destinations belong to the agency. | They are released when their rows are deleted. |
| Exports (016-C) | Retained report CSVs, sealed under the token keyring in PostgreSQL for 7 days, with downloads authorized again each time. | The offboarding export reuses the same sealing, storage pattern and download rules. |
| Roles | `tracking_app` (runtime) never deletes most tenant rows; `tracking_lifecycle` deletes ended or expired rows of named tables under narrow grants. | The purge needs a delete right that cannot reach an agency that is not closed. |
| Accounts (D-024) | Users are platform accounts and may belong to several agencies; account closure pseudonymizes the user. Memberships are never deleted today. | Users stay. Memberships of the purged agency go. |
| Backups (003, 020) | No backup tooling exists. The 003 design has restores reapply deletions from an independent journal (020). | A restore must reapply purges; that belongs to 020. |

## 3. Decisions for the owner

The recommendations are for synthetic data and disposable PostgreSQL. They are product and policy choices, not legal advice. They leave Q-003, Q-004 and Q-012 open.

| ID | Recommended choice | Alternative and its effect |
|---|---|---|
| D1 Scope and delivery | 017-B has three parts: the offboarding export, the disconnection and release at completion, and the purge. Phases P0-P5 run on one branch, `codex/spec-017b-agency-offboarding`. Verified commits are pushed after each phase (D-051), and one pull request is opened for review. | Two slices: disconnection and purge first, the export later. The purge is the legal minimum, but it would then delete data before any way to take it back exists. |
| D2 Export window | An active Owner of a closing agency requests the export during the closing period, until 24 hours before the closing time, so that it is ready before the purge. Nothing can be exported after the closure completes. The 30-day closing period of 017-A is the export window that the 003 design calls for. | A second 30-day window after completion, with the data kept stored and unreachable meanwhile: more time, but every closed agency's data then lives 60 days. |
| D3 Request and download | The request needs the reauthentication of account closure (the password, or a recent session) and is audited. Only active Owners download, with the scope resolved again each time. One export at a time per agency; a new request replaces the previous file. | Admins too: more people can take the data back, but the file holds every client's data. |
| D4 Contents | Every client's first-party data with its internal IDs, as JSON Lines: workspace configuration (clients, links, campaigns, templates, forms, model versions, rules and schedules); collected events and consent records; identity persons, links and merges; revenue evidence and the ledger; bookings, CRM deals and WhatsApp referrals; attribution conversions and credit. **Excluded:** provider-sourced data (social metrics and ad spend), because provider terms govern their reuse and the agency can export the 016 reports before it requests closure; secrets, keys, digests and tokens; audit and security logs; deletion tombstones, diagnostics and processing state. | Include provider-sourced metrics too, after the rules of each provider are verified again: a fuller file, at the cost of a check per provider. |
| D5 Format, storage and bounds | One ZIP file (Python standard library): a folder per client of JSON Lines files, and a manifest with the schema version, the row count and the SHA-256 of each file. The worker builds it in the background. It is sealed in parts of at most 8 MiB under the token keyring and stored in PostgreSQL, as 016-C exports are. It is kept 7 days or until the purge. Development bound: 2,000,000 rows and 512 MiB, beyond which the export fails with `export_too_large`. Production sizes come with Q-004 and 020. | CSV files per table: easier to open in a spreadsheet, but nested fields and JSON values lose their structure. |
| D6 Completion effects | The first worker pass after completion runs the offboarding as the runtime role. It disconnects every live connection with the reason `agency_closed`, so that the 009 teardown revokes the tokens and deletes the provider data. It also revokes service keys, pending invitations and report exports, and disables sources and destinations, so nothing can reach the agency again before the purge. | Revoke the connections at the closure request: tokens end 30 days earlier, but a cancelled closure would need every account reconnected (017-A D8). |
| D7 Purge | The purge begins once every teardown of the agency has settled, or its 72-hour deadline has passed. It deletes every row of the agency in every tenant table, children first, in bounded batches that can be resumed. Then it replaces the agency's name with a pseudonym and records the purge. A test asserts that no row of a purged agency remains in any table. | Keep the data for a further period after completion before purging, as a recovery buffer: safer against a mistaken closure, but 017-A already gives 30 days to cancel. |
| D8 What stays | The agency row (status `closed`, pseudonymous name, purge time), its plan assignment history (for 017-C billing) and a purge record: the closure dates, the export summary and the deleted row count of each table. Users stay as platform accounts; their memberships, the agency's audit log and everything else go. | Keep the agency's audit log until Q-012 decides its retention: more evidence, but it names members and resources of a deleted agency. |
| D9 Purge privilege | `tracking_lifecycle` purges only through one database function, owned by the migration role, which refuses any agency that is not closed and whose offboarding has not completed. It deletes in its fixed table order. The role gets no direct delete right on tenant configuration. | Grant the lifecycle role delete rights on every tenant table. Simpler, but a fault in the runner could then delete an active agency's data. |
| D10 Backups | Backups are not edited. A restore must reapply the recorded purges (the 003 journal, 020). Development has no backups. | Edit backups: not possible with standard PostgreSQL backups. |
| D11 Operator command | `python -m app.agency_offboarding status --agency <id>` shows the offboarding and purge state with counts. `run --agency <id> --confirm` runs the pending steps of one closed agency at once, for a stuck teardown. JSON output, no names. | No command: the operator waits for the workers. |
| D12 Schema | One additive migration, `0033_agency_offboarding`: `agency_exports`, `agency_export_parts`, `agency_purges`, `agencies.purged_at`, the guarded purge function, the disconnect reason `agency_closed` and the new audit actions. Scoped keys, closed checks, data policy rows and restricted grants follow 0026-0032. It is tested on disposable PostgreSQL only, and the downgrade refuses stored rows. | Plain delete grants without the function (see D9). |
| D13 Boundaries | Backend only, synthetic data, disposable PostgreSQL, no new dependency and no live provider: the revocations of the tests reach synthetic providers only. No frontend, billing (017-C) or backup tooling (020). Agencies that are not closed behave exactly as before. | Run the teardown against live providers: that is an owner-operated check after the merge. |
| D14 Completion evidence | The [verification matrix](#5-verification-matrix) OV01-OV20 is executed with the existing suites, and every command and count is recorded. Each new safeguard is shown to fail its test when disabled. The completed branch is presented for independent review in its pull request. | Unit tests only: fast, but they would miss the function's guard, the teardown wait and the completeness of the purge. |

## 4. Design for implementation after approval

The design note of P0 (`design-017b.md`) fixes the exact statements, answers and tests. It follows these lines.

### 4.1 Schema (`0033_agency_offboarding`, after `0032_report_delivery`)

- **`agency_exports`:** the agency, the requesting membership, the status (`pending`, `ready`, `failed`, `revoked`), the closed error code, the request, ready and expiry times, the part count, the size, the row counts by file (JSONB) and the manifest's SHA-256.
- **`agency_export_parts`:** the export, the part number and the sealed chunk (KEK ID, wrap nonce, wrapped key, nonce, ciphertext, algorithm, AAD version).
- **`agency_purges`:** one row per closed agency: the copied closure times, the export summary, the offboarding start and end, the teardown settlement, the purge start and end, the deleted row counts by table (JSONB) and the state (`offboarding`, `waiting`, `purging`, `purged`).
- **Changes:** `agencies.purged_at`, the disconnect reason `agency_closed`, audit actions `agency.export_requested` and `agency.export_revoked`, and the function `purge_agency_batch(agency_id uuid, budget integer)`, granted to `tracking_lifecycle` only.

### 4.2 Export

- **Routes:**
  - `POST /agencies/{a}/closure/export` (Owner of a closing agency, reauthenticated, until 24 hours before the closing time);
  - `GET /agencies/{a}/closure/export` (status);
  - `GET /agencies/{a}/closure/export/download` (the ZIP, streamed part by part, `no-store`).
- **Build:** a pass of the worker builds pending exports from one consistent snapshot per client. It writes the ZIP to a temporary file and seals it in parts. It stores the parts only if the agency is still closing.
- **Catalog:** the design note lists each exported table with its columns and states the rule for each excluded column (D4).

### 4.3 Offboarding and purge

- **Offboarding:** `python -m app.offboarding_worker` (one bounded pass) builds pending exports and starts the offboarding of agencies closed since its last pass (D6). It records the state in `agency_purges`.
- **Purge:** the lifecycle runner calls `purge_agency_batch` for agencies whose teardowns have settled, within its batch bounds, until the function reports nothing left. It then completes the purge record.
- **Function:**
  - It refuses an agency unless it is `closed` with a settled offboarding.
  - It deletes at most `budget` rows per call, table by table in its fixed children-first order.
  - It returns the counts.
  - A test compares its table list with every table that carries `agency_id` or `client_id`.

## 5. Verification matrix

| Case | Required observable evidence |
|---|---|
| OV01 Export request | Only an active Owner of a closing agency, reauthenticated, until 24 hours before the closing time; an Admin, an active agency, a closed agency and a key are refused; audited. |
| OV02 Export contents | The ZIP holds every included table of every client with the listed columns and a manifest whose counts and SHA-256 match. No excluded table or column appears, and no secret, digest or token. |
| OV03 Export bounds | Beyond the development bound the export fails with `export_too_large`; nothing partial is stored. |
| OV04 Export storage | Parts are sealed, bound to the export and agency, and no plaintext is stored; a copied part does not open. |
| OV05 Download | Owners only, with the scope resolved again; the file streams, is byte for byte the built ZIP, and is gone after expiry, revocation or purge. |
| OV06 Completion before readiness | An export still pending when the closure completes is discarded, never stored. |
| OV07 Offboarding | After completion, every live connection is `disconnecting` with `agency_closed`, and service keys, invitations, report exports, sources and destinations are revoked or disabled. A second pass changes nothing. |
| OV08 Teardown | The synthetic providers receive each revocation; the purge waits until every teardown settles or its deadline passes. |
| OV09 Purge completeness | After the purge, no row with the agency's ID or one of its client IDs remains in any table, and the function's table list covers every scoped table. |
| OV10 What stays | The agency row (closed, pseudonymous name, `purged_at`), its plan assignments and the purge record with counts; users still exist and can sign in. |
| OV11 Isolation | Another agency, including one with the same members, keeps every row. |
| OV12 Guard | The function refuses an active, suspended or closing agency and a closed agency whose offboarding has not settled; the lifecycle role cannot delete tenant configuration directly. |
| OV13 Bounded and resumable | The purge runs in bounded batches, survives an interruption between batches and finishes on the next run. |
| OV14 Released bindings | After the purge, the WhatsApp number and the custom domain of the agency can be claimed by another agency. |
| OV15 Workers | No worker processes a closed or purged agency's sync, delivery, attribution, report or export work except the offboarding steps. |
| OV16 Operator command | `status` and `run --confirm`; `--confirm` is required; output has no name. |
| OV17 Concurrency | The completion, the offboarding pass, the export build and the purge never interleave into a stored export or a remaining row; two offboarding workers do not run one agency twice. |
| OV18 Migration | Upgrade from a populated `0032`, grants and data policy rows as D12 states, and a downgrade that refuses stored rows. |
| OV19 Logs | No name, figure, token or file content appears in a log line or in worker or command output. |
| OV20 Existing behavior | Every existing suite passes, and the OpenAPI snapshot has additions only. |

## 6. What remains after 017-B

- **017-C:** subscription billing with a payment provider, prices and any trial (Q-005), after research and an owner decision.
- **020:** the purge journal of restores, the worker schedule, object storage and managed keys.
- **Owner-operated checks:** the teardown of live connections against Meta and Google after the merge.
- **The frontend:** the export and closure pages (018).
