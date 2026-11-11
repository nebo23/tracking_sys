# Specification 005 evidence

Date: 2026-11-10. Authority: D-033 (recommended D1-D10 and design revision 1 prepared at `a909990`). Branch: `codex/spec-005-links-tracker`, local commits only; nothing was pushed, published, merged, deployed or migrated natively.

**Update 2026-11-11 (D-035):** the independent review of PR 4 at `14e8288` raised eleven findings (R005-01 to R005-11). They are corrected and verified in [Review corrections](#review-corrections-2026-11-11) below; the sections before it record the original 2026-11-10 implementation and its results. **Update 2026-11-11 (D-036):** the independent review of those corrections at `9c49d89` raised seven further findings (R005-12 to R005-18), corrected and verified in [Second review corrections](#second-review-corrections-2026-11-11). **Update 2026-11-11 (D-037):** the independent review of tracker 0.5.2 at `f90b527` raised four further findings (R005-19 to R005-22), corrected and verified in [Third review corrections](#third-review-corrections-2026-11-11). **Update 2026-11-11 (D-038):** the final review of PR 4 at `4ebe5ab` raised one further finding (R005-23), corrected and verified in [Final review correction](#final-review-correction-2026-11-11).

## Scope delivered

| Slice | Commit | Delivered |
|---|---|---|
| Approval record | `069ff5c` | D-033 in the decision register and AGENTS.md; specification status. |
| 005-B | `5d2c13b`, fix `ed1f245` | Migration `0008_links_tracker`: six client-scoped tables, nullable same-client `collected_events.link_id`, column-limited runtime grants without deletes, extended audit codes, guarded downgrade. Owner/Admin administration with audit; scoped reader lists; exact destination origins with static query names; immutable issued targets and UTM snapshots; UTM precedence; `GET|HEAD /r/{slug}` with host-scoped resolution, 302/no-store/no-referrer, no telemetry or cookies; host-namespace lock against managed-host loops. |
| 005-C | `cb580fd` | Optional envelope `link_id` validated against the authenticated or source-derived client; pre-005 fingerprints preserved; `POST /collect/v1/{public_key}/consent-state` (non-mutating, own rate-limit bucket); public CORS for the new route and `Retry-After` exposure to accepted origins only. |
| 005-D | `2418720` | `packages/tracker-js`: native ES module, consent state machine, sessionStorage policy, GPC, form-value exclusion, browser-side minimization, bounded queue and retries; Node and Playwright tests; installation example. |
| 005-E | `c9bcb2c` | Domain challenge, verification phases and stale-result protection; `DomainVerifier` with live dnspython and pinned-TLS adapters and injected test adapters; dnspython as a direct requirement; real-browser end-to-end journey. |
| Regressions | `0c846a9` | Remaining verification-matrix rows (database-level scoped references, concurrent hostname claims, populated downgrade refusal, adapter selection, opener windows). |

The documentation commit that adds this file follows `ed1f245`; it changes no code or test.

### Defect found by the final verification run

The first final run (on `0c846a9`) failed one case: issuing a link intermittently raised `invalid_destination`. `compose_target` applied the email/card-number pattern check to the whole target, including the random `ts_link` UUID, whose hyphen-joined digit groups can form a Luhn-valid number (observed: `c2142041-6274-442a-...`). Measured over 200,000 random UUIDs, 541 (0.27%) trigger the card rule. Commit `ed1f245` restricts the check to the configured destination, static and UTM values (the generated reference is not customer data) and adds a regression with the observed UUID. The complete verification below was then repeated from the start. The earlier unexplained one-off fixture error during 005-C development had the same cause.

## Verified tree and environment

- Code and tests: `ed1f245` (all checks below). Baseline before any change: the unmodified tree passed **481**.
- Worktree `.worktrees/spec-005-links-tracker` (no `.env`); project `.venv`, Python 3.12.4; FastAPI 0.162.0, SQLAlchemy 2.1.6, dnspython 2.9.1, cryptography 50.0.2.
- Disposable PostgreSQL: Compose project `tracking-spec005-20261110`, only the `database` service (`postgres:18.6-bookworm`, PostgreSQL 18.6), database `tracking_foundation_test` on `127.0.0.1:55433` with separate `tracking_app`, `tracking_migrator` and `tracking_lifecycle` roles and synthetic credentials kept outside the repository. Inherited `TRACKING_`, `PG` and `PYTHON` variables were removed. Native `tracking_sys` was not accessed.
- Node.js 24.17.0, npm 11.13.0; Playwright 1.64.1 with Chromium 156.0.8078.4 and Firefox 157.0 installed in `packages/tracker-js/node_modules` (`PLAYWRIGHT_BROWSERS_PATH=0`); no global browser cache was created.

## Dependencies

| Package | Version | Selection | Integrity |
|---|---|---|---|
| dnspython | 2.9.1 | Already locked through email-validator; promoted to a direct requirement unchanged (2.9.2 was a week old). Supports Python 3.11+. | Existing SHA-256 hashes in `requirements.txt` and `requirements-dev.txt`; only provenance comments changed. |
| playwright (dev only) | 1.64.1 | Released 2026-10-14; 1.65.0 (2026-11-05) was too recent. Requires Node 20+. Single dependency `playwright-core` 1.64.1. | `package-lock.json` with npm `sha512` integrity for both packages. |

`pip check`: no broken requirements. No package was installed globally.

## Commands and results (final run on `ed1f245`)

| Check | Result |
|---|---|
| Backend suite with PostgreSQL and browsers: `TRACKING_RUN_DB_TESTS=1 TRACKING_RUN_BROWSER_TESTS=1 python -m pytest -q -rs` (from `backend/`) | **611 passed** in 171.78 s; no failures, errors or skips. 334 unit/contract and 277 PostgreSQL cases; 130 are new in 005 (27 link policy, 3 envelope compatibility, 37 parity, 23 domain verification, 14 link integration, 6 event-link integration, 17 domain integration, 3 browser journey). |
| `ruff check .` and `ruff format --check .` | All checks passed; 100 files already formatted. |
| `python -m pip check` | No broken requirements found. |
| Migration, metadata, grant and data-policy checks (inside the suite) | Base-to-head-to-base cycle and re-upgrade; model/migration metadata equality; 35-table data-policy registry against metadata and the migrated database; immutable provenance and no-delete grants; populated 0008 downgrade refused. |
| OpenAPI snapshot (`tests/test_contract.py`) | Matches: 60 paths, 75 operations (53 before 005). |
| Node unit tests: `npm test` | **24 passed** (consent state machine, storage, transport, parity fixtures). |
| Real browsers: `npm run test:browser` | **20 passed** (10 cases in Chromium and in Firefox). |
| `git diff --check` and secret, credential and control-character scans of the 005 changes | Clean; see the final review below. |

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| 1. A test link reaches its destination and preserves content/campaign provenance without personal information in the URL | Met (synthetic) | L2 tests; browser journey follows a verified branded link through a real 302 to the exact issued target with `utm_*`, `utm_id` and `ts_link`; envelopes carry `link_id`, never a visitor identifier; prohibited patterns are refused in destinations. |
| 2. Disallowed destinations, unsafe protocols and redirect loops are rejected; management requires client permission | Met | L1, L3, L4 integration tests; database-level scoped foreign keys; concurrent origin/domain claims never coexist. |
| 3. Analytics failure does not break redirects; bots and prefetch are not counted as qualified clicks | Met | Redirects succeed with collection functions failing and a read-only database session, for bot, headless and prefetch requests, with no rows, cookies or counters written; storage outage returns 503 without a fallback. |
| 4. Custom domains require ownership verification; TLS and slug conflicts are verified | Met for implemented logic with synthetic DNS/TLS; **live operation not performed** | Domain tests: TXT ownership, CNAME routing, address policy, pinned TLS with SNI, certificate expiry, stale results, rate limits; slug and hostname uniqueness under concurrency. |
| 003 C4 (no identifier before consent) | Met in real browsers | Pre-consent tests show no storage, cookie, random, value or network access and no backlog. |
| 003 M4 (prohibited form values absent from requests) | Met in real browsers | Password, hidden, card, card security code, one-time-code, email, textarea and unconfigured values are never read and are absent from every request byte. |

## Verification matrix

| Row | Evidence (tests) | Result |
|---|---|---|
| L1 | `test_links.py::test_owner_and_admin_manage_readers_list_and_others_are_denied` | Passed |
| L2 | `test_redirect_issues_the_immutable_target_with_utm_precedence`, `test_link_provenance_columns_are_immutable_for_the_runtime`, link-policy UTM cases | Passed |
| L3 | `test_unsafe_destinations_and_unregistered_origins_are_rejected`, `test_concurrent_duplicate_slugs_have_one_winner`, link-policy destination cases | Passed |
| L4 | `test_managed_hosts_cannot_become_destinations_and_hosts_resolve_exactly`, `test_later_platform_configuration_cannot_create_a_loop`, `test_concurrent_origin_and_domain_claims_never_create_a_loop`, `test_concurrent_duplicate_hostname_claims_have_one_winner` | Passed |
| L5 | `test_redirect_is_independent_of_telemetry_and_writes_nothing`, `test_missing_link_storage_returns_503_without_a_fallback`, `test_expired_verification_and_disabled_or_expired_links_fail_closed` | Passed |
| P1 | `test_event_link_contract.py` (golden pre-005 fingerprints), `test_old_clients_keep_deduplicating_and_link_references_are_content`, `test_public_link_claims_are_limited_trust_and_upgraded_by_trusted_copies`, `test_event_link_references_are_scoped_by_the_database` | Passed |
| P2 | `test_erasure_and_lifecycle_remove_link_references_but_keep_configuration` (including log scan for tokens and targets) | Passed |
| C1 | Browser "before consent nothing is stored, read, generated or sent"; Node pre-consent test | Passed (Chromium, Firefox) |
| C2 | Browser "reload resumes from the server state without a new grant or a renewed expiry"; Node resume tests | Passed |
| C3 | Browser withdrawal/stale-read/back-forward-cache test; Node pending-grant, erasure and stale-state tests | Passed |
| C4 | Browser storage-fallback and opener-window tests; Node local-expiry and storage tests | Passed. Observed: both engines copy `sessionStorage` into a window opened without `noopener` and not with it; documented, not hidden. |
| C5 | `test_consent_state_reads_current_consent_without_mutating_anything`, `test_consent_state_enforces_origin_body_and_its_own_rate_limit`; journey reads `Retry-After` from the registered origin and nothing from an unregistered one | Passed |
| C6 | Browser and Node GPC tests | Passed |
| M1 | Browser "after a grant only mapped, permitted values leave the browser" and "prohibited controls are excluded before their values are read"; journey request-byte scan | Passed |
| M2 | 37 Python parity cases, Node parity tests, in-browser parity in both engines, and stored-equals-sent comparison against the real API | Passed |
| T1 | Browser hang/503/429/offline navigation test; Node retry, TTL, queue and size tests | Passed |
| D1 | `test_failed_checks_never_activate_a_domain`, `test_reissued_and_expired_challenges_do_not_verify`, verifier unit cases | Passed (synthetic DNS) |
| D2 | Pinned-TLS probe tests (wrong host, expired, untrusted, near expiry, SNI, no application data), address-policy and rebinding cases, loopback DNS adapter tests | Passed (loopback TLS, test-only CA) |
| D3 | `test_results_completing_after_concurrent_changes_are_stale`, `test_a_revoked_actor_cannot_complete_a_check`, `test_a_conflicting_origin_blocks_activation`, `test_redirects_never_probe_dns_or_tls` | Passed |
| DB1 | `test_postgres.py`, `test_migration_matches_model_metadata`, `test_data_policy_schema.py`, `test_downgrade_refuses_populated_link_state`, scoped-foreign-key tests | Passed |
| E2E | `test_tracker_journey.py` in Chromium and Firefox: branded link, destination, consent, page/form/link events, stored rows, withdrawal and suppressed event, erasure and rejected replay | Passed |

## Synthetic verification versus live operation

Verified here, synthetically: all link, redirect, consent-state, tracker and verification logic; real Chromium and Firefox behavior against loopback servers; the real API and real PostgreSQL (disposable); dnspython against a loopback UDP responder; TLS handshakes against loopback servers presenting certificates from a per-session test authority.

**Not performed, and not claimed:** live DNS resolution of a real customer hostname, a real CNAME to an operator service target, certificate issuance or validation by a public authority, reverse-proxy routing, hosting, deployment, installation on a customer website, native `tracking_sys` migration, or real customer intake. Live custom-domain readiness, production readiness and comprehensive personal-data detection are not established. A live smoke test needs separate owner authorization, a hostname under the owner's control, the configured service target and an operator certificate.

## Limitations and open items

- Pattern checks recognize email-like values and card numbers only. Because they err toward refusal, a destination path or a page path containing a random UUID can occasionally be refused as a card-like value (the inherited 004 page-URL rule behaves the same way); the generated `ts_link` is no longer affected.
- JavaScript recognizes Unicode 17 digits and Python Unicode 15 digits, so the browser can drop a value the server would keep; never the reverse. Bracketed IPv6 hosts are validated more loosely in the browser than by Python; the server applies its own rule again.
- A remote withdrawal reaches an open tab at its next state read (at most 60 seconds while collecting); tabs do not share consent; delivery is not guaranteed after a page closes.
- Development limits and retention values remain provisional (Q-004, Q-012). Q-001 to Q-003 stay open for real intake.
- Predecessor items P1-P4 were not included.


## Review corrections (2026-11-11)

Authority: D-035. Review: independent review of PR 4 on 2026-11-11 at reviewed head `14e8288` (request changes; eleven findings). Corrections on `codex/spec-005-links-tracker`:

| Commit | Content |
|---|---|
| `371c9f3` | D-035 record |
| `834f871` | R005-10, R005-11 (domain verification) |
| `85774db` | Consent writes return `expires_at` and `server_time` (additive; supports R005-03) |
| `f6d9e1e` | R005-01 to R005-08 (tracker 0.5.1) |
| `433fae7` | R005-09 (installation example) and tracker README |

The documentation commit that updates this file follows `433fae7` and changes no code or test. **Tested tree: `433fae7`.**

| Finding | Correction | Regression tests (all confirmed failing on the reviewed code first, except where noted) |
|---|---|---|
| R005-01, P1 retry kept `gclid` after attribution withdrawal | Each queued event records every purpose its serialized bytes need (analytics, plus attribution while a URL keeps a click identifier); narrowing drops affected events and every send rechecks them. Eligible retries keep their ID and bytes. | `review-corrections.test.js` "R005-01: a confirmed attribution withdrawal drops queued retries carrying click IDs"; "eligible retries keep their event ID and exact bytes" (preservation check, passed before and after); real-browser "review sequences R005-01 to R005-03" |
| R005-02, P1 host denial still sent an event | `resume()` applies the host's choices synchronously: excluded purposes stop, the queue is purged and older state reads can no longer widen permission; a pending or unavailable read keeps the narrower ceiling. | "R005-02: a host denial on an active tracker stops new and queued events at once"; "a narrower host choice holds while a state read is pending or unavailable"; real-browser sequence |
| R005-03, P1 server expiry ignored | Per-purpose `expires_at` is translated through `server_time` and enforced at capture and send, after a grant, a resume or a refresh; consent writes now return these fields. | "R005-03: an analytics grant expiring before the next refresh stops capture"; "a fresh grant and a resume establish earlier per-purpose deadlines"; "an expired attribution grant removes click IDs from new and queued events"; `test_consent_responses_report_each_granted_purpose_expiry`; real-browser sequence |
| R005-04, P2 expired token used for refresh | Background reads (timers, visibility, page restore, refresh) check the fixed local lifetime first; expiry clears the subject, record and timers. An explicit `erase()` can still reach the expired subject. | "R005-04: background reads never send a token past the local lifetime" |
| R005-05, P2 partial withdrawal revoked analytics | A late grant response is reconciled per purpose against the latest choices; the blanket compensating withdrawal is removed. | "R005-05: withdrawing one purpose during a pending grant keeps the others" (server state, tracker state and a later analytics event) |
| R005-06, P2 GPC-refused purpose stayed enabled | GPC restrictions apply to every permission check, and a sale/share or advertising grant the collector still reports is withdrawn once through the existing tracker source (narrowing only, per D-033). | "R005-06: GPC narrows an existing subject's grants locally and on the server" (grant and resume paths) |
| R005-07, P2 SPA used the first `ts_link` | The link reference is read from the current URL for each new event; queued retries keep their original bytes. | "R005-07: each page view carries the current route's link reference" |
| R005-08, P2 stalled request blocked the queue | Each event request is aborted when the event's 60-second lifetime ends; the queue then continues with fresh events. | "R005-08: a stalled request is aborted at its lifetime and fresh events continue" |
| R005-09, P2 example blocked by its CSP | The initializer moved to the same-origin module `examples/install.js`; the policy is unchanged. | `install-example.browser.test.js` (Chromium and Firefox, committed files served unchanged): module loads, banner visible, no pre-consent request, no policy violation, consent then page view |
| R005-10, P2 verification exceeded five seconds | One absolute monotonic deadline is passed through DNS (TXT, CNAME, A, AAAA), TCP connect and TLS handshake; each blocking step gets only the remaining budget. Pinning, SNI and trust checks are unchanged. | `test_dns_subqueries_share_one_total_deadline` (lifetimes 13, 9, 5, 1 s under an injected clock); `test_connect_and_handshake_share_one_total_deadline` (handshake bounded by the remaining 1 s) |
| R005-11, P3 mixed-case target failed | The configured target is stored canonically and the verifier compares canonical forms. | `test_service_target_comparison_is_case_insensitive`; `test_equivalent_service_target_spellings_verify_identically` (API) |

Behavior change to note: `grant()` with only denials and no known subject now sends no request (previously one request that stored nothing); one existing Node expectation was updated accordingly.

### Results on `433fae7`

Same environment class as above: worktree without `.env`, project `.venv` (Python 3.12.4), a new disposable Compose project `tracking-spec005-review-20261111` running only PostgreSQL 18.6 as `tracking_foundation_test` on `127.0.0.1:55433` with separate runtime, migration and lifecycle roles and synthetic credentials outside the repository; Node 24.17.0 with the locked Playwright 1.64.1 browsers (Chromium 156.0.8078.4, Firefox 157.0) in the package. Native `tracking_sys` was not accessed.

| Check | Result |
|---|---|
| Backend suite with PostgreSQL and browser journey (`TRACKING_RUN_DB_TESTS=1 TRACKING_RUN_BROWSER_TESTS=1 pytest -q -rs -W default`) | **616 passed** in 186.09 s; no failures or skips (611 before plus 5 new) |
| Warnings | One `UnsupportedFieldAttributeWarning` from Pydantic in the inherited 002 test `test_concurrent_invitation_acceptance_creates_one_membership`; it appears intermittently when concurrent threads first build request validators and is unrelated to 005 code |
| `ruff check`, `ruff format --check`, `pip check` | Clean (100 files formatted); no broken requirements |
| Migration, grant, metadata, data-policy and OpenAPI checks | Pass inside the suite; OpenAPI snapshot updated additively (consent response fields), still 60 paths and 75 operations |
| Node unit tests (`npm test`) | **36 passed** (24 before plus 12 review regressions) |
| Real browsers (`npm run test:browser`) | **24 passed**: 12 cases in Chromium and in Firefox (10 before, the installation example, and the R005-01 to R005-03 transport sequences) |
| Regressions against the reviewed code | Before the corrections, 11 of the 12 new Node cases, the 3 new verification unit cases and both installation-example cases failed in the ways the review describes |

Limitations unchanged by these corrections: verification remains synthetic (no live DNS, CNAME, certificate, hosting or customer site); GPC reconciliation records withdrawals through the existing tracker source rather than a separate GPC source; a request already on the wire cannot be recalled when permission narrows, but it is never retried.

## Second review corrections (2026-11-11)

Authority: D-036. Review: independent review of the corrections on 2026-11-11 at reviewed head `9c49d89` (request changes; seven findings, all in the tracker and its installation example). The original R005-01 to R005-11 regressions are kept unchanged and still pass. Corrections on `codex/spec-005-links-tracker`:

| Commit | Content |
|---|---|
| `9a9c8e6` | D-036 record |
| `65534f8` | R005-12 to R005-17 (tracker 0.5.2); browser harness collector reports `expires_at` and `server_time` like the real API |
| `1c1bb05` | R005-18 (installation example); example and README import tracker 0.5.2 |

The documentation commit that updates this file follows `1c1bb05` and changes no code or test. **Tested tree: `1c1bb05`.** No backend code, schema, migration, dependency or API contract changed.

| Finding | Correction | Regression tests (each confirmed failing on the reviewed code first) |
|---|---|---|
| R005-12, P1 failed resume re-enabled withdrawn analytics | A purpose the host newly allows (through `grant` or `resume`) records a request-sequence watermark; it becomes effective only from a consent or state answer whose request started after that point. `withdraw` and denials also drop the cached server grant at once. A pending, failed or older answer therefore cannot widen permission. | `consent-integrity.test.js` "R005-12: a pending, failed or stale state read never re-enables a confirmed withdrawal" (zero event requests while pending, after 503, after the stale answer and after a second 503; collector stays `withdrawn`; a confirmed regrant then sends a fresh event); "a server state confirmed before the host widened a purpose cannot enable it"; real-browser "review sequences R005-12 and R005-14 hold at the real transport" (Chromium and Firefox, same sequence at the loopback collector) |
| R005-13, P1 latency extended the server expiry | Each grant's remaining lifetime (`expires_at - server_time`) is added to the local time at which its request started, for grant, resume and refresh alike; `confirmedAt` uses the same start time. A grant without a valid expiry or server time, or with no remaining lifetime, is not effective. | "R005-13: a state answer delivered after the grant's expiry never permits capture" (one second left, answer delivered 2.5 s later, for grant, resume and refresh: zero event requests); "a late answer ends attribution on time for new events and queued retries" (the queued retry carrying `gclid` is discarded and the fresh event's URL bytes keep only `utm_source`); "a grant reported without a valid expiry or server time is not effective" (four variants) |
| R005-14, P1 page restore sent the token after full withdrawal | `refresh()`, the `pageshow` handler, the refresh timer and visibility handling need current host permission. After a full withdrawal the token stays in memory only so that `erase()` can reach the subject. | "R005-14: after a full withdrawal no background request carries the subject token" (page restore, visibility changes, three refresh intervals and `refresh()` produce zero requests and no timers; `erase()` then reaches the same subject); real-browser sequence (zero collector requests after restore and visibility events; erasure body carries the same token) |
| R005-15, P2 GPC reconciliation stopped after transient failures | Reconciliation state is kept per subject and purpose (pending, consecutive failures, request sequence at which the last round ended). A round starts when an adopted answer, requested after the previous round ended, still reports a prohibited grant; at most `LIMITS.gpcRounds` (3) consecutive rounds may fail. Reconciliation follows every grant the collector reports, even one whose expiry data make it locally ineffective. Local GPC restrictions apply throughout. | "R005-15: GPC reconciliation resumes after transient withdrawal failures" (three 503 attempts, then one confirmed withdrawal after recovery: exactly 4 withdrawal requests, collector `withdrawn`, analytics untouched); "stays bounded while the collector keeps failing" (exactly 9 requests over six refreshes); "a newer grant is withdrawn again when GPC returns" (exact consent request sequence and final collector state) |
| R005-16, P2 in-flight event retried across a withdrawal | Each server grant carries an identity that survives refreshes but not a withdrawal or lapse; each event records the identity of every grant its bytes depend on. Narrowing marks in-flight events as revoked, so they are never attempted again even after a regrant. | "R005-16: an in-flight event narrowed by a withdrawal is never retried after a regrant" (the original event transmitted exactly once; a fresh post-regrant event delivered, and its own retry keeps its ID and bytes); existing "R005-01: eligible retries keep their event ID and exact bytes" still passes |
| R005-17, P2 stalled state read blocked the queue past its TTL | Consent, state and erasure requests are aborted after `LIMITS.controlTimeoutMs` (10 s), including reading the body. The queue waits for a state read at most until its oldest event's lifetime ends and is woken by any newly adopted state; a late answer is ignored as stale. The event-fetch abort and permission checks are unchanged. | "R005-17: a stalled state read cannot keep an expired event or block fresh traffic" (deterministic clock, hidden page, every state read held: the payload is removed at its lifetime with one event request; with a further read pending, an explicit grant lets a fresh event through; the late `unknown` answer is ignored and collection continues) |
| R005-18, P2 example failed without session storage | `examples/install.js` keeps its own choice record through helpers that tolerate read and write failures with an in-memory fallback; each handler calls the tracker before recording the choice. The Content Security Policy is unchanged. | `install-example.browser.test.js`, committed files served unchanged in Chromium and Firefox with storage available, access blocked and writes failing: banner visible, no request before consent, no policy violation, consent then page view, withdrawal of all purposes, erasure of the same subject, nothing else sent |

Before the corrections, all 11 new Node cases failed in the ways the review describes; the R005-17 case reproduces once the scheduled refresh is skipped by a hidden page, as in the reported sequence. The new browser cases failed in both engines on the reviewed tracker and example: the page view was queued while the resume read was pending, the banner never appeared with storage blocked, and no consent was sent when writes failed. The case with storage available passed before and after.

### Results on `1c1bb05`

Same environment class as above: worktree without `.env`, project `.venv` (Python 3.12.4), a new disposable Compose project `tracking-spec005r2` running only PostgreSQL 18.6 as `tracking_foundation_test` on `127.0.0.1:55433` with separate runtime, migration and lifecycle roles and synthetic credentials outside the repository; Node 24.17.0 with the locked Playwright 1.64.1 browsers (Chromium 156.0.8078.4, Firefox 157.0) in the package. Native `tracking_sys` was not accessed.

| Check | Result |
|---|---|
| Backend suite with PostgreSQL and browser journey (`TRACKING_RUN_DB_TESTS=1 TRACKING_RUN_BROWSER_TESTS=1 pytest -q -rs -W default`) | **616 passed** in 238.00 s; no failures, skips or warnings |
| `ruff check`, `ruff format --check`, `pip check` | Clean (100 files formatted); no broken requirements |
| Migration, grant, metadata, data-policy and OpenAPI checks | Pass inside the suite; no backend or contract change in this round |
| Node unit tests (`npm test`) | **47 passed** (36 before plus 11 new) |
| Real browsers (`npm run test:browser`) | **30 passed**: 15 cases in Chromium and in Firefox (12 before; the installation example now runs in three storage modes; plus the R005-12 and R005-14 transport sequence) |
| `git diff --check`, non-ASCII and credential scans of `9c49d89..HEAD` | Clean |

Behavior changes to note: a purpose newly allowed through `resume` or `grant` becomes effective only when its own state or consent request succeeds; the tracker no longer treats a reported grant without expiry data as effective; consent and state requests time out after 10 seconds; `refresh()` returns `false` without a request when the host allows no purpose.

Limitations: page restoration is exercised by dispatching a persisted `pageshow` event, not by a real back/forward-cache navigation; verification remains synthetic (no live DNS, CNAME, certificate, hosting or customer site); GPC withdrawals use the existing tracker consent source; a request already on the wire cannot be recalled when permission narrows, but it is never retried; a consent write aborted by the timeout may still have been applied by the collector, and its result is then learned at the next state read.

## Third review corrections (2026-11-11)

Authority: D-037. Review: independent review of tracker 0.5.2 on PR 4 on 2026-11-11 at reviewed head `f90b527` (request changes; four findings, all in the tracker). The branch and the published PR head were both at `f90b527` when this work started, so all four findings applied unchanged. The R005-01 to R005-18 regressions are kept unchanged and still pass. Corrections on `codex/spec-005-links-tracker`:

| Commit | Content |
|---|---|
| `115a64e` | D-037 record |
| `8051e89` | R005-19 to R005-22 (tracker 0.5.3), their Node and real-browser regressions, and a browser-harness option that delays an answer after the collector applied the request |

The documentation commit that updates this file follows `8051e89` and changes no code or test. **Tested tree: `8051e89`.** No backend code, schema, migration, dependency or API contract changed.

| Finding | Correction | Regression tests |
|---|---|---|
| R005-19, P1 queued resume sent the subject token after a newer denial | `resume()` records the host's intent for the purposes it was asked for. When its queued turn comes it goes ahead only while the host still allows one of them under the same choice; otherwise it ends as `superseded` before storage is read or a request is sent. `grant()` already re-checked its choices at that point, and withdrawals and erasures are always sent. | `consent-coordination.test.js` "R005-19: a queued resume sends no subject token after a newer host denial" (grant, confirmed full withdrawal, held resume, queued resume, newer denial: zero requests and zero storage accesses after the denial while the queue drains and over three refresh intervals; then a later valid resume reads the state exactly once with the same token and delivers a fresh event, and an explicit erasure reaches the subject); "a queued resume behind a withdrawal or an erasure sends only that request"; "a queued resume the host still stands by reads the state as before" (preservation check, passed before and after). Real browsers: `consent-coordination.browser.test.js` "R005-19: a queued resume sends no subject token after a newer host denial" in Chromium and Firefox against the loopback HTTP collector (the collector's request log after the denial is empty; later resume, event and erasure as above). |
| R005-20, P2 overlapping read hid a committed grant | A background state read is adopted only if no consent write (`grant`, withdrawal, erasure, GPC withdrawal) was on the wire while it was outstanding and no local change happened; the collector may process an overlapping read and write in either order, so the write's own answer is the one adopted. A read that was answered but not adopted is repeated once the pending consent operations have finished, unless a newer answer was adopted meanwhile, and only after `refresh()` has re-checked host permission, the token and its lifetime. While such a repeat is due, no further background read is sent. Local denial stays synchronous. | "R005-20: a state read answered before a pending grant commits never hides the grant" (triggered by `refresh()` and by a restored page: grant result `granted`, collector `granted`, tracker collecting with a scheduled refresh, a fresh page view delivered with the subject's token, and collection still running two refresh intervals later); "a state read processed after the grant committed leaves the grant in place" (the other processing order, both triggers; preservation check); "a newer local withdrawal still wins over the late grant in either order" (grant result `superseded`, collector `withdrawn`, no purposes, zero events, no state read after the withdrawal; preservation check); "a grant whose answer is lost is learned from one repeated state read"; "a state read dropped by a local change is repeated so collection continues". Real browsers: three R005-20 cases in Chromium and Firefox covering both processing orders, `refresh()` and a dispatched persisted `pageshow`, and the newer withdrawal, asserting the grant result, the collector's final state, the tracker's final state and the delivered event. |
| R005-21, P2 GPC-only choice skipped the server withdrawal | A choice that GPC refuses now starts a bounded withdrawal round for every sale/share or advertising grant the collector is known to report for the subject held in memory, in `grant()` and `resume()`, also when GPC filters every requested choice. The call still returns `nothing_sent` or `blocked`, the local permission set stays empty and tracking stays blocked. Without a known subject nothing happens. | "R005-21: a GPC-only choice withdraws the known subject's existing server grant" (through `grant` and through `resume`: exactly one request, `{subject_token, choices: {sale_or_share: "withdrawn"}}`, collector `withdrawn`, no purposes, page view blocked, zero events over three simulated minutes, and a repeated choice sends nothing more); "the GPC-only withdrawal stays bounded while the collector keeps failing" (exactly 9 requests over six repeated choices, collector still `granted`, tracking blocked); "a GPC-only choice from a new visitor creates no subject, identifier or request" (no request, no storage access, no location read, no random value, no timer, no subject at the collector; passed before and after). |
| R005-22, P2 new grant inherited an exhausted GPC budget | The reconciliation state per subject and purpose now records which grant its failures were counted for. A grant is identified by the expiry instant the collector reports for it, which a routine read repeats unchanged and every new consent record replaces. A different identity starts a new budget of `LIMITS.gpcRounds` rounds; the same identity keeps its count. | "R005-22: a distinct new grant gets its own bounded GPC reconciliation budget" (the reported sequence: 9 failed requests exhaust the budget; three routine refreshes after recovery add none and the collector stays `granted`; GPC off, explicit withdrawal confirmed `withdrawn`, explicit regrant confirmed `granted`; GPC on and one refresh: exactly one reconciliation request with the exact body, collector `withdrawn`, analytics untouched); "the new grant's own budget is bounded and a routine refresh never resets it" (a regrant made elsewhere gets exactly 9 more requests during a second outage, then none after recovery). The R005-15 cases are unchanged and pass. |

