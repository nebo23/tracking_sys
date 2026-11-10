# Specification 005 design — revision 1

Prepared: 2026-11-10 against merged `main` at `e8ef587` and the local entry commit `05cc15a`. **Proposal for review, not implementation approval.** D-032 authorizes preparation. Every new schema, policy value and dependency below requires the [decision packet](decision-packet.md). Existing D-025/D-027 rules remain binding.

## 1. Sources and baseline

The [feature register](../../docs/product/feature-register.md) maps PDF-003 to verified custom tracking domains, PDF-015 to branded short links that survive analytics failure, PDF-016 to UTM templates and PDF-024 to per-content links without automatic post editing. PDF-001 and PDF-008 supply tracker/form requirements. Preserve all four 005 acceptance criteria and inherited C4/M4 tests.

Code inspected: `app/collection/contract.py`, `app/api/collection.py`, `app/api/public_cors.py`, `app/services/collection.py`, `app/services/lifecycle.py`, `app/services/tenancy.py`, and `app/data_policy.py`. The JavaScript tracker and React folders currently contain documentation only. Node v24.17.0 and npm 11.13.0 are installed; no package was installed during preparation.

| Existing fact | Design consequence |
|---|---|
| EventEnvelope v1 forbids extra top-level fields; URL minimization drops non-allowlisted query parameters | A link reference needs an explicitly reviewed contract extension, not an invented payload field. |
| Public consent POST appends records and may issue a token; there is no read-only public consent-state route | Reloading a page must not call grant again to restore a session. Propose a non-mutating state endpoint. |
| Public CORS matches events/consent/erasure and exposes no Retry-After header | Extend only the public route matcher and response-header exposure required by the tracker. Keep platform credentialed CORS separate. |
| Forms allow option/code/quantity classes only | DOM collection must be narrower than the registered form schema and exclude all other fields before reading their values. |
| Every collection event requires a subject token and granted purposes | An unconsented redirect cannot be turned into a subject-linked event. |
| Client locks serialize ingestion, consent, erasure and lifecycle | New event-link validation and state reads must respect this ordering without taking agency locks afterwards. |

## 2. Proposed scope and slices

1. **005-A:** approve this design, schema/privilege packet and regression matrix.
2. **005-B:** client-scoped campaign/content references, UTM templates, destination allowlists, domains and managed links; safe redirects; administrative audit.
3. **005-C:** optional validated event link reference and non-mutating consent-state endpoint, preserving 004 compatibility and erasure/lifecycle behavior.
4. **005-D:** self-hostable JavaScript tracker, explicit consent API, optional DOM bindings, parity fixtures and browser tests.
5. **005-E:** domain ownership/routing/TLS verifier, synthetic DNS/TLS integration, installation example and complete acceptance evidence.

All implementation slices are proposed. DNS purchases, public hosting, certificate issuance and customer-site installation are separately authorized operations. Domain-verification logic is included; unperformed live verification stays visibly unverified. Do not declare custom domains production-ready from mocked tests.

Excluded: React dashboard, social posting, full content publishing system, identity stitching, contact-value capture, payment proof, attribution calculations, replay/heatmaps, cross-site tracking and new provider SDKs. These exclusions do not reduce the dual social-analytics/attribution launch scope.

## 3. Observable example

An Owner/Admin registers a synthetic campaign/content reference and destination `https://shop.example.test/offer`, then creates a managed link. GET `/r/spring-offer` redirects to the stored destination with server-composed UTM values and a stable `ts_link` UUID shared by every visitor to that link. It contains no visitor token. Arbitrary query input on the short link is not forwarded.

The website self-hosts the tracker. Before consent it performs no tracking request, DOM-value capture or storage access. After an explicit analytics grant, the tracker obtains a token and submits a minimized page view with the link reference. When consent is withdrawn, local collection stops immediately and the server receives the withdrawal. Page navigation and form submission continue independently of telemetry failures.

This proves link provenance and collection, not that a visitor is a known person or that a redirect is a qualified human click.

## 4. Link/UTM and redirect policy — proposed

