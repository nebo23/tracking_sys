# Plans, limits and agency closure
Specification 017-A under D-092: every agency has a plan whose limits the server enforces on creation, Owners, Admins and Analysts see the plan and its use, the platform operator manages plans from the command line, an Owner can close an agency with a 30-day grace period, and every account records which Terms of Service and Privacy Policy versions it agreed to. There is no payment provider, price or trial (017-C), and no purge or export of a closed agency (017-B). Status: implemented and tested on the disposable database; native `tracking_sys` rollout of `0031_saas_plans` needs its own owner approval. See the [entry review](../../specs/017-saas-lifecycle/entry-review-017a.md), the [design note](../../specs/017-saas-lifecycle/design-017a.md) and the [evidence](../../specs/017-saas-lifecycle/evidence-017a.md).

## Plans
A plan is immutable data with an internal key and name and five limits: clients, seats, connections, managed links and tracked events per month. A missing limit (`null`) is unlimited. Only the default flag of a plan changes, and exactly one plan is the default. To change an agency's limits, the operator creates a new plan and assigns it.

Migration `0031_saas_plans` seeds the `development` plan as the default (5 clients, 10 seats, 10 connections, 500 active managed links, 100,000 tracked events per month) and assigns it to every agency that existed before it. `create_agency` gives a new agency the current default plan in the same transaction. Assignments are an insert-only history (`agency_plan_assignments`); the current plan is the highest `revision` of the agency.

## Limits
The four counted limits are hard on creation only. Each creation point counts under the agency row lock it already takes (`TenancyService._manager(write=True)`), so concurrent creations cannot exceed a limit, and a refusal answers:

```json
{"error": "plan_limit_reached", "limit": "clients", "value": 5, "used": 5}
```

| Limit | Counts | Checked by |
|---|---|---|
| `clients` | active client workspaces | `create_client`; reactivating an archived client |
| `seats` | active memberships plus pending, unexpired invitations | `invite`; `add_member`; re-enabling a disabled member |
| `connections` | connector connections that are `active` or `reconnect_required` | the connect start, and again where the callback creates the connection (the callback then redirects with `error=plan_limit_reached` and disposes of the grant) |
| `managed_links` | managed links with status `active`, whatever their expiry or client status | `create_link`; re-enabling a disabled link |

Never refused: reads, synchronizations, redirects, collection, erasure, deletion, archival, revocation, disconnection, reconnects and invitation acceptance (a pending invitation already holds its seat). Moving an agency to a smaller plan disables, deletes and hides nothing; the agency only cannot add more.

The monthly tracked-event allowance is soft (D5): events beyond it are accepted and counted, and the agency is shown `over_allowance`. A month is a UTC calendar month. The count covers the `collected_events` of all the agency's clients by `first_received_at`, up to 1,000,000 rows (`count_capped` beyond).

## Usage view
`GET /agencies/{agency_id}/plan` is for an active Owner, Admin or Analyst of an active agency, in a browser session; client viewers, other agencies and every bearer key are refused. It reads one READ ONLY REPEATABLE READ snapshot and names no client, person or event: the plan (key, name, `assigned_at`), each limit with its value, use and state (`within`, `at_limit`, `unlimited`), and the month's tracked events with their allowance and state (`within`, `over_allowance`, `unlimited`).

## Operator command
`python -m app.agency_plans` runs with the application settings as `tracking_app` and prints one JSON document. Every change needs `--confirm` (otherwise argparse exits with 2 before connecting) and writes an audit row with `actor_kind = 'platform_operator'` and no user; plan events belong to no agency, agency events appear in that agency's audit log.

```powershell
python -m app.agency_plans plans
python -m app.agency_plans create-plan --key growth --name "Growth" --clients 20 --seats 25 --connections 30 --managed-links unlimited --tracked-events 1000000 --reason new_offer --confirm
python -m app.agency_plans set-default --plan growth --confirm
python -m app.agency_plans assign --agency <uuid> --plan growth --reason plan_change --confirm
python -m app.agency_plans agencies --over-allowance --limit 100
python -m app.agency_plans suspend --agency <uuid> --confirm
python -m app.agency_plans reactivate --agency <uuid> --confirm
```

