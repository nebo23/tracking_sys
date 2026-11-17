# Specification 004: independent pre-merge review

Reviewed: 2026-11-10. Recommendation: **request changes before merge**.

PR: https://github.com/nebo23/tracking_sys/pull/3

Reviewed head: `b90fa530a60425d39e3fe57659ceb7207896d55a` on `codex/spec-004-event-collection`.
Base: `bab3a3309bb4f4b8ab171036ef87434a8cf16b45` on `main`.
Scope: five commits, 49 changed files. D-027 decisions D1-D11 and D-028 publication approval were considered. No merge, deployment, native migration, implementation edit, or GitHub review submission was performed.

## R004-01 — P1: public consent cannot deliver its token to a customer page

Location: `backend/app/api/collection.py:227-245`; global CORS configuration in `backend/app/main.py:90-97`.

The public consent endpoint creates a subject and returns its only raw `subject_token`. However, its source-specific Origin allowlist does not grant browser access to the response. Global CORS admits only configured platform origins. A registered customer origin outside that list can submit a simple `text/plain` POST, but JavaScript cannot read the returned token; using `no-cors` also produces an opaque response. Subsequent collection requires that token. JSON requests additionally fail preflight.

Reproduced with the existing integration fixture's registered `https://shop.example.test` source:

- POST `/collect/v1/{public_key}/consent`, `Content-Type: text/plain`, body granting analytics: HTTP 200 with a token in the server response, but **no `Access-Control-Allow-Origin`**.
- OPTIONS with that Origin, POST method and `content-type` requested header: **HTTP 400**.

Required correction: provide a readable, narrowly scoped public consent response for the registered source origin, without expanding credentialed platform CORS to arbitrary customer sites. Define and test the supported content types and preflight behavior. Update design sections 2, 6 and 7: `application/json` is not a CORS-safelisted content type, and token issuance is not a write-only response.

Regression: an allowed customer origin can obtain the returned token and submit a subsequent event; an unrelated origin cannot. Test actual browser behavior as well as headers, and preserve platform cookie/CSRF isolation.

## R004-02 — P2: lifecycle can remove consent used by an in-flight event

Location: `backend/app/services/lifecycle.py:131-140`, `171-175`.

D-027/D10 requires lifecycle expiry to take the same per-client privacy lock as admission, consent and erasure. The new cleanup predicates use an inactivity/no-event snapshot, but deletion takes neither that client lock nor a subject lock before deleting consent. The lifecycle job's namespace-3003 lock only serializes other lifecycle jobs.

Reproduction uses the supported `subject_retention_days=30` configuration (allowed range 0-395), an otherwise valid grant, a subject last active 31 days ago, and no previously stored event:

1. Start normal `admit()` under the runtime role. It holds its real client/subject locks, accepts the event, inserts it and refreshes activity, but has not committed.
2. In an independent lifecycle-role transaction, run the actual consent-record deletion batch.
3. Cleanup sees the old activity/no-event snapshot and deletes **two consent records** without waiting for admission.
4. Commit admission: **one event remains, zero consent records remain**. Retrying that event returns **422 `consent_unknown`**.

The event's stored consent-basis IDs have lost their evidence, and a valid returning subject loses collection eligibility. This exact reproduction uses shortened retention; it does not claim a valid 365-day grant survives 395 days of inactivity under the default values.

Required correction: serialize lifecycle eligibility checks and deletion with the approved client privacy lock, re-evaluate after acquiring it, and preserve bounded batches/timeouts and role privileges. The repeated DELETE predicate alone cannot protect rows whose eligibility depends on a different table's uncommitted update.

Regression: both transaction orders for returning-subject admission versus consent/subject cleanup, including shortened supported retention and normal defaults. Consent referenced by a committed retained event must remain available.

## R004-03 — P2: repeated webhook rotation silently shortens the overlap

Location: `backend/app/services/collection.py:625-633`; rotation implementation at `756-776`.

`rotate_secret()` gives each outgoing current secret a 24-hour expiry, and permits further rotations. `live_webhook_secrets()` nevertheless reads only the three newest versions. After three rotations, the original secret is still inside its recorded overlap but is excluded from verification.

Reproduced by creating a webhook source, performing three successful rotations (HTTP 201 each), then immediately sending a correctly signed request using its original secret: **HTTP 401 `signature_invalid`**, instead of acceptance. No clock advance or expired timestamp was involved.

Required correction: honor all unexpired versions, or explicitly enforce a reviewed rotation bound before issuing another version. Do not silently revoke a still-valid version through a query limit. Keep signature verification bounded and document the chosen behavior.

Regression: several rotations within one overlap window; every promised unexpired key verifies, and each key stops verifying at its own expiry. Preserve source/client isolation.

## Additional privacy observation: allowlisted query values bypass the card check

Location: `backend/app/collection/contract.py:217-236`.

The implementation checks decoded URL paths for email-like values and card numbers, then filters query parameters by name without checking retained values. A `page_view` with synthetic URL `https://shop.example.test/?utm_campaign=4111111111111111` returned **201**, and that Luhn-valid test number remained in `collected_events.payload`.

The 004 field matrix explicitly describes the card check for paths only, so this is also a design-policy gap rather than an unambiguous failure to implement that matrix. It conflicts with the broader intent of the 003 prohibited PAN class. Resolve this before real customer intake: apply the relevant sensitive-value protection to retained query values, or record a precise reviewed boundary. A parameter-name allowlist does not establish that its value is non-sensitive. This observation is separate from the unmerged 003 long-digit-run performance follow-up.

## Verification

The exact published commit was exported with `git archive` into an isolated temporary directory without `.env`. Tests used the existing project `.venv`, synthetic secrets, local mail capture, and a dedicated Docker Compose project `tracking-review004`. PostgreSQL was disposable `tracking_foundation_test` on `127.0.0.1:55433`, with separate runtime/migration/lifecycle roles. Native `tracking_sys` was not accessed.

- Initial unchanged-suite run: **454 passed, 1 failed in 102.66 seconds**. The sole failure assumed tombstone key ID `tomb1`, while the reviewer supplied the valid synthetic ID `review`; this was not an application erasure failure.
- Full unchanged-suite rerun with the expected test key identifier: **455 passed in 99.01 seconds**, no skips.
- `ruff check app migrations tests`: **passed**.
- `ruff format --check app migrations tests`: **82 files already formatted**.
- `pip check`: **no broken requirements**.
- `git diff --check bab3a33..b90fa53`: **passed**.
- Four additional diagnostic assertions: **4 failed in 3.74 seconds**, demonstrating the three findings and the separate privacy observation above. An initial diagnostic harness expected 200 instead of the rotation endpoint's documented 201; that harness assertion was corrected before the recorded reproduction.
- GitHub reports PR 3 open and mergeable at the reviewed head. The connector returned no commit statuses or PR-triggered workflow runs; this is not evidence of a passing remote CI run.

The diagnostic code was run only in the temporary archive, and the published worktree remained clean. Existing root-worktree changes were preserved. This review did not run a real browser, a load test, a production provider, or an API-container smoke test; the CORS finding is based on observed HTTP headers/preflight behavior and the browser access requirement. Passing the existing suite does not cover the newly reproduced cases.

## Follow-up for the implementing model

Fix R004-01, R004-02 and R004-03 on the same specification branch, add the regression cases above, and reconcile the public-transport documentation. Resolve the query-value privacy observation explicitly. Re-run the unchanged suite plus the new regressions in the isolated environment with a disposable database, then inspect the final diff and update verification evidence. Keep unrelated local changes and predecessor follow-ups separate. Merge and native rollout remain owner decisions.
