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
            "Delete with agency or client offboarding.",
            "017",
        ),
        DataClass(
            "tenancy.configuration",
            "Tenant identifiers, roles, statuses, grants, and their timestamps.",
            Sensitivity.MEDIUM,
            Personal.PSEUDONYMOUS,
            Provenance.SYSTEM,
            "Delete with agency or client offboarding.",
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
            "(D-033); offboarding is 017.",
            "005, 017",
        ),
        DataClass(
            "link.label",
            "Free-text campaign labels, content platform labels, and template names; may name "
            "a person.",
            Sensitivity.MEDIUM,
            Personal.DIRECT,
            Provenance.PROVIDED,
            "Delete with client offboarding (017).",
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
            "Kept for the workspace lifetime; offboarding is 017. Run retention is Q-012.",
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
            **_same("tenancy.configuration", "id", "status", "created_at", "updated_at"),
        },
        (_row(RuleStatus.DEFERRED, "017", "Agency closure and offboarding belong to 017."),),
    ),
    "client_workspaces": TablePolicy(
        {
            "name": "tenancy.label",
            **_same(
                "tenancy.configuration", "id", "agency_id", "status", "created_at", "updated_at"
            ),
        },
        (_row(RuleStatus.DEFERRED, "017", "Archiving is reversible; offboarding belongs to 017."),),
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
                "Disabled, never deleted, including on account closure (D-024); agency "
                "offboarding belongs to 017.",
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
                "Kept while the client exists; disabling keeps the row. Offboarding is 017.",
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
        (_row(RuleStatus.DEFERRED, "017; D-027", "Kept while the client exists (017)."),),
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
        ),
        (
            _row(
                APPROVED,
                "D-027",
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
        },
        (
            _row(
                APPROVED,
                "D-027; D-033",
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
                "Kept for the workspace lifetime as the record of erasure; offboarding is 017.",
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
                "Insert-only for the runtime and unreachable by the lifecycle role; kept for the "
                "workspace lifetime. Offboarding is 017.",
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
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, slugs, "
                "and hostnames are not recycled. Offboarding is 017.",
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
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, slugs, "
                "and hostnames are not recycled. Offboarding is 017.",
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
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, slugs, "
                "and hostnames are not recycled. Offboarding is 017.",
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
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, slugs, "
                "and hostnames are not recycled. Offboarding is 017.",
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
                "client. Reassignment and offboarding need a later reviewed process (017).",
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
                "Kept for the workspace lifetime; the runtime never deletes rows, so codes, slugs, "
                "and hostnames are not recycled. Offboarding is 017.",
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
                "the account reference. Offboarding is 017.",
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
                "The row is kept as destruction evidence with its connection; offboarding is 017.",
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
                "Deletion and offboarding are 017 and 018.",
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
    "alembic_version": TablePolicy(
        {"version_num": "system.schema_version"},
        (_row(RuleStatus.NOT_APPLICABLE, "001", "Schema revision marker; no personal data."),),
    ),
}


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
