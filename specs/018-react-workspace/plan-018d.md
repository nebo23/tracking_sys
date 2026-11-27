# 018-D plan: links, website tracking and integrations

Prepared: 2026-11-27, under D-100. Status: implemented on 2026-11-27 on `codex/spec-018-workspace-screens`, with the thirty packages of the [018-A plan](plan-018a.md) and no other. The results, the corrections and the differences from this plan are in the [018-D evidence](evidence-018d.md).

## 1. Goal and boundaries
018-D is the last slice of [specification 018](spec.md) before attribution (D14 of the [entry review](entry-review.md)). After it, the people who manage a client can issue the client's short links, set up the website tracker and its forms, see what the collector accepted and refused, erase a visitor on request, and connect the client's payments, bookings, CRM, WhatsApp numbers and Meta conversion destinations, in English and Arabic and in both themes, on the reference styles the owner approved.

In scope:

- The Collect group of the client level (D11): Links, Website tracking and Integrations.
- Links (specification 005): managed links with their campaigns, content references, UTM templates, destination sites and custom domains.
- Website tracking (specifications 004 and 005): browser and webhook sources with the install code, registered forms, daily diagnostics and deletion requests.
- Integrations (specifications 014 and 015): Paymob payment sources, Cal.com and signed webhook sources, CRM stage rules, WhatsApp numbers, and the Meta conversion destinations with their deliveries.

Not in scope:

- Overview, content, revenue and ad spend (018-C): revenue imports, declarations and reconciliation belong there. 018-C needs its own package decision (Recharts).
- Attribution, journeys and identity screens (after 016-B and 006).
- Any change to the API, the contract or the schema, and any new package. The slice needs none.
- Live providers and real data: no call to Paymob, Cal.com or Meta, no DNS change, no real visitor (Q-002, Q-004 and Q-012 stay open).

## 2. What the API already provides
Read from the [contract](../../contracts/openapi.json) at `7f727df`, `backend/app/api/links.py`, `collection.py`, `payments.py`, `integrations.py`, `whatsapp.py`, `advertising.py`, their services, and the guides for [links and the tracker](../../docs/engineering/links-and-tracker.md), [event collection](../../docs/engineering/event-collection.md), [integrations](../../docs/engineering/integrations.md) and the [tracker package](../../packages/tracker-js/README.md).

| Fact | Consequence for the interface |
|---|---|
| Links, campaigns, content references, UTM templates, destination sites and domains are listed page by page (1 to 100, 50 by default) to every reader of the client. Owners and Admins create and change them from a browser session; each change is audited. | Lists are read to the end. Changes are offered to owners and admins only. |
| A link has a slug (3 to 64 lowercase letters, digits and hyphens, starting with a letter or digit, and not one of 19 reserved words), a destination under an active destination site of the client, and optionally a campaign, a content reference, a UTM template, its own UTM values, an expiry and a verified or pending custom domain. Afterwards only its status (`active`, `disabled`) and its expiry change. | The form checks the slug, the site and the values before sending. A link can be paused, resumed and given another expiry; its address never changes. |
| Link rules that fail answer `422 validation_failed` without their reason. A slug already used on the same domain answers `409 state_conflict`. | The interface explains each rule beside its field; the API's refusal gets one general sentence. |
| The issued target is the destination with the template's and the link's UTM values, the campaign code as `utm_id`, and `ts_link` with the link's own identifier. | The address visitors arrive at exists only once the link exists. It is shown from the API's answer. |
| The short link is `GET /r/{slug}` on a platform host or on a verified custom domain, and answers `302` with the issued target. No operation names the platform host (`link_platform_hosts` is a server setting). | The short address uses a public build setting, `VITE_SHORT_LINK_ORIGIN`, that defaults to the API origin. A domain link uses its hostname. |
| A destination site is an exact HTTPS origin with up to 20 static query names to keep. The platform's own host or a claimed custom domain answers `409 host_conflict`. | One sentence for the conflict. |
| A custom domain is claimed (`pending`), gets a TXT challenge whose value is shown once and lasts 24 hours, and is checked: `verified`, `failed` with a closed failure code, or `stale`. Without an enabled verifier the check answers `503 verification_unavailable`; five checks a minute at most. A domain can be turned off and stays reserved. | The challenge is shown once, like a key. Each failure code has a sentence. The development server says that checks are not available. |
| UTM templates: a name and at least one of the six `utm_` parameters with code values (letters, digits, `_`, `.`, `-`, up to 64). A change raises the revision; issued links keep their copy. | |
| Ingestion sources, forms and deletion requests are read and changed by Owners and Admins only. A browser source has 1 to 10 exact origins and the SHA-256 digest of the consent notice its site shows, and gets a non-secret `pk_` key. A webhook source returns its `whsec_` signing secret once; rotating keeps the previous secret for 24 hours. Without the keyrings the API answers `503 collection_not_configured`. | Analysts and client viewers see the diagnostics only. The notice digest is calculated in the browser from the text the person pastes; only the digest is sent. |
| Daily diagnostics: counters by day, channel, outcome and reason over at most 31 days, for every reader of the client. | A table of the last 7 or 30 days, with the accepted and refused totals. No chart in this slice. |
| A deletion request names a visitor by subject token or by one event identifier, optionally with an objection, and deletes the visitor's events, consent records and subject at once. | Asked as an alert that says what is deleted and that it cannot be undone. |
| Paymob sources (Owners and Admins): name, the merchant HMAC secret (written, never returned) and the declared live integration identifiers; the API gives the callback path. `503 payments_unavailable` while the source type is off. | The secret field is write-only. The callback address is the API origin with that path. |
| Integration sources (Owners and Admins): Cal.com takes the secret set in Cal.com; a signed webhook source returns a platform-issued secret once. Each has a callback path and a replaceable secret. `503 integration_unavailable` while a kind is off. Booking totals are readable by every reader. | |
| CRM stage rules (Owners and Admins): pipeline, stage, `won` or `lost`. Deal totals are readable by every reader; amounts need financial access. | Totals only; no amount is requested in this slice. |
| WhatsApp numbers (Owners and Admins): phone number identifier and name. A registration is a pending claim that the platform operator verifies; only a verified number can be turned off or on (`409 verification_required`). `409 number_already_bound`, `503 whatsapp_unavailable`. Referral counts are readable by every reader. | The pending state says who verifies it. |
| Conversion destinations: one per delivery connection (`meta_capi` or its stand-in), created off, with an event name (`Purchase` by default) and an optional test event code. Every reader lists them; Owners and Admins change them. Deliveries carry values and need financial access; a configuration rejection can be requeued, a rejected or undeliverable delivery dismissed. | The deliveries are requested for every reader; a refusal says that financial access is needed. |
| A Meta dataset is connected like any account: `POST .../connections` with provider `meta_capi` and the dataset number as `account`. | The integrations page opens the connect dialog of 018-B with the dataset providers. |

