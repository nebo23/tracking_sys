# Managed links, redirects, and the website tracker

Specification 005 (D-033). Applies to local and disposable environments. Native migration of `tracking_sys`, publication, live customer intake, domain purchases, DNS changes, certificate issuance and deployment are separately gated. Read with the [event collection guide](event-collection.md), the [design](../../specs/005-links-tracker/design.md) and the [evidence](../../specs/005-links-tracker/evidence.md).

## Data model and permissions

Migration `0008_links_tracker` adds six client-scoped tables and the nullable `collected_events.link_id`:

| Table | Purpose | Mutable by the runtime |
|---|---|---|
| `link_campaigns` | Immutable client-unique public code (used as `utm_id`) and a display label | label, status |
| `link_content_references` | Opaque external content code with an optional platform label; no content body, credential or proof of platform access | platform label, status |
| `link_utm_templates` | Named UTM parameter set; edits increase `revision` | parameters, revision, status |
| `link_destination_origins` | Exact registered destination origin and its approved static query names | query names, status |
| `link_domains` | Custom short-link hostname reserved globally to one client, with challenge digest and verification state | status and verification columns |
| `managed_links` | Slug, optional domain, issued destination, UTM snapshot, issued target URL and provenance | status, expiry |

All references use composite agency/client foreign keys, so a link, event or campaign of one client can never point at another client's rows. The runtime has no `DELETE` on these tables: slugs and hostnames are never recycled in 005. Configuration is kept for the workspace lifetime (offboarding is 017). Event link references are deleted with their events by erasure and by lifecycle expiry; the lifecycle role received no new privilege.

Owner/Admin members of an active agency manage resources with the browser session, platform Origin and `X-CSRF-Token`. Every mutation writes an audit row with object IDs only. Granted Analyst/ClientViewer members and read service keys can list non-secret metadata; ingest keys and other clients' principals cannot.

Routes under `/agencies/{agency_id}/clients/{client_id}` (paginated lists: `limit` 1-100, default 50; `offset`):

- `link-campaigns`, `link-content-references`, `link-utm-templates`, `link-destination-origins`, `link-domains`, `managed-links`: `POST` creates, `GET` lists, `PATCH /{id}` changes the mutable fields above.
- `POST link-domains/{id}/challenge`: issues a new ownership challenge; the raw value is returned only in this response.
- `POST link-domains/{id}/verify`: runs the DNS/TLS check described below.

## Destinations and UTM rules

- Destination origins are exact HTTPS origins on port 443 with a lowercase IDNA hostname. Credentials, paths, IP literals, wildcards and internal names (`localhost`, `.local`, `.internal`, `.home.arpa` and similar) are refused. `TRACKING_LINK_ALLOW_LOOPBACK_DESTINATIONS=true` permits `http(s)://localhost` or `127.0.0.1` on any port for local development only.
- A link destination must fall under an active registered origin of the same client. It must be printable ASCII with an absolute path, no fragment, no credentials, no dot segments and no ambiguous percent-encoding. Query parameters must be configured static names or the six `utm_*` names, each at most once, with bounded code values. `ts_link` is reserved. Email-like and card-number patterns in the path or values are refused; this is pattern matching, not general personal-data detection.
- Static query names cannot be UTM or click-identifier names, nor names that look like credentials, signatures, sessions, or person or customer identifiers.
- UTM precedence: explicit link values, then the template, then UTM values already in the destination. `utm_id` comes from the campaign code when no input sets it. The issued target appends `ts_link=<link UUID>`, one stable value shared by every visitor of that link.
- The destination, UTM snapshot, target, slug, domain, campaign, content reference and template revision are immutable once issued. Issue a new link to change provenance.

## Redirects

`GET|HEAD /r/{slug}` resolves by the request's `Host` header: a configured platform authority (`TRACKING_LINK_PLATFORM_HOSTS`, exact `host:port` entries) for links without a domain, or a custom domain whose verification is current on `TRACKING_LINK_CUSTOM_DOMAIN_PORT` (443 outside local tests). Forwarded-host headers are ignored; the incoming query string is ignored.

- Success: `302` with the issued target, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, no cookie and no body for `HEAD`.
- Unknown, disabled, expired, out-of-scope or unverified: `404 {"error": "not_found"}`. Other methods: `405`. Storage unavailable: `503` without a fallback destination.
- The redirect writes nothing: no event, counter, cookie, subject, visitor or click row, so telemetry failures cannot affect it and bots or prefetchers are never counted as qualified clicks. It never performs DNS, TLS or HTTP requests.
- Loop prevention: destinations served by the platform itself are refused. Origin registration, domain claims and domain activation share one host-namespace advisory lock and check each other; the redirect also refuses a target that later configuration made a managed host.

## Event provenance and consent-state

EventEnvelope v1 accepts an optional `link_id`. Admission accepts it only for a managed link of the same client (any status, so disabled links keep historical provenance). Unknown or foreign references are rejected with the closed reason `unknown_link` (`422` for trusted senders, the generic `202` for public intake). A present reference is part of the stored content and fingerprint; an absent one keeps the pre-005 fingerprint, so earlier retries still deduplicate. Browser link claims remain limited-trust (rank 1) and are replaced by trusted copies.

