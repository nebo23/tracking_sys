# Quality gates
Status: Draft. Quantitative targets require owner decisions Q-004 and Q-011.

| Area | Required evidence | Stage |
|---|---|---|
| Tenant/client access | Two agencies with two clients each; denied API, job, cache, and export access cases | 002 and every relevant change |
| Event integrity | Duplicates, conflicts, out-of-order delivery, invalid signatures, timestamp/schema/body limits | 004 |
| Tracker | Denied consent, form redaction, and successful redirects during collector failure | 005 |
| Identity | Shared devices, identifier conflicts, merge/unmerge, and cross-client denial | 006 |
| Ledger | Sale, refund, chargeback, reversal, FX, and reconciliation fixtures | 007 |
| Attribution | Expected First/Last/Linear results, unknown sources, window boundaries, rounding invariants | 008 |
| Connectors | Actual access grant, sanitized contract fixtures, revocation, rate limits, and historical coverage | 009-015 |
| Reporting | Reconciled totals, non-additive metrics, partial/unavailable states, and scoped exports | 016 |
| SaaS lifecycle | Approved trials/plans/usage, delayed billing events, and offboarding | 017 |
| Interface | Complete workflows, permissions, state/cache isolation, approved RTL support, accessibility | 018 |
| Load/security | Agreed capacity, dependency review, webhook replay, SSRF, injection, and authorization | 019 |
| Recovery | Backup restoration, migration recovery, worker crashes, and reapplication of deletion controls | 020 |

## Proposed definition of done
An approved specification, evidence for acceptance criteria, current documentation, migration/recovery procedures where applicable, protected secrets, known limitations, and reviewer acceptance. Never label an unexecuted check as passed.

## Measurable assurance
Define calculation correctness for known inputs, coverage and missing-event limits, measurable service objectives, and recovery procedures. Platform approval and provider outages are outside application control; their impact must be visible. A universal 100% guarantee is not a valid release criterion.

## Reproducible environments
Run future Python application checks inside the project virtual environment or an appropriate container using declared dependencies. Use project-local frontend dependencies. Record actual runtime and dependency versions with meaningful validation evidence; do not install project packages globally.

## Continuous integration (review follow-up A2)
Status on 2026-11-22: **not configured.** The repository has no `.github/workflows`, the pull requests show no commit statuses or check runs, and `main` has no branch protection or required checks. Every result so far is a local run recorded in the specification evidence. An empty status list is not a passing check.

A minimal check path would use only the approved, pinned stack, with no paid service, no new dependency and no deployment step. It would run on GitHub-hosted runners for pull requests against `main`:
1. Python 3.12 with `pip install --require-hashes -r backend/requirements.txt -r backend/requirements-dev.txt` into a job-local virtual environment, then `pip check`, `ruff check` and `ruff format --check` in `backend/`.
2. The unit and contract suite, with synthetic settings: `pytest -m "not integration"`. It includes the OpenAPI snapshot comparison.
3. The integration suite against a `postgres:18.6` service container. It needs the role script of `infra/docker/postgres/init-roles.sh`, the guarded database name and port of `backend/tests/integration/conftest.py`, and synthetic passwords and keyrings generated in the job, never repository secrets.
4. The tracker package: `npm ci` with the committed lockfile, `npm test`, then `npm run install:browsers` and `npm run test:browser` for Chromium and Firefox. With `TRACKING_RUN_BROWSER_TESTS=1`, the backend browser journeys run as well.

Activating such a workflow is a repository-process change: it runs on every push, uses the hosted runners' minutes and may become a required check. It needs an explicit owner decision under the working agreement. Until then, the D-069 merge gate relies on the recorded local runs.
