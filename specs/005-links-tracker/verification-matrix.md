# Specification 005 verification matrix

Status: **executed on 2026-11-10** against the D-033 implementation; see the [evidence](evidence.md) for the tested tree, commands, counts and the test that covers each row. Prepared against [design revision 1](design.md). Use synthetic domains, tenants, forms and tokens. External DNS/ACME/provider success must not be inferred from injected adapters.

| Case | Scenario and required observable evidence | Requirement |
|---|---|---|
| L1 | Authorized Owner/Admin creates link; allowed reader sees scoped metadata; other agency/client, disabled member and read/ingest keys cannot mutate. Check stored rows and audit scope. | AC2, tenancy |
| L2 | Link redirects to exact immutable destination with deterministic UTM precedence and stable ts_link; template edits do not rewrite old links; no visitor token/PII enters Location. | AC1 |
| L3 | Reject unsafe schemes, credentials, control characters, malformed encodings, query injection and unauthorized origins. Ignore incoming redirect query parameters. Concurrent duplicate slugs have one winner. | AC2 |
| L4 | Reject direct managed-host destinations and conflicts introduced by later domain activation; verify host canonicalization, Host/forwarded-host spoofing and foreign domain claims. | AC2/4 |
| L5 | Successful lookup redirects even when telemetry is unavailable; GET/HEAD set no cookies and write no event or visitor data. Missing storage returns 503 rather than an unsafe fallback. Bot/prefetch hits create no qualified-human metrics. | AC3 |
| P1 | Old v1 clients and stored fingerprints deduplicate unchanged. Present link_id participates in conflicts/upgrades, rejects foreign references and remains a limited-trust claim. | 004 compatibility |
| P2 | Event erasure/retention removes link references with subject data; tombstone replay still fails. Shared link configuration remains; raw tokens/URLs do not appear in logs. | 003/004 privacy |
| C1 | Real browser before consent: no storage reads/writes, token generation, outbound tracking request, form value access or pre-consent backlog. Intercept requests and instrument storage/value access. | 003 C4/E1 |
| C2 | Explicit grant issues one token; reload/resume reads state without appending grants or renewing expiry/activity. Remote withdrawal, expired grant, missing/deleted token and changed source configuration stay blocked. | Consent continuity |
| C3 | Test withdrawal during pending grant, event retry, state refresh and BFCache restoration; stale responses cannot re-enable capture. Verify local stop first, exact server outcome and no subsequent queued event. | Consent race |
| C4 | sessionStorage refusal, expiry, opener-copy behavior, source namespaces and memory fallback; no localStorage/cookies introduced. No promise of cross-tab identity or instantaneous revocation. | D6 policy |
| C5 | Non-mutating consent-state enforces Origin/token/client lock/rate limits; no activity/grant changes. Real browser can read Retry-After only for permitted origins; platform CORS/CSRF stays intact. | API/CORS |
| C6 | GPC true prevents sale/share and advertising grants; false/absent never creates permission. Analytics/attribution still require explicit decisions, with no new jurisdiction profile. | Inherited 003 contract |
| M1 | Form with password, hidden, cc-number/cc-csc, one-time-code, unknown and permitted controls: forbidden values are never read and absent from all outgoing bytes; valid registered option/code/quantity values survive. | 003 M4 |
| M2 | Python/JavaScript fixtures cover card separators, encoded email/card URLs, click IDs without attribution, duplicate parameters, referrer reduction and bounds. Compare actual sanitized envelopes, not helper invocations. | Minimization parity |
| T1 | Navigation/form submission works during timeout/offline/429/503. Retries preserve IDs/payloads, respect Retry-After/TTL/count/byte bounds and permission changes. 202 means received, not proven storage. | Reliability |
| D1 | TXT wrong/expired/reissued proof, CNAME mismatch/loop/overlong chain, unknown host and concurrent claims never activate a domain. | AC4 |
| D2 | Certificate hostname/CA/expiry failure, mixed/private DNS answers and rebinding fail; socket uses validated address with original SNI. No HTTP follow, raw cert/DNS secret log or live connection in deterministic tests. | AC4/SSRF |
| D3 | Verification completing after domain disablement, challenge rotation, actor revocation or origin conflict cannot activate stale state. Redirect never probes network and fails when verification expires. | Concurrency |
| DB1 | Fresh migration cycle, re-upgrade, metadata comparison, populated downgrade refusal, scoped FKs, partial uniqueness, mutable-column grants and data-policy registry. | Schema review |
| E2E | Synthetic branded link -> destination -> explicit consent -> tracker page/form/link event -> scoped stored event -> withdrawal -> suppressed event -> erasure/replay rejection. Assert browser bytes and DB absence/presence. | Full path |

## Required execution record after implementation

Record exact commit/tree, dependency locks, isolated Python/Node versions, disposable DB/container identity, browser versions, commands, counts, failures/skips and limitations. Run the existing full backend suite, Ruff lint/format, pip check, OpenAPI and schema checks; native Node tests and real Playwright browser tests; final diff/secret inspection. Start with Chromium and Firefox unless the dependency decision changes the supported test matrix. No elapsed-time performance claim without measurement, and no live custom-domain acceptance without actual authorized DNS/TLS evidence.

The application must pass the behavioral matrix before 005 is called complete. A documentation packet or injected verifier alone does not complete tracker, browser or live deployment acceptance. Deployment-specific evidence may remain separately gated, but must be labelled as such.
