# Claude handoff: Specification 003 privacy and data lifecycle

Historical implementation handoff. For the scoped PR review corrections authorized on 2026-11-08, use [review-corrections-prompt.md](review-corrections-prompt.md) under D-026. Its correction-specific publication approval supersedes this document's earlier upload gate for that task only.

Prepared: 2026-11-04. Authority: D-023. Working directory: `C:\Code\Tracking-system`.
Branch: `codex/spec-003-privacy-data-policy`. Base: merged main at `98747a296dd570c5f40f76c68796d3e53edb9cc4` (PR 1).

## Task and working agreement

Continue specification 003 through concrete design reconciliation, independently reviewable implementation slices, relevant verification, and owner review. The owner wants progress toward completion, with a dedicated branch containing only this specification and its amendments. Communicate in Arabic; keep project files, documentation, comments, and contributions in formal English.

Work on the existing dedicated branch. Do not return to `claude/development`, commit to `main`, or create another branch merely because another agent created this one. For subsequent specifications, create a fresh specification branch from then-current merged main; keep corrections for the same specification on its branch until merged. Do not carry unfinished specifications into the next branch.

D-023 authorizes continuation, not blanket approval of candidate privacy policies, new schema, privileges, dependencies, spending, hosting, or provider use. Prepare concrete choices and their consequences before asking for decisions; do not ask the owner again whether to start. Continue independent authorized work while a dependent policy decision is pending. Do not silently choose retention values or deletion behavior. Do not push, open/update a PR, merge, or deploy until the owner separately approves that step after reviewing the completed work.

## Read before editing

