# Specification 003 evidence: slice 003-A (003-A1 to 003-A5)
Date: 2026-11-04. Branch: `codex/spec-003-privacy-data-policy`. Base: merged main `98747a2` (PR 1). Authority: D-023 (continuation and independent work for 003-A1/003-A2) and D-024 (003-A3 to 003-A5). Status: implemented locally for owner review; not uploaded, not merged, not rolled out.

## Scope
- **003-A1, data-class registry:** [backend/app/data_policy.py](../../backend/app/data_policy.py) maps every stored column to a data class. Each table has end-of-life rules with a decision status and reference. A check compares the registry with the SQLAlchemy metadata and the migrated database.
- **003-A2, log allowlist:** [backend/app/logging_config.py](../../backend/app/logging_config.py) admits only registered application events with closed field codes. It switches every existing handler and uvicorn's handlers to the allowlist formatter and reduces library records and exceptions to safe diagnostics. The application lifespan and the mail worker apply the same configuration.

Excluded and unchanged: schema, migrations, runtime grants, dependencies, API and OpenAPI, retention periods, deletion behavior, mail delivery, configuration, native `tracking_sys`, and private `.env` files. Slices 003-A3 to 003-A5 await the [decision packet](decision-packet-003a.md).

## Baseline established before changes
| Check | Command and target | Result |
|---|---|---|
| Full suite at `98747a2` (working tree with only the pre-existing owner formatting edit in `models/tenancy.py`) | `pytest -q` against `tracking_foundation_test` on `127.0.0.1:55433` (Compose project `tracking-spec003-test`) | **196 passed**, 2 Pydantic `UnsupportedFieldAttributeWarning` warnings from two concurrency tests, 68.42 s. The warnings were not reported in the later runs; they appear order- or thread-dependent and were not investigated. |
| Runtime grants and foreign keys | Catalog queries as the migrator on the disposable database at `0004_identity` | 19 application tables plus alembic_version, 10 single-column foreign keys to users, no ON DELETE rules, roles `tracking_app` and `tracking_migrator`. The grant matrix is in the [decision packet](decision-packet-003a.md#decision-4-privilege-model). |
| Log leakage probe | Real uvicorn 0.54 server in a child process with uvicorn's default logging configuration | Three synthetic secrets reached stderr: a `tracking` record with `%`-arguments (M1), an exception message in the `uvicorn.error` traceback (M2), and an unconfigured library logger through Python's last-resort handler (M3). |
| New logging tests on an untouched archive of `98747a2` | `pytest tests/test_logging.py` | **7 failed, 1 passed.** Only the registered-event case passes, as expected. |
| PostgreSQL DETAIL claim | Synthetic duplicate insert on the disposable 18.6 server, rolled back (0 rows left) | Confirmed: with `log_error_verbosity = default`, the server log DETAIL line contains the conflicting key value. The client exception also contains it; the application's integrity handler does not log it. |

## Results after the change
| Check | Result |
|---|---|
| Full suite on the disposable database | **215 passed** in 81.30 s: 63 unit/contract and 152 PostgreSQL. No failures, skips, or reported warnings. This adds 19 tests (18 unit, 1 integration) to the 196-test baseline, which all still pass. |
| Unit and contract only (`-m "not integration"`) | **63 passed**, 152 deselected, 6.79 s |
| Registry tests (`tests/test_data_policy.py`, `tests/integration/test_data_policy_schema.py`) | 11 passed. They cover the current schema in metadata and in the migrated database; a synthetic unclassified column and table; a dropped column; a user reference outside `account.reference`; an unknown class; a missing row rule; an approved rule without a decision; and a rule targeting a missing column. Only two rules are approved, both decided under 002. |
| Logging tests (`tests/test_logging.py`) | 8 passed. They cover a registered event with a permitted code; rejection of positional arguments (M1), an f-string event, an unregistered field, and an invalid field value (M3); exceptions reduced to type and origin; and two real uvicorn servers in child processes, one with the factory built after uvicorn's logging configuration (CLI order) and one with the application built before it. Exception text, the request query string, `%`-arguments, and library arguments are all absent from stdout and stderr; no traceback is written; access lines carry only their template. |
| M6 and existing redaction tests | Pass. `CurrentStderrHandler` writes to the stderr current at emit time, so `capsys` assertions in existing tests now observe the real output rather than a stream bound when the first application was created. |
| Ruff | `ruff check` and `ruff format --check` pass on `backend/app`, `backend/migrations`, and `backend/tests`, with the owner's uncommitted `models/tenancy.py` edit checked at its committed version. |
| `pip check` | No broken requirements. No dependency was added. |

Every run used a guarded runner. It drops inherited `TRACKING_*` variables, takes synthetic disposable credentials from `.env.docker`, and forces local mail mode with Google sign-in and the Gmail sender disabled and blank, so the root `.env` (native database, Gmail mode) cannot reach tests. The integration fixtures also refuse any database other than `tracking_foundation_test` on port 55433. No external email was sent, no provider was contacted by tests, and the native database was not used. The Gmail worker loop left running from the specification 002 owner test (one delivery at 18:52) was stopped before this work, so the native outbox is no longer being drained.

During the run, Docker Desktop stopped outside this work. It was restarted, and the disposable database was recreated under the same project name before the reported runs.

## Compared with the 2026-11-03 proposal
- The inventory listed `0003_auth` with 16 tables. The actual state is `0004_identity` with 19 tables, including `external_identities`, `oauth_transactions`, and `verification_challenges`, and `mail_outbox.expires_at`.
- The proposed mail payload expiry already exists for verification codes (`expired_before_delivery`, D-022). Reset and invitation messages still lack it (decision 5).
- The password re-entry-only closure proposal does not cover Google-only accounts (decision 3).
- `retention_runs` is not needed for the time-based credential-state slice (decision 1).
- The constraint DETAIL concern is now verified.

## Migration and grant impact
None in 003-A1/003-A2. The registry check runs as the migrator in tests only. Proposed changes for later slices (lifecycle role, `users.closed_at`, `account_closed`, one column-limited runtime grant, one API operation) are listed in the decision packet and are not implemented.

## Not validated
- No live Google sign-in, Gmail delivery, or production configuration was exercised; none was needed for these slices.
- The Alembic command-line process keeps its own logging configuration (revision names only). Exceptions printed by Python itself when a command-line process crashes, and warnings raised through the `warnings` module, are outside logging and are not covered.
- PostgreSQL server settings on native or future operated servers were not inspected or changed; `log_error_verbosity = terse` is a recommendation.
- Gmail's retention of API-sent messages in the sender's Sent folder is expected behavior but was not verified.
- Library message templates are pinned to uvicorn 0.54 wording. A changed template degrades to `library_record_suppressed` (safe, less informative).

## 003-A3 and 003-A4 under D-024
The owner selected the recommended option of every decision packet item on 2026-11-04 (D-024).

Changes:
- **Mail expiry (A4).** Reset and invitation messages are queued with `expires_at` equal to their token expiry, so the worker clears an undelivered expired link unsent.
- **Lifecycle runner (A3).** [backend/app/services/lifecycle.py](../../backend/app/services/lifecycle.py) and `python -m app.lifecycle` delete ended credential state after the D-024 periods. The periods are settings whose defaults are also their maxima. The runner holds an advisory lock in the two-key space and uses ordered batches that re-check eligibility in the outer `DELETE`. A batch waits at most 100 ms for a row lock, so a conflict defers only the lifecycle batch, never an API request. The runner also deletes development `.eml` files older than 7 days in local mode.
- **Migration and role.** `0005_lifecycle` grants the new `tracking_lifecycle` role (`NOINHERIT`, no schema privileges) `SELECT` and `DELETE` on six tables. The role is provisioned in `init-roles.sh`, `local-roles.sql`, and the new `lifecycle-role.sql` for existing native installations. Compose gains a `lifecycle` profile. A generated password was added to the ignored `.env.docker` without being displayed. The data-class registry now marks the six tables and the outbox payload rule as approved under D-024.

Results on the disposable database (fresh volume created with the new role):

| Check | Result |
|---|---|
| Full suite | **240 passed** in 61.96 s: 69 unit/contract and 171 PostgreSQL. No failures, skips, or reported warnings. |
| Lifecycle settings and file cleanup (unit) | 6 passed. Defaults equal the approved periods, and longer values are rejected. Only old `.eml` and `.pending` files directly in the directory are deleted; the 7-day boundary is kept. Nothing is deleted in production or Gmail mode. |
| Boundaries (L3) | 13 anchor cases across six tables. A row exactly at its boundary and rows that have not ended are kept; a row one microsecond past is deleted. A second run deletes nothing. |
| Bounded runs and resumption | Batch size 2 with one batch per run deletes 2, then 2 (status `partial`, target listed), then the last row; nothing is skipped. |
| Competing runner | With the advisory lock held elsewhere, the run returns `skipped_concurrent_run` and deletes nothing; after release, the next run deletes the row. |
| Row locked by a request | The run finishes in under 2 s with only that table incomplete, while other tables are purged. The request's transaction still commits, and the next run deletes the row. |
| Authentication after purge | Through the real HTTP flow, after deleting revoked sessions, an expired reset token, a consumed challenge, and delivered outbox rows: the active session still works; a deleted session cookie gets 401; replaying the deleted reset token gets the generic `invalid_or_expired_token`; login still succeeds. No foreign-key error occurs. |
| Mail expiry (L4) | Reset and invitation outbox rows carry exactly their token and invitation expiry. Once expired, the worker reports 2 expired, 0 attempts, payloads cleared, and no file written. |
| Lifecycle role (L7) | 12 statements are refused: deleting users, credentials, identities, security and audit events, memberships, or invitations; reading users; updating or inserting credential state; creating a table. Role attributes show no superuser, database or role creation, RLS bypass, or inheritance. Existing `tracking_app` privilege tests still pass unchanged. |
| OpenAPI | Unchanged (contract equality test passes). |
| Ruff | Passes on `backend/app`, `backend/migrations`, and `backend/tests`, excluding only the owner's uncommitted `models/tenancy.py` edit. |

Not validated for A3/A4:
- Native rollout: no role was created and no migration was applied on tracking_sys. Until that owner-approved step, an API started from this branch against native tracking_sys reports readiness `not_ready` (`schema_mismatch`) while its endpoints keep working, and the runner cannot connect.
- Rate-limit races are covered by the outer predicate re-check, but only by analysis; no deterministic concurrent-restart test.
- Outbox rows queued without `expires_at` before D-024 stay until delivered.

## 003-A5 under D-024
Changes:
- **Migration 0006_account_closure.** It adds `users.closed_at` with the check `closed_at IS NULL OR status = 'disabled'` and the `account_closed` security action. It grants `tracking_app` `UPDATE` on only `email_normalized`, `display_name`, `status`, and `closed_at`, and grants `tracking_lifecycle` `SELECT` on users and `SELECT`/`DELETE` on password credentials and external identities. Its guarded downgrade refuses populated closure state. The `tenancy.py` model change was staged on top of HEAD, so the owner's uncommitted formatting edit in that file stays out of the commit.
- **Closure endpoint.** `POST /auth/close-account` checks Origin and CSRF and is throttled per peer and per user. Reauthentication is the password, or, for an account without one, a session at most 10 minutes old (a setting with that approved maximum). The endpoint locks the user row, then every agency of the user's active memberships in ID order, and refuses with 409 if an agency would lose its last active Owner. Otherwise it pseudonymizes the email and name, disables the account with `closed_at`, revokes sessions, ends open tokens, challenges, and OAuth transactions, disables memberships with audit rows, and records `account_closed`.
- **Runner.** It deletes a closed account's credential, external identity, sessions, tokens, challenges, and OAuth transactions without a period. The registry marks users, credentials, and external identities as approved under D-024. OpenAPI regenerated: 30 paths, 37 operations.
- **Intentional change to 002 privilege expectations.** Two parametrized checks expected the runtime to be unable to run `UPDATE users SET status='disabled'`. D-024 grants exactly that column-limited update for closure, so the checks now assert that other user columns (`created_at`, `id`) and `DELETE FROM users` stay refused.

Results:

| Check | Result |
|---|---|
| Full suite on the disposable database | **254 passed** in each of four runs (67-71 s): 69 unit/contract and 185 PostgreSQL. No failures or skips. One run reported one warning whose summary was not captured, and it did not recur; the intermittent Pydantic warning seen at baseline is the likely source (unverified). |
| Closure tests (`tests/integration/test_account_closure.py`) | 12 passed in each of five consecutive runs. The two thread-based concurrency tests also passed in ten further consecutive runs. |
| Password account | 204, cookie cleared, another session of the same user gets 401, and login with the old email fails. The row holds `closed-<id>@tracking.invalid`, `Closed account`, `disabled`, and `closed_at`. `account_closed` is recorded and no session stays open. The same email registers again as a new user ID. |
| Wrong or missing password; missing CSRF | 401 `invalid_credentials` or 403, and nothing changes. |
| Google-only account | A session older than 10 minutes gets 403 `reauthentication_required`; a fresh session closes the account. Google sign-in for that subject is refused until the runner deletes the identity (1 identity, 1 session); afterward the same subject and email sign up as a new user. |
| Credential deletion | The runner deletes the closed account's password credential; the pseudonymized row remains. |
| Last Owner and memberships | A sole Owner gets 409, and the account stays active. With a second Owner, closure succeeds and one active Owner remains. An analyst in agency A who is also an admin in agency B closes; all three memberships are disabled, with `membership.updated` audit rows attributed to the closing users. |
| Concurrency and lock order | Two co-owners closing at once: exactly one 204 and one 409, one Owner left. Closure racing a self-demotion: one succeeds, one gets 409, one Owner left. Deterministic test: while a tenancy transaction holds the agency lock, the closure is observed waiting in `pg_stat_activity`; the holder demotes the other Owner and commits, and the closure then re-checks and returns 409. Reverse order: after a co-owner closes, demoting the remaining Owner returns 409. |
| Migration | The full suite's base-to-head cycle includes 0005 and 0006; the 0006 downgrade with a closed account is refused and the revision stays at `0006_account_closure`. |
| Container | `docker compose --profile lifecycle run --rm lifecycle` built the image, ran the migrate step, connected as `tracking_lifecycle` to the disposable database, and printed a completed run. |
| Ruff and `pip check` | Pass, including the staged `tenancy.py`; no dependency was added. |

Not validated for A5:
- No native rollout.
- No browser test with a real Google sign-in followed by closure; the Google path used the account-policy function with synthetic claims.
- A membership added concurrently in an agency that was not locked stays active for the disabled user. This is inert, and its adder remains an active Owner there.
- Closure cannot be undone.

## Acceptance criteria of specification 003
| Criterion | Evidence now | Outstanding dependency |
|---|---|---|
| 1. Consent-violating events kept out of storage and outbound queues | None | 003-B with 004, 005, 014 |
| 2. Password and payment fields excluded from form telemetry and logs | Logs: M1-M3, M6 pass on the real server path | Form telemetry M4/M5 with 005 and 004 |
| 3. Deletion covers raw, derived, cache, export, and blocks replay | Platform-user scope: account closure pseudonymizes identity and the runner deletes credentials, external identities, and ended credential state (A3, A5) | Subject, connector, cache, export, and replay blocking: 003-B, 003-C, 016 |
| 4. Restore reapplies tombstones before service | None | 003-D with 019, 020 |

The specification is not complete. Both social analytics and attribution, and multi-agency isolation, remain required launch scope.
