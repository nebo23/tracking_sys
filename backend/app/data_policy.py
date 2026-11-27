"""Specification 003 data-class registry (the DataClassPolicy contract) for stored columns.

Classification only: importing or checking this registry deletes, expires, or changes nothing.
Each table records the decision status of its end-of-life rules. No retention period is
approved by this module; candidate periods remain proposals in the specification 003 design
until the owner records a decision (Q-012). A test compares this registry with the SQLAlchemy
metadata and with the migrated database, so a new column cannot be added unclassified.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

# Version of this registry's class meanings. A used class code never changes meaning; a
# changed meaning needs a new code and a reviewed registry version.
POLICY_VERSION = "010-A"


class Sensitivity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Whether values identify a person directly, identify one only with other data held by the
# platform (pseudonymous data is still personal data), or are not about a person.
class Personal(StrEnum):
    DIRECT = "direct"
    PSEUDONYMOUS = "pseudonymous"
    NONE = "none"


# How the value came to exist: supplied by a person, observed by the system, derived from
# other values, or generated system state.
class Provenance(StrEnum):
    PROVIDED = "provided"
    OBSERVED = "observed"
    DERIVED = "derived"
    SYSTEM = "system"


# Decision status of an end-of-life rule. APPROVED rules are backed by a recorded owner
# decision and implemented. PENDING_DECISION rules await a decision; DEFERRED rules are decided
# or owned elsewhere but implemented by a later slice or specification. Neither is in force.
class RuleStatus(StrEnum):
    APPROVED = "approved"
    PENDING_DECISION = "pending_decision"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


# One data class. end_of_life is the proposed action from the design, not enacted behavior.
@dataclass(frozen=True)
class DataClass:
    code: str
    description: str
    sensitivity: Sensitivity
    personal: Personal
    provenance: Provenance
    end_of_life: str
    specification: str


# One end-of-life rule for a whole row ("row") or a single column. reference names the
# decision (D-n), open decision (Q-n or 003-A decision n), or later specification that owns it.
@dataclass(frozen=True)
class EndOfLifeRule:
    target: str
    status: RuleStatus
    reference: str
    description: str


@dataclass(frozen=True)
class TablePolicy:
    columns: Mapping[str, str]
    rules: tuple[EndOfLifeRule, ...]


CLASSES: dict[str, DataClass] = {
    item.code: item
    for item in (
        DataClass(
            "account.identity",
            "Platform-user email address and display name.",
            Sensitivity.HIGH,
            Personal.DIRECT,
            Provenance.PROVIDED,
            "Erase or pseudonymize on account closure (003-A decision 3).",
            "003-A, 017",
        ),
        DataClass(
            "account.reference",
            "Platform-user identifier, account state, and every column referencing a user.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Delete with the referencing row, or keep pointing at a pseudonymized user.",
            "003-A",
        ),
        DataClass(
            "contact.invitee",
            "Invitee email entered by an inviter; the person may never register.",
            Sensitivity.HIGH,
            Personal.DIRECT,
            Provenance.PROVIDED,
            "Delete with the ended invitation (003-A decision 2).",
            "003-A",
        ),
        DataClass(
            "credential.secret_verifier",
            "Argon2 password hashes and keyed verification-code verifiers.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Replace on change; delete on account closure.",
            "003-A",
        ),
        DataClass(
            "credential.token_digest",
            "SHA-256 digests of random session, link, key, OAuth state, and binding tokens.",
            Sensitivity.HIGH,
            Personal.NONE,
            Provenance.DERIVED,
            "Delete with the ended credential row.",
            "003-A",
        ),
        DataClass(
            "credential.lifecycle",
            "Creation, activity, expiry, consumption, revocation, and attempt state of "
            "credentials, sessions, challenges, and OAuth transactions.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Delete with the ended credential row.",
            "003-A",
        ),
        DataClass(
            "identity.external_subject",
            "Validated external sign-in issuer and subject (a stable provider identifier).",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Delete on unlinking or account erasure (003-A decision 3).",
            "003-A",
        ),
        DataClass(
            "security.telemetry",
            "Authentication event codes and keyed rate-limit buckets over IPs and emails.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Delete after the approved period (Q-012).",
            "003-A",
        ),
        DataClass(
            "message.transactional",
            "Encrypted queued message: recipient, verification code, or link with a raw token.",
            Sensitivity.HIGH,
            Personal.DIRECT,
            Provenance.DERIVED,
            "Clear after delivery or expiry.",
            "002 (D-019, D-022), 003-A",
        ),
        DataClass(
            "message.delivery_state",
            "Outbox purpose, attempts, schedule, delivery time, and sanitized failure code.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Delete after the approved period (Q-012).",
            "003-A",
        ),
        DataClass(
            "tenancy.label",
            "Free-text agency, client, and service-credential names; may name a person.",
            Sensitivity.MEDIUM,
            Personal.DIRECT,
            Provenance.PROVIDED,
            "Deleted or, for an agency, replaced by a pseudonym in the purge of a closed agency "
            "(017-B); client offboarding without closing the agency is undecided.",
            "017",
        ),
        DataClass(
            "tenancy.configuration",
            "Tenant identifiers, roles, statuses, grants, and their timestamps.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Deleted by the purge of a closed agency (017-B), which keeps the agency row and its "
            "plan history (D-098 D8); client offboarding without closing the agency is undecided.",
            "017",
        ),
        DataClass(
            "audit.administrative",
            "Append-only tenant mutation record: identifiers and action codes only.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Delete after the approved period; actor follows account erasure (decision 3).",
            "003-A",
        ),
        DataClass(
            "credential.sealed_secret",
            "AES-GCM sealed webhook signing secret with its wrapped data key and key ID.",
            Sensitivity.HIGH,
            Personal.NONE,
            Provenance.DERIVED,
            "Delete after rotation overlap or with the source (D-027).",
            "004",
        ),
        DataClass(
            "collection.subject",
            "Opaque collection subject: identifier, bearer-token digest, and activity times.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Delete on erasure or after inactivity (D-027).",
            "004",
        ),
        DataClass(
            "consent.record",
            "Consent choices of a subject: purpose, state, source, profile, policy and notice "
            "digests, and times.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.PROVIDED,
            "Delete with the subject (D-027).",
            "004",
        ),
        DataClass(
            "event.content",
            "Sanitized event content: minimized URLs, mapped form values, lead actions, "
            "purchase claims, occurred time, fingerprint, and consent basis.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Delete after the approved period or on erasure (D-027).",
            "004",
        ),
        DataClass(
            "event.delivery_state",
            "Event identity and processing state: event ID, type, channel, trust, revision, "
            "receipt times, conflict counters, traffic label, policy version, and expiry.",
            Sensitivity.LOW,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Delete with the event row (D-027).",
            "004",
        ),
        DataClass(
            "event.diagnostic_count",
            "Daily outcome counters by channel and closed reason code.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Delete after the approved period (D-027).",
            "004",
        ),
        DataClass(
            "deletion.request",
            "Erasure request state and per-store outcomes; no identifier of the subject.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Keep for the workspace lifetime (D-027).",
            "004, 017",
        ),
        DataClass(
            "deletion.tombstone",
            "Keyed match values that block reuse and replay after erasure.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Keep for the workspace lifetime (D-025, D-027).",
            "004, 017",
        ),
        DataClass(
            "link.configuration",
            "Managed-link business configuration: campaign and content codes, UTM templates, "
            "destination origins and static query names, custom hostnames, slugs, issued "
            "destinations, UTM snapshots and targets, link references, statuses, and expiry.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.PROVIDED,
            "Keep for the workspace lifetime to preserve provenance and unrecycled slugs "
            "(D-033), until the purge of a closed agency (017-B).",
            "005, 017",
        ),
        DataClass(
            "link.label",
            "Free-text campaign labels, content platform labels, and template names; may name "
            "a person.",
            Sensitivity.MEDIUM,
            Personal.DIRECT,
            Provenance.PROVIDED,
            "Deleted with the client workspace by the purge of a closed agency (017-B).",
            "005, 017",
        ),
        DataClass(
            "domain.verification",
            "Custom-domain ownership challenge digest, generation, expiry, verification times, "
            "observed certificate expiry, closed failure code, and version.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.SYSTEM,
            "Replaced on each challenge or check; kept with the domain (D-033).",
            "005",
        ),
        DataClass(
            "connector.sealed_token",
            "AES-GCM sealed OAuth access and refresh tokens of a client connection with their "
            "wrapped data keys, nonces, and key ID.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Revoke at the provider, then destroy the material on disconnect, replacement, or "
            "reconnect (D-048).",
            "009",
        ),
        DataClass(
            "connector.token_state",
            "Kind, version, status, provider revocation outcome, expiry, refresh, and "
            "destruction times of a sealed token version.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept with the connection as evidence of destruction (D-048).",
            "009",
        ),
        DataClass(
            "connector.account_reference",
            "Provider external account identifier, display label, and account kind of a "
            "connection; may identify a person.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Cleared by the disconnect purge (D-048).",
            "009",
        ),
        DataClass(
            "connector.lifecycle",
            "Connection provider, status, reason, generation, scopes, outcome, deadline, and "
            "timing state, and sync-run state; no provider data.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept for the workspace lifetime, until the purge of a closed agency (017-B). Run "
            "retention is Q-012.",
            "009, 017",
        ),
        DataClass(
            "connector.provider_data",
            "Provider object identifiers and observed metrics fetched through a connection, "
            "with the run and adapter version that stored them.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Purged on disconnect (D-048); per-provider retention is 010-013.",
            "009, 010-013",
        ),
        DataClass(
            "connector.sync_state",
            "Opaque provider cursor of the next page of a running synchronization and the "
            "coverage watermarks of a connection's stream.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.OBSERVED,
            "Deleted by the disconnect purge (D-049).",
            "009",
        ),
        DataClass(
            "connector.usage",
            "Provider data call counts in the provider's cost unit with operation, outcome, "
            "attempt, and UTC day; no provider data.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept with run history; retention awaits Q-012 (D-049).",
            "009",
        ),
        DataClass(
            "connector.webhook_delivery",
            "SHA-256 digest of a provider webhook event ID with its provider, receipt time, and "
            "number of connections notified; no payload or account.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Deleted 7 days after receipt (D-049).",
            "009",
        ),
        DataClass(
            "connector.deletion_request",
            "A provider data deletion request: provider, random confirmation code, receipt and "
            "completion times, and the number of connections it stopped; no account or tenant.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept as deletion evidence; retention awaits Q-012 (D-053).",
            "010",
        ),
        DataClass(
            "advertising.account",
            "Ad account of a spend connection: account ID, name, currency, time zone, status, "
            "and the previous currency or time zone with the time of the change.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.OBSERVED,
            "Purged when the connection's disconnect completes (D-064 D13).",
            "014",
        ),
        DataClass(
            "advertising.object",
            "Campaigns, ad sets and ads of a spend connection: IDs, parents, names and "
            "effective statuses; advertiser business data, not personal data.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.OBSERVED,
            "Purged when the connection's disconnect completes (D-064 D13).",
            "014",
        ),
        DataClass(
            "advertising.spend",
            "Daily ad-level spend in exact minor units of the reported currency, impressions "
            "and clicks, with refusals, revisions, provisional marking and provenance.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.OBSERVED,
            "Purged at disconnect; deleted 730 days after the spend date (D-064 D13).",
            "014",
        ),
        DataClass(
            "advertising.destination",
            "Conversion destination of a delivery connection: event name, optional test event "
            "code, enabled flag, creator and times; no person data.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept until deleted; disabled when its connection's disconnect completes (D-064 D13).",
            "014",
        ),
        DataClass(
            "advertising.delivery_state",
            "Delivery of one verified sale: deterministic event ID, event name, action source, "
            "event time, deadline, value and currency, state, closed reason, counters, schedule, "
            "consent basis record IDs and policy version; no match key or subject reference.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Deleted 30 days after the delivery ends (D-064 D13).",
            "014",
        ),
        DataClass(
            "advertising.sealed_payload",
            "AES-GCM sealed delivery payload (fbc match key, subject references and replay keys) "
            "with its wrapped data key and key ID.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Destroyed when the delivery ends (D-064 D9, D13).",
            "014",
        ),
        DataClass(
            "advertising.acknowledgement",
            "Provider answer to one delivery attempt: time, outcome class, closed provider code, "
            "events received and the provider trace ID, which is never returned or logged.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.OBSERVED,
            "Deleted with its delivery, 30 days after the delivery ends (D-064 D13).",
            "014",
        ),
        DataClass(
            "revenue.evidence",
            "Received revenue evidence of one client: delivery and operation IDs, source "
            "account, kind, evidence class, amount in minor units and currency, effective and "
            "receipt times, parent operation, intake provenance, content digest and, for "
            "declarations, the reason and source reference; no card, billing, shipping or "
            "customer data (D-067 D6).",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Kept for the life of the client workspace; legal retention pending Q-012 and Q-003 "
            "(D-067 D14).",
            "015",
        ),
        DataClass(
            "payment.source",
            "Paymob payment source of one client: provider, region, name, status, the public key "
            "of its callback URL, creator and times; no card or customer data.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept with the client workspace; disabled to stop intake (D-067 D14).",
            "015",
        ),
        DataClass(
            "payment.callback_diagnostic",
            "One verified Paymob callback: source, a digest of the received signature, receipt "
            "time and a closed outcome and reason; no payload.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.OBSERVED,
            "Deleted 30 days after receipt (D-067 D14).",
            "015",
        ),
        DataClass(
            "revenue.import_record",
            "One committed transaction CSV file: the file's SHA-256 digest, row counts, the "
            "committing membership and the commit time; the file itself is never kept.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Deleted 13 months (395 days) after the commit (D-067 D14).",
            "015",
        ),
        DataClass(
            "integration.source",
            "Integration source of one client: kind, name, status, the public key of its callback "
            "URL, creator and times; no provider data.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept with the client workspace; disabled to stop intake (D-068).",
            "015",
        ),
        DataClass(
            "integration.delivery",
            "One verified integration delivery: source, a digest of the body, receipt time and a "
            "closed outcome and reason; no payload.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.OBSERVED,
            "Deleted 30 days after receipt (D-068 E9).",
            "015",
        ),
        DataClass(
            "booking.record",
            "One booking chain and its minimal events: provider booking IDs, event type, schedule, "
            "status, reschedule count and times; no attendee, answer, note or meeting link.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Deleted 395 days after the last update (D-068 E9).",
            "015",
        ),
        DataClass(
            "crm.rule",
            "An approved won or lost stage of one client's CRM pipeline, with creator and times.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept with the client workspace.",
            "015",
        ),
        DataClass(
            "crm.deal",
            "The latest known stage of one CRM deal: deal ID, pipeline, stages, stage time, an "
            "optional amount and payment reference; no contact, name or note.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Deleted 395 days after the last update (D-068 E9).",
            "015",
        ),
        DataClass(
            "whatsapp.number",
            "A registered WhatsApp Business phone number ID of one client (a business number), "
            "with name, status, creator and times.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept with the client workspace; disabled to stop intake (D-068).",
            "015",
        ),
        DataClass(
            "whatsapp.referral",
            "One inbound WhatsApp message: a digest of its ID, its times and only its "
            "Click-to-WhatsApp referral (source type, ad ID, click-ID presence); no person data.",
            Sensitivity.LOW,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Deleted 395 days after receipt (D-068 E9).",
            "015",
        ),
        DataClass(
            "identity.pseudonym",
            "Keyed identifier of one verified email address, phone number or client account "
            "reference (HMAC under a per-client key), with kind, normalizer, status and "
            "verification method; never the value.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Deleted with its owning person; a contested key 395 days after last verification "
            "(D-075, design section 12.5).",
            "006",
        ),
        DataClass(
            "identity.link",
            "Assertion evidence and segments that associate a collection subject with a person.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.OBSERVED,
            "Deleted with its collection subject, at withdrawal (W1), on erasure, or 395 days "
            "after receipt (D-075).",
            "006",
        ),
        DataClass(
            "identity.receipt",
            "Public retry receipt: the sender's assertion ID, a keyed fingerprint and its window.",
            Sensitivity.LOW,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Purged after its 24-hour window (D-075).",
            "006",
        ),
        DataClass(
            "identity.profile",
            "A client-scoped person record without identifier values: status, merge pointer, "
            "counters and evidence times.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Deleted when no key or link remains, or 395 days after the last evidence (D-075).",
            "006",
        ),
        DataClass(
            "identity.correction",
            "Merge ledger entries and their versions, reason codes and recorded results.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Active edges while both participants exist; closed entries 2 years after reversal "
            "or closure, or earlier erasure (D-075).",
            "006",
        ),
        DataClass(
            "identity.change",
            "Per-client change records (person ID, kind, revision, time) and feed watermarks.",
            Sensitivity.LOW,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Change records 30 days; the feed state lives with the client workspace (D-075).",
            "006",
        ),
        DataClass(
            "deletion.hold",
            "One event held by one erasure request, and the settlement of that hold.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Held until settled; settled rows keep no event reference and are deleted 30 days "
            "after their request completes (D-075).",
            "006",
        ),
        DataClass(
            "revenue.ledger",
            "Persisted receipts, signed movements, transaction projections and reconciliation "
            "reviews derived from revenue evidence, in minor units of the original currency; no "
            "person, identity key or contact data.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.DERIVED,
            "Kept with its evidence for the client workspace lifetime (D-075, D-067 D14).",
            "007",
        ),
        DataClass(
            "attribution.model",
            "Per-client attribution model versions: model, lookback window, rule set, default "
            "flag, retirement and the idempotency record of their administration.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept for the client workspace lifetime with the credit history it explains "
            "(D-079 D3, D12).",
            "008",
        ),
        DataClass(
            "attribution.credit",
            "Non-identifying stored attribution: conversion kinds and statuses, revisions, "
            "causes, exact shares, amounts in minor units of the original currency, reporting "
            "dates and campaign, content, link and source provenance.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.DERIVED,
            "Kept for the client workspace lifetime under the financial policy; failed staging "
            "rows are discarded (D-079 D12).",
            "008",
        ),
        DataClass(
            "attribution.pointer",
            "Identity person, lead event and touchpoint (collected event) references of stored "
            "attribution rows, and the keys derived from them; never a contact value, token or "
            "raw identifier.",
            Sensitivity.HIGH,
            Personal.PSEUDONYMOUS,
            Provenance.DERIVED,
            "Scrubbed with the person or its evidence: erasure, expiry (395 days) or deletion "
            "of the person (D-079 D9, D12).",
            "008",
        ),
        DataClass(
            "attribution.state",
            "Per-client attribution consumer state: published generation, checkpoint over the "
            "ledger journal and the identity feed, unit of work and counters.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept for the client workspace lifetime (D-079).",
            "008",
        ),
        DataClass(
            "plan.definition",
            "Platform plan definitions: key, internal name, the five limits, the default flag, "
            "a closed reason code and the creation time; never about a person.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Never deleted: plans are immutable and referenced by assignment history (D-092 D2).",
            "017-A",
        ),
        DataClass(
            "plan.assignment",
            "Plan assignment history of an agency: revision, plan, time, assigning party and a "
            "closed reason code.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept with the agency, also after the purge of a closed agency (D-098 D8).",
            "017-A",
        ),
        DataClass(
            "agency.closure",
            "Closure requests of an agency: the requesting and cancelling memberships and the "
            "request, scheduled closing, cancellation and completion times.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Kept with the agency; the purge of a closed agency deletes it (D-098).",
            "017-A",
        ),
        DataClass(
            "account.agreement",
            "Agreement of an account to one version of the Terms of Service or the Privacy "
            "Policy: document, version label, time and channel, and the versions a sign-in "
            "transaction carries.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.PROVIDED,
            "Deleted with a closed account's credential state (D-024), unless legal advice "
            "requires keeping proof of agreement (Q-012).",
            "017-A",
        ),
        DataClass(
            "report.export",
            "Metadata of a retained report export: family, normalized parameters, period, "
            "source, state, revocation reason, times, sizes, report revision and download "
            "count; references to the client, connection, schedule and requesting membership.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.SYSTEM,
            "Deleted by the lifecycle runner when the export expires, 7 days after creation "
            "(D-095).",
            "016-C",
        ),
        DataClass(
            "report.export_content",
            "Sealed CSV of a ready export (AES-GCM under the token keyring, bound to the "
            "export, agency and client); it may hold financial figures.",
            Sensitivity.HIGH,
            Personal.NONE,
            Provenance.DERIVED,
            "Deleted at once on revocation and by the lifecycle runner at expiry (D-095).",
            "016-C",
        ),
        DataClass(
            "report.schedule",
            "Report schedule of a client: the manager-entered name, family and parameters, "
            "cadence, hour, time zone, state, owner membership and the last run's outcome "
            "codes and counts.",
            Sensitivity.MEDIUM,
            Personal.NONE,
            Provenance.PROVIDED,
            "Deleted by a manager; otherwise kept with the client workspace.",
            "016-C",
        ),
        DataClass(
            "report.recipient",
            "Membership that receives a schedule's report notifications.",
            Sensitivity.LOW,
            Personal.PSEUDONYMOUS,
            Provenance.PROVIDED,
            "Deleted when the recipient leaves, is replaced or the schedule is deleted.",
            "016-C",
        ),
        DataClass(
            "branding.profile",
            "Agency branding profile: the display name its clients see, an accent color, an "
            "optional PNG logo with its dimensions, and the last change.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.PROVIDED,
            "Kept with the agency; deleted by the purge of a closed agency (D-098).",
            "016-C",
        ),
        DataClass(
            "agency.export",
            "Metadata of an agency's offboarding export: state, closed error code, the request, "
            "ready, revocation and expiry times, part count, size, row counts by file path "
            "(client IDs and table names), the manifest digest and the download count; "
            "references to the agency and the requesting membership.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Kept with the agency until the purge of the closed agency (D-098 D5, D8).",
            "017-B",
        ),
        DataClass(
            "agency.export_content",
            "Sealed parts of an offboarding ZIP (AES-GCM under the token keyring, bound to the "
            "agency, the export and the part number); they hold every client's first-party data, "
            "names and personal data included.",
            Sensitivity.HIGH,
            Personal.DIRECT,
            Provenance.DERIVED,
            "Deleted at revocation, by the lifecycle runner at the export's expiry 7 days after "
            "the request, and by the purge (D-098 D5).",
            "017-B",
        ),
        DataClass(
            "agency.purge",
            "Purge record of a closed agency: the copied closure times, the export summary, the "
            "offboarding, teardown and purge times, the state and the deleted row count of each "
            "table; never a name, a client ID or a figure.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "Kept after the purge as the minimal record of the closed agency (D-098 D8).",
            "017-B",
        ),
        DataClass(
            "system.schema_version",
            "Migration revision marker.",
            Sensitivity.LOW,
            Personal.NONE,
            Provenance.SYSTEM,
            "None; replaced by migrations.",
            "001",
        ),
    )
}

PENDING = RuleStatus.PENDING_DECISION
RETENTION = "Q-012; 003-A decision 2"
APPROVED = RuleStatus.APPROVED


def _row(status: RuleStatus, reference: str, description: str) -> EndOfLifeRule:
    return EndOfLifeRule("row", status, reference, description)


def _same(code: str, *columns: str) -> dict[str, str]:
    return dict.fromkeys(columns, code)


# 008-B (D-079 D9, D12): the end-of-life rule of the four attribution history tables.
ATTRIBUTION_RULE = _row(
    APPROVED,
    "D-079",
    "Person, lead event and touchpoint pointers are scrubbed (D9) in the transaction "
    "that erases, expires or deletes the person or its evidence; the non-identifying "
    "record is kept for the workspace lifetime, and rows of a failed staging generation "
    "are deleted by tracking_lifecycle (D12).",
)


TABLES: dict[str, TablePolicy] = {
    "users": TablePolicy(
        {
            **_same("account.identity", "email_normalized", "display_name"),
            **_same(
                "account.reference",
                "id",
                "status",
                "email_verified_at",
                "closed_at",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-024",
                "Self-service closure replaces the email and name with pseudonyms, disables the "
                "account, and keeps the row for audit references. Unverified registrations "
                "remain pending (Q-012).",
            ),
        ),
    ),
    "password_credentials": TablePolicy(
        {
            "user_id": "account.reference",
            "password_hash": "credential.secret_verifier",
            "changed_at": "credential.lifecycle",
        },
        (
            _row(
                APPROVED,
                "D-024",
                "Hash replaced on change or reset; deleted by the lifecycle runner after "
                "account closure.",
            ),
        ),
    ),
    "auth_sessions": TablePolicy(
        {
            "user_id": "account.reference",
            "token_digest": "credential.token_digest",
            **_same(
                "credential.lifecycle",
                "id",
                "created_at",
                "last_seen_at",
                "expires_at",
                "revoked_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-024",
                "Deleted by the lifecycle runner 30 days after revocation, absolute expiry, or "
                "idle expiry.",
            ),
        ),
    ),
    "auth_tokens": TablePolicy(
        {
            "user_id": "account.reference",
            "token_digest": "credential.token_digest",
            **_same(
                "credential.lifecycle", "id", "purpose", "created_at", "expires_at", "consumed_at"
            ),
        },
        (_row(APPROVED, "D-024", "Deleted 7 days after consumption or expiry."),),
    ),
    "verification_challenges": TablePolicy(
        {
            "user_id": "account.reference",
            "verifier": "credential.secret_verifier",
            **_same(
                "credential.lifecycle",
                "id",
                "purpose",
                "failed_attempts",
                "created_at",
                "expires_at",
                "consumed_at",
                "invalidated_at",
            ),
        },
        (_row(APPROVED, "D-024", "Deleted 7 days after consumption, invalidation, or expiry."),),
    ),
    "oauth_transactions": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("credential.token_digest", "state_digest", "binding_digest"),
            **_same(
                "credential.lifecycle", "id", "purpose", "created_at", "expires_at", "consumed_at"
            ),
            **_same("account.agreement", "terms_version", "privacy_version"),
        },
        (_row(APPROVED, "D-024", "Deleted 1 day after consumption or expiry."),),
    ),
    "external_identities": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("identity.external_subject", "provider", "issuer", "subject"),
            **_same("credential.lifecycle", "id", "created_at", "last_login_at"),
        },
        (
            _row(
                APPROVED,
                "D-024",
                "Kept while linked; deleted by the lifecycle runner after account closure, which "
                "frees the Google subject. Unlinking without closure is not offered.",
            ),
        ),
    ),
    "auth_rate_limits": TablePolicy(
        _same("security.telemetry", "bucket_key", "attempts", "expires_at"),
        (_row(APPROVED, "D-024", "Deleted at window expiry; an expired bucket restarts anyway."),),
    ),
    "security_events": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("security.telemetry", "id", "action", "occurred_at"),
        },
        (_row(PENDING, RETENTION, "Append-only for the runtime; kept indefinitely."),),
    ),
    "mail_outbox": TablePolicy(
        {
            "encrypted_payload": "message.transactional",
            **_same(
                "message.delivery_state",
                "id",
                "purpose",
                "created_at",
                "attempts",
                "next_attempt_at",
                "delivered_at",
                "failure_code",
                "expires_at",
            ),
        },
        (
            EndOfLifeRule(
                "encrypted_payload",
                APPROVED,
                "D-019; D-022; D-024",
                "Cleared after confirmed delivery, or unsent at expires_at, which every new "
                "message carries for its verification code or reset or invitation link.",
            ),
            _row(
                APPROVED,
                "D-024",
                "Deleted 30 days after delivery or expiry. Rows queued without expires_at before "
                "D-024 remain until delivered.",
            ),
        ),
    ),
    "agency_invitations": TablePolicy(
        {
            "email_normalized": "contact.invitee",
            "token_digest": "credential.token_digest",
            "accepted_by_user_id": "account.reference",
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "inviter_membership_id",
                "role",
                "status",
                "expires_at",
                "created_at",
                "updated_at",
            ),
        },
        (_row(PENDING, RETENTION, "Accepted, revoked, and expired-pending invitations stay."),),
    ),
    "invitation_client_grants": TablePolicy(
        _same(
            "tenancy.configuration",
            "agency_id",
            "invitation_id",
            "client_id",
            "can_view_financials",
            "can_view_identities",
        ),
        (_row(PENDING, RETENTION, "Follow their invitation."),),
    ),
    "service_credentials": TablePolicy(
        {
            "name": "tenancy.label",
            "token_digest": "credential.token_digest",
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "creator_membership_id",
                "kind",
                "expires_at",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (_row(PENDING, RETENTION, "Revoked and expired credentials stay."),),
    ),
    "service_client_grants": TablePolicy(
        _same(
            "tenancy.configuration",
            "agency_id",
            "credential_id",
            "client_id",
            "can_view_financials",
        ),
        (_row(PENDING, RETENTION, "Follow their service credential."),),
    ),
    "agencies": TablePolicy(
        {
            "name": "tenancy.label",
            **_same(
                "tenancy.configuration", "id", "status", "created_at", "updated_at", "purged_at"
            ),
        },
        (
            _row(
                APPROVED,
                "D-092; D-098",
                "Closure moves an agency to closing and then closed (017-A); the purge "
                "keeps the row with status closed, a pseudonymous name and purged_at "
                "(017-B, D8).",
            ),
        ),
    ),
    "client_workspaces": TablePolicy(
        {
            "name": "tenancy.label",
            **_same(
                "tenancy.configuration", "id", "agency_id", "status", "created_at", "updated_at"
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017",
                "Archiving is reversible; deleting one client without closing its agency "
                "is undecided.",
            ),
        ),
    ),
    "agency_memberships": TablePolicy(
        {
            "user_id": "account.reference",
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "role",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-024",
                "Disabled, never deleted while the agency exists, including on account "
                "closure (D-024).",
            ),
        ),
    ),
    "client_grants": TablePolicy(
        _same(
            "tenancy.configuration",
            "agency_id",
            "client_id",
            "membership_id",
            "can_view_financials",
            "can_view_identities",
        ),
        (_row(RuleStatus.APPROVED, "D-017", "Deleted when the grant is revoked (002-A)."),),
    ),
    "audit_events": TablePolicy(
        {
            "actor_user_id": "account.reference",
            **_same(
                "audit.administrative",
                "id",
                "agency_id",
                "client_id",
                "actor_kind",
                "action",
                "resource_type",
                "resource_id",
                "occurred_at",
            ),
        },
        (
            _row(
                PENDING,
                f"{RETENTION}; D-024",
                "Append-only; kept indefinitely (retention pending). After closure the actor ID "
                "points to the pseudonymized user (D-024).",
            ),
        ),
    ),
    # Specification 004 (D-027): provisional development periods; Q-012 stays open for real
    # customer intake.
    "ingestion_sources": TablePolicy(
        {
            "name": "tenancy.label",
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "creator_membership_id",
                "kind",
                "status",
                "public_key",
                "allowed_origins",
                "notice_sha256",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-027",
                "Kept while the client exists; disabling keeps the row.",
            ),
        ),
    ),
    "ingestion_source_secrets": TablePolicy(
        {
            **_same(
                "credential.sealed_secret",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same("credential.lifecycle", "version", "created_at", "retires_at"),
        },
        (
            _row(
                APPROVED,
                "D-027",
                "A rotated-out version is deleted by the lifecycle runner once retires_at "
                "(24 hours after rotation) has passed; the current version stays with its source.",
            ),
        ),
    ),
    "collection_forms": TablePolicy(
        _same(
            "tenancy.configuration",
            "id",
            "agency_id",
            "client_id",
            "form_key",
            "version",
            "fields",
            "status",
            "created_at",
            "updated_at",
        ),
        (_row(RuleStatus.DEFERRED, "017; D-027", "Kept while the client exists."),),
    ),
    "collection_subjects": TablePolicy(
        _same(
            "collection.subject",
            "id",
            "agency_id",
            "client_id",
            "token_digest",
            "created_at",
            "last_activity_at",
            "issuance_channel",
            "identity_floor_at",
            "identity_shared_at",
        ),
        (
            _row(
                APPROVED,
                "D-027; D-075",
                "Deleted on erasure, or by the lifecycle runner 395 days after last activity "
                "once no event row references it.",
            ),
        ),
    ),
    "consent_records": TablePolicy(
        _same(
            "consent.record",
            "id",
            "agency_id",
            "client_id",
            "subject_id",
            "purpose",
            "state",
            "source",
            "jurisdiction_profile",
            "policy_version",
            "notice_sha256",
            "received_at",
            "captured_at",
            "expires_at",
            "supersedes_id",
        ),
        (
            _row(
                APPROVED,
                "D-027",
                "Never updated; deleted with their subject (erasure or inactivity). A grant is "
                "evaluated as expired 365 days after receipt.",
            ),
        ),
    ),
    "collected_events": TablePolicy(
        {
            **_same(
                "event.content",
                "occurred_at",
                "payload",
                "fingerprint",
                "consent_basis",
                "subject_id",
            ),
            **_same(
                "event.delivery_state",
                "id",
                "agency_id",
                "client_id",
                "event_id",
                "event_type",
                "channel",
                "source_id",
                "credential_id",
                "trust_rank",
                "first_received_at",
                "last_received_at",
                "revision",
                "traffic_label",
                "policy_version",
                "conflict_count",
                "last_conflict_at",
                "expires_at",
            ),
            "link_id": "event.content",
            "identity_excluded_at": "event.delivery_state",
        },
        (
            _row(
                APPROVED,
                "D-027; D-033; D-075",
                "Deleted by the lifecycle runner 395 days after first receipt (expires_at), or "
                "on erasure, with any link reference. Purchase claims are readable only with "
                "financial access.",
            ),
        ),
    ),
    "event_diagnostics": TablePolicy(
        _same(
            "event.diagnostic_count",
            "id",
            "agency_id",
            "client_id",
            "day",
            "channel",
            "outcome",
            "reason",
            "count",
        ),
        (_row(APPROVED, "D-027", "Deleted by the lifecycle runner 30 days after their day."),),
    ),
    "deletion_requests": TablePolicy(
        {
            "requested_by_user_id": "account.reference",
            **_same(
                "deletion.request",
                "id",
                "agency_id",
                "client_id",
                "requester_kind",
                "scope_kind",
                "status",
                "objected",
                "received_at",
                "completed_at",
                "target_outcomes",
            ),
        },
        (
            _row(
                APPROVED,
                "D-027",
                "Kept for the workspace lifetime as the record of erasure.",
            ),
        ),
    ),
    "deletion_tombstones": TablePolicy(
        _same(
            "deletion.tombstone",
            "id",
            "agency_id",
            "client_id",
            "deletion_request_id",
            "scope_kind",
            "match_type",
            "match_key",
            "match_key_id",
            "effective_at",
            "objected",
        ),
        (
            _row(
                APPROVED,
                "D-025; D-027",
                "Insert-only for the runtime and unreachable by the lifecycle role; kept for "
                "the workspace lifetime.",
            ),
        ),
    ),
    "link_campaigns": TablePolicy(
        {
            "label": "link.label",
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "public_code",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, "
                "slugs, and hostnames are not recycled while the workspace exists.",
            ),
        ),
    ),
    "link_content_references": TablePolicy(
        {
            "platform_label": "link.label",
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "external_code",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, "
                "slugs, and hostnames are not recycled while the workspace exists.",
            ),
        ),
    ),
    "link_utm_templates": TablePolicy(
        {
            "name": "link.label",
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "parameters",
                "revision",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, "
                "slugs, and hostnames are not recycled while the workspace exists.",
            ),
        ),
    ),
    "link_destination_origins": TablePolicy(
        {
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "origin",
                "hostname",
                "query_names",
                "status",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, "
                "slugs, and hostnames are not recycled while the workspace exists.",
            ),
        ),
    ),
    "link_domains": TablePolicy(
        {
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "hostname",
                "status",
                "created_at",
                "updated_at",
            ),
            **_same(
                "domain.verification",
                "challenge_digest",
                "challenge_expires_at",
                "challenge_generation",
                "verified_at",
                "verification_expires_at",
                "certificate_expires_at",
                "last_checked_at",
                "failure_code",
                "version",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; disabling keeps the hostname reserved to the "
                "client until the purge of a closed agency releases it (017-B). Reassignment "
                "between clients needs a later reviewed process.",
            ),
        ),
    ),
    "managed_links": TablePolicy(
        {
            **_same(
                "link.configuration",
                "id",
                "agency_id",
                "client_id",
                "domain_id",
                "slug",
                "origin_id",
                "destination",
                "utm",
                "target_url",
                "campaign_id",
                "content_reference_id",
                "template_id",
                "template_revision",
                "status",
                "expires_at",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-033",
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, "
                "slugs, and hostnames are not recycled while the workspace exists.",
            ),
        ),
    ),
    "connector_connections": TablePolicy(
        {
            **_same(
                "connector.account_reference",
                "external_account_id",
                "account_label",
                "account_kind",
            ),
            **_same(
                "tenancy.configuration", "id", "agency_id", "client_id", "created_by_membership_id"
            ),
            **_same(
                "connector.lifecycle",
                "provider",
                "status",
                "status_reason",
                "generation",
                "granted_scopes",
                "created_at",
                "updated_at",
                "connected_at",
                "last_successful_sync_at",
                "disconnect_requested_at",
                "purge_due_at",
                "disconnected_at",
                "revocation_status",
                "destruction_status",
                "purge_status",
                "teardown_attempts",
                "teardown_lease_until",
                "deletion_request_id",
                "reconnect_required_since",
                "account_label_refreshed_at",
                "grant_expires_at",
                "agent_approved_at",
                "agent_disclosure",
            ),
            "day_zone": "connector.account_reference",
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-048",
                "Kept for the workspace lifetime with its outcome; the disconnect purge clears "
                "the account reference.",
            ),
            EndOfLifeRule(
                "external_account_id",
                APPROVED,
                "D-048",
                "Cleared with the account label when a disconnect completes.",
            ),
            EndOfLifeRule(
                "account_label",
                APPROVED,
                "D-058",
                "For providers that refresh their labels, cleared by tracking_lifecycle 30 days "
                "after the last refresh (011-A D11); always cleared when a disconnect completes.",
            ),
        ),
    ),
    "connector_oauth_transactions": TablePolicy(
        {
            **_same("credential.token_digest", "state_digest", "binding_digest"),
            **_same(
                "tenancy.configuration",
                "agency_id",
                "client_id",
                "connection_id",
                "initiator_membership_id",
            ),
            **_same(
                "credential.lifecycle",
                "id",
                "expected_generation",
                "provider",
                "purpose",
                "created_at",
                "expires_at",
                "consumed_at",
                "agent_approved_at",
                "agent_disclosure",
            ),
            "requested_account": "connector.account_reference",
        },
        (_row(APPROVED, "D-048", "Deleted 1 day after consumption or expiry."),),
    ),
    "connector_token_secrets": TablePolicy(
        {
            **_same(
                "connector.sealed_token",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "connector.token_state",
                "kind",
                "version",
                "alg",
                "aad_version",
                "status",
                "revocation",
                "provider_expires_at",
                "last_refreshed_at",
                "created_at",
                "destroyed_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-048",
                "The row is kept as destruction evidence with its connection.",
            ),
            EndOfLifeRule(
                "ciphertext",
                APPROVED,
                "D-048",
                "Material destroyed after provider revocation, or at the teardown deadline, and "
                "when a version is replaced.",
            ),
        ),
    ),
    "connector_sync_runs": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "connector.lifecycle",
                "connection_generation",
                "status",
                "attempt",
                "error_kind",
                "lease_expires_at",
                "created_at",
                "started_at",
                "finished_at",
                "kind",
                "window_since",
                "window_until",
                "not_before",
                "retries",
                "pages",
                "stream",
            ),
        },
        (_row(PENDING, RETENTION, "Run history retention awaits Q-012."),),
    ),
    "connector_checkpoints": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "connector.sync_state",
                "stream",
                "run_id",
                "cursor",
                "covered_from",
                "complete_through",
                "updated_at",
            ),
        },
        (_row(APPROVED, "D-049", "Deleted when a disconnect completes."),),
    ),
    "connector_usage_records": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "connector.usage",
                "run_id",
                "attempt",
                "provider",
                "operation",
                "unit",
                "quantity",
                "outcome",
                "period",
                "occurred_at",
                "settled_at",
                "bucket",
            ),
        },
        (_row(PENDING, RETENTION, "Kept with run history; retention awaits Q-012."),),
    ),
    "connector_records": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "connector.provider_data",
                "connection_generation",
                "provider_object_id",
                "observed_at",
                "metrics",
                "fetched_at",
                "source_run_id",
                "adapter_version",
                "stream",
                "product_type",
                "unavailable",
                "attributes",
                "attributes_refreshed_at",
                "provisional_until",
            ),
        },
        (
            _row(
                APPROVED,
                "D-048; D-053; D-058",
                "Purged when a disconnect, deauthorization or data deletion request completes, "
                "or when the provider confirms the object deleted (011-A D11); deleted by "
                "tracking_lifecycle 730 days after observation at the latest (D9), or after the "
                "provider's shorter period.",
            ),
            EndOfLifeRule(
                "attributes",
                APPROVED,
                "D-058",
                "Allow-listed attributes are cleared by tracking_lifecycle 30 days after their "
                "last refresh; the statistics stay (011-A D11).",
            ),
        ),
    ),
    "connector_deletion_requests": TablePolicy(
        {
            **_same(
                "connector.deletion_request",
                "id",
                "provider",
                "confirmation_code",
                "received_at",
                "connections",
                "completed_at",
            ),
        },
        (_row(PENDING, RETENTION, "Deletion evidence retention awaits Q-012."),),
    ),
    "connector_webhook_deliveries": TablePolicy(
        {
            **_same(
                "connector.webhook_delivery",
                "id",
                "provider",
                "event_digest",
                "received_at",
                "notified",
            ),
        },
        (_row(APPROVED, "D-049", "Deleted 7 days after receipt."),),
    ),
    "ad_accounts": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "advertising.account",
                "account_id",
                "name",
                "currency",
                "time_zone",
                "account_status",
                "previous_currency",
                "currency_changed_at",
                "previous_time_zone",
                "time_zone_changed_at",
                "observed_at",
                "refreshed_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-064",
                "Kept while the connection is active and purged when its disconnect completes "
                "(D13).",
            ),
        ),
    ),
    "ad_objects": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "advertising.object",
                "object_id",
                "level",
                "campaign_id",
                "adset_id",
                "name",
                "effective_status",
                "first_observed_at",
                "refreshed_at",
                "source_run_id",
                "adapter_version",
            ),
        },
        (
            _row(
                APPROVED,
                "D-064",
                "Kept while the connection is active and purged when its disconnect completes "
                "(D13).",
            ),
        ),
    ),
    "ad_spend_facts": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "connection_id"),
            **_same(
                "advertising.spend",
                "ad_id",
                "adset_id",
                "campaign_id",
                "spend_date",
                "time_zone",
                "currency",
                "spend_minor",
                "impressions",
                "clicks",
                "refusal",
                "provisional_until",
                "revisions",
                "first_observed_at",
                "last_observed_at",
                "source_run_id",
                "adapter_version",
            ),
        },
        (
            _row(
                APPROVED,
                "D-064",
                "Purged when the connection's disconnect completes; deleted by "
                "tracking_lifecycle 730 days after the spend date at the latest (D13). No "
                "production retention is approved (Q-012).",
            ),
        ),
    ),
    "conversion_destinations": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "connection_id",
                "created_by_membership_id",
            ),
            **_same(
                "advertising.destination",
                "event_name",
                "test_event_code",
                "enabled",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "017; D-064",
                "Kept until deleted; disabled when its connection's disconnect completes (D13). "
                "Deletion outside the purge of a closed agency belongs to 018.",
            ),
        ),
    ),
    "conversion_deliveries": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "destination_id",
                "connection_id",
            ),
            **_same(
                "advertising.sealed_payload",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
            **_same(
                "advertising.delivery_state",
                "event_id",
                "event_name",
                "action_source",
                "event_time",
                "deadline",
                "currency",
                "currency_exponent",
                "value_minor",
                "status",
                "reason",
                "rejection_class",
                "attempts",
                "retries",
                "requeues",
                "not_before",
                "lease_expires_at",
                "consent_basis",
                "policy_version",
                "created_at",
                "updated_at",
                "delivered_at",
                "ended_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-064",
                "Deleted by tracking_lifecycle 30 days after the delivery ends (D13). No "
                "production retention is approved (Q-012).",
            ),
            EndOfLifeRule(
                "ciphertext",
                APPROVED,
                "D-064",
                "The sealed payload is destroyed when the delivery ends: delivered, blocked, "
                "cancelled, expired, rejected as payload, undeliverable or dismissed (D9).",
            ),
        ),
    ),
    "conversion_acknowledgements": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "delivery_id"),
            **_same(
                "advertising.acknowledgement",
                "attempt",
                "occurred_at",
                "outcome",
                "provider_code",
                "events_received",
                "trace_id",
            ),
        },
        (_row(APPROVED, "D-064", "Deleted with its delivery, 30 days after it ends (D13)."),),
    ),
    "revenue_evidence": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id"),
            "actor": "account.reference",
            **_same(
                "revenue.evidence",
                "sequence",
                "delivery_id",
                "source_account_id",
                "operation_id",
                "kind",
                "classification",
                "currency",
                "currency_exponent",
                "amount_minor",
                "effective_at",
                "received_at",
                "parent_operation_id",
                "reason",
                "source_reference",
                "intake",
                "intake_id",
                "content_digest",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-067; 017",
                "Append-only; kept for the life of the client workspace (D14); legal "
                "retention is pending Q-012 and Q-003.",
            ),
        ),
    ),
    "payment_sources": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "created_by_membership_id",
            ),
            **_same(
                "payment.source",
                "provider",
                "region",
                "name",
                "status",
                "public_key",
                "live_integration_ids",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-067; 017",
                "Kept with the client workspace; a source is disabled to stop intake (D14).",
            ),
        ),
    ),
    "payment_source_secrets": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same(
                "credential.sealed_secret",
                "version",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
            **_same("credential.lifecycle", "created_at", "retires_at"),
        },
        (
            _row(
                APPROVED,
                "D-067",
                "A replaced secret retires 24 hours later and is then deleted by "
                "tracking_lifecycle (D14).",
            ),
        ),
    ),
    "payment_callback_diagnostics": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same(
                "payment.callback_diagnostic",
                "delivery_digest",
                "received_at",
                "outcome",
                "reason",
            ),
        },
        (_row(APPROVED, "D-067", "Deleted by tracking_lifecycle 30 days after receipt (D14)."),),
    ),
    "revenue_imports": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "committed_by_membership_id",
            ),
            **_same(
                "revenue.import_record",
                "file_digest",
                "total_rows",
                "stored_rows",
                "duplicate_rows",
                "rejected_rows",
                "committed_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-067",
                "Deleted by tracking_lifecycle 395 days after the commit (D14); the declared "
                "evidence stays for the life of the workspace.",
            ),
        ),
    ),
    "integration_sources": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "created_by_membership_id",
            ),
            **_same(
                "integration.source",
                "kind",
                "name",
                "status",
                "public_key",
                "created_at",
                "updated_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-068; 017",
                "Kept with the client workspace; a source is disabled to stop intake.",
            ),
        ),
    ),
    "integration_source_secrets": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same(
                "credential.sealed_secret",
                "version",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
            **_same("credential.lifecycle", "created_at", "retires_at"),
        },
        (
            _row(
                APPROVED,
                "D-068",
                "A replaced secret retires 24 hours later and is then deleted by "
                "tracking_lifecycle.",
            ),
        ),
    ),
    "integration_deliveries": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same("integration.delivery", "delivery_digest", "received_at", "outcome", "reason"),
        },
        (_row(APPROVED, "D-068", "Deleted by tracking_lifecycle 30 days after receipt (E9)."),),
    ),
    "bookings": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            "subject_id": "collection.subject",
            **_same(
                "booking.record",
                "provider",
                "status",
                "event_type_ref",
                "start_at",
                "end_at",
                "reschedule_count",
                "linked_at",
                "first_received_at",
                "updated_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-068",
                "Deleted by tracking_lifecycle 395 days after the last update (E9); erasing the "
                "linked subject, or its lifecycle expiry, clears the link (R002, D-070).",
            ),
        ),
    ),
    "booking_events": TablePolicy(
        {
            **_same(
                "tenancy.configuration", "id", "agency_id", "client_id", "booking_id", "source_id"
            ),
            **_same(
                "booking.record",
                "provider",
                "kind",
                "ref",
                "previous_ref",
                "event_type_ref",
                "occurred_at",
                "start_at",
                "end_at",
            ),
        },
        (_row(APPROVED, "D-068", "Deleted with its booking (E9)."),),
    ),
    "crm_stage_rules": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "created_by_membership_id",
            ),
            **_same(
                "crm.rule", "pipeline", "stage", "outcome", "status", "created_at", "updated_at"
            ),
        },
        (_row(RuleStatus.DEFERRED, "D-068; 017", "Kept with the client workspace."),),
    ),
    "crm_deals": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "source_id"),
            **_same(
                "crm.deal",
                "deal_ref",
                "pipeline",
                "stage",
                "previous_stage",
                "stage_at",
                "amount_minor",
                "currency",
                "currency_exponent",
                "amount_at",
                "payment_reference",
                "payment_reference_at",
                "first_received_at",
                "updated_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-068",
                "Deleted by tracking_lifecycle 395 days after the last update (E9).",
            ),
        ),
    ),
    "whatsapp_numbers": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "created_by_membership_id",
            ),
            **_same(
                "whatsapp.number",
                "phone_number_id",
                "name",
                "status",
                "created_at",
                "updated_at",
                "verified_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-068; 017",
                "Kept with the client workspace; the purge of a closed agency releases the "
                "number (017-B).",
            ),
        ),
    ),
    "whatsapp_messages": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "number_id"),
            **_same(
                "whatsapp.referral",
                "message_digest",
                "message_at",
                "received_at",
                "has_referral",
                "source_type",
                "source_id",
                "click_id_present",
            ),
        },
        (_row(APPROVED, "D-068", "Deleted by tracking_lifecycle 395 days after receipt (E9)."),),
    ),
    "identity_key_secrets": TablePolicy(
        {
            **_same("tenancy.configuration", "id", "agency_id", "client_id", "created_at"),
            **_same(
                "credential.sealed_secret",
                "version",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-075; 017",
                "Kept for the client lifetime; never deleted by the lifecycle runner.",
            ),
        ),
    ),
    "identity_subjects": TablePolicy(
        _same(
            "identity.profile",
            "id",
            "agency_id",
            "client_id",
            "status",
            "merged_into_id",
            "version",
            "journey_revision",
            "created_at",
            "updated_at",
            "last_evidence_at",
        ),
        (
            _row(
                APPROVED,
                "D-075",
                "Deleted on erasure or withdrawal, when no key or link remains, or 395 days "
                "after the last evidence (development).",
            ),
        ),
    ),
    "identity_keys": TablePolicy(
        _same(
            "identity.pseudonym",
            "id",
            "agency_id",
            "client_id",
            "kind",
            "key_bytes",
            "key_version",
            "normalizer",
            "subject_id",
            "status",
            "contested_reason",
            "candidate_ids",
            "merge_id",
            "original_owner_ids",
            "anchor_key_ids",
            "method",
            "first_verified_at",
            "last_verified_at",
            "created_at",
        ),
        (
            _row(
                APPROVED,
                "D-075",
                "Deleted with the owning person, with an identity_key tombstone on erasure; a "
                "contested key 395 days after its last verification.",
            ),
        ),
    ),
    "identity_assertions": TablePolicy(
        _same(
            "identity.link",
            "id",
            "agency_id",
            "client_id",
            "assertion_id",
            "credential_id",
            "collection_subject_id",
            "fingerprint",
            "proof",
            "received_at",
            "outcome",
            "reason",
            "evidence",
            "candidate_ids",
            "subject_id",
            "merge_id",
        ),
        (
            _row(
                APPROVED,
                "D-075",
                "Deleted with its collection subject, at withdrawal (W1), on erasure with "
                "assertion tombstones, or 395 days after receipt.",
            ),
        ),
    ),
    "identity_assertion_receipts": TablePolicy(
        _same(
            "identity.receipt",
            "id",
            "agency_id",
            "client_id",
            "assertion_id",
            "fingerprint",
            "received_at",
            "expires_at",
        ),
        (_row(APPROVED, "D-075", "Purged by the lifecycle runner after expires_at (24 hours)."),),
    ),
    "identity_links": TablePolicy(
        _same(
            "identity.link",
            "id",
            "agency_id",
            "client_id",
            "collection_subject_id",
            "status",
            "subject_id",
            "candidate_ids",
            "assertion_ref",
            "asserted_at",
            "eligible_from",
            "provisional_from",
            "eligible_until",
            "closed_reason",
            "merge_id",
            "original_owner_ids",
            "key_ids",
            "grant_started_at",
        ),
        (
            _row(
                APPROVED,
                "D-075",
                "Deleted with its collection subject, at withdrawal (W1), on erasure, or 395 "
                "days after its assertion.",
            ),
        ),
    ),
    "identity_handoffs": TablePolicy(
        {
            **_same(
                "credential.token_digest",
                "code_digest",
                "challenge_digest",
            ),
            **_same(
                "credential.lifecycle",
                "id",
                "agency_id",
                "client_id",
                "collection_subject_id",
                "identity_consent_receipt_id",
                "expires_at",
                "consumed_at",
                "created_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-075",
                "Deleted 1 day after expiry or consumption, at withdrawal and on erasure.",
            ),
        ),
    ),
    "identity_merges": TablePolicy(
        {
            "actor_membership_id": "tenancy.configuration",
            **_same(
                "identity.correction",
                "id",
                "agency_id",
                "client_id",
                "operation_id",
                "kind",
                "survivor_id",
                "merged_id",
                "reverses_id",
                "status",
                "closed_reason",
                "survivor_version_before",
                "merged_version_before",
                "survivor_version_after",
                "merged_version_after",
                "fingerprint",
                "result",
                "reason_code",
                "created_at",
                "ended_at",
            ),
        },
        (
            _row(
                APPROVED,
                "D-075",
                "An active edge is kept while both participants exist; closed entries 2 years "
                "after reversal or closure, or until earlier erasure of a participant.",
            ),
        ),
    ),
    "identity_changes": TablePolicy(
        _same(
            "identity.change",
            "id",
            "agency_id",
            "client_id",
            "seq",
            "person_id",
            "kind",
            "journey_revision",
            "occurred_at",
        ),
        (_row(APPROVED, "D-075", "Pruned by the lifecycle runner 30 days after occurred_at."),),
    ),
    "identity_feed_state": TablePolicy(
        _same(
            "identity.change",
            "client_id",
            "agency_id",
            "last_seq",
            "pruned_through_seq",
            "updated_at",
        ),
        (_row(RuleStatus.DEFERRED, "D-075; 017", "Kept for the client workspace lifetime."),),
    ),
    "identity_erasure_holds": TablePolicy(
        _same(
            "deletion.hold",
            "id",
            "agency_id",
            "client_id",
            "deletion_request_id",
            "collected_event_id",
            "state",
            "held_at",
            "settled_at",
        ),
        (
            _row(
                APPROVED,
                "D-075",
                "Held until settled; settled rows are deleted 30 days after their request "
                "completes.",
            ),
        ),
    ),
    "ledger_projection_state": TablePolicy(
        _same(
            "revenue.ledger",
            "client_id",
            "agency_id",
            "generation",
            "staging_generation",
            "algorithm",
            "status",
            "last_evidence_sequence",
            "receipt_ordinal",
            "movement_sequence",
            "receipt_digest",
            "last_received_at",
            "financial_revision",
            "updated_at",
        ),
        (_row(RuleStatus.DEFERRED, "D-075; 017", "Kept for the client workspace lifetime."),),
    ),
    "ledger_receipts": TablePolicy(
        _same(
            "revenue.ledger",
            "id",
            "agency_id",
            "client_id",
            "generation",
            "receipt_ordinal",
            "evidence_id",
            "evidence_sequence",
            "input_digest",
            "previous_digest",
            "receipt_digest",
            "outcome",
            "closing_states",
            "created_at",
        ),
        (
            _row(
                RuleStatus.DEFERRED,
                "D-075; 017",
                "Append-only; kept with its evidence for the client workspace lifetime.",
            ),
        ),
    ),
    "ledger_movements": TablePolicy(
        _same(
            "revenue.ledger",
            "id",
            "agency_id",
            "client_id",
            "generation",
            "movement_sequence",
            "receipt_id",
            "source_account_id",
            "transaction_id",
            "operation_id",
            "kind",
            "direction",
            "amount_minor",
            "currency",
            "currency_exponent",
            "effective_at",
            "trigger_evidence_id",
            "reason",
        ),
        (
            _row(
                RuleStatus.DEFERRED,
                "D-075; 017",
                "Append-only; kept with its evidence for the client workspace lifetime.",
            ),
        ),
    ),
    "ledger_transactions": TablePolicy(
        _same(
            "revenue.ledger",
            "id",
            "agency_id",
            "client_id",
            "generation",
            "source_account_id",
            "operation_id",
            "currency",
            "currency_exponent",
            "sale_effective_at",
            "captured",
            "refunded",
            "charged_back",
            "reversed",
            "corrected",
            "net",
            "entries",
            "evidence_ids",
            "financial_revision",
            "updated_at",
        ),
        (
            _row(
                RuleStatus.DEFERRED,
                "D-075; 017",
                "Replaceable projection, rebuilt from evidence; kept for the workspace lifetime.",
            ),
        ),
    ),
    "ledger_reconciliation_actions": TablePolicy(
        {
            "actor_membership_id": "tenancy.configuration",
            **_same(
                "revenue.ledger",
                "id",
                "agency_id",
                "client_id",
                "operation_id",
                "issue_id",
                "issue_fingerprint",
                "issue_version",
                "evidence_ids",
                "action",
                "reason_code",
                "request_fingerprint",
                "created_at",
            ),
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-075; 017",
                "Append-only audit of reconciliation reviews; kept for the workspace lifetime.",
            ),
        ),
    ),
    "revenue_identity_bindings": TablePolicy(
        {
            **_same(
                "tenancy.configuration",
                "id",
                "agency_id",
                "client_id",
                "credential_id",
                "actor_membership_id",
            ),
            **_same(
                "revenue.ledger",
                "association_id",
                "revision",
                "source_account_id",
                "sale_operation_id",
                "state",
                "reason",
                "detach_reason",
                "expected_revision",
                "received_at",
                "closed_at",
            ),
            **_same(
                "identity.link",
                "request_id",
                "request_fingerprint",
                "assertion_ref",
                "collection_subject_id",
                "owner_subject_id",
                "key_ids",
            ),
        },
        (
            _row(
                APPROVED,
                "D-075",
                "Identifying pointers and retry material are cleared (F1) on withdrawal, erasure "
                "or expiry of the person; the non-identifying record follows the ledger.",
            ),
        ),
    ),
    "attribution_model_versions": TablePolicy(
        {
            **_same(
                "attribution.model",
                "id",
                "agency_id",
                "client_id",
                "version_key",
                "model",
                "window_seconds",
                "rules",
                "is_default",
                "status",
                "operations",
                "created_at",
                "retired_at",
            ),
            "created_by_membership_id": "tenancy.configuration",
        },
        (
            _row(
                RuleStatus.DEFERRED,
                "D-079; 017",
                "Kept for the client workspace lifetime; a retired version keeps its history.",
            ),
        ),
    ),
    "attribution_conversions": TablePolicy(
        {
            **_same(
                "attribution.credit",
                "id",
                "agency_id",
                "client_id",
                "generation",
                "kind",
                "association_id",
                "binding_id",
                "source_account_id",
                "sale_operation_id",
                "effective_at",
                "status",
                "superseded_generation",
                "superseded_at",
                "superseded_reason",
                "scrubbed_at",
                "recheck_at",
                "created_at",
            ),
            **_same(
                "attribution.pointer",
                "owner_person_id",
                "lead_event_id",
                "slot_key",
                "conversion_key",
            ),
        },
        (ATTRIBUTION_RULE,),
    ),
    "attribution_runs": TablePolicy(
        {
            **_same(
                "attribution.credit",
                "id",
                "agency_id",
                "client_id",
                "generation",
                "conversion_id",
                "model_version_id",
                "revision",
                "status",
                "basis",
                "causes",
                "currency",
                "currency_exponent",
                "verified_net_minor",
                "window_start",
                "window_end",
                "ledger_generation",
                "receipt_ordinal",
                "identity_seq",
                "excluded_reasons",
                "touch_bound_exceeded",
                "recorded_at",
            ),
            "excluded_touchpoint_ids": "attribution.pointer",
        },
        (ATTRIBUTION_RULE,),
    ),
    "attribution_allocations": TablePolicy(
        {
            **_same(
                "attribution.credit",
                "id",
                "agency_id",
                "client_id",
                "run_id",
                "ordinal",
                "credited",
                "recipient",
                "basis",
                "position",
                "share_numerator",
                "share_denominator",
                "amount_minor",
                "evidence_class",
                "source",
                "campaign_ref",
                "content_ref",
                "link_ref",
            ),
            **_same("attribution.pointer", "touchpoint_id", "occurred_at"),
        },
        (ATTRIBUTION_RULE,),
    ),
    "attribution_credit_changes": TablePolicy(
        {
            **_same(
                "attribution.credit",
                "id",
                "agency_id",
                "client_id",
                "run_id",
                "model_version_id",
                "generation",
                "ordinal",
                "conversion_kind",
                "effective_at",
                "recipient",
                "source",
                "campaign_ref",
                "content_ref",
                "link_ref",
                "delta_share_numerator",
                "delta_share_denominator",
                "delta_minor",
                "currency",
                "currency_exponent",
                "recorded_at",
            ),
            "touchpoint_id": "attribution.pointer",
        },
        (ATTRIBUTION_RULE,),
    ),
    "attribution_consumer_state": TablePolicy(
        _same(
            "attribution.state",
            "client_id",
            "agency_id",
            "version",
            "generation",
            "status",
            "ledger_generation",
            "receipt_ordinal",
            "identity_seq",
            "model_set_digest",
            "unit_kind",
            "staging_generation",
            "target_ledger_generation",
            "target_receipt_ordinal",
            "target_identity_seq",
            "target_model_set_digest",
            "unit_started_at",
            "progress_key",
            "sweep_after_key",
            "scrub_epoch",
            "failure_code",
            "published_at",
            "updated_at",
            "created_at",
        ),
        (_row(RuleStatus.DEFERRED, "D-079; 017", "Kept for the client workspace lifetime."),),
    ),
    # Specification 017-A (D-092): plans, their assignment history, agency closures and the
    # agreement record.
    "saas_plans": TablePolicy(
        _same(
            "plan.definition",
            "id",
            "key",
            "name",
            "clients_limit",
            "seats_limit",
            "connections_limit",
            "managed_links_limit",
            "tracked_events_limit",
            "is_default",
            "reason",
            "created_at",
        ),
        (
            _row(
                APPROVED,
                "D-092",
                "Never deleted: plans are immutable apart from the default flag and referenced "
                "by the assignment history (D2).",
            ),
        ),
    ),
    "agency_plan_assignments": TablePolicy(
        _same(
            "plan.assignment",
            "id",
            "agency_id",
            "plan_id",
            "revision",
            "assigned_at",
            "assigned_by",
            "reason",
        ),
        (
            _row(
                APPROVED,
                "D-092; D-098",
                "Insert-only history kept with the agency, also after the purge of a closed "
                "agency, for 017-C billing (D8).",
            ),
        ),
    ),
    "agency_closures": TablePolicy(
        _same(
            "agency.closure",
            "id",
            "agency_id",
            "requested_by_membership_id",
            "requested_at",
            "closes_at",
            "cancelled_at",
            "cancelled_by_membership_id",
            "completed_at",
        ),
        (
            _row(
                APPROVED,
                "D-092; D-098",
                "Kept with the agency; the purge of a closed agency deletes it and keeps its "
                "times in the purge record (D8).",
            ),
        ),
    ),
    "user_agreements": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("account.agreement", "id", "document", "version", "accepted_at", "channel"),
        },
        (
            _row(
                APPROVED,
                "D-092; D-024",
                "Deleted by the lifecycle runner with a closed account's credential state; "
                "keeping proof of agreement beyond that awaits legal advice (Q-012).",
            ),
        ),
    ),
    # Specification 016-C (D-095): retained exports, report schedules and agency branding.
    "report_exports": TablePolicy(
        _same(
            "report.export",
            "id",
            "agency_id",
            "client_id",
            "family",
            "parameters",
            "connection_id",
            "period_start",
            "period_end",
            "includes_financials",
            "source",
            "schedule_id",
            "requested_by_membership_id",
            "status",
            "revoked_at",
            "revoked_reason",
            "created_at",
            "stored_at",
            "expires_at",
            "row_count",
            "byte_size",
            "report_revision",
            "download_count",
            "last_downloaded_at",
        ),
        (
            _row(
                APPROVED,
                "D-095",
                "Deleted by tracking_lifecycle when the export expires, 7 days after creation; "
                "a discarded row, or a pending row older than one hour, on the next run. A "
                "revoked row stays until its expiry so that the list shows why it is gone.",
            ),
        ),
    ),
    "report_export_contents": TablePolicy(
        {
            **_same("report.export", "export_id", "agency_id", "client_id", "created_at"),
            **_same(
                "report.export_content",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
                "alg",
                "aad_version",
            ),
        },
        (
            _row(
                APPROVED,
                "D-095",
                "Deleted at once when its export is revoked, and by tracking_lifecycle at the "
                "export's expiry.",
            ),
        ),
    ),
    "report_schedules": TablePolicy(
        _same(
            "report.schedule",
            "id",
            "agency_id",
            "client_id",
            "name",
            "family",
            "parameters",
            "sale_values",
            "compare",
            "cadence",
            "weekday",
            "hour",
            "time_zone",
            "status",
            "pause_reason",
            "owner_membership_id",
            "next_run_at",
            "last_run_at",
            "last_outcome",
            "last_error_code",
            "last_notified",
            "last_skipped",
            "consecutive_failures",
            "created_at",
            "updated_at",
        ),
        (
            _row(
                RuleStatus.DEFERRED,
                "D-095; 017",
                "Deleted by an Owner or Admin; otherwise kept with the client workspace.",
            ),
        ),
    ),
    "report_schedule_recipients": TablePolicy(
        {
            **_same("report.schedule", "schedule_id", "agency_id", "client_id", "created_at"),
            "membership_id": "report.recipient",
        },
        (
            _row(
                APPROVED,
                "D-095",
                "Deleted when the recipient leaves the schedule, a manager replaces the "
                "recipients, or the schedule is deleted.",
            ),
        ),
    ),
    "agency_branding": TablePolicy(
        _same(
            "branding.profile",
            "agency_id",
            "display_name",
            "accent_color",
            "logo",
            "logo_width",
            "logo_height",
            "updated_at",
            "updated_by_membership_id",
        ),
        (
            _row(
                APPROVED,
                "D-095; D-098",
                "Kept with the agency; deleted by the purge of a closed agency (017-B).",
            ),
        ),
    ),
    # Specification 017-B (D-098): the offboarding export, its sealed parts and the purge record.
    "agency_exports": TablePolicy(
        _same(
            "agency.export",
            "id",
            "agency_id",
            "requested_by_membership_id",
            "status",
            "error_code",
            "requested_at",
            "ready_at",
            "revoked_at",
            "expires_at",
            "part_count",
            "byte_size",
            "row_count",
            "row_counts",
            "manifest_sha256",
            "download_count",
            "last_downloaded_at",
        ),
        (
            _row(
                APPROVED,
                "D-098",
                "One per request; a new request or a cancellation revokes the open one. Kept "
                "with the agency until its purge; its parts end at revocation, expiry or purge "
                "(D5, D8).",
            ),
        ),
    ),
    "agency_export_parts": TablePolicy(
        {
            **_same("agency.export", "export_id", "part", "agency_id", "created_at"),
            **_same(
                "agency.export_content",
                "kek_id",
                "wrap_nonce",
                "wrapped_dek",
                "nonce",
                "ciphertext",
                "alg",
                "aad_version",
            ),
        },
        (
            _row(
                APPROVED,
                "D-098",
                "Deleted at once when its export is revoked, by tracking_lifecycle at the "
                "export's expiry (7 days after the request) and by the purge (D5).",
            ),
        ),
    ),
    "agency_purges": TablePolicy(
        _same(
            "agency.purge",
            "agency_id",
            "state",
            "closure_requested_at",
            "closes_at",
            "closure_completed_at",
            "export_summary",
            "offboarding_started_at",
            "offboarding_completed_at",
            "teardown_settled_at",
            "purge_started_at",
            "purge_completed_at",
            "deleted_counts",
        ),
        (
            _row(
                APPROVED,
                "D-098",
                "Kept after the purge as the minimal record of a closed agency (D8).",
            ),
        ),
    ),
    "alembic_version": TablePolicy(
        {"version_num": "system.schema_version"},
        (_row(RuleStatus.NOT_APPLICABLE, "001", "Schema revision marker; no personal data."),),
    ),
}

# 017-B (D-098 D7, D9): purge_agency_batch deletes every row of a closed agency from every table
# that carries agency_id or client_id, except the record that stays (D8). The rule is added to
# each such table here, so a new scoped table gets it by construction.
KEPT_AFTER_PURGE = frozenset({"agency_plan_assignments", "agency_purges"})
PURGE_RULE = _row(
    APPROVED,
    "D-098",
    "Deleted by the purge of its closed agency (017-B), after the closing period's export "
    "window and once every teardown of the agency has settled.",
)


def _add_purge_rule(tables: dict[str, TablePolicy]) -> None:
    for name, policy in list(tables.items()):
        if name not in KEPT_AFTER_PURGE and {"agency_id", "client_id"} & set(policy.columns):
            tables[name] = TablePolicy(policy.columns, (*policy.rules, PURGE_RULE))


_add_purge_rule(TABLES)


# Compare a schema (table name -> column names) and its user references (table, column pairs
# with a foreign key to users.id) against the registry. Returns sorted human-readable
# problems; an empty list means every column is classified and every rule is well formed.
def registry_problems(
    schema: Mapping[str, Iterable[str]],
    user_references: Iterable[tuple[str, str]] = (),
) -> list[str]:
    problems: list[str] = []
    for table, columns in schema.items():
        policy = TABLES.get(table)
        if policy is None:
            problems.append(f"unclassified table: {table}")
            continue
        present = set(columns)
        problems.extend(
            f"unclassified column: {table}.{column}" for column in present - set(policy.columns)
        )
        problems.extend(
            f"stale registry column: {table}.{column}" for column in set(policy.columns) - present
        )
    problems.extend(f"stale registry table: {table}" for table in set(TABLES) - set(schema))
    for table, policy in TABLES.items():
        problems.extend(
            f"unknown class: {table}.{column} -> {code}"
            for column, code in policy.columns.items()
            if code not in CLASSES
        )
        if not any(rule.target == "row" for rule in policy.rules):
            problems.append(f"missing row rule: {table}")
        for rule in policy.rules:
            if rule.target != "row" and rule.target not in policy.columns:
                problems.append(f"rule target is not a column: {table}.{rule.target}")
            if not rule.reference.strip() or not rule.description.strip():
                problems.append(f"rule without reference or description: {table}.{rule.target}")
            if rule.status is RuleStatus.APPROVED and not rule.reference.startswith("D-"):
                problems.append(f"approved rule without a recorded decision: {table}")
    for table, column in user_references:
        code = TABLES.get(table, TablePolicy({}, ())).columns.get(column)
        if code is not None and code != "account.reference":
            problems.append(f"user reference not classed account.reference: {table}.{column}")
    return sorted(problems)