## 3. What the approved screens show that the API cannot supply
The [links screen](../../docs/design/preview/screens/links.html) and the integration cards of the [connections screen](../../docs/design/preview/screens/connections.html) were drawn before the interface was built against the API. No reference screen exists for website tracking; it follows the [design language](../../docs/design/README.md). None of these gaps needs a change to the API.

| Screen | Shown in the design | State of the API | In this slice |
|---|---|---|---|
| Links | A name for each link, such as "Ramadan offer, reel" | No name field | The short address names the link; the destination is shown under it. |
| Links | The address visitors arrive at, while the link is drawn up | No preview; `ts_link` is the new link's identifier | Shown from the API's answer once the link is created, and in each link's details. |
| Links | Tabs Links, Campaigns, UTM templates and Domains | Content references and destination sites have their own operations, and a link needs a site | Two more tabs: Content and Destination sites. |
| Links | "5 of 18 active links" with pages | Paged by offset | Read to the end and filtered in the browser, as in 018-B. |
| Connections | Paymob "Last payment" and "This month: 214 verified, 3 to review" | No count per source | Left out. Revenue arrives with 018-C. |
| Connections | Paymob, Cal.com, WhatsApp and Meta conversions among the connections | Integrations with their own operations | Their own page, Integrations, in the Collect group (D11). |

## 4. How it is built
### 4.1 Addresses
| Address | Screen |
|---|---|
| `/agencies/{agency}/clients/{client}/links` | Links, with a tab in the address (`?tab=campaigns`, `content`, `templates`, `sites`, `domains`) |
| `/agencies/{agency}/clients/{client}/tracking` | Website tracking |
| `/agencies/{agency}/clients/{client}/integrations` | Integrations |

As in 018-B, an address that names a client the person may not read shows the "not found" page; the API decides.

### 4.2 Navigation
The client level gains the Collect group above Manage: Links, Website tracking and Integrations, as D11 orders them. Overview and Analyze follow 018-C. The phone tab bar carries the four client destinations and the account.