Reproduction on the reviewed tracker (`f90b527`, before `8051e89`): 9 of the 13 new Node cases failed in the ways the review describes (R005-19: the queued resume sent a `consent-state` request with the subject token after the denial and after a withdrawal, and after an erasure it ran and read storage without sending a request; R005-20: the grant returned `nothing_granted`, the overlapping read was adopted, and a read dropped by a local change was never repeated; R005-21: no withdrawal request; R005-22: no reconciliation request for the new grant). The four that passed are the preservation checks named above. The final test file was also run against a scratch copy of the reviewed tracker outside the repository, with the same 9 failures.

### Results on `8051e89`

Same environment class as above: worktree without `.env`, project `.venv` (Python 3.12.4), a new disposable Compose project `tracking-spec005r3` running only PostgreSQL 18.6 as `tracking_foundation_test` on `127.0.0.1:55433` with separate runtime, migration and lifecycle roles and synthetic credentials generated outside the repository; inherited `TRACKING_`, `PG` and `PYTHON` variables were removed for the run. Node 24.17.0 with the locked Playwright 1.64.1 browsers (Chromium 156.0.8078.4, Firefox 157.0) in the package. Native `tracking_sys` was not accessed.

| Check | Result |
|---|---|
| Backend suite with PostgreSQL and browser journey (`TRACKING_RUN_DB_TESTS=1 TRACKING_RUN_BROWSER_TESTS=1 pytest -q -rs -W default`) | **616 passed** in 232.15 s; no failures, skips or warnings (the intermittent Pydantic warning noted for the reviewed baseline did not appear in this run) |
| `ruff check`, `ruff format --check`, `pip check` | Clean (100 files formatted, Ruff 0.17.3); no broken requirements |
| Migration, grant, metadata, data-policy and OpenAPI checks | Pass inside the suite; no backend or contract change in this round |
| Node unit tests (`npm test`) | **60 passed**, none skipped (47 before plus 13 new) |
| Real browsers (`npm run test:browser`) | **38 passed**, none skipped: 19 cases in Chromium and in Firefox (15 before plus the R005-19 case and three R005-20 cases) |
| `git diff --check`, non-ASCII and credential scans of `f90b527..HEAD` | Clean |