- Owner/Admin manage resources within an active agency/client; authorized client readers may list non-secret link metadata. Read/ingest service keys do not gain administration privileges.
- Normalize hostnames to lowercase ASCII IDNA; compare exact scheme/host/effective-port tuples. Production-style destinations are HTTPS/443; loopback HTTP is allowed only by explicit development configuration. Reject credentials, fragments, control characters, ambiguous encodings, IP-literal destinations and reserved/internal hostnames. No URL fetch is performed to validate a redirect destination.
- Destination origins are explicitly registered by the client's Owner/Admin. No wildcard or suffix matching. Restrict stored query names to an approved per-origin allowlist (initially the six existing `utm_*` names); additional static query names need explicit configuration. Values are bounded non-identifying codes, not arbitrary contact data. Reject recognized email/card patterns in path/query and forbid signed URLs, tokens and customer IDs. Pattern checks do not establish universal PII detection.
- Proposed UTM normalization: keys from the existing six-parameter set; values `[A-Za-z0-9_.-]{1,64}`; preserve value case. Merge precedence: explicit link values > template > stored destination UTMs; conflicting duplicate keys in any input are rejected. Add `utm_id` from the campaign's stable public code if absent. Reserve `ts_link` for the managed link UUID.
- Campaign/content references are business identifiers, never visitor identifiers. Each content reference is an opaque external reference plus optional platform label; it is not proof of access to that social platform. One content reference may have several deliberately created links; no automatic post editing.
- Link destination, UTM snapshot, campaign/content association, domain and slug are immutable after issuance. Create a replacement link for changed provenance; existing link status/expiry can change. Templates may change, but previously issued links keep their snapshots. Referenced campaign/content public codes are immutable; display labels may change.
- Proposed slugs: lowercase `[a-z0-9][a-z0-9-]{2,63}`, with a reserved-name list. Enforce uniqueness in the database, never by a preflight query alone. Do not recycle disabled slugs in 005.
- Resolve only by configured platform host or a verified, active custom host, and the exact slug. Ignore forwarded-host headers unless an explicitly configured trusted proxy owns them; never let request input select a tenant directly.
- GET and HEAD produce a **302** with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. HEAD does not record a click. Other methods return 405. Missing/disabled/expired records or disabled agency/client/domain return a generic 404; database unavailability returns a sanitized 503. These failures must not choose a caller-supplied fallback destination.
- Forbid destinations at the platform short-link host or any managed custom host. Domain activation and destination registration must also check for existing conflicts, under a shared namespace lock, to prevent later configuration from creating managed-link loops. This does not claim detection of redirect chains operated by arbitrary external websites; no external HTTP chain is followed.
- The redirect performs no analytics transaction, consent mutation, cookie write, subject generation or raw-click persistence. Database lookup is still necessary, so this does not claim redirects survive a complete storage outage. Simulated telemetry failure must not affect a successful lookup/redirect. Bot/prefetch traffic is never counted as a qualified human click merely because it redirected.

## 5. Proposed schema and privileges

Propose additive migration `0008_links_tracker`, following `0007_event_collection`: **six new tables** and one nullable event column. This is a schema review, not an instruction to execute a migration. All tenant resources have UUID keys, `agency_id`, `client_id`, created/updated timestamps, scoped unique keys and composite foreign keys; no unscoped caller-supplied references.

| Table | Proposed domain fields and constraints |
|---|---|
| `link_campaigns` | Immutable client-unique public code (1-64 code characters), display label (1-100), active/archived status. |
| `link_content_references` | Client-unique external code (1-128 code characters), optional platform label, active/archived status; no content body, customer record or social credential. |
| `link_utm_templates` | Client-unique name, validated six-key UTM JSON object, revision counter, active/archived status. |
| `link_destination_origins` | Exact normalized origin, approved static-query names, active/disabled status; unique per client. Disabling prevents subsequent redirects to that origin. |
| `link_domains` | Globally unique canonical hostname, client ownership, pending/verified/disabled status; challenge digest and expiry, verification time/deadline, observed certificate expiry, closed failure code and version counter. Raw challenge returned only at issuance; no DNS credentials or certificate private keys. |
| `managed_links` | Nullable client-owned `domain_id` (null means platform hostname), immutable slug, origin reference, destination and UTM snapshot, optional campaign/content references, active/disabled status and optional expiry. Partial unique index on platform slug when domain is null; unique `(domain_id, slug)` for custom domains. |

Add nullable `collected_events.link_id` with scoped FK to `managed_links` and appropriate index. Existing rows remain null. No new redirect log, cookie, raw-hit counter, visitor table or tracker-installation table. Existing source and form configuration are reused; installation config is assembled from authorized source/form metadata.

Runtime: SELECT/INSERT plus explicit mutable-column UPDATE on six tables; no hard DELETE. Issued link provenance and primary/scope keys are never mutable. Existing event INSERT/upgrades may carry the validated link reference; client/event identity remains immutable. Add fixed audit action codes for configuration mutations, recording object IDs only, not URLs or challenge values. Preserve grants on all existing privacy stores.

