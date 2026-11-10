# Event collection
Specification 004 under D-027. Status: implemented and tested on disposable PostgreSQL only. Native tracking_sys has not received migration 0007, and no real customer data may be collected until Q-002, Q-004 and Q-012 are decided. The [design](../../specs/004-event-collection/design.md) holds the reasoning; this guide is the operating view.

## Configuration
Collection routes need two development keyrings in the ignored `.env` (or `.env.docker`). They answer `503 collection_not_configured` while a needed keyring is blank. Production configuration is refused; managed custody follows specification 020.

```powershell
# Token keyring (D-025 local custody): seals webhook signing secrets.
..\.venv\Scripts\python.exe -c "import base64,secrets; print('dev1:' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
# Tombstone keyring: keys erasure tombstones independently of every other secret.
..\.venv\Scripts\python.exe -c "import secrets; print('tomb1:' + secrets.token_hex(32))"
```

Set `TRACKING_TOKEN_KEYRING` / `TRACKING_TOKEN_KEYRING_ACTIVE=dev1` and `TRACKING_TOMBSTONE_KEYRING` / `TRACKING_TOMBSTONE_KEYRING_ACTIVE=tomb1`. Tombstone rotation is add-only: append `,tomb2:<hex>`, make `tomb2` active, and keep `tomb1` for as long as its tombstones exist, because a tombstone cannot be re-keyed without the deleted value. Token keyring rotation follows `token_secrets.rewrap`.

## Who can do what
| Actor | Can | Cannot |
|---|---|---|
| Owner/Admin (browser session) | Create, edit, disable sources; rotate webhook secrets; register forms; request erasure; issue ingest keys | Send events |
| Analyst/ClientViewer with a client grant, or a read key | Read daily counters and event metadata of granted clients | Administer sources or erase |
| Ingest key (`kind: "ingest"`) | Send events and API consent for granted clients | Read anything; carry financial visibility |
| Browser (public key + exact Origin) | Record its own consent, send events for its subject, erase its own subject | Act for another subject; set trusted fields |
| Webhook sender (source secret) | Send signed events for that source's client | Anything else |

Existing service keys are `read` keys. A key's kind is fixed at issuance and cannot be updated, even by the runtime database role.

## Flow
1. An Owner/Admin creates a browser source (`POST /agencies/{a}/clients/{c}/ingestion-sources` with `allowed_origins` and the SHA-256 of the consent notice text) and receives a non-secret `pk_` key. A webhook source returns its `whsec_` signing secret once.
2. The banner records an explicit choice: `POST /collect/v1/{pk}/consent` with `{"choices": {"analytics.first_party": "granted"}}`. The first grant creates a subject and returns its `sbj_` token once; a request granting nothing stores nothing. Trusted servers use `POST /agencies/{a}/clients/{c}/consent` with an ingest key and `notice_sha256`.
3. Events carry that token in an EventEnvelope v1 (one event per request, at most 16 KiB):

```json
{"schema_version": 1, "event_id": "00000000-0000-4000-8000-000000000004",
 "event_type": "page_view", "occurred_at": "2030-01-01T12:00:00Z",
 "subject_token": "sbj_<43 characters>",
 "payload": {"url": "https://shop.example.test/offer?utm_source=demo"}}
```

Public routes take the JSON body as `text/plain` (a CORS simple request, no preflight) or `application/json` (the browser sends a preflight first). Any other or missing media type returns `415 unsupported_media_type`. They read no cookies. A preflight succeeds (204, POST and Content-Type only, 600 seconds, no credentials) only for an Origin registered for that public key's active browser source; any other preflight gets 403. Responses to a registered origin carry `Access-Control-Allow-Origin` for that origin, so the page can read the consent token and error codes. Other origins get no read access, and customer origins never enter the credentialed platform CORS policy. Event routes always answer `202 {"status":"received"}`, whether the event was stored, deduplicated, conflicting, suppressed or rejected for an unknown subject. Trusted and webhook senders receive `201` accepted, `200` duplicate or upgraded, `409 event_conflict`, or `422` with a closed reason code such as `consent_withdrawn`. Retry `429` (with Retry-After), `503` and network failures with the same `event_id`.

