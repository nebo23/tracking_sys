# Specification 003: review corrections R003-01 to R003-03

Date: 2026-11-09. Authority: D-026 and its [handoff](review-corrections-prompt.md). Branch: `codex/spec-003-privacy-data-policy`, [PR 2](https://github.com/nebo23/tracking_sys/pull/2). Corrected code: commit `4c3b046b4a5a6a1a5577eab5c8d9c3b44844d145` (tree `f59d1b66432af16351201672fbb5518dde01f2cb`, backend tree `54d013c819d56aab35fa808e27ec62e1cd41e5bf`). Status: implemented and verified on the disposable database, then published to PR 2 under D-026. Merge, deployment, native rollout, and the legacy queued-mail policy remain owner decisions.

The findings come from the local review report `pull-request-review-2026-11-04.md`, which reviewed head `0796351` against base `98747a2` and requested changes. That report remains an uncommitted historical document; its failing diagnostics describe the code before these corrections. The backend at the reviewed head is identical to the backend at the handoff commit `b77964b` (tree `b03ccb3722db16f1b7fa82239243d11fdc480c22`).

## Summary

| Finding | Change | Regression tests | Reviewed code | Corrected code |
|---|---|---|---|---|
| R003-01 (P1), closure and Google-link lock cycle | Closure no longer updates OAuth transactions | 2 PostgreSQL tests in `test_account_closure.py` | Callback HTTP 503 after a server `deadlock detected` (SQLSTATE 40P01) | Closure succeeds; callback rejected with `google_sign_in_failed`; no identity; runner removes the rows |
| R003-02 (P2), whitespace card bypass | One separator definition: any whitespace and hyphen or dash characters | 26 unit tests in `test_privacy_collection.py` | 14 of 17 card variants retained | All variants dropped; 9 ordinary texts kept |
| R003-03 (P2), incomplete restore journal | Trusted journal head required; watermark and completeness checks; explicit restore states | 25 unit tests in `test_privacy_secrets_restore.py` | Truncated and empty journals produced empty plans | Each incomplete or invalid input is rejected |

## R003-01: account closure and an in-flight Google link

### Lock paths examined
- **Closure** (`POST /auth/close-account`): `authenticate` locks the user (`FOR NO KEY UPDATE`) and then the session (`FOR UPDATE`). `close_account` locks the agencies of active memberships in ID order, then updates the user, the user's sessions, tokens, challenges, and memberships, and inserts audit and security events.
- **Google link callback**: locks its OAuth transaction (`FOR UPDATE`) and consumes it. After the provider exchange, `authenticate` locks the user and then the session; the account policy locks the user again and inserts the identity and event.
- **Google login callback**: locks its transaction, which names no user, then locks the user of an existing identity.
- **Link start**: `authenticate` (user, then session), then inserts a transaction row.
- **Lifecycle runner**: deletes with a 100 ms lock timeout, so it yields to API requests.

The only user/session-to-OAuth edge was closure's `UPDATE oauth_transactions` of the user's unconsumed rows. The callback's opposite edge is deliberate: it must hold its consumed transaction so the state cannot be replayed, and it must authenticate after the provider exchange so that a revocation during the exchange is observed (correction R-01 of specification 002).

### Chosen strategy
Closure no longer updates OAuth transactions. No remaining closure statement touches a row that the callback holds before it waits for the user lock, so the cycle cannot form. D-024 decision 3, item 3, lists the synchronous closure effects as sessions, tokens, and challenges; item 4 assigns OAuth transactions to the lifecycle runner, which already deletes a closed account's rows without a period. No retry, exception masking, schema, or privilege change was added.

The alternative of consistent ordering was rejected. Locking the user and session before the transaction row would either hold the user lock throughout the provider exchange, which blocks logout-all and password reset for that time and removes R-01's observation of a concurrent revocation, or move the single-use consumption after the exchange. Both weaken merged behavior.

### Why a pending link still fails closed
- **Callback waiting while closure commits:** after the lock wait, PostgreSQL re-evaluates the callback's `status = 'active'` predicate against the committed row. The disabled user no longer matches, so authentication fails, the savepoint rolls back, and the callback redirects with `google_sign_in_failed`. Its consumed transaction still commits and cannot be replayed.
- **Callback after closure:** the binding requires the initiating session, which closure revoked, and the account policy refuses a disabled user. A retained cookie does not help.
- **Callback holding the user lock first:** the link completes before closure; closure then waits for the user lock, closes the account, and the runner deletes the identity.
- **Login transactions** name no user. A Google sign-in for a closed account's identity is refused until the runner deletes the identity, as before.

Preserved: originating-session binding, revocation and reset checks, expiry checks after lock waits, browser binding, state, nonce, and PKCE validation, last-active-Owner protection, and the prohibition on attaching an identity to a closed account.

Behavior change: a callback for a closed account's pending link now performs the provider code exchange before it is rejected; previously it was rejected at the consumed-transaction check. A link already behaves this way after logout-all or a reset, and the exchanged tokens are discarded as before. A closed account's pending rows stay unconsumed until the callback consumes them or the runner deletes them; they authorize nothing.

### Regression tests
In `backend/tests/integration/test_account_closure.py`, using real services, the HTTP callback, and the controlled Google substitute:
- `test_closure_completes_while_a_google_link_callback_waits`: a synthetic password user starts a link. The closure transaction authenticates and holds the user and session locks. The callback is started, and the test waits, for at most 5 seconds, until `pg_stat_activity` and `pg_blocking_pids` show the callback blocked by the closure backend on the `users` row lock. A `FOR UPDATE SKIP LOCKED` probe confirms that the callback holds its OAuth transaction row. Closure then runs and commits. The test asserts that closure succeeds; the callback returns 303 with `google_sign_in_failed` and no session cookie; no identity or `google_identity_linked` event exists; the account is disabled with `closed_at`; the transaction row is consumed; and the old session cookie gets 401. The lifecycle runner then completes, deletes the OAuth transaction and password credential, and leaves no OAuth transaction, session, or credential of that user.
- `test_pending_google_link_cannot_complete_after_closure`: closure over HTTP leaves the pending row unconsumed; the callback with the retained cookie is rejected without attaching an identity; the runner deletes the row.

### Results
- **Reviewed code** with the new tests: both fail. The concurrent test received HTTP 503, and the disposable server logged one `deadlock detected` error (SQLSTATE 40P01). The sequential test failed because the reviewed closure had consumed the pending row.
- **Corrected code:** both pass in every full-suite run, in 29 consecutive runs of the committed tree under normal operation, and in 10 consecutive runs of the first candidate. That candidate differs from the committed tree only in how four regular-expression characters and ten test-string characters are written (literal Unicode instead of escapes, with the same values). On it, the Google, authentication-review (R-01 to R-03), closure (including last-Owner), and lock-order files passed 46 of 46 in each of three consecutive runs; their code is identical in the committed tree.
- **One failed run:** the run started at the end of the second full-suite run failed once, after 133.95 s instead of about 2 s. The disposable server's log has no entries from 14:36 UTC on 2026-11-08 to 09:07 UTC on 2026-11-09 while the container stayed up, which indicates a host suspension during that run. Its failure output was not captured. The server logged no deadlock and no lock timeout for it; the only lock timeout in that log is the lifecycle runner's intentional 100 ms timeout from an existing lifecycle test.

## R003-02: card numbers separated by common whitespace

### Change
In `backend/app/privacy/collection.py`, `_SEPARATOR` matches any whitespace (Python `\s`, including tabs, line breaks, and the no-break U+00A0, narrow no-break U+202F, and figure U+2007 spaces) and the hyphen-minus, U+2010 to U+2015, the minus sign U+2212, and the fullwidth hyphen-minus U+FF0D. `_DIGIT_RUN` matches digit groups joined by runs of those separators, and the groups of a run are read with `\d+`, so locating and splitting share one definition. Detection is unchanged otherwise: every span of consecutive groups with 13 to 19 digits is checked with Luhn, and a span stops growing past 19 digits. Digits and separators are disjoint and each separator run must be followed by digits, so a match is unambiguous and linear. Submitted values are never rewritten; an unsafe field is dropped and counted as `payment_card_number`.

### Regression tests
Through `sanitize_submission` with `FormField("message")` and the mapping `{"message": "lead.contact"}`, using the published test number 4111 1111 1111 1111:
- 17 dropped cases: single space, double spaces, tabs, no-break spaces, narrow no-break spaces, figure spaces, mixed whitespace runs, line breaks, hyphens, spaced hyphens, en dashes, non-breaking hyphens, contiguous digits, a number inside a sentence, and numbers followed by a security code or an expiry date or preceded by other digit groups.
- 9 kept cases: Luhn-invalid numbers with double spaces, tabs, or no-break spaces; a 12-digit order number; a telephone number with mixed whitespace; times and dates; a quantity and price; 20 contiguous digits; and text without digits.

The earlier direct-detection cases, including the adjacent security-code and expiry regressions, are unchanged.

### Results
Reviewed code: 14 of the 17 card cases failed because the value was retained; the single-space, hyphen, and contiguous formats and all 9 kept cases passed. Corrected code: all pass.

### Limits
- Line breaks count as separators, so detection errs toward not collecting. A free-text field containing several numbers separated only by whitespace, whose consecutive groups form a Luhn-valid span of 13 to 19 digits, is dropped. This extends the existing Luhn false-positive limit.
- Groups separated by other punctuation, such as dots or slashes, by zero-width characters, or written as words are not detected. Deliberate obfuscation is outside a collection-minimization safety net.
- This corrects the library contract only. Tracker (005) and ingestion (004) enforcement stay with the consuming specifications under D-025.

## R003-03: complete restore journal

### Contract
In `backend/app/privacy/restore.py`:
- `JournalHead(seq, chain)` is the trusted journal head: the sequence number and chain value of the last appended entry. Construction rejects a negative, boolean, or non-integer sequence, a chain that is not 64 lowercase hexadecimal characters, and any pairing other than sequence 0 with `GENESIS`. `EMPTY_HEAD` is the head of an empty journal.
- `to_reapply(key, entries, restored_max_seq, *, expected_head)` requires the head as a keyword-only argument without a default, so the earlier call form raises `TypeError`. It returns the entries after the watermark only after every check passes, in this order:

| Condition | Result |
|---|---|
| No `JournalHead` supplied | `JournalIncomplete("journal_head_required")` |
| Watermark negative, boolean, or not an integer | `ValueError("invalid_restored_watermark")` |
| Watermark above the head | `JournalIncomplete("journal_head_stale")` |
| Fewer entries than the watermark | `JournalIncomplete("journal_shorter_than_watermark")` |
| Gap, reordering, changed entry, or wrong key | `JournalTampered` (existing checks, from `GENESIS`) |
| Entries end before the head | `JournalIncomplete("journal_missing_suffix")` |
| Entries extend beyond the head | `JournalIncomplete("journal_head_stale")` |
| Final chain value differs from the head | `JournalTampered("journal_head_mismatch")` |

- `JournalIncomplete` subclasses `JournalTampered`, so a caller written to block on tampering also blocks on an incomplete journal. Every failure is a `ValueError`.
- `RestoreState` has four values: `NOT_RESTORED`, `RECONCILIATION_PENDING`, `JOURNAL_UNVERIFIED`, and `RECONCILED`. `readiness_failure(state, fingerprint_matches)` is ready only for `NOT_RESTORED` or `RECONCILED` with a fingerprint value that is exactly `True`. `JOURNAL_UNVERIFIED` returns `restore_journal_unverified`; anything else, including `None`, booleans, and strings, returns `restore_reconciliation_pending`. The previous `bool | None` input treated every value other than `False` as ready, including a `None` produced by a missing lookup, which conflated an incomplete restore with no restore.
- `reconcile` is unchanged: it is idempotent and returns counts only after every entry was handled; an exception from either callable propagates.

### Trust boundary and obligations of future callers
The head proves completeness only because it does not come from the entries being verified. The journal writer records `JournalHead(entry.seq, entry.chain)` with every append, in custody independent of both the database being restored and the journal entry storage. A recovery stops the writer, reads the head from that custody, and never computes it from the supplied entries. Trust assumptions: the HMAC key is secret and unchanged, the custody cannot be truncated or rolled back by the same failure as the journal, the head is written atomically with each append, and the writer stays stopped during reconciliation. Specification 020 must provide that custody, establish the head's freshness for each restore epoch, record the epoch's `RestoreState`, and keep readiness blocked while the journal is unverified; specification 019 must include an incomplete-journal recovery in its release evidence. Both spec.md files now state this. The library cannot detect a stale but authentic head that was rolled back together with the journal.

### Regression tests
Five truncation cases: the reviewed reproduction (entries 1 and 2 with watermark 3), an empty journal with a nonzero watermark, entries that reach or pass the watermark but miss the tail, and an empty supply for a nonempty journal; each also raises `JournalTampered`. Further tests cover forked and stale heads, a changed entry and a wrong key despite a correct head, missing completeness evidence (the old call form, `None`, a tuple, and a journal entry), six invalid watermarks, nine invalid heads, legitimate empty recovery with the trusted empty head, repeated idempotent recovery including a restored database that already holds every entry, an apply failure that returns no counts and keeps readiness blocked until a later run completes, and readiness for every state and for out-of-contract inputs. The R2, R4, and tampering tests were kept, with the head added where required.

### Results
Reviewed module, using the review's reproduction: entries 1 and 2 with watermark 3, entries 1 to 3 with watermark 3, and an empty journal with watermark 2 each returned an empty plan; watermark -1 returned all four entries; and `readiness_failure(0, True)` reported ready. Corrected module: these raise `journal_shorter_than_watermark`, `journal_missing_suffix`, `journal_shorter_than_watermark`, and `invalid_restored_watermark`, and readiness returns `restore_reconciliation_pending`. All restore tests pass.

### Limits
This is a library contract. No journal store, head custody, freshness check, restore epoch, readiness integration, or restore drill exists; these remain obligations of 019 and 020, and no end-to-end restore guarantee is claimed. Verification reads the whole chain from `GENESIS`, so its cost grows with the journal.

## Documentation follow-ups
1. **Legacy queued mail:** [data-lifecycle.md](../../docs/engineering/data-lifecycle.md#legacy-queued-mail-proposal-awaiting-owner-approval) now states that undelivered rows with both `delivered_at` and `expires_at` NULL are outside time-based cleanup and can keep their encrypted payloads indefinitely. It proposes a transition with two options, T1 (derive the expiry only from an exactly matching token digest) and T2 (explicit retirement), and recommends T1 with T2 for the rest. The policy and its rollout await owner approval. No expiry was guessed, no retention period or migration was added, no native row was changed, and the limitation is not fixed.
2. **Native and Docker rollout wording:** the PR description no longer says that existing Docker volumes must be recreated. The lifecycle guide states that adding the role in place before the reviewed migrations preserves the volume. Native tracking_sys was last verified at `0004_identity` on 2026-11-04; this task made no native connection and created no role, applied no migration, ran no lifecycle deletion, and used no real provider.
3. **Status:** README.md, specs/README.md, and this specification's spec.md, tasks.md, design.md, and evidence.md describe the PR 2 review state. The evidence file labels the 003-A1/003-A2 section as a historical record and annotates the closure behavior changed by R003-01. The authentication guide describes the new closure behavior. Owner acceptance, merge, production readiness, and downstream enforcement are not marked complete.

## Verification
Environment: the project `.venv` (Python 3.12.4, pytest 9.2.0, Ruff 0.17.3) with the locked requirements; no package was installed. The disposable database was the Compose project `tracking-spec003-r003` (pinned `postgres:18.6` image) with generated synthetic credentials, `tracking_foundation_test` on `127.0.0.1:55433`, and its own volume, recreated before each candidate run. Tests ran from `git archive` extracts of the tested trees, which contain no `.env`. The runner dropped every inherited `TRACKING_` variable and set the runtime, migrator, and lifecycle connections, synthetic hexadecimal secrets, local mail with a temporary directory, and disabled Google sign-in and Gmail explicitly. A preflight printed only non-secret settings and confirmed the target server, an empty schema, and the three roles. The integration guards in `backend/tests/integration/conftest.py` were unchanged.

| Check (run from `backend`) | Tested content | Result |
|---|---|---|
| `python -m pytest` on the three new test modules | Reviewed backend plus the new tests | Collection 14 failed, 40 passed; both R003-01 tests failed (503 with 40P01; consumed row) |
| R003-03 reproduction | Reviewed `restore.py` | Incomplete journals and watermark -1 accepted; readiness fail-open (above) |
| `python -m pytest -q` | Commit `4c3b046` | **380 passed** (193 unit/contract, 187 PostgreSQL) in 97.89 s; no failures, skips, or warnings |
| `python -m pytest -q` | Same tree as `4c3b046` before commit | 380 passed in 362.61 s; the host was suspended shortly afterwards |
| `python -m pytest -q` | First candidate, with literal Unicode characters instead of escapes in one regular expression and the test strings (same values) | 380 passed in 162.35 s |
| `python -m ruff check app migrations tests` | Commit `4c3b046` | All checks passed |
| `python -m ruff format --check app migrations tests` | Commit `4c3b046` | 72 files already formatted |
| `python -m pip check` | Project `.venv` | No broken requirements |
| Installed versions against `requirements.txt` and `requirements-dev.txt` | Project `.venv` | 74 applicable pins match; `httpx2-jsfetch` is limited to `sys_platform == 'emscripten'` and correctly absent |

The suite count grew from the historical 327 to 380: 51 unit tests (26 for R003-02, 25 for R003-03) and 2 PostgreSQL tests (R003-01).

Unchanged and verified by diff against the reviewed head: no migration (the head remains `0006_account_closure`), requirement, `pyproject.toml`, infrastructure, role, grant, configuration, or `contracts/openapi.json` change, and the OpenAPI equality test passes. The owner's unrelated working-tree edits, including `backend/app/api/schemas.py`, `backend/app/models/tenancy.py`, the D-021/Q-008 hunks in `AGENTS.md` and `docs/planning/decisions.md`, the 001/002 task files, and the untracked review documents, are excluded from these commits and were not tested.

## Not validated
- No live Google sign-in, Gmail delivery, native database, or production configuration was used.
- No browser test of closure during a real Google link; the provider was the controlled substitute.
- The lock analysis covers the current code paths. Future code that updates OAuth transactions while holding a user lock would reintroduce the cycle, and the regression test covers only closure.
- GitHub reports no configured checks for this repository; no CI result exists for these commits.