Lifecycle: no new table privilege in this proposal. Campaign/content/link configuration is held for the workspace lifetime to preserve provenance and non-reused slugs; expired challenge material is invalid even if its digest remains until challenge replacement. This retention is a proposed development policy, not approval for live customer data. Add every table/column to the data-policy registry. Subject erasure deletes its event link references with the events, but does not delete shared marketing configuration. Client offboarding/purge remains an explicit later workflow.

Downgrade must refuse any populated new table or non-null event link reference rather than discard data. Test upgrade, re-upgrade, metadata equivalence, grants and refusal on disposable PostgreSQL. Native migration remains separately gated.

## 6. API and event compatibility — proposed

Under `/agencies/{a}/clients/{c}`: authenticated list/create endpoints for campaigns, content references, UTM templates, destination origins, domains and links, with PATCH limited to reviewed mutable fields. Paginate lists (default 50, maximum 100). Add domain challenge issuance/verification operations and link disablement; never put challenge values into audit or access logs. All administrative writes require existing cookie/CSRF protections and Owner/Admin authorization.

Public redirect: `GET|HEAD /r/{slug}` with host-scoped resolution as above. Static tracker assets are versioned project files served by the customer's own site in the default installation; no CDN or extra server asset route is selected.

Extend EventEnvelope v1 with optional `link_id` only if D4 is approved. Parse the stable `ts_link` from the destination URL after consent, exclude it from the transmitted minimized URL and send it in `link_id`. Admission resolves its agency/client association from existing trusted scope, not from the supplied UUID. Unknown/foreign references reject generically (trusted 422; existing public generic 202). A disabled historical link can still supply a valid reference for an otherwise admissible event; it cannot redirect. Browser-supplied attribution remains limited-trust and is never payment proof.

Include a present link reference in event fingerprinting/conflict rules. For absent/null references preserve the previous canonical input exactly, so retries of pre-005 events remain duplicates. Trusted upgrades follow existing rank/type/subject rules. Erasure, replay tombstones and lifecycle expiry must still remove subject-associated references. Test old clients, old stored fingerprints, cross-client references and false provenance claims.

Propose `POST /collect/v1/{public_key}/consent-state` with `{subject_token}` in the bounded body. It checks the registered Origin, live source, client lock and token possession, then returns current states, server time and applicable per-purpose expiry, plus an active/unknown result. It does not issue tokens, append consent, renew expiry or refresh subject activity. Missing/deleted tokens produce a fixed unknown state without explaining deletion history. Use a purpose-specific rate-limit bucket and no-store headers. There is no token in a URL or a GET query.

Extend the public CORS matcher only for this route; expose `Retry-After` only to the accepted registered origin. Add no credential grant and no arbitrary-header wildcard. MDN documents that non-safelisted response headers need explicit exposure [S005-02]. The source grant must be set before route-level rate limiting so permitted origins can read 429 retry information.

## 7. Tracker contract and consent state machine — proposed

Author `packages/tracker-js` as native JavaScript with no production dependency or TypeScript/bundler. Use a self-hostable ES module with an explicit import/initialization example. Node's built-in test runner covers pure code; a project-local Playwright dev dependency covers real-browser integration [S005-07, S005-08]. A classic-script build is not assumed and requires a separate packaging decision if wanted.

Public API proposal: `createTracker(config)`, `grant(choices)` for an actual new consent action, `resume(currentChoices)` for a host/CMP-confirmed existing decision, `withdraw(purposes)`, `erase()`, `trackPageView()`, `trackLinkClick(element)`, `trackForm(formKey, element)`, and `destroy()`. Return closed statuses without echoing sensitive data. The site's own banner/CMP supplies explicit decisions; no vendor or banner UI is selected. Manual calls and explicitly registered DOM bindings are supported; automatic full-site capture is not the default.

Configuration includes collector origin, public source key, reviewed form descriptors and optional DOM selectors. It contains no private ingest key. The backend's stored descriptors remain authoritative: browser configuration never widens what 004 will accept. Do not fetch a configuration endpoint on initialization.

Read the browser's GPC signal without creating an identifier. A true signal may only narrow permission: refuse sale/share, ads.measurement and ads.personalization grants, consistent with the existing 003 `GPC_PURPOSES`; it does not grant analytics or attribution. No new jurisdiction profile or claim of legal compliance is introduced. Public consent records keep the existing tracker-banner source; do not fabricate a trusted GPC source. Add signal-present/absent tests and preserve J1 default denial.