Behavior changes to note: a `resume` that waited behind other consent work may now end as `superseded` without a request; `refresh()` returns `false` for a state read that overlapped a consent write or while a repeat of such a read is due, and the tracker repeats that read itself; `grant` and `resume` with a choice that GPC refuses may send one bounded withdrawal for a known subject, in a mixed call before the remaining choices are sent; the GPC failure limit applies per distinct grant.

Limitations: the R005-21 correction acts on the subject and grant the tracker holds in memory. After a reload, a GPC-only choice does not read `sessionStorage`, so a stored subject whose only grant GPC refuses keeps its server grant until a permitted `grant` or `resume` makes the subject known again; reading storage on that path is a policy choice left to the owner. A grant is told apart by its reported expiry, so an answer without a valid expiry shares one budget. A state read is not coordinated with consent changes made in another tab; it reports whatever the collector held when it was processed. A state read that overlaps a write is still sent once before it is discarded. Page restoration is exercised by dispatching a persisted `pageshow` event, not by a real back/forward-cache navigation. The earlier limitations stand: verification remains synthetic (no live DNS, CNAME, certificate, hosting or customer site); GPC withdrawals use the existing tracker consent source; a request already on the wire cannot be recalled; and a consent write aborted by the timeout may still have been applied by the collector. In Chromium and in Firefox, the R005-19 case recorded one `consent-state` request carrying the subject token after the denial, and the R005-20 read-first case returned `nothing_granted`; the two other browser cases passed before and after.