1. `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, and `specs/README.md`.
2. This specification's `spec.md`, `plan.md`, `tasks.md`, `design.md`, and `review-amendments.md`.
3. `research_notes/privacy-data-policy/sources.md`, including its access limitations and confidence labels.
4. `specs/002-tenancy-access/auth-design.md`, `auth-evidence.md`, and `auth-corrections-2026-11-04.md`.
5. Current models, migrations, services, logging, mail worker, configuration, database grants, and relevant tests. Documentation is not a substitute for reading current behavior.

## Establish the actual baseline

- Inspect `git status`, branch, base, and targeted diffs before editing. PR 1 already merged specifications 001/002, Google sign-in, Gmail delivery, numeric verification OTPs, and the R-01 to R-03 corrections. Do not implement those features again.
- Latest baseline migration is `0004_identity`. The privacy proposal still describes `0003_auth` and 16 application tables; refresh it against actual metadata and migration code. Include external identities, OAuth transactions, verification challenges, and the current mail expiry behavior. Verify names, fields, constraints, permissions, and data paths instead of copying this list as evidence.
- Preserve Google linking's originating-session binding and revocation checks; preserve serialized OTP attempt accounting and expiry checks after lock waits. Read the regression tests before changing shared authentication code.
- The previously reported baseline suite had 196 passing checks. This is historical evidence, not a test result for your changes. Record actual commands and results for the new revision. README status text predates the merge; reconcile relevant status statements using Git evidence.
- The older Google/Gmail amendment file contains superseded proposals and unchecked preparation steps. The approved auth design and actual code take precedence for implemented behavior. Do not infer live provider success from configuration or automated substitutes.

## Preserve existing work and keep the diff scoped

At handoff time, unrelated tracked edits exist in `backend/app/models/tenancy.py`, `specs/001-foundation/tasks.md`, and `specs/002-tenancy-access/tasks.md`. Older untracked review/handoff documents also exist under specifications 001/002. Preserve them without staging or rewriting them as part of this specification. Shared `AGENTS.md` and `docs/planning/decisions.md` contain pre-existing owner changes as well as D-023; inspect their hunks and stage only the changes intentionally included in this handoff or required by the approved slice.

The privacy `design.md`, `review-amendments.md`, and research sources were existing local preparation. Preserve useful content and distinguish inherited proposals from your changes. Scope commits to specification 003 documents/research, approved implementation/tests, and necessary shared workflow or contract updates. Use explicit staging paths or hunks; never `git add .`. Do not stash, reset, clean, or delete owner work to obtain a clean status.

## First deliverable: reconcile the design and prepare the next slice

Produce an updated inventory and a concrete 003-A design that fits the merged schema. Mark each item as implemented, proposed, awaiting an owner decision, or dependent on a later specification. Review the five required contracts: `ConsentRecord`, `DataClassPolicy`, `DeletionRequest`, `TokenSecretReference`, and the provider-specific policy table.

Prepare a compact owner decision packet for the choices that block 003-A:

1. Exact boundaries of the first implementation slice and proposed migration/API/privilege changes, including alternatives with no schema change where practical.
2. Retention eligibility, timestamp anchors, periods, holds, and treatment of new identity/OTP/OAuth records. Q-012 candidate values remain proposals; do not activate them by labeling them development defaults.
3. Account closure and erasure behavior, audit references, last-active-Owner protection, concurrent membership/session changes, email reuse, external-identity reuse, and reauthentication for Google-only accounts. The old password-reentry-only proposal does not cover all current accounts.
4. Dedicated lifecycle role versus other privilege models, with a table-by-table grant matrix that preserves runtime append-only audit/security permissions.
5. Remaining mail cleanup/retry changes after checking what D-022 already implemented. Do not duplicate existing payload expiry or silently introduce the proposed retry cap or local-file deletion periods.

Present a recommended option with concrete effects and focused alternatives. Record only the owner's actual decisions. Resolve Q-003 and other broader policy questions when their dependent work requires them; do not infer a market from Arabic conversation or block unrelated inventory/design work on later hosting choices. Reverify legal and provider claims against current primary sources before making decisions from them, recording dates, unsupported claims, and access limits. This handoff does not revalidate the old research.

## Implementation and verification after applicable decisions

- **003-A, current data:** implement the approved data-class registry, log protection, lifecycle operations, mail cleanup, and account closure/erasure as independently reviewable slices. Map every relevant column, including new identity tables. Unresolved retention rules must be explicitly pending, not falsely described as approved. Do not enact destructive behavior from the proposal alone.
- Exercise boundary times, idempotency, batching/resumption, holds, competing runners, lock ordering, and partial failures. Verify that retry/resume logic cannot permanently skip eligible rows. Cover the effect of deleting identity or verification rows on foreign keys and authentication.
- Prove secret-bearing exception messages, interpolated log arguments, and unexpected library records cannot leak synthetic secrets. Preserve useful sanitized diagnostics. Test actual logger routes rather than only a helper in isolation.
- Test authorization across agency/client boundaries, account ownership changes and last-owner races, and preserve the R-01 to R-03 regressions. Keep `tracking_app` audit/security privileges restricted.
- Use existing isolated dependencies. Any major dependency or schema change needs the concrete reviewed decision first; keep approved manifests/locks synchronized.
- Run migrations, rollback/recovery, lifecycle deletion, concurrency, and data-changing integration checks only on a verified disposable PostgreSQL database. The earlier disposable endpoint was `127.0.0.1:55433` / `tracking_foundation_test`; verify the actual target and guard it before use. Never treat the native `tracking_sys` database on port 5432 as a test target. Native rollout requires its own reviewed authorization.
- Use synthetic fixtures and mocked providers. Do not send external mail, drain a native Gmail outbox, modify OAuth accounts, or print `.env`, passwords, tokens, recipient data, or provider response bodies.
- Run checks appropriate to each change and the relevant authentication/tenancy regression suite; record passed, failed, skipped, and untested cases honestly. Remove one-time scripts and exports after use, retaining reusable tooling.

## Keep the complete specification visible

003-A does not complete every acceptance criterion of specification 003. Maintain the dependency map from the design:

- **003-B:** consent and deletion contracts, with ingestion/tracker/outbound enforcement owned by the relevant 004/005/014 slices.
- **003-C:** provider restrictions and protected connector secrets, coordinated with 009-016.
- **003-D:** deletion reconciliation after restore, with 019/020 and their storage/recovery decisions.

Review and prepare these contracts within specification 003 without silently implementing unapproved downstream business features or selecting infrastructure. Map every original acceptance criterion to its concrete evidence or named outstanding dependency. Synthetic contract tests demonstrate only the tested contracts; do not claim end-to-end enforcement before the real consumer exists. Both social analytics and attribution, and multi-agency isolation, remain required launch scope.

## Review handoff

Keep `spec.md`, `plan.md`, `tasks.md`, and `design.md` consistent with the actual scope and decisions. Add a concise implementation evidence/review document with baseline comparison, completed changes, migration/grant impact, exact validation results, remaining decisions, and deferred acceptance cases. Link sources instead of claiming certification or automatic compliance.

Commit each completed, checked slice locally on `codex/spec-003-privacy-data-policy`, excluding unrelated owner edits. End with an Arabic review report naming the branch and commits, what is ready for review, what still requires decisions, and what has not been validated. Upload and merge remain separate owner decisions. Never mark the whole specification complete merely because 003-A passes.