| State/transition | Required behavior |
|---|---|
| Initial unknown/denied | No tracker storage read/write, token generation, telemetry request, URL-value collection or DOM-value capture. Load the module from the site's own assets; `init` only validates static configuration and registers callbacks. |
| Explicit grant | Call consent once for the user's action. Enable only purposes granted in the response. Store the returned token only afterwards. No delayed transmission of pre-consent events. |
| Reload/resume | After the host confirms current local permission, read the scoped stored token and call consent-state. Never call grant just to resume. If no token or server state is unknown, withdrawn or expired, remain blocked pending an explicit grant; do not silently recreate a subject. |
| Withdrawal | Stop affected capture, discard queued affected events and clear persistent permission immediately. Serialize consent mutations and reconcile late grant responses by sending withdrawal for any resulting token; never let an old response re-enable capture. |
| Network failure during withdrawal | Stay locally blocked. Retain only the token/control request in memory for bounded retry; report unconfirmed server withdrawal rather than claiming success. No durable event queue or guarantee after page destruction. |
| Erasure | Stop capture, clear browser state/queues, submit erasure while the token is available in memory; only a new explicit grant may start a new subject. Local deletion does not imply server acknowledgement. |
| Restore/BFCache/resume after inactivity | Suspend queued sends and recheck current host permission/server state before capture resumes; previous responses with an older local generation are ignored. |

Proposed storage choice: source-namespaced `sessionStorage` containing only the subject token, granted-state snapshot and a fixed local expiry **at most 24 hours from initial storage**, never extended by activity. Check expiry after local permission before any event; a stricter server expiry always wins. No localStorage, cookies, cross-site sharing or persistent event payloads. Storage failure falls back to memory only and is reported as reduced continuity. sessionStorage survives reloads and can initially be copied from an opener, so do not claim guaranteed visitor/tab isolation; the installation example uses noopener where it creates links [S005-01]. Cross-tab/cross-device identity is not promised.

State is refreshed on resume and at most 60 seconds after the previous confirmed state while collecting; block capture when a refresh is due and unavailable. The server still evaluates every event. This limits stale client capture after a remote withdrawal but cannot promise instantaneous cross-tab revocation; disclose that limit. Consent writes, state reads and erasure use `credentials: omit`, `referrerPolicy: no-referrer` and JSON. No state check renews consent.

## 8. Capture, minimization and transport — proposed

Only `page_view`, `link_click` and constrained `form_submit` are generated by built-in DOM bindings. Lead/purchase signals require separate explicit approved callers and are not inferred from button text or form submission.

- After analytics permission, read URL/referrer; keep only origin for referrer. Apply the existing allowed UTM/click-purpose split, credential/fragment removal, and card/email path/query protections before serialization. Test Python/JavaScript parity with shared synthetic fixtures, including percent encoding and card separators. Do not copy the unmerged 003 long-run implementation follow-up into this branch.
- Read no form value until its selector/name has matched a configured registered field and its DOM descriptor passes never-collect rules. Password/hidden/payment-frame/cc-*/one-time-code fields and unknown controls are excluded first. Then read permitted option/code/quantity values and apply the existing bounds/card rule. No `FormData(form)` over the whole form, arbitrary text, input monitoring or DOM snapshots.
- Track configured link clicks without preventing navigation, blocking form submission or rewriting unrelated page code. SPA page views use an explicit host call in v1; avoid monkey-patching the History API by default.
- Generate UUID event IDs only after consent; preserve the exact sanitized envelope for retries. Never rewrite its timestamp/payload under the same ID. Keep at most 20 sanitized events and 128 KiB in memory, TTL 60 seconds, one event per request and the inherited 16 KiB UTF-8 body bound. Overflow drops the oldest queued event with a local count, no payload log.
- Proposed retry: at most three total attempts, jittered delays around 1 and 4 seconds for network/5xx; honor readable Retry-After on 429/503 only within the 60-second queue TTL. Recheck permission before each send. A 202 ends retries as a generic acknowledgement, not proof of storage. Other 4xx are not retried automatically.
- Prefer fetch with credentials omitted and no referrer; optional keepalive for bounded final sends. Keepalive does not guarantee delivery, and its shared browser budget is not the same as the backend's per-event bound. Do not use sendBeacon as an automatic fallback because the transport needs explicit credential settings and response handling [S005-03, S005-04]. Navigation proceeds if send fails.
- Withdrawal during in-flight requests stops subsequent sends but cannot undo a request already processed; server consent ordering remains authoritative. No raw event body, token, form value or URL in application logs, DOM debug output or error messages.

