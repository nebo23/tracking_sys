# Specification 005 evidence

Date: 2026-11-10. Authority: D-033 (recommended D1-D10 and design revision 1 prepared at `a909990`). Branch: `codex/spec-005-links-tracker`, local commits only; nothing was pushed, published, merged, deployed or migrated natively.

**Update 2026-11-11 (D-035):** the independent review of PR 4 at `14e8288` raised eleven findings (R005-01 to R005-11). They are corrected and verified in [Review corrections](#review-corrections-2026-11-11) below; the sections before it record the original 2026-11-10 implementation and its results.

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

## Final review and cleanup

The final diff `a909990..HEAD` was inspected for unrelated changes, secrets, credentials, tokens and control characters; the root workspace's unrelated work was not touched. The disposable Compose project and its volume, the scratch runner, synthetic credentials, generated helper scripts and logs were removed after the run. The tracker's local `node_modules` (Playwright and test browsers) is ignored by Git and kept as reusable test tooling.