### 4.3 Data and the cache
- Every query key of these screens carries the agency and the client, so leaving a client removes them (acceptance criterion 2).
- A secret the API shows once (a webhook signing secret, a signed webhook source secret, a domain's TXT value) lives in the component that shows it while its dialog is open, and nowhere else: not in the query cache, not in storage and not in the address.
- A secret the person types (Paymob HMAC, Cal.com) is sent once and never read back; its field does not offer autofill.
- A mutation refreshes what it changed. Nothing is shown before the API has confirmed it.

### 4.4 Roles
| | Owner, Admin | Analyst | Client viewer |
|---|---|---|---|
| See links, campaigns, content, templates, destination sites and domains | Yes | Granted clients | Granted clients |
| Create or change them, check a domain | Yes | No | No |
| Tracking sources, forms and deletion requests | Yes | Not shown | Not shown |
| Daily diagnostics | Yes | Granted clients | Granted clients |
| Payment, booking and webhook sources, CRM rules, WhatsApp numbers | Yes | Not shown | Not shown |
| Booking, deal and referral counts; conversion destinations | Yes | Granted clients | Granted clients |
| Conversion deliveries with values | Yes | With financial access | With financial access |
| Connect a dataset, change a destination, requeue or dismiss a delivery | Yes | No | No |

### 4.5 States
| What the API reports | Shown as |
|---|---|
| Link `active`, `disabled`, or past its `expires_at` | "Active", "Paused", "Expired" |
| Domain `pending` without a current challenge | "Not verified" and "Get the DNS record" |
| Domain `pending` with a challenge that has not expired | "Waiting for DNS" with the record's expiry |
| Domain `verified` while `verification_expires_at` is ahead | "Verified" with the time it is checked again |
| Domain `verified` past that time, or a `failure_code` | "Check again", with the sentence of the failure code |
| Domain `disabled` | "Turned off" |
| Source, rule or number `active`, `disabled`; number `pending`, `revoked` | "On", "Off", "Waiting for verification", "Revoked" |
| Destination `enabled` | "Sending" or "Off" |
| Delivery `queued`, `sending`, `delivered`, `blocked`, `cancelled`, `expired`, `rejected`, `undeliverable`, `dismissed` | One word and its reason, with the actions the API allows |
| A switched-off integration (`503 ..._unavailable`) | "Not available on this server", without the form |

## 5. Screens of the slice
| Route | Screen | API operations |
|---|---|---|
| `.../links` | Tabs. Links: search, campaign filter, Active and Paused, the table, a panel that creates a link beside the list, copy, pause and resume, expiry. Campaigns, content, templates and sites: lists with create, rename or change, archive or turn off. Domains: claim, the DNS record shown once, check, turn off. | `managed-links`, `link-campaigns`, `link-content-references`, `link-utm-templates`, `link-destination-origins`, `link-domains` with `challenge` and `verify` |
| `.../tracking` | Sources with the install code, a new browser or webhook source, the signing secret shown once and its rotation; forms with their fields; daily diagnostics; deletion requests. | `ingestion-sources`, `collection-forms`, `event-diagnostics`, `deletion-requests` |
| `.../integrations` | Cards for Paymob, Cal.com and signed webhooks, CRM stages, WhatsApp and Meta conversions, each with its state, callback address, totals and actions; deliveries. | `payment-sources`, `integration-sources`, `bookings`, `crm/stage-rules`, `crm/deals`, `whatsapp-numbers`, `whatsapp/referrals`, `conversion-destinations`, `conversion-deliveries`, `connections` |

## 6. Checks that close the slice
| Check | What it proves |
|---|---|
| `tsc --noEmit`, ESLint with the accessibility rules, the contract drift check | As in 018-A. |
| Unit and component tests | Each role sees only its sections and actions; the link form applies the API's slug, site and code rules; the short address is built from the setting and the domain; a secret shown once is in neither the cache nor storage; the notice digest is the SHA-256 of the text; diagnostics never ask for more than 31 days; every new error code has a sentence; each state of section 4.5 is drawn as stated; the data of a client is removed when the person leaves it. |
| Browser journeys in Chromium and Firefox against the real API on the disposable stack | Register a site, a campaign and a template, create a link and follow its short address to the issued target, pause it and see the short address refused; claim a domain and see its record once; set up a browser source and see the install code, a webhook source and its secret once; register a form; send a synthetic event and see it counted; erase that visitor; the integrations that the stack switches on; the roles of an analyst; Arabic, the dark theme and the keyboard. |
| axe-core on every new screen and dialog, both languages and both themes, and at 390 pixels | No finding. |
| The bundle search | No secret, key, token or backend setting (acceptance criterion 5). |
| Removed protections | Each protection of the unit tests fails a test when it is removed. |

Not covered: live providers, a real DNS check, real visitors, screen readers, Safari, real phones and usability with Arabic-speaking users. The journeys never use the owner's `tracking_sys` database (D-015).

## 7. Order of work
Each step ends with its checks and a commit pushed to `codex/spec-018-workspace-screens` (D-051).

1. The Collect group and Links with its six tabs.
2. Website tracking.
3. Integrations.
4. Journeys, accessibility checks, the evidence file and the records.