## 9. Domain ownership, routing and TLS — proposed

An exact canonical hostname is reserved globally to one client. No wildcard host, IP literal, reserved platform hostname or automatic cross-client transfer. A disabled row retains the reservation in 005; reassignment requires a separately reviewed ownership-transfer process. Customer names must support the required CNAME; automatic apex flattening is not assumed.

Issue a 256-bit random challenge for `_tracking-verification.<host>`, bound to the client and challenge generation; store its SHA-256 digest and a proposed 24-hour expiry. Return the raw challenge once in the authorized response, never in logs. Reissue invalidates prior challenges and resets verification. The public CNAME must resolve to an operator-configured service target; CNAME alone is not ownership proof. Do not reuse ACME challenges as application authorization: certificate validation and application tenancy are distinct [S005-06].

Verifier adapter checks the current TXT proof, bounded CNAME chain (maximum 8), approved service target, A/AAAA results, and trusted TLS certificate/hostname/expiry on port 443. Deny non-global addresses and ambiguous/mixed public/private results in the live adapter. Bind the connection to a validated IP with the original hostname for SNI/certificate checks; do not perform an HTTP fetch or follow redirects. OWASP describes why a DNS check followed by a fresh unpinned connection is insufficient [S005-05].

Perform outbound checks outside an open administrative DB transaction. On completion, recheck actor authorization, challenge generation, client/domain state and origin/managed-host conflicts before activating. A stale check cannot reactivate a disabled/reassigned domain. The redirect itself never performs DNS or TLS probes.

Proposed budgets: total verification deadline 5 seconds; maximum five attempts/minute per domain and actor; successful verification valid at most 24 hours and never beyond certificate expiry minus one hour. Failure does not extend a previous deadline; disabling revokes immediately. Redirects fail closed when verification expires. Status exposes closed reasons such as ownership_missing, routing_mismatch, tls_invalid, expired and verification_unavailable, not raw resolver/certificate data.

Propose `dnspython` for bounded TXT/CNAME resolution, using Python's existing ssl/socket facilities for the pinned TLS check. Pin a reviewed compatible release with hashes in the project requirements before implementation; no package is installed by this proposal [S005-09]. Local tests inject DNS/TLS adapters and a test CA/loopback transport; these bypasses must not be available through customer inputs or production configuration. Live network verification stays disabled until an owner-authorized smoke test. Certificate issuance, reverse-proxy routing and deployment belong to the separately approved operational rollout, not to a fake `verified=true` endpoint.

## 10. Review gates and evidence

Use the [decision packet](decision-packet.md) and [verification matrix](verification-matrix.md). All policy numbers in sections 4-9 are proposals for synthetic/local use. Do not interpret initial market or production retention choices from them. Q-001/Q-002/Q-003 stay open where they affect real providers/intake; Q-004/Q-009/Q-012 affect capacity/tooling/retention. They do not block writing the reviewed local design.

No new tests were executed during design preparation. The inherited 481-test run belongs to 004. Implementation must record its own exact tested tree, full backend/integration results, browser/network/storage assertions, schema/grants, lock ordering, parity and static/diff checks. Keep live infrastructure limitations explicit and preserve predecessor items P1-P4.

## Sources checked on 2026-11-10

- S005-01: [MDN sessionStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage) — lifetime, opener-copy and storage-failure behavior.
- S005-02: [MDN Access-Control-Expose-Headers](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Access-Control-Expose-Headers) — readable cross-origin response headers.
- S005-03: [MDN RequestInit](https://developer.mozilla.org/en-US/docs/Web/API/RequestInit) — credentials, referrer and keepalive settings.
- S005-04: [W3C Beacon](https://www.w3.org/TR/beacon/) — delivery limits and using fetch for non-default request settings.
- S005-05: [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) and [redirect guidance](https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html) — allowlists, address validation and redirect boundaries.
- S005-06: [Let's Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/) — domain-control checks for certificate issuance, not tenant ownership policy.
- S005-07: [Node 24 test runner](https://nodejs.org/docs/latest-v24.x/api/test.html) — built-in test tooling; implementation uses APIs supported by the installed Node major.
- S005-08: [Playwright installation](https://playwright.dev/docs/intro) — project-local browser-testing tooling and browser prerequisites.
- S005-09: [dnspython project](https://www.dnspython.org/) and [package metadata](https://pypi.org/project/dnspython/) — TXT/CNAME-capable DNS toolkit; exact version selection remains an implementation dependency review.