Plan reasons are `new_offer`, `replacement` and `individual`; assignment reasons `plan_change` and `correction`. Refusals print `{"error": code}` and exit with 1: `plan_exists`, `plan_not_found`, `already_default`, `agency_not_found`, `already_assigned`, `agency_closed`, `not_active` and `not_suspended` (the last two with the current status, so a closing or closed agency is never suspended or reactivated). `agencies` examines at most `--limit` agencies in ID order after `--after` and returns `next_after`. Output carries identifiers, keys, numbers, codes and times only, never a name, email, token or secret.

## Agency closure
| Route | Who | Effect |
|---|---|---|
| `POST /agencies/{agency_id}/closure` with `{"confirm_name", "password"?}` | an active Owner of an active agency | The exact name and the account-closure reauthentication (the password, or for an account without one a session under ten minutes old) are required; throttled three times per user per hour. The agency becomes `closing` with `closes_at` 30 days later. |
| `GET /agencies/{agency_id}/closure` | Owners, while active or closing | `{"agency_id", "agency_status", "closure"}` |
| `DELETE /agencies/{agency_id}/closure` | Owners, before `closes_at` | The agency is `active` again; connections were never revoked and work without reconnecting. |

A closing agency stops exactly as a suspended one: every existing check requires status `active`, so member routes, keys, collection, redirects, payments, integrations, WhatsApp, the connector, delivery and attribution workers refuse or skip it. `GET /agencies` still lists it for its Owners with `status: "closing"`. Refusal codes: `closure_in_progress`, `confirmation_mismatch`, `invalid_credentials`, `reauthentication_required`, `closure_not_open`, `grace_period_ended`, and `access_denied` for anyone else or any other state.

`python -m app.lifecycle` completes closures whose `closes_at` has passed, in bounded batches as `tracking_lifecycle` (agency lock first, as a cancellation does): it sets `completed_at` and the agency's status to `closed` (`deleted["agency_closures_completed"]`, reported only when non-zero). A closed agency is refused everywhere, also for its Owners, and nothing reopens it. Its data stays stored until the 017-B purge.

The sole Owner of a closing or closed agency may close the account (D9); an active or suspended agency still keeps its last Owner. Handing over ownership stays as before: an Owner makes another member an Owner.

## Agreement record
Registration and every sign-in send the versions the person accepted:

```json
{"email": "...", "password": "...", "agreements": {"terms": "draft-1", "privacy": "draft-1"}}
```

Google sign-in starts with `GET /auth/google/start?terms=draft-1&privacy=draft-1`; the sign-in transaction carries the versions to the callback. Missing or outdated versions answer `422 {"error": "agreement_required", "agreements": {"terms", "privacy", "published"}}` before any credential, account or provider work; the Google navigations redirect to the completion URL with `error=agreement_required` instead. A row per document is written only for a version the account has not agreed to yet (`user_agreements`, channel `registration`, `password_sign_in` or `google_sign_in`). `GET /auth/agreements` returns the current versions and whether the texts are published.

The versions are settings: `TRACKING_TERMS_VERSION` and `TRACKING_PRIVACY_VERSION` (`draft-1` in development) and `TRACKING_AGREEMENT_TEXTS_PUBLISHED` (false until the owner publishes the texts). Changing a version makes every client send the new one at its next sign-in. The lifecycle runner deletes the agreements of a closed account with its credential state; keeping proof longer awaits legal advice (Q-012).

## `Retry-After`
Platform CORS exposes `Retry-After` (D11) and nothing else, so the interface can say how long to wait after a `429`. Public collection CORS is unchanged.

## Tests
`backend/tests/integration/test_saas_plans.py`, `test_agency_closure.py`, `test_agency_closure_stops.py` and `test_agreements.py`, and `backend/tests/test_agency_plans_command.py`. The integration conftest keeps the seeded development plan between tests and accepts it in an otherwise empty database. Shared sign-in helpers send the current versions from `tests/integration/auth_support.py`.