Specification 005 adds an optional `link_id` to the envelope: the UUID of a managed link of the same client (the tracker takes it from the landing page's `ts_link`). Unknown or foreign references are rejected as `unknown_link` (generic `202` on public routes). A present reference is part of the stored content and fingerprint; an absent one leaves the earlier fingerprint unchanged. `POST /collect/v1/{pk}/consent-state` with `{"subject_token": ...}` reads the current per-purpose states without issuing tokens, appending records, renewing expiry or refreshing subject activity; missing and erased subjects read as `unknown`. Accepted registered origins can read `Retry-After` (`Access-Control-Expose-Headers`). See the [links and tracker guide](links-and-tracker.md).

Webhook signature: header `X-Tracking-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>` over the bytes `<t>.<raw body>`, within 5 minutes. Each rotation gives the outgoing secret 24 more hours. Every secret verifies until its own expiry, however many rotations happen in that time.

## What is kept
| Input | Kept |
|---|---|
| URLs | Scheme, host, port, path; `utm_*` with analytics; click identifiers (`gclid`, `fbclid`, ...) only when attribution is also granted. A path holding an email-like value or card number rejects the event. A kept query value holding one (also when percent-encoded once more) is removed and counted as `sensitive_query_value`; the rest of the URL is kept. These are recognized patterns, not complete personal-data detection. |
| Referrer | Origin only. |
| Forms | Fields of a registered form mapped to `form.option`, `form.code` or `form.quantity`, after the 003 never-collect and card-number rules. Free text, email, phone, name and address are not collected in 004. |
| Purchase signal | Reference, minor-unit amount and currency, as an unverified claim; never revenue evidence. |
| IP, user agent | Never stored; used transiently for rate limits and bot labels. |

Required consent: `analytics.first_party` for page views, link clicks and form submissions; `attribution` for lead and purchase signals. Admission evaluates current consent under the client lock, so a withdrawal or erasure committed first always wins.

## Erasure and replay
`POST /agencies/{a}/clients/{c}/deletion-requests` with `subject_token` or one of the subject's `event_id` values (Owner/Admin, audited), or `POST /collect/v1/{pk}/erasure` by the token holder, deletes the subject's events, consent records and subject row in one transaction and writes keyed tombstones for the token and every deleted event ID. Afterwards the old token is rejected (`subject_deleted`), re-delivered event IDs are rejected from every channel (`replay_before_deletion`), and new collection needs a new consent grant, which creates an unlinked subject. Tombstones and requests are kept for the workspace lifetime.

## Diagnostics and retention
`GET .../event-diagnostics?start=&end=` returns daily counters by channel, outcome and reason (at most 31 days); `GET .../events/{event_id}` returns metadata without payload or subject. The lifecycle runner (`python -m app.lifecycle`) deletes event rows 395 days after first receipt, counters after 30 days, rotated-out webhook secrets after their overlap, and subjects with their consent records 395 days after last activity once no event references them. Event, consent and subject expiry runs per client under the same client privacy lock as admission, so it never removes consent that an in-flight event relies on. It removes a subject's consent history oldest first per purpose, so a stopped or bounded run never leaves an older grant in force in place of a later withdrawal or denial. The runner cannot read or delete tombstones or erasure requests. See [data lifecycle](data-lifecycle.md).

## Limits
16 KiB body, one event, 32 form fields, 2,048 characters per string and URL, occurred time from 7 days before to 5 minutes after receipt, 60 requests per minute per browser source and peer address, a separate 60 consent-state reads per minute per browser source and peer, 600 per minute per ingest key or webhook source. These are development values, not capacity commitments (Q-004).
