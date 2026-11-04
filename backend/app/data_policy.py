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
POLICY_VERSION = "003-A1"


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


# Decision status of an end-of-life rule. Only APPROVED rules describe behavior backed by a
# recorded owner decision; PENDING_DECISION and DEFERRED rules are not in force.
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
ERASURE = "003-A decision 3"


def _row(status: RuleStatus, reference: str, description: str) -> EndOfLifeRule:
    return EndOfLifeRule("row", status, reference, description)


def _same(code: str, *columns: str) -> dict[str, str]:
    return dict.fromkeys(columns, code)


TABLES: dict[str, TablePolicy] = {
    "users": TablePolicy(
        {
            **_same("account.identity", "email_normalized", "display_name"),
            **_same(
                "account.reference", "id", "status", "email_verified_at", "created_at", "updated_at"
            ),
        },
        (
            _row(
                PENDING,
                f"{ERASURE}; {RETENTION}",
                "Never deleted or erased; the runtime cannot change email, name, or status. "
                "Account closure and unverified registrations await decisions 2 and 3.",
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
                PENDING,
                ERASURE,
                "Hash replaced on change or reset; the row is removed only by account closure.",
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
                PENDING,
                RETENTION,
                "Revoked, absolutely expired, and idle sessions stay as rows (one per login).",
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
        (_row(PENDING, RETENTION, "Consumed and expired reset or legacy verify tokens stay."),),
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
        (_row(PENDING, RETENTION, "Consumed, invalidated, and expired challenges stay (D-022)."),),
    ),
    "oauth_transactions": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("credential.token_digest", "state_digest", "binding_digest"),
            **_same(
                "credential.lifecycle", "id", "purpose", "created_at", "expires_at", "consumed_at"
            ),
        },
        (_row(PENDING, RETENTION, "Consumed and expired ten-minute transactions stay (D-022)."),),
    ),
    "external_identities": TablePolicy(
        {
            "user_id": "account.reference",
            **_same("identity.external_subject", "provider", "issuer", "subject"),
            **_same("credential.lifecycle", "id", "created_at", "last_login_at"),
        },
        (
            _row(
                PENDING,
                ERASURE,
                "Kept while linked; unlinking and erasure await 003 (D-022 policy 5).",
            ),
        ),
    ),
    "auth_rate_limits": TablePolicy(
        _same("security.telemetry", "bucket_key", "attempts", "expires_at"),
        (_row(PENDING, RETENTION, "Expired buckets restart in place on reuse; otherwise stay."),),
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
                RuleStatus.APPROVED,
                "D-019; D-022",
                "Cleared after confirmed delivery; a verification-code payload is cleared "
                "unsent at expires_at. Reset and invitation payloads have no expiry yet "
                "(003-A decision 5).",
            ),
            _row(PENDING, f"{RETENTION}; 003-A decision 5", "Delivered and expired rows stay."),
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
                f"017; {ERASURE}",
                "Memberships are disabled, never deleted; account closure awaits decision 3.",
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
                f"{RETENTION}; {ERASURE}",
                "Append-only for the runtime; kept indefinitely. Actor follows decision 3.",
            ),
        ),
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
