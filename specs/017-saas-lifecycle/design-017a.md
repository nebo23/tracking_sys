# Spec 017-A design: plans, limits and agency closure

Prepared: 2026-11-26 under D-092. Revision: 1. Status: approved scope ([D1-D14](entry-review-017a.md#3-decisions-for-the-owner), D-092, without amendment). This note fixes the exact statements, answers, error codes, grants and tests before any code; section 4 of the entry review is its source. Section 12 lists the routine details resolved here. No material new choice was found that needs the owner.

## 1. Inventory on the branch (P0)

Baseline: `codex/spec-017a-saas-plans` at `25975bf`, created from `origin/claude/keen-fermat-otlr9d`; merged `main` at `633ea9a` is an ancestor, and `origin/main` has not moved beyond it. D-092 is recorded in `AGENTS.md` and `docs/planning/decisions.md`. Pull request 17 (Spec 018) is still open, so the Spec 018 decisions and its frontend application are not on this branch: `frontend/` holds only placeholder README files.

### 1.1 Every check of the agency status

Every check compares `agencies.status` with `'active'`, so a `closing` or `closed` agency fails each of them exactly as a `suspended` one does. No check needs to change.

| Place | Check | Effect for a non-active agency |
|---|---|---|
| `TenancyService._membership` (`services/tenancy.py`) | `Agency.status == 'active'`, also under `FOR UPDATE` | Every member route and every service built on it (clients, members, grants, audit, invitations, keys, links, connectors, collection administration, revenue, identity, attribution, reports) is refused with `403 access_denied`. |
| `resolve_scope` (`services/access.py`) | through `_membership` for users | Client reads, finance reads, identity reads refused. |
| `live_service_credential` (`services/access.py`) | `Agency.status == 'active'` | Read and ingest keys fail with `401 authentication_required`. |
| `AccessService.accept_invitation` | `Agency.status == 'active'` under `FOR UPDATE` | `400 invalid_or_expired_token`. |
| `GET /agencies` (`api/tenancy.py`) | `Agency.status == 'active'` | The agency is not listed. |
| `collection.live_source` | `Agency.status == 'active'` | Public browser intake, consent, consent-state, erasure, identity handoff and signed webhook intake refused. |
| `links.resolve_redirect` | `Agency.status == 'active'` | Managed-link redirects answer as unknown. |
| `payments` source lookup | `Agency.status == 'active'` | Paymob callbacks answer like an unknown source. |
| `integrations` source lookup | `Agency.status == 'active'` | Cal.com and signed CRM webhooks answer like an unknown source. |
| `whatsapp` number lookup | `Agency.status == 'active'` | WhatsApp referrals are not routed. |
| `connectors.schedule_syncs` | `Agency.status == 'active'` | No synchronization is queued. |
| `connectors._claim` and `_fence` | `agency != 'active'` | A queued run is cancelled (`client_inactive`); a running one stops before persisting. |
| `connector_webhooks` | `Agency.status == 'active'` | A verified provider webhook queues nothing. |
| `delivery._client_active` and the delivery claim | `Agency.status == 'active'` | Conversions are not enqueued or sent. |
| `attribution_store.run_pass` | `Agency.status == 'active'` | The attribution worker skips the agency's clients. |

Teardowns of connections already disconnecting continue for a suspended agency today (`test_connectors.py`), and they continue for a closing agency in the same way. The lifecycle retention targets do not read the agency status and keep running.

### 1.2 Creation points and the changes that raise use

| Limit | Creation point | Status change that raises use | Lock already taken |
|---|---|---|---|
| clients | `TenancyService.create_client` | `update_client`: `archived` to `active` | `_manager(write=True)` |
| seats | `AccessService.invite`; `TenancyService.add_member` | `update_member`: `disabled` to `active` | `_manager(write=True)` |
| connections | `ConnectorAdmin.begin` (connect); `connectors._install` (connect) | none: a reconnect keeps a live connection live | `_manager(write=True)`; `_initiator(write=True)` |
| managed_links | `LinkAdmin.create_link` | `update_link`: `disabled` to `active` | `_write` through `_manager(write=True)` |

`create_agency` adds the founder's Owner membership; it is counted as a seat but never refused. `accept_invitation` turns a pending invitation, already counted as a seat, into a membership, so it is never refused (`add_member(..., seat_reserved=True)`). No other code inserts these rows.

## 2. Migration `0031_saas_plans` (after `0030_reporting_indexes`)

### 2.1 Tables

```sql
CREATE TABLE saas_plans (
    id uuid NOT NULL,
    key varchar(32) NOT NULL,
    name varchar(100) NOT NULL,
    clients_limit integer,
    seats_limit integer,
    connections_limit integer,
    managed_links_limit integer,
    tracked_events_limit bigint,          -- monthly allowance; soft (D5)
    is_default boolean NOT NULL DEFAULT false,
    reason varchar(24) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_saas_plans PRIMARY KEY (id),
    CONSTRAINT uq_saas_plans_key UNIQUE (key),
    CONSTRAINT ck_saas_plans_valid_key CHECK (key ~ '^[a-z][a-z0-9_-]{1,31}$'),
    CONSTRAINT ck_saas_plans_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_saas_plans_limits CHECK (
        (clients_limit IS NULL OR clients_limit >= 0)
        AND (seats_limit IS NULL OR seats_limit >= 0)
        AND (connections_limit IS NULL OR connections_limit >= 0)
        AND (managed_links_limit IS NULL OR managed_links_limit >= 0)
        AND (tracked_events_limit IS NULL OR tracked_events_limit >= 0)),
    CONSTRAINT ck_saas_plans_valid_reason
        CHECK (reason IN ('seed', 'new_offer', 'replacement', 'individual'))
);
CREATE UNIQUE INDEX uq_saas_plans_default ON saas_plans (is_default) WHERE is_default;

CREATE TABLE agency_plan_assignments (
    id uuid NOT NULL,
    agency_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    revision integer NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    assigned_by varchar(20) NOT NULL,
    reason varchar(20) NOT NULL,
    CONSTRAINT pk_agency_plan_assignments PRIMARY KEY (id),
    CONSTRAINT fk_agency_plan_assignments_agency_id_agencies
        FOREIGN KEY (agency_id) REFERENCES agencies (id),
    CONSTRAINT fk_agency_plan_assignments_plan_id_saas_plans
        FOREIGN KEY (plan_id) REFERENCES saas_plans (id),
    CONSTRAINT uq_agency_plan_assignments_revision UNIQUE (agency_id, revision),
    CONSTRAINT ck_agency_plan_assignments_positive_revision CHECK (revision >= 1),
    CONSTRAINT ck_agency_plan_assignments_valid_assigned_by
        CHECK (assigned_by IN ('default', 'platform_operator')),
    CONSTRAINT ck_agency_plan_assignments_valid_reason
        CHECK (reason IN ('initial', 'new_agency', 'plan_change', 'correction')),
    CONSTRAINT ck_agency_plan_assignments_reason_matches
        CHECK ((assigned_by = 'default') = (reason IN ('initial', 'new_agency')))
);
CREATE INDEX ix_agency_plan_assignments_plan_id ON agency_plan_assignments (plan_id);

CREATE TABLE agency_closures (
    id uuid NOT NULL,
    agency_id uuid NOT NULL,
    requested_by_membership_id uuid NOT NULL,
    requested_at timestamptz NOT NULL,
    closes_at timestamptz NOT NULL,
    cancelled_at timestamptz,
    cancelled_by_membership_id uuid,
    completed_at timestamptz,
    CONSTRAINT pk_agency_closures PRIMARY KEY (id),
    CONSTRAINT fk_agency_closures_agency_id_agencies
        FOREIGN KEY (agency_id) REFERENCES agencies (id),
    CONSTRAINT fk_agency_closures_requested_by_agency_memberships
        FOREIGN KEY (agency_id, requested_by_membership_id)
        REFERENCES agency_memberships (agency_id, id),
    CONSTRAINT fk_agency_closures_cancelled_by_agency_memberships
        FOREIGN KEY (agency_id, cancelled_by_membership_id)
        REFERENCES agency_memberships (agency_id, id),
    CONSTRAINT ck_agency_closures_grace_period CHECK (closes_at > requested_at),
    CONSTRAINT ck_agency_closures_cancellation
        CHECK ((cancelled_at IS NULL) = (cancelled_by_membership_id IS NULL)
               AND (cancelled_at IS NULL
                    OR (cancelled_at >= requested_at AND cancelled_at < closes_at))),
    CONSTRAINT ck_agency_closures_completion
        CHECK (completed_at IS NULL OR completed_at >= closes_at),
    CONSTRAINT ck_agency_closures_one_outcome
        CHECK (cancelled_at IS NULL OR completed_at IS NULL)
);
CREATE UNIQUE INDEX uq_agency_closures_open ON agency_closures (agency_id)
    WHERE cancelled_at IS NULL AND completed_at IS NULL;
CREATE INDEX ix_agency_closures_due ON agency_closures (closes_at)
    WHERE cancelled_at IS NULL AND completed_at IS NULL;

CREATE TABLE user_agreements (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    document varchar(16) NOT NULL,
    version varchar(32) NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    channel varchar(20) NOT NULL,
    CONSTRAINT pk_user_agreements PRIMARY KEY (id),
    CONSTRAINT fk_user_agreements_user_id_users FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT uq_user_agreements_user_document_version UNIQUE (user_id, document, version),
    CONSTRAINT ck_user_agreements_valid_document CHECK (document IN ('terms', 'privacy')),
    CONSTRAINT ck_user_agreements_valid_version
        CHECK (version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$'),
    CONSTRAINT ck_user_agreements_valid_channel
        CHECK (channel IN ('registration', 'password_sign_in', 'google_sign_in'))
);
```

The current plan of an agency is its assignment with the highest `revision`; every assignment takes the agency row lock, so revisions are gapless and follow commit order. The unique key `(agency_id, revision)` makes a concurrent duplicate fail instead of creating two current plans.

### 2.2 Changes to existing tables

| Table | Change |
|---|---|
| `agencies` | `ck_agencies_valid_status` becomes `status IN ('active', 'suspended', 'closing', 'closed')`. |
| `oauth_transactions` | Two nullable columns, `terms_version varchar(32)` and `privacy_version varchar(32)`: the versions a Google sign-in accepted at its start (entry review 4.5, "the Google completion carries them in the stored transaction"). Link transactions leave them null. |
| `audit_events` | `actor_kind varchar(20) NOT NULL DEFAULT 'user'`; `actor_user_id` and `agency_id` become nullable; `ck_audit_events_actor`: `(actor_kind = 'user' AND actor_user_id IS NOT NULL) OR (actor_kind = 'platform_operator' AND actor_user_id IS NULL)`; `ck_audit_events_scope`: `agency_id IS NOT NULL OR (actor_kind = 'platform_operator' AND resource_type = 'plan')`. The closed lists gain the actions `agency.plan_assigned`, `agency.suspended`, `agency.reactivated`, `agency.closure_requested`, `agency.closure_cancelled`, `plan.created` and `plan.default_set`, and the resources `plan`, `plan_assignment` and `agency_closure`. |

The audit change is required by D7 and 4.6: the operator's changes are audited in the agency's audit log "with the actor `platform_operator`", which is not a user, and `plan.created` and `plan.default_set` belong to no agency. Rows written by users are unchanged (`actor_kind = 'user'`). Platform-level rows (no agency) are never listed by `GET /agencies/{agency_id}/audit`, which filters by agency.

### 2.3 Seed

```sql
INSERT INTO saas_plans (id, key, name, clients_limit, seats_limit, connections_limit,
                        managed_links_limit, tracked_events_limit, is_default, reason)
VALUES (gen_random_uuid(), 'development', 'Development', 5, 10, 10, 500, 100000, true, 'seed');
INSERT INTO agency_plan_assignments (id, agency_id, plan_id, revision, assigned_by, reason)
SELECT gen_random_uuid(), a.id, p.id, 1, 'default', 'initial'
FROM agencies a CROSS JOIN saas_plans p WHERE p.key = 'development';
```

### 2.4 Grants

| Role | Grants |
|---|---|
| `tracking_app` | `SELECT, INSERT` on `saas_plans` with `UPDATE (is_default)`; `SELECT, INSERT` on `agency_plan_assignments`; `SELECT, INSERT` on `agency_closures` with `UPDATE (cancelled_at, cancelled_by_membership_id)`; `SELECT, INSERT` on `user_agreements`. No `DELETE` or `TRUNCATE` anywhere; existing table-level grants already cover the new `oauth_transactions` and `audit_events` columns. |
| `tracking_lifecycle` | `SELECT (id, status)` and `UPDATE (status, updated_at)` on `agencies`; `SELECT (id, agency_id, closes_at, cancelled_at, completed_at)` and `UPDATE (completed_at)` on `agency_closures`; `SELECT (id, user_id)` and `DELETE` on `user_agreements`. Nothing on `saas_plans` or `agency_plan_assignments`. |

The lifecycle role thereby changes one tenancy column for the first time: an agency's status, only from `closing` to `closed` by the runner's predicate (the grant cannot restrict values; the predicate and the `agencies` check constraint do). The operator command runs as `tracking_app` (4.6).

### 2.5 Guarded downgrade

Under `ACCESS EXCLUSIVE` locks on the four new tables, `agencies`, `oauth_transactions` and `audit_events`, the downgrade refuses (`RuntimeError: Refuse to remove stored plan, closure or agreement state; use a forward fix.`) when any of these exists: a plan other than the seed (`reason <> 'seed'`); an assignment that is not a default assignment of the seed plan (`assigned_by <> 'default'`); any closure row; any agreement row; an agency in `closing` or `closed`; an OAuth transaction with an agreement version; an audit row with `actor_kind <> 'user'`, no agency, a new action or a new resource. Otherwise it revokes the grants, drops the four tables, the two transaction columns and `actor_kind`, restores the `NOT NULL` constraints and the previous check constraints. Default assignments of the seed plan carry nothing that cannot be rebuilt: the next upgrade assigns the seed plan again.

## 3. Limits (D4, entry review 4.2)

`app/services/plans.py` holds the plan reads, the counts and the check. Every count runs after the creation point has taken the agency row lock (`SELECT ... FROM agencies ... FOR UPDATE`, through `_manager(write=True)` or `_initiator(write=True)`), under READ COMMITTED, so each statement sees every committed creation, and a concurrent creation for the same agency waits for the lock and then counts again.

| Limit | Counting statement |
|---|---|
| clients | `SELECT count(*) FROM client_workspaces WHERE agency_id = :a AND status = 'active'` |
| seats | `(SELECT count(*) FROM agency_memberships WHERE agency_id = :a AND status = 'active') + (SELECT count(*) FROM agency_invitations WHERE agency_id = :a AND status = 'pending' AND expires_at > :now)` |
| connections | `SELECT count(*) FROM connector_connections WHERE agency_id = :a AND status IN ('active', 'reconnect_required')` |
| managed_links | `SELECT count(*) FROM managed_links WHERE agency_id = :a AND status = 'active'` |
| current plan | `SELECT p.* FROM agency_plan_assignments x JOIN saas_plans p ON p.id = x.plan_id WHERE x.agency_id = :a ORDER BY x.revision DESC LIMIT 1` |

`require_capacity(session, agency_id, limit)` refuses when the plan's value is not null and `used + 1 > value`, raising `PlanLimitReached(limit, value, used)`. The API answers `409 {"error": "plan_limit_reached", "limit": "clients" | "seats" | "connections" | "managed_links", "value": <int>, "used": <int>}`. An agency without any assignment (never expected: the migration and `create_agency` assign one) is refused with `409 plan_unavailable`.

- A connect checks at `begin`, so a full agency is told before it leaves for the provider, and again when `_install` creates the connection under the agency lock; there the refusal is `ConnectorError("plan_limit_reached", 409)`, the exchanged grant is disposed of, and the callback redirects to the completion URL with `error=plan_limit_reached` (added to `CALLBACK_ERRORS`).
- Counted resources ignore the client's status (an archived client keeps its links and connections), and expiry does not change a link's status, so the only changes that raise use are the three of section 1.2. Disabling a link, archiving a client, disabling a member, revoking or letting an invitation expire and disconnecting free a place.
- Never refused (D4): every read, synchronization, redirect, collection, erasure, deletion, archival, revocation, disconnection, invitation acceptance, reconnect, and every status change that lowers use.

## 4. Usage view (D6, entry review 4.3)

`GET /agencies/{agency_id}/plan`, browser sessions only (`BrowserDep`, so any bearer key, read or ingest, is refused with `401 authentication_required`). After authentication, the read runs in a separate READ ONLY REPEATABLE READ snapshot (`report_snapshot`), which first checks that the caller is an active Owner, Admin or Analyst of the active agency (`403 access_denied` otherwise, also for a client viewer and for another agency), then reads the plan, the four counts and the month's events. The answer names no client, person or event:

```json
{
  "agency_id": "uuid",
  "plan": {"key": "development", "name": "Development", "assigned_at": "2026-11-26T10:00:00Z"},
  "limits": [
    {"limit": "clients", "value": 5, "used": 2, "state": "within"},
    {"limit": "seats", "value": 10, "used": 4, "state": "within"},
    {"limit": "connections", "value": 10, "used": 0, "state": "within"},
    {"limit": "managed_links", "value": 500, "used": 0, "state": "within"}
  ],
  "tracked_events": {
    "period_start": "2026-11-01T00:00:00Z", "period_end": "2026-12-01T00:00:00Z",
    "count": 0, "count_capped": false, "allowance": 100000, "state": "within"
  },
  "as_of": "2026-11-26T10:00:00Z"
}
```

- Limit states: `unlimited` when the value is null, `at_limit` when `used >= value` (also after a downgrade below the use), otherwise `within`.
- Tracked events are the `collected_events` rows of all the agency's clients whose `first_received_at` falls in the current UTC calendar month of the snapshot's `now()`: `SELECT count(*) FROM (SELECT 1 FROM collected_events WHERE agency_id = :a AND client_id = ANY(:clients) AND first_received_at >= :start AND first_received_at < :end LIMIT 1000001) bounded`, which uses `ix_collected_events_client_received`. With more than 1,000,000 rows the count is reported as 1,000,000 with `count_capped: true`. The state is `unlimited` without an allowance, `over_allowance` when the count exceeds it, otherwise `within`. Nothing is refused or dropped (D5).

## 5. Agency closure (D8, D9, entry review 4.4)

### 5.1 State machine

| From | Event | To | Closure row |
|---|---|---|---|
| `active` | Owner request | `closing` | inserted with `closes_at = requested_at + 30 days` |
| `closing` | Owner cancel before `closes_at` | `active` | `cancelled_at`, `cancelled_by_membership_id` set |
| `closing` | lifecycle step at or after `closes_at` | `closed` | `completed_at` set to the run's cutoff |
| `active` | operator `suspend` | `suspended` | none |
| `suspended` | operator `reactivate` | `active` | none |

A suspended agency cannot request closure (the operator reactivates it first), the operator cannot suspend a closing or closed agency, `reactivate` refuses a closing or closed agency, and nothing reopens a closed agency. Connections are not revoked at the request (D8); 017-B purges.

### 5.2 Routes (`app/api/plans.py`)

The closure routes resolve the caller with `_closure_owner`: the agency must be `active` or `closing`, the user active, the membership active and its role Owner; otherwise `403 access_denied`. They are the only routes that read a closing agency, besides `GET /agencies`.

| Route | Body and answer | Refusals, in check order |
|---|---|---|
| `POST /agencies/{agency_id}/closure` | `{"confirm_name": str, "password": str?}`; `201` with the closure state | `429 rate_limited` (per peer, and three per user per hour in scope `agency-closure`); `403 access_denied`; `409 closure_in_progress` (already closing); `422 confirmation_mismatch` (not exactly the agency's name); `401 invalid_credentials` (an account with a password, wrong or missing); `403 reauthentication_required` (an account without a password and a session older than `closure_reauthentication_seconds`) |
| `GET /agencies/{agency_id}/closure` | `200` with the closure state | `403 access_denied` |
| `DELETE /agencies/{agency_id}/closure` | `204` | `403 access_denied`; `409 closure_not_open` (no open closure); `409 grace_period_ended` (`now >= closes_at`) |

The closure state answer is `{"agency_id", "agency_status": "active" | "closing", "closure": {"id", "requested_at", "closes_at", "requested_by_membership_id"} | null}`. The request and the cancellation take the agency write lock, write the closure row and the agency status together, and are audited as `agency.closure_requested` and `agency.closure_cancelled` (resource `agency_closure`, actor the Owner). The reauthentication is the account-closure rule of D-024, moved into `AuthService.reauthenticate` and shared by both closures.

`GET /agencies` lists, besides the active agencies of the caller's active memberships, the closing agencies in which the caller is an active Owner; each entry gains `status` (`active` or `closing`). Every other route refuses a closing or closed agency through the unchanged checks of section 1.1.

### 5.3 Lifecycle step

`app/services/agency_lifecycle.py`, run by `run_lifecycle` after the attribution step under the job's advisory lock, as `tracking_lifecycle`. Each batch is one transaction with the 100 ms batch lock timeout:

```sql
SELECT id, agency_id FROM agency_closures
WHERE cancelled_at IS NULL AND completed_at IS NULL AND closes_at <= :cutoff
ORDER BY closes_at, id LIMIT :size;
-- for each candidate, agency first, as a cancellation does:
SELECT status FROM agencies WHERE id = :agency FOR UPDATE;         -- skip unless 'closing'
SELECT id FROM agency_closures WHERE id = :closure AND cancelled_at IS NULL
  AND completed_at IS NULL AND closes_at <= :cutoff FOR UPDATE;     -- skip unless found
UPDATE agency_closures SET completed_at = :cutoff WHERE id = :closure;
UPDATE agencies SET status = 'closed', updated_at = :cutoff WHERE id = :agency;
```

Batches repeat until one completes fewer than `lifecycle_batch_size` closures or `max_batches` is reached (then `agency_closures` is reported incomplete, as is a lock timeout). A re-run selects nothing already completed, so the step is idempotent. Completed closures are counted as `deleted["agency_closures_completed"]`, reported only when non-zero, as the attribution step does with its counts. No audit row is written: the lifecycle role has no audit grant, and the closure row records the completion.

### 5.4 Account closure (D9)

`close_account` locks the agencies of the user's active memberships as today and reads their status under the lock. An Owner membership blocks the closure only when its agency is `active` or `suspended` and no other active Owner with an active account remains. A closing or closed agency never blocks it; its membership is disabled and audited like the others. A closing agency whose last Owner closed the account can no longer be cancelled and completes at `closes_at`.

## 6. Agreement record (D10, entry review 4.5)

### 6.1 Settings and discovery

`Settings.terms_version` and `Settings.privacy_version` (default `draft-1`, pattern `^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$`) and `Settings.agreement_texts_published` (default `false`; set only once the owner publishes the texts under these labels). `GET /auth/agreements` (public, no database access) answers `{"terms": "draft-1", "privacy": "draft-1", "published": false}`.

### 6.2 Requests and the order of the checks

| Request | Agreement input | Order |
|---|---|---|
| `POST /auth/register` | `"agreements": {"terms": str, "privacy": str}` | Origin; throttles; agreement check; registration |
| `POST /auth/login` | the same | Origin; throttles; agreement check; credential check; session and records |
| `GET /auth/google/start` (login) | query `terms` and `privacy` | enabled check; peer throttle; agreement check; transaction with the versions; redirect to Google |
| `GET /auth/google/callback` (login) | the versions stored in the transaction | transaction check and consumption; stored versions against the current ones; code exchange; account policy; session and records |

The field is optional in the schema, so that a missing value is answered with the agreement code rather than `validation_failed`. Missing or different versions answer `422 {"error": "agreement_required", "agreements": {"terms": ..., "privacy": ..., "published": ...}}`, before any credential, account or provider work, so they reveal nothing. Google start and callback are browser navigations; they redirect to the completion URL with `error=agreement_required` instead (added to the callback codes), and the callback has consumed its transaction first. Google account linking is not a sign-in and needs no agreement.

### 6.3 Records

`agreements.record(session, user_id, channel, settings)` inserts one row per document with `ON CONFLICT (user_id, document, version) DO NOTHING`, in the transaction that creates the account (registration, channel `registration`), the session (password sign-in, channel `password_sign_in`) or, inside the callback's savepoint, the Google session (channel `google_sign_in`). A registration of an existing email changes nothing and records nothing, as before. A second sign-in with the same versions writes nothing; a new version writes one row per document. The lifecycle runner deletes the agreements of a closed account with its credential state (4.1; whether proof must be kept longer awaits legal advice, Q-012).

## 7. `Retry-After` (D11)

`PlatformCors` gains `expose_headers=["Retry-After"]`. Platform responses to an allowed origin carry `Access-Control-Expose-Headers: Retry-After` and nothing else; other origins still receive no CORS grant, and public collection CORS is unchanged.

## 8. Operator command (D7, entry review 4.6)

`python -m app.agency_plans` runs with `Settings()` as `tracking_app`, prints one JSON document on standard output, and exits 0 on success, 1 with `{"error": code}` on a refusal, and 2 with an argparse message when the arguments are invalid or `--confirm` is missing for a change.

| Subcommand | Arguments | Effect and output |
|---|---|---|
| `plans` | none | every plan: key, name, the five limits (`null` for unlimited), `is_default`, reason, `created_at`, and the number of agencies whose current plan it is |
| `create-plan` | `--key`, `--name`, `--clients`, `--seats`, `--connections`, `--managed-links`, `--tracked-events` (each a non-negative integer up to 1,000,000,000 or `unlimited`, all required), `--reason {new_offer,replacement,individual}`, `--confirm` | inserts the plan; audit `plan.created`; prints the plan; `plan_exists` |
| `set-default` | `--plan KEY`, `--confirm` | moves the default flag; audit `plan.default_set`; `plan_not_found`, `already_default` |
| `assign` | `--agency UUID`, `--plan KEY`, `--reason {plan_change,correction}`, `--confirm` | new assignment under the agency lock; audit `agency.plan_assigned`; `agency_not_found`, `plan_not_found`, `already_assigned`, `agency_closed` |
| `agencies` | `--over-allowance`, `--after UUID`, `--limit N` (1-500, default 100) | examines at most `--limit` agencies in ID order after `--after` and prints `{"agencies": [...], "next_after": UUID | null}`: ID, status, plan key, `assigned_at`, the four uses and the month's tracked events; with `--over-allowance`, only the examined agencies over their allowance |
| `suspend` | `--agency UUID`, `--confirm` | `active` to `suspended` under the agency lock; audit `agency.suspended`; `agency_not_found`, `not_active` (with the current status) |
| `reactivate` | `--agency UUID`, `--confirm` | `suspended` to `active`; audit `agency.reactivated`; `agency_not_found`, `not_suspended` (with the current status, so a closing or closed agency is refused) |

Plan changes run under a transaction advisory lock (namespace 1701), so two concurrent `set-default` commands cannot both clear the flag. Audit rows have `actor_kind = 'platform_operator'` and no actor user; agency rows carry the agency, plan rows none. The output never contains an agency or client name, a person, an email, a token or a secret: only identifiers, keys, numbers, codes and times.

## 9. Data policy and lifecycle

New data classes: `plan.definition` (low, not personal, system), `plan.assignment` (low, not personal, system), `agency.closure` (medium, pseudonymous through memberships, system) and `account.agreement` (medium, pseudonymous, provided). Table rules:

| Table | Rule |
|---|---|
| `saas_plans` | approved (D-092): never deleted; plans are immutable and referenced by the assignment history (D2) |
| `agency_plan_assignments` | deferred (017-B; D-092): insert-only history kept with the agency; the purge of a closed agency belongs to 017-B |
| `agency_closures` | deferred (017-B; D-092): kept with the agency until the 017-B purge |
| `user_agreements` | approved (D-092; D-024): deleted by the lifecycle runner with a closed account's credential state; proof of agreement beyond that awaits legal advice (Q-012) |
| `agencies` | deferred (017-B; D-092): closure moves an agency to `closing` and then `closed`; its purge belongs to 017-B |

`audit_events.actor_kind` is `audit.administrative`; the two `oauth_transactions` version columns are `account.agreement` and follow the transaction's one-day rule. The lifecycle runner gains the target `user_agreements` (closed accounts, no period) and the closure step of section 5.3. The table counts become 91 in both data policy tests, and 11 single-column user references.

## 10. API changes

Additions: `GET /agencies/{agency_id}/plan`; `POST`, `GET` and `DELETE /agencies/{agency_id}/closure`; `GET /auth/agreements`; the optional `agreements` field of `Registration` and `Login`; the optional `terms` and `privacy` query parameters of `GET /auth/google/start`; `status` in `AgencyAccess`; `actor_kind` in `AuditResponse`; the schemas `PlanLimitError`, `PlanSummary`, `PlanLimitUse`, `TrackedEventsUse`, `AgencyPlanResponse`, `AgencyClosureInput`, `AgencyClosureResponse`, `OpenAgencyClosure`, `AgreementAcceptance`, `AgreementVersions` and `AgreementRequiredError`.

Documented changes that are not additions:
- `AuditResponse.actor_user_id` becomes nullable, for the operator's audit rows (section 2.2).
- The `409` response of the use-raising routes documents `PlanLimitError`, a superset of `ErrorResponse` (`error` plus the optional `limit`, `value` and `used`): `POST` and `PATCH` of clients, `PATCH` of members, `POST` of invitations, the connector connect, and `POST` and `PATCH` of managed links.
- The agency status values are documented on `AgencyAccess.status`; `AgencyResponse.status` stays a plain string, because client responses share it.

## 11. Test helpers and inventory

### 11.1 Helper changes

- `tests/integration/conftest.py`: `TABLES` gains `user_agreements`, `agency_closures`, `agency_plan_assignments` and `saas_plans` in child-first order. The teardown and the empty-database guard treat `saas_plans` specially: the seed row (`reason = 'seed'`) is kept and restored as the default, every other plan is deleted. `api.agreements` holds the current versions, and `api.login` sends them.
- The module helpers that register or sign in send the versions: `test_auth.register`, `test_account_closure.registered_user`, `test_verification_code.register`, `test_google.start`, and the direct calls in `test_auth`, `test_account_closure`, `test_auth_review_regressions`, `test_google`, `test_lifecycle` and `test_origin_config`. Nothing else in those tests changes.
- `test_postgres.py` accepts the four new tables and the seed row before it downgrades to base; `test_data_policy.py` and `test_data_policy_schema.py` expect 91 tables and 11 user references.

### 11.2 Inventory (SV01-SV20)

| Case | Test (modules under `backend/tests/`) |
|---|---|
| SV01 | `integration/test_saas_plans.py::test_sv01_new_agencies_get_the_current_default_plan`; the existing agencies in SV18 |
| SV02 | `test_saas_plans.py::test_sv02_each_limit_refuses_exactly_the_creation_beyond_it` (four limits), `::test_sv02_changes_that_raise_use_are_limited`, `::test_sv02_a_missing_limit_never_refuses` |
| SV03 | `test_saas_plans.py::test_sv03_concurrent_creations_at_the_limit_have_one_winner` (clients, invitations, connections, links), `::test_sv03_a_waiting_creation_counts_after_the_lock` |
| SV04 | `test_saas_plans.py::test_sv04_a_smaller_plan_keeps_everything_and_refuses_only_new_creations` |
| SV05 | `test_saas_plans.py::test_sv05_reads_syncs_redirects_collection_erasure_archival_and_revocation_are_never_refused` |
| SV06 | `test_saas_plans.py::test_sv06_events_beyond_the_allowance_are_accepted_and_counted_by_utc_month` |
| SV07 | `test_saas_plans.py::test_sv07_usage_view_roles_keys_and_answer` |
| SV08 | `test_saas_plans.py::test_sv08_operator_command_subcommands_audit_and_refusals`; `test_agency_plans_command.py` (argument checks, `--confirm`) |
| SV09 | `test_saas_plans.py::test_sv09_suspension_stops_the_agency_and_reactivation_restores_it`; the `suspended` cases of SV11 |
| SV10 | `integration/test_agency_closure.py::test_sv10_closure_request_is_owner_only_named_and_reauthenticated` |
| SV11 | `integration/test_agency_closure_stops.py`, each case for `suspended` and `closing`: member routes and keys, collection, redirects, payments, integrations, WhatsApp, the connector worker, the delivery worker, the attribution worker |
| SV12 | `test_agency_closure.py::test_sv12_cancellation_restores_the_agency_and_its_connections` |
| SV13 | `test_agency_closure.py::test_sv13_lifecycle_completes_due_closures_once_and_in_bounded_batches` |
| SV14 | `test_agency_closure.py::test_sv14_sole_owner_account_closure_by_agency_status` (active, suspended, closing, closed) |
| SV15 | `integration/test_agreements.py::test_sv15_registration_requires_and_records_the_current_versions` |
| SV16 | `test_agreements.py::test_sv16_password_sign_in_records_a_new_version_once`, `::test_sv16_outdated_versions_are_refused_before_the_credential_check`, `::test_sv16_google_sign_in_carries_the_versions_in_its_transaction` |
| SV17 | `test_agreements.py::test_sv17_retry_after_is_readable_from_the_application_origin` |
| SV18 | `test_saas_plans.py::test_sv18_upgrade_seeds_and_assigns_grants_and_guarded_downgrade` |
| SV19 | `test_saas_plans.py::test_sv19_agencies_never_see_each_other_and_output_carries_no_secret`; `test_agency_closure.py::test_sv19_closure_isolation_and_logs` |
| SV20 | every existing module unchanged apart from section 11.1; `test_contract.py`; the semantic OpenAPI diff of section 10 |

The mutation check of P5 disables, one at a time, the four limit checks, the agency lock (`_membership` without `FOR UPDATE`), the status change of the closure request (intake and workers), the Owner-only rule, the closure reauthentication, the completion step, the D9 sole-Owner rule (both directions), the agreement check, the single record per version and `--confirm`, and records which tests fail.

## 12. Routine details resolved here

1. Plan reasons and assignment reasons are closed codes (privacy: no free text). Plan reasons: `seed`, `new_offer`, `replacement`, `individual`; assignment reasons: `initial` and `new_agency` (by default), `plan_change` and `correction` (by the operator).
2. The current plan is the highest `revision`, unique per agency, instead of the latest time, so ties cannot occur.
3. A change that raises use (unarchiving a client, re-enabling a member, re-enabling a link) is checked like a creation; without it a full agency could archive, create and unarchive past its limit. 4.2 never refuses only the changes that lower use.
4. Counted resources ignore the client's status and the link's expiry, so archiving a client or an expiry never changes use invisibly.
5. A connect is checked at its start and again where the connection is created; the callback refusal disposes of the grant.
6. Tracked events are counted up to 1,000,000 per month and flagged `count_capped` beyond.
7. The usage view is for browser sessions; every bearer key is refused.
8. `POST /closure` answers `201`; `DELETE /closure` answers `204`, like the other deletions; the name must match exactly; the request is throttled like account closure; after `closes_at` an Owner can no longer cancel, even before the runner has completed the closure.
9. The operator's audit rows extend `audit_events` with `actor_kind` (section 2.2).
10. A Google start without the current versions redirects to the completion URL with `error=agreement_required`, because the start is a browser navigation; JSON routes answer `422`.
11. `agreement_texts_published` is an explicit setting, so the answers can say that the texts are not published.
12. The lifecycle completion records `completed_at` at the run's cutoff and writes no audit row.

## 13. Change the frontend needs (reported, not implemented)

The Spec 018 frontend is on pull request 17, not on this branch. Its sign-in and registration need these changes once both merge: read `GET /auth/agreements`; send `agreements: {terms, privacy}` with `POST /auth/register` and `POST /auth/login` when the box is ticked; open `GET /auth/google/start?terms=...&privacy=...`; on `422 agreement_required` or `error=agreement_required` on the Google completion page, show the agreement box again with the returned versions; show `409 plan_limit_reached` with its limit, value and use, and the usage view; offer the closure routes to Owners; and read `Retry-After`, which the browser can now see.