## Final review correction (2026-11-11)

Authority: D-038. Review: final review of PR 4 on 2026-11-11 at reviewed head `4ebe5ab` (one finding in the tracker). The branch and the published PR head were both at `4ebe5ab` when this work started. The R005-01 to R005-22 regressions are kept unchanged and still pass. Corrections on `codex/spec-005-links-tracker`:

| Commit | Content |
|---|---|
| `2a45556` | D-038 record |
| `0ebe670` | R005-23 (tracker 0.5.4), its Node and real-browser regressions, and a switchable Global Privacy Control signal in the browser harness |
| `cbccaf6` | Test-only: the existing reload case checks the stored local expiry against the page clock (see the note under the results) |

The documentation commit that updates this file follows `cbccaf6` and changes no code or test. **Tested tree: `cbccaf6`.** No backend code, schema, migration, dependency or API contract changed.

**R005-23: a queued consent grant sent a restricted grant after GPC became active.** `grant()` read the signal only when it was called. A grant that waited behind other consent work was serialized later under the earlier reading.

Observed on the reviewed tracker (`4ebe5ab`), with the reported sequence (GPC off; an explicit analytics grant on the wire with its answer held; `grant({ sale_or_share: "granted" })` queued with its request not started; the signal switched on with no further tracker call; the first answer released). Requests that started after activation, as raw bodies at the loopback collector, identical in Chromium and Firefox:

1. `POST consent` `{"choices":{"sale_or_share":"granted"},"subject_token":"sbj_..."}` (the defect: one prohibited grant)
2. `POST consent` `{"subject_token":"sbj_...","choices":{"sale_or_share":"withdrawn"}}` (the existing reconciliation)

The final collector state was `withdrawn`, so a check of the final state alone would have passed. The mixed browser case recorded two prohibited grants (`sale_or_share` and `ads.personalization`) in one body. On the reviewed tracker, 5 of the 7 new Node cases failed (the three restricted purposes, both mixed requests, the request without a subject, which also created one, and the known server grant, which was granted again before being withdrawn), and 2 of the 3 browser cases failed in each engine; the cases that passed are the preservation checks (GPC staying off; queued withdrawal, erasure and reconciliation). The final Node file was also run against a scratch copy of the reviewed tracker outside the repository, with the same 5 failures.

Correction: after the per-purpose host-intent check and in the same synchronous turn that issues the request, the queued task reads the signal again. `sale_or_share`, `ads.measurement` and `ads.personalization` grants restricted at that moment are removed from the choices to be serialized, added to the result's `refused` list and disallowed locally, as at the call. The remaining choices are sent. When nothing remains, the task returns `nothing_sent` before storage is read, so no subject is created and no empty consent write is sent; when only denials remain and no subject is known, the existing rule returns `nothing_granted` without a request. A grant the collector is already known to report for the subject in memory still starts the bounded withdrawal. With the fix, the same sequence records **zero** prohibited grants and zero requests after activation.

