# Spec 017-A merge review (PR 19)

Reviewed 2026-11-27 under D-093 at head `a4421d1` of `codex/spec-017a-saas-plans`, against `main` at `633ea9a`. The owner asked Claude to review the completed branch and merge it if the review confirmed it.

## Scope of the review

The review checked the implementation against decisions D1-D14 of the [entry review](entry-review-017a.md), the [design note](design-017a.md) and the [evidence](evidence-017a.md):
- **Migration `0031_saas_plans`:**
  - the four tables and their closed checks;
  - the partial unique indexes: one default plan, and one open closure per agency;
  - the seed and its assignment to every existing agency;
  - the wider checks of `agencies.status` and `audit_events`, with the operator actor;
  - the runtime and lifecycle column grants, and the guarded downgrade.
- **Plans and limits (`plans.py`):**
  - the current plan as the highest assignment revision;
  - the default plan in the transaction that creates an agency;
  - the four counting statements;
  - the capacity check under the agency row lock at every creation point and every status change that raises use. These are clients, members, invitations and their acceptance, the connector start and installation, and managed links.
  - the bounded tracked-event count by UTC month;
  - the usage view in one read-only snapshot.
- **Operator command (`agency_plans.py`):** `--confirm` before any connection, the plan advisory lock, the agency row lock, the audit rows with the `platform_operator` actor, the refusals, and output without names or secrets.
- **Agency closure (`agency_closure.py`, `agency_lifecycle.py`):**
  - Owner only, the exact name, and the reauthentication and throttle of account closure;
  - the lock order that the cancellation shares with the lifecycle step: the agency, then the closure;
  - the grace-period checks on both sides;
  - the bounded, idempotent completion with its lock timeout;
  - the D9 rule in `close_account`.
- **Stop behavior.** Every existing check of the agency status compares with `active`, so a closing or closed agency stops as a suspended one does. Only the closure routes, and the agency list for Owners, read a closing agency.
- **Agreement record (`agreements.py`, the authentication and Google routes):**
  - the check before any credential, account or provider work;
  - one row per account, document and version;
  - the versions that the Google transaction carries, checked again at the callback after the transaction is consumed.
- **`Retry-After`:** exposed on platform CORS only.
- **Contract and tests:** the OpenAPI changes, the shared authentication helpers, and the changed expectations of existing tests.

## Verification run by the reviewer

All cases ran on a fresh disposable PostgreSQL 18.6 service (127.0.0.1:55433, `tracking_foundation_test`), with the repository's three roles and synthetic settings only.

| Check at `a4421d1` | Result |
|---|---|
| `ruff check app tests migrations`, `ruff format --check app tests migrations` | Clean (309 files) |
| `pytest -m "not integration"` | 949 passed |
| `pytest -m integration` with `TRACKING_RUN_BROWSER_TESTS=1`, Chromium | 738 passed; 7 skipped (the opt-in AV16, BV19 and D-076 measurements); the Firefox journey case not run |
| Tracker unit and browser (Chromium); the tracker is unchanged on this branch | 73 and 25 passed |
| `pip check`, `git diff --check`, relative links of the changed Markdown (330) | Clean |
| OpenAPI, semantic comparison with `main` | 3 paths and 11 schemas added; `AgencyAccess`, `AuditResponse`, `Login` and `Registration` gain fields; 10 operations document the new refusals or parameters; nothing removed |

Firefox is not installable in the review environment, so the Firefox cases were not run here. The implementing model's evidence records them passing.

## Findings

No defect was found. The following points are recorded limits or follow-ups, not changes:
- **The Spec 018 frontend.** Registration and every sign-in now require the agreement versions. Pull request 17 must therefore send them, from `GET /auth/agreements`, before its sign-in works with this backend. That pull request is brought up to date when the frontend work starts (D-091). The evidence (section 8) lists the change.
- **A closing agency without an Owner.** Under D9, the sole Owner of a closing agency may close their account. Nobody can then cancel the closure, and the agency closes at its closing time. D9 accepts this.
- **Two clocks.** The request and the cancellation use the application clock; the lifecycle step uses the database clock. Both sides lock the agency first, and the checks allow one outcome per closure. A difference between the clocks can therefore only move the moment of the change, never produce two outcomes.
- **The lifecycle grant.** `tracking_lifecycle` may update any agency status. Only the step's predicate and the status check restrict the value, as the evidence notes.

## Result

PR 19 merged into `main` as `06d6a19`, a merge commit of `633ea9a` and `a4421d1` whose tree equals the reviewed head `a4421d1`.
