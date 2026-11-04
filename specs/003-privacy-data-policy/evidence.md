# Specification 003 evidence: 003-A1 and 003-A2
Date: 2026-11-04. Branch: `codex/spec-003-privacy-data-policy`. Base: merged main `98747a2` (PR 1). Authority: D-023 (continuation and independent work). Status: implemented locally for owner review; not uploaded, not merged, not rolled out.

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

## Acceptance criteria of specification 003
| Criterion | Evidence now | Outstanding dependency |
|---|---|---|
| 1. Consent-violating events kept out of storage and outbound queues | None | 003-B with 004, 005, 014 |
| 2. Password and payment fields excluded from form telemetry and logs | Logs: M1-M3, M6 pass on the real server path | Form telemetry M4/M5 with 005 and 004 |
| 3. Deletion covers raw, derived, cache, export, and blocks replay | Registry identifies every column that references a user (10) as a closure target | Decision 3 (003-A5); 003-B, 003-C, 016 |
| 4. Restore reapplies tombstones before service | None | 003-D with 019, 020 |

The specification is not complete. Both social analytics and attribution, and multi-agency isolation, remain required launch scope.