| Regression test | Asserts |
|---|---|
| `gpc-queued-grant.test.js` "R005-23: a queued grant sends no restricted grant once GPC has become active" | For each of the three restricted purposes: the exact sequence; zero restricted grants and no request at all after activation over 30 simulated seconds; result `{status: "nothing_sent", refused: [purpose]}`; tracker purposes `[analytics.first_party]`; collector holds only the analytics grant; switching the signal off again does not revive the choice. |
| "a mixed queued grant keeps its permitted choices and drops the restricted ones" | One request after activation whose body carries exactly `attribution: granted` and `ads.personalization: denied`; `sale_or_share` and `ads.measurement` are absent and listed under `refused`; result `granted` with analytics and attribution; collector state matches; a page view is queued. |
| "a queued permitted analytics grant with a restricted grant reaches the collector alone" | The body carries exactly `analytics.first_party: granted`; the collector grants analytics; `sale_or_share` is absent and refused. |
| "filtering every grant creates no subject and sends no empty consent write" | With no subject (the first grant fails): no request, no stored record, no subject at the collector and no timer, for one restricted grant, two restricted grants, and a restricted grant with a denial. |
| "a queued restricted regrant of a known server grant is withdrawn, never granted" | The only request after activation is the bounded withdrawal `{subject_token, choices: {sale_or_share: "withdrawn"}}`; collector `withdrawn`. |
| "a queued grant still succeeds while GPC stays off" | For each restricted purpose the queued grant is sent with its exact body and becomes effective (passed before and after). |
| "queued withdrawal, erasure and GPC reconciliation still reach the collector" | A queued explicit withdrawal is sent after activation, reconciliation withdraws the other reported grant, and a queued erasure erases the subject (passed before and after). |
| `gpc-queued-grant.browser.test.js` (Chromium and Firefox, loopback HTTP collector) "a queued grant sends no restricted grant once GPC has become active" | The reported ordering for each restricted purpose: the collector's raw request log after activation is empty; result, tracker state and collector state as above. |
| "a mixed queued grant keeps its permitted choice and drops the restricted ones" | The one request after activation carries exactly `attribution: granted`; then a page view is delivered, an explicit withdrawal is confirmed and an erasure removes the subject. |
| "a queued grant still succeeds while GPC stays off" | The queued `sale_or_share` grant is sent and effective (passed before and after). |

