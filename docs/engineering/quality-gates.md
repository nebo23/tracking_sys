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
