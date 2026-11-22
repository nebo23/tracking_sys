# Spec 015 and predecessor review corrections

Prepared on 2026-11-22 under D-069. Execute this handoff; do not return another implementation plan without doing the authorized work. Communicate with the owner in Arabic. Write project files, comments, evidence and commit messages in formal English.

## Objective and authority

Correct and individually verify all eleven findings R001-R011 from the [cross-specification review](../../reports/specs-001-015-review-2026-11-22.md), including R010 in Spec 014 and R011 in Spec 010. Keep the corrections on `codex/spec-015-business-integrations` in the existing [PR 13](https://github.com/nebo23/tracking_sys/pull/13). Do not open a replacement PR or commit to `main`.

The owner requested a correction prompt, verification of each problem one by one, and merge at the end. D-069 records that sequence: implement, prove each correction, review the final code, publish the verified corrections, and merge PR 13 only when every merge condition below is satisfied. This is conditional authorization, not authorization to merge the currently defective head or to bypass a required review or check. Do not request upload approval again for these corrections. The preparation commit changes documents and carries the regression patch; it does not fix application code.

Existing gates for new product/security policies, schema decisions, major dependencies, live providers, native database rollout and deployment remain in force. Routine implementation details and reversible verification within the approved correction scope do not require another permission request. If a concrete fix needs a genuinely new decision, prepare the smallest reviewable option with its consequences, request only that decision, and continue independent corrections. A pending decision keeps the affected finding open and prevents merge.

## Read before editing

1. `AGENTS.md`, `README.md`, `docs/planning/decisions.md`, especially D-025, D-051, D-063 to D-069.
2. The complete [review report](../../reports/specs-001-015-review-2026-11-22.md), not only its summary, and the [correction tracker](review-corrections-tracker.md).
3. `spec.md`, `entry-review.md`, `entry-review-round2.md`, `design-015a.md`, `design-015b.md`, `evidence.md` and `tasks.md` in this directory.
4. `docs/engineering/payments.md`, `integrations.md`, `advertising.md`, `event-collection.md` and `data-lifecycle.md`.
5. The relevant Spec 003/004 privacy contracts, Spec 007-A ledger contracts, Spec 010 day-cursor follow-up, and Spec 014 currency-preservation rules.
6. `backend/tests/README.md` and `packages/tracker-js/package.json` for the actual verification commands and environment.

## Establish the working state

- Prefer the existing worktree `C:\Code\Tracking-system\.worktrees\spec-015-business-integrations`. The root checkout was older than GitHub at review time. Inspect the current branch, status, worktrees and remote PR head before changing anything.
- Fetch the existing branch and `main`. Preserve later owner commits and uncommitted work. Never reset, force-push or clean another session's files. If a concurrent writer is present, isolate the work and coordinate before publishing overlapping edits.
- The immutable defective baseline is `db750d1b728f2ca352a999afe71c92a1b10730e1`; base main was `73efae9249e7111281a9c5e8c1f7a12771cd013a`. The handoff itself is a later documentation commit, so do not demand that the current head still equals the defective baseline.
- Read the actual diff from `db750d1` to the current head. If fixes already exist, verify them rather than overwriting them. Keep the baseline SHA in every comparison.
- Use project-local dependencies. Never print credentials or copy ignored environment files into a review archive. Preserve the native database on port 5432 and all unrelated containers.

## Reproduce before fixing

The original existing suite at `db750d1` passed 1,243 backend cases, plus 67 JavaScript unit cases and 44 Chromium/Firefox cases. Those counts exclude the new regressions and do not prove the defects absent.

The [regression patch](../../reports/specs-001-015-review-regressions.patch) adds:

- `backend/tests/integration/test_review_001_015.py`: 12 integration cases.
- `backend/tests/test_review_instagram_cursor.py`: one unit case.

From the repository root, inspect and apply the patch with `git apply --check reports/specs-001-015-review-regressions.patch`, then `git apply reports/specs-001-015-review-regressions.patch`. If already applied, inspect the existing tests instead. Keep these tests or clearly mapped equivalent permanent regressions in the final suite.

Reproduce the cases in an isolated archive/checkout of `db750d1`, with a disposable PostgreSQL database and the browser/test settings explicitly enabled. The review observed 12 integration failures in 24.04 seconds and one Instagram assertion failure. Failures must be at the intended assertion or erasure constraint, not fixture setup, missing dependencies, a disabled feature, or database connectivity. Save concise results in the tracker/evidence. Preserve the historical report and patch as baseline evidence.

The repository guard expects the disposable test database on port 55433. The audit used port 55434 only in a private fixture copy to avoid another session. Inspect port ownership and container labels; use an independent disposable service when necessary and document any test-only guard adaptation. Never weaken the guard to permit arbitrary databases, and never run these tests against `tracking_sys`.

## Work through every finding

For each ID: read its full report entry, reproduce it, explain the root cause, implement the smallest sound correction, run the corresponding regression and adjacent positive cases, then record the commit, commands and results. A changed assertion alone is not a correction. Do not skip, xfail, delete, or weaken a test to obtain a passing count. Adapt a test only when a reviewed contract genuinely changes; retain an equivalent test of the original failure and explain the difference.

### R001 P1 Authenticate the financial meaning of Paymob evidence

Reproduce both unchanged-signature attacks: test-to-live promotion through `is_live`, and refund retargeting through `parent_transaction`. Keep Paymob's documented signature algorithm unchanged. A valid HMAC does not authenticate fields outside that algorithm, and the signed child flags do not identify the refund's parent or the environment.

Establish a trustworthy source for environment and parent linkage before posting verified evidence. Re-read current official documentation for any protocol proposal; distinguish independently authenticated evidence from merchant-controlled assertions. If the existing approved callback-only contract cannot establish the property, prepare a concrete decision amendment with an explicit unverified/pending outcome or an independently verified path. Keep live provider calls out of this task. Do not silently make every payment unverified, disable the provider, trust the callback URL as evidence, or invent a signature field. Such behavior changes cannot be labelled feature-complete without the necessary recorded decision.

Verify valid confirmed sales and refunds still work under the resulting approved contract, test-mode events never post, unsigned changes cannot create/reassign verified revenue, duplicate and reordered callbacks remain safe, and the 008/014 consumers never promote unverified evidence.

### R002 P1 Keep booking detachment and subject erasure atomic

Fix the mismatch between `ON DELETE SET NULL` and `ck_bookings_valid_link`: both `subject_id` and `linked_at` must be consistent when a subject is deleted. Cover explicit erasure and lifecycle expiry, including a newer booking referring to an older subject. Use the client privacy lock and the real restricted database roles. Test successful deletion, link removal, retained booking integrity, tombstone replay prevention, rollback and cross-client isolation. Do not drop the consistency constraint or broaden runtime/lifecycle privileges indiscriminately.

### R003 P1 Enforce current attribution consent on booking links

Cover withdrawal, expiry, report reads and later/replayed deliveries. A historical grant must not keep a booking attributable after consent ends or restore that link without a valid new grant and the required evidence. Make the effective relation and all consumers consistent; changing only the displayed total is insufficient if a downstream path still uses an invalid relation. Add a concurrency test where it protects the actual privacy invariant.

### R004 P1 Verify the external WhatsApp asset before routing

An agency Owner's authority over its own workspace is not proof that it owns an arbitrary Meta phone-number ID. Make legitimate provider-to-client binding precede activation/routing. A global uniqueness constraint or an extra confirmation by the same claimant is insufficient.

Propose the smallest trustworthy binding mechanism, such as a separately authorized platform binding or a provider-verified ownership flow, with its actor, evidence, revocation and transfer semantics. A new onboarding/security policy or schema needs its specific decision; D-069 does not select a protocol by implication. Use synthetic proof fixtures only, not a live Meta call. Keep a valid enrollment and callback path working. Test another agency's first claim, attempted reassignment, pending/unproven claims, duplicate registration, disabled bindings and routing after verification. Never store extra personal message data to implement the proof.

### R005 P2 Refuse malformed Paymob callback types uniformly

Validate `type` before set membership. Lists, objects, null and other malformed discriminators must not throw HTTP 500 or persist evidence. Preserve the uniform 401 response and the existing signature, size, rate and keyring behavior. Cover both valid callback kinds.

### R006 P2 Separate booking identity namespaces

Two independent signed webhook sources may both use `booking-1`. Scope identity lookup, uniqueness and chain merging to a source or an explicitly shared account namespace. A cancellation or reschedule from one source must not affect the other. Keep true duplicates, out-of-order chain reconciliation, multiple clients and intentional provider-account semantics covered. Review necessary schema changes explicitly; do not revise merged migrations silently.

### R007 P2 Make CRM optional evidence independent of delivery order

Keep the same latest stage, amount/currency and payment reference for both orders of the reported events. Define whether changes are partial updates or complete snapshots and make parsing, storage and documentation agree. Preserve atomic amount/currency pairs and deterministic tie handling. If adopting complete snapshots would change the approved public contract, resolve that decision first. Cover three or more events, identical timestamps, omitted values and the verified-sale match, while ensuring stage changes never create revenue.

### R008 P2 Calculate CRM totals over the full authorized scope

Separate full-scope aggregates from bounded detail results. Cover more than 500 deals, each outcome, multiple currencies and financial permissions. If adding pagination, use deterministic ordering and a complete cursor, update OpenAPI and docs, and prove that every detail row is reachable without duplication or a tenant leak. Do not label a page subtotal as the full total.

### R009 P2 Isolate malformed WhatsApp messages within a notification

Validate `referral.source_type` before set membership and bound timestamp conversion, including the exceptions supported platforms raise. A malformed item must not discard a valid sibling or cause endless retries of an otherwise handled signed batch. Keep the approved acknowledgement and diagnostic/minimization contracts consistent. Test malformed items first and last, multiple valid siblings, duplicates, unsupported shapes, extreme dates and unsigned requests. Never catch every exception and report success for database/storage failures.

### R010 P2 Preserve every advertising currency group across pages

Use the full grouping key, including currency, for sorting and pagination. Cover same-object multiple currencies, limit 1, all grouping levels, missing IDs, empty/final pages and stable traversal. Keep totals and financial authorization correct. The current schema deliberately preserves currencies on historical facts; refusing existing supported facts is not a valid pagination fix.

### R011 P2 Keep Instagram's historical day cursor stable

Use an absolute day or stable original range so a resumed account read cannot skip a day when the rolling history boundary moves at UTC midnight. Cover the demonstrated boundary, multiple midnights, restart/resume, exhausted windows and truthful coverage watermarks. Check the already corrected YouTube approach for reusable reasoning, while preserving Instagram's actual API contract. Do not make a live Instagram call or change the separate token/access follow-ups.

## Decisions and repository follow-ups

- Ordinary fixes that restore an approved contract are authorized. Do not create approval gates for routine refactoring or verification. For a new schema, security policy or major dependency, prepare a concrete minimal proposal and cite the applicable existing gate. R001 and R004 especially require an explicit trust model; continue other work while any required decision is pending.
- Do not edit merged migrations 0001-0019 to repair an upgraded database. For unmerged 0020-0025 or a new corrective migration, document the selected approach, obtain any required schema decision, and test empty and populated upgrade paths and restricted grants on disposable PostgreSQL. No native rollout.
- **A1 documentation:** reconcile README/backend README, migration head and actual API operation count, Spec 015 acceptance claims and provider selections, and the review-next/index status. Preserve historical evidence as historical. Do not describe open findings as resolved.
- **A2 CI:** record the lack of repository CI and prepare a minimal automated check path for the existing pinned Python/PostgreSQL/Node/browser stack. Use it when permitted within current repository authority; do not introduce a paid service, new major dependency or deploy workflow by inference. If activation requires an unapproved decision or unavailable permission, retain it as an explicit follow-up and report actual local checks. Never invent a green GitHub status.
- **A3 scale:** preserve the ledger-read scaling observation. Use bounded measurements if the correction affects ledger work; do not turn this task into implementation of 007-B or invent a production load/SLO. Document the remaining constraint and the required next decision.
- Specs 012/013 remain deferred. Spec 006 implementation, 007-B/C, production attribution, React, billing, dashboards, live providers and deployment are not implicit bug fixes. Keep those limitations visible.

## Final verification and a second review pass

After the individual corrections:

1. Run Ruff check and format check, `pip check`, the full backend unit and integration suites, the OpenAPI contract check, JavaScript unit tests, and Chromium/Firefox tests. Enable the three backend browser journeys too. Use the approved Python version and PostgreSQL 18, synthetic credentials and local/disposable services. Inspect the repository's test instructions; do not copy the owner's production environment into a test run.
2. Run all thirteen review regressions together at the corrected head. Add adjacent tests described above where needed. Record counts, skips, commands, versions and the tested commit. Historical 1,354 passes are a baseline, not a fixed target; test coverage must grow with these regressions. A skipped required check is not a pass.
3. Test any migration changes on both a fresh database and representative populated predecessor state. Exercise runtime/lifecycle permissions and refusal of unsafe downgrade where applicable.
4. In a separate review pass after implementation, re-read R001 through R011 in order against the complete final diff and code, not from memory or from checkmarks. Recheck each failure mechanism and its positive counterpart. Inspect cross-feature effects: erasure/consent/bookings, payments/CRM/ledger/conversion eligibility, and provider cursors/coverage. Do not call this independent external review unless another reviewer actually performed it; no sub-agent is required by this handoff.
5. Fill the tracker for every ID with baseline failure, fix commit, passing regression, adjacent cases and final review verdict. Write the detailed correction evidence in `review-corrections-evidence.md` and link it from the existing `evidence.md`. A passing test without explanation of why the original defect is no longer possible is insufficient.
6. Any new issue or change discovered during the second pass returns the affected finding to open. Make the fix, rerun relevant checks and update evidence. Run the final aggregate gates after the final implementation changes, rather than quoting results from an earlier code tree.
7. Check `git diff --check`, file targets, generated contracts, intended file list and secret handling. Remove one-time scripts, exports and private test containers while preserving reusable tests and owner assets.

## Publication and conditional merge

Commit independently reviewable corrections on the existing specification branch and push under D-051/D-069; do not force-push. Update PR 13's title/body for the final scope, with a concise problem/result description and a complete R001-R011 evidence table, including the two predecessor fixes. Keep unrelated decisions and follow-ups separate from verified closure. Do not create another PR.

Before merge, all of these must be true:

- Every R001-R011 row is `CLOSED_VERIFIED`, with evidence from the final implementation tree. None is deferred, hidden by a feature gate, awaiting a decision, or merely marked fixed by inspection.
- All required local suites and the final second review passed. No new unresolved correctness, privacy, financial or isolation finding remains. A1 documentation is reconciled; A2/A3 and unchanged product/provider follow-ups are accurately disclosed, not presented as completed features.
- Every necessary new decision is recorded, and all GitHub-required checks/reviews for the actual PR head are satisfied. Do not use an administrator bypass or remove a required check. Lack of configured CI does not waive the local checks.
- Fetch/check the actual PR and base immediately before merge. The remote head must match the reviewed correction head, with only separately verified documentation-only evidence commits after the last tested code tree. Review later changes; if the base changed materially, verify the combined result. Resolve conflicts without discarding other work.

Only then execute the owner's requested final merge of PR 13 using the repository's allowed merge method and an expected-head check where supported. Do not merge a different head, an unresolved PR, or enable automatic merge on pending/unreviewed changes. Verify that GitHub reports the PR merged and that the resulting main contains the corrected tree. Do not deploy, migrate the native database, delete another worktree or start the next specification as part of that merge.

If a condition is not satisfied, keep PR 13 open, finish unaffected authorized work, and state exactly what remains. Do not claim the requested merge happened until observed. The Arabic final response must contain the per-finding outcome, final test counts, any remaining explicit follow-ups, the PR link, and the corrected and merge SHAs where applicable.