### Results on `cbccaf6`

Same environment class as above: worktree without `.env`, project `.venv` (Python 3.12.4), a new disposable Compose project `tracking-spec005r4` running only PostgreSQL 18.6 as `tracking_foundation_test` on `127.0.0.1:55433` with separate runtime, migration and lifecycle roles and synthetic credentials generated outside the repository; inherited `TRACKING_`, `PG` and `PYTHON` variables were removed for the run. Node 24.17.0 with the locked Playwright 1.64.1 browsers (Chromium 156.0.8078.4, Firefox 157.0) in the package. Native `tracking_sys` was not accessed.

| Check | Result |
|---|---|
| Backend suite with PostgreSQL and browser journey (`TRACKING_RUN_DB_TESTS=1 TRACKING_RUN_BROWSER_TESTS=1 pytest -q -rs -W default`) | **616 passed** in 191.67 s; no failures or skips. One warning: the Pydantic `UnsupportedFieldAttributeWarning` in the inherited 002 test `test_concurrent_invitation_acceptance_creates_one_membership`, the same intermittent warning recorded for the reviewed baseline and unrelated to 005 code |
| `ruff check`, `ruff format --check`, `pip check` | Clean (100 files formatted, Ruff 0.17.3); no broken requirements |
| Migration, grant, metadata, data-policy and OpenAPI checks | Pass inside the suite; no backend or contract change in this round |
| Node unit tests (`npm test`) | **67 passed**, none skipped (60 before plus 7 new) |
| Real browsers (`npm run test:browser`) | **44 passed**, none skipped, in three consecutive complete runs: 22 cases in Chromium and in Firefox (19 before plus the three R005-23 cases) |
| `git diff --check`, non-ASCII and credential scans of `4ebe5ab..HEAD` | Clean |