`POST /collect/v1/{public_key}/consent-state` with `{"subject_token": "sbj_..."}` (JSON or `text/plain`) returns `status` (`active` or `unknown`), per-purpose `states`, the `expires_at` of each granted purpose and the `server_time`. It issues no token, appends no consent record, renews no expiry and leaves subject activity untouched; missing and erased subjects read the same. It uses its own rate-limit bucket (`TRACKING_CONSENT_STATE_PER_MINUTE`, at most 60 per source and peer). Consent writes (`POST .../consent`, public and trusted) now also return `expires_at` for each granted purpose and `server_time`, an additive response change, so the tracker can apply per-purpose deadlines immediately after a grant. Public CORS now covers this route and exposes `Retry-After` to accepted registered origins only; platform CORS, cookies and CSRF are unchanged.

## Website tracker

The tracker in [packages/tracker-js](../../packages/tracker-js/README.md) (version 0.5.3) is a self-hosted ES module with no runtime dependency. See its README for the consent API (`grant`, `resume`, `withdraw`, `erase`), storage policy, form rules, transport limits and the [installation example](../../packages/tracker-js/examples/install.html). It never contains or needs a private service key. It relies on the consent responses' `expires_at` and `server_time`: a grant without them is not effective in the tracker, and remaining lifetimes are counted from each request's start so that latency never extends them. Newly allowed purposes wait for a current server confirmation, and background state reads need current host permission. Queued consent work checks the host's latest choice again before it reads storage or sends the subject token; a state read that overlaps a consent write is not adopted and is repeated after the pending consent work; and under Global Privacy Control a known subject's sale/share or advertising grant is withdrawn at the collector with a bounded number of attempts per distinct grant, which the tracker identifies by the `expires_at` the collector reports for it.

## Custom domains

1. `POST link-domains` claims a canonical hostname for the client (status `pending`). A hostname used by a destination origin or the platform is refused (`409 host_conflict`); a claimed hostname stays reserved even when disabled.
2. `POST link-domains/{id}/challenge` returns `record_name` (`_tracking-verification.<host>`), `record_value` (`tracking-verification=<256-bit value>`, shown once; only its SHA-256 digest is stored), a 24-hour expiry and the CNAME service target. Reissuing invalidates earlier challenges and verification.
3. The customer publishes the TXT record and a CNAME from the hostname to the operator's service target; the operator separately arranges certificates and routing.
4. `POST link-domains/{id}/verify` checks, within one total five-second deadline shared by every DNS query (including the separate A and AAAA queries), the TCP connection and the TLS handshake: the TXT proof; a CNAME chain of at most eight hops, without loops, reaching the service target; that every A/AAAA answer is a global address; and one TLS handshake to the validated address with the hostname as SNI, a trusted chain, a matching name and at least one hour of validity. No HTTP request is sent and DNS is resolved once, so answers cannot rebind between check and connection. Certificate validation is never treated as proof of tenancy.
5. The network phase runs outside any database transaction. Completion re-authorizes the actor, takes the host-namespace lock and discards the result (`outcome: stale`) if the domain was disabled, its challenge reissued or another check completed meanwhile. Success makes the domain `verified` for at most 24 hours and never later than one hour before certificate expiry; failures record a closed `failure_code` (`ownership_missing`, `routing_mismatch`, `address_not_allowed`, `tls_invalid`, `challenge_expired`, `verification_unavailable`, `host_conflict`) and never extend an earlier deadline. At most five checks per domain and actor per minute. Disabling revokes immediately; redirects fail closed when verification expires.

Live checks use dnspython and Python's `ssl` only when `TRACKING_LINK_DOMAIN_VERIFICATION=live` and `TRACKING_LINK_SERVICE_TARGET` are set; the default `disabled` answers `503 verification_unavailable`. Tests inject synthetic DNS answers, a loopback TLS server with a test-only certificate authority and a loopback address policy in code; no setting or customer input can select them. **No live DNS, certificate, hosting or customer infrastructure has been verified.** A live smoke test needs owner authorization, a real hostname under the owner's control, the configured service target and an operator-provided certificate.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRACKING_LINK_PLATFORM_HOSTS` | `["127.0.0.1:8000","localhost:8000"]` | Exact platform short-link authorities (JSON list); no wildcards. |
| `TRACKING_LINK_ALLOW_LOOPBACK_DESTINATIONS` | `false` | Development only: loopback destination origins. |
| `TRACKING_LINK_CUSTOM_DOMAIN_PORT` | `443` | Port on which custom-domain redirects are served. |
| `TRACKING_LINK_SERVICE_TARGET` | empty | Operator CNAME target for custom domains; stored and compared in canonical lowercase form. |
| `TRACKING_LINK_DOMAIN_VERIFICATION` | `disabled` | `live` enables real DNS/TLS checks (needs the service target). |
| `TRACKING_CONSENT_STATE_PER_MINUTE` | `60` | Consent-state reads per source and peer per minute (maximum 60). |

## Verification commands

From `backend/` against the disposable database (see [local setup](local-environment.md)): `python -m pytest -q -rs` with `TRACKING_RUN_DB_TESTS=1`; add `TRACKING_RUN_BROWSER_TESTS=1` after installing the tracker's browsers to run the end-to-end journey. From `packages/tracker-js/`: `npm ci`, `npm run install:browsers`, `npm test`, `npm run test:browser`.