Note on the reload case: the first two complete browser runs on `0ebe670` failed the existing case "reload resumes from the server state without a new grant or a renewed expiry" (in both engines, then in Chromium only) at `stored.expiresAt - Date.now() <= 24 h`, while the same file passed four times when run alone. That line compared an expiry written with the page's clock against a later reading of the Node process's clock with no tolerance. Measured on the verification machine, the page clock was 1 to 3 ms ahead of a later Node reading in 200 of 200 samples in Chromium and ahead in 191 of 200 in Firefox, so the comparison could fail whenever less time than that had passed. The tracker was not involved: it sets the expiry once from its own clock. `cbccaf6` evaluates the unchanged 24-hour bound with the page clock; the complete browser suite then passed three times in a row. On `0ebe670` the backend suite had also passed (616 in 205.00 s, no skips or warnings).

Behavior changes to note: a queued `grant` may now return `nothing_sent`, or list additional purposes under `refused`, when the signal became active after the call; such purposes are disallowed locally, as when GPC refuses them at the call.

Limitations: the signal is evaluated in the browser turn that issues the request; a request already on the wire when the signal becomes active cannot be recalled, and its grant is then withdrawn by the existing bounded reconciliation once an answer reports it. A queued `resume` made before the signal became active still performs its state read (it sends no grant, and the read lets the reconciliation withdraw a reported grant). The limitations recorded for the earlier rounds stand.

## Final review and cleanup

The final diff `a909990..HEAD` was inspected for unrelated changes, secrets, credentials, tokens and control characters; the root workspace's unrelated work was not touched. The disposable Compose project and its volume, the scratch runner, synthetic credentials, generated helper scripts and logs were removed after the run. The tracker's local `node_modules` (Playwright and test browsers) is ignored by Git and kept as reusable test tooling. For the third review corrections, the diff `f90b527..HEAD` was inspected in the same way, and the disposable Compose project `tracking-spec005r3` with its volume and network, the synthetic credential file, the scratch runner, the scratch copy of the reviewed tracker and the logs were removed after the run. For the final review correction, the diff `4ebe5ab..HEAD` was inspected in the same way, and the disposable Compose project `tracking-spec005r4` with its volume and network, the synthetic credential file, the scratch runner, the clock measurement script, the scratch copy of the reviewed tracker and the logs were removed after the run.
