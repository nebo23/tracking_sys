"""Identity keys, assertions, segments, merges, change feed and erasure holds

Revision ID: 0026_identity_journey
Revises: 0025_whatsapp
Created: 2026-11-23

Specification 006 (D-075, joint decisions J2-J7; design revision 4 section 12.1 as amended by
specs/006-identity-journey/joint-design.md). The historical proposal named this migration
0009_identity_journey; that number belongs to the connector runtime and is never used.

Adds the eleven identity tables: identity_key_secrets (the sealed per-client matching key),
identity_subjects (persons), identity_keys (keyed identifiers, never raw values),
identity_assertions (assertion evidence), identity_assertion_receipts (the 24-hour public retry
receipts), identity_links (owned, ambiguous and neutral segments of a collection subject),
identity_handoffs (one-time browser handoff digests), identity_merges (the merge ledger),
identity_changes and identity_feed_state (the per-client change feed), and
identity_erasure_holds (the exact events held by one erasure request).

Existing tables: collection_subjects gains the immutable issuance_channel (unknown for every
row created before this revision), the monotonic identity_floor_at and the write-once
identity_shared_at; collected_events gains the scoped unique key that the erasure-hold foreign
key targets (R006-23) and the write-once identity_excluded_at marker (R006-24); client_grants
and invitation_client_grants gain can_view_identities (default false, D8). Tombstones accept
the identity_key, assertion_id and assertion_fp match types, diagnostics the identity channel,
and audit events the identity actions and the identity_subject resource. Row triggers enforce
the immutable, monotonic and write-once columns for every role.

tracking_app receives the column-limited privileges the identity services need. Retry receipts
are never deleted by the runtime. tracking_lifecycle receives only the expiry, settlement,
closure and feed privileges of the development retention rules; it cannot read the matching
secret or tombstones. The downgrade refuses populated identity state and non-default new
columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0026_identity_journey"
down_revision: str | Sequence[str] | None = "0025_whatsapp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Children before parents (downgrade order).
TABLES = (
    "identity_erasure_holds",
    "identity_changes",
    "identity_feed_state",
    "identity_handoffs",
    "identity_links",
    "identity_assertion_receipts",
    "identity_assertions",
    "identity_keys",
    "identity_merges",
    "identity_subjects",
    "identity_key_secrets",
)
HEX64 = "~ '^[0-9a-f]{64}$'"
EMPTY_UUIDS = sa.text("'{}'::uuid[]")
PREVIOUS_ACTIONS = (
    "action IN ('agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
    "'source.secret_rotated', 'form.updated', 'deletion.requested', "
    "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
    "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
    "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
    "'link.created', 'link.updated', 'connector.connected', 'connector.reconnected', "
    "'connector.disconnect_requested', 'destination.created', 'destination.updated', "
    "'delivery.requeued', 'delivery.dismissed', 'payment_source.created', "
    "'payment_source.updated', 'payment_source.secret_replaced', "
    "'revenue_import.committed', 'revenue.declared', 'integration.created', "
    "'integration.updated', 'integration.secret_replaced', 'crm_rule.created', "
    "'crm_rule.updated', 'whatsapp_number.created', 'whatsapp_number.updated')"
)
NEW_ACTIONS = (
    "identity.merged",
    "identity.unmerged",
    "identity.erased",
    "identity.erasure_resolved",
)
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", " + ", ".join(f"'{item}'" for item in NEW_ACTIONS) + ")"
PREVIOUS_RESOURCES = (
    "resource_type IN ('agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number')"
)
RESOURCES = PREVIOUS_RESOURCES[:-1] + ", 'identity_subject')"
PREVIOUS_MATCH_TYPES = "match_type IN ('subject_token', 'event_id')"
MATCH_TYPES = (
    "match_type IN ('subject_token', 'event_id', 'identity_key', 'assertion_id', 'assertion_fp')"
)
PREVIOUS_CHANNELS = "channel IN ('browser', 'server', 'webhook', 'consent', 'erasure')"
CHANNELS = "channel IN ('browser', 'server', 'webhook', 'consent', 'erasure', 'identity')"
CHANGE_KINDS = (
    "'linked', 'unlinked', 'contested', 'merged', 'unmerged', 'merge_closed', 'erased', "
    "'withdrawn', 'expired', 'events_changed'"
)
REASON_CODES = "'same_person_confirmed_by_client', 'duplicate_account', 'data_correction'"
CLOSED_REASONS = "'participant_expired', 'participant_withdrew', 'participant_erased'"
LINK_CLOSURES = (
    "'switched', 'ambiguous', 'neutral_boundary', 'consent_ended', 'merge_reversed', "
    "'participant_lost', 'erased'"
)
ASSERTION_REASONS = (
    "'replay_before_deletion', 'assertion_id_reused', 'no_consent_after_deletion', "
    "'subject_objected'"
)
HOLD_STATES = "'held', 'erased', 'retained', 'expired', 'erased_elsewhere'"

RUNTIME_GRANTS = (
    "GRANT SELECT, INSERT ON identity_key_secrets, identity_changes TO tracking_app",
    "GRANT SELECT, INSERT, DELETE ON identity_subjects, identity_keys, identity_assertions, "
    "identity_links, identity_handoffs, identity_merges TO tracking_app",
    "GRANT SELECT, INSERT ON identity_assertion_receipts, identity_feed_state, "
    "identity_erasure_holds TO tracking_app",
    "GRANT UPDATE (status, merged_into_id, version, journey_revision, updated_at, "
    "last_evidence_at) ON identity_subjects TO tracking_app",
    "GRANT UPDATE (subject_id, status, contested_reason, candidate_ids, merge_id, "
    "original_owner_ids, method, last_verified_at) ON identity_keys TO tracking_app",
    "GRANT UPDATE (candidate_ids, merge_id, subject_id) ON identity_assertions TO tracking_app",
    # R006-26: an expired receipt's fingerprint and window are replaced atomically.
    "GRANT UPDATE (fingerprint, received_at, expires_at) ON identity_assertion_receipts "
    "TO tracking_app",
    "GRANT UPDATE (status, subject_id, candidate_ids, provisional_from, eligible_until, "
    "closed_reason, merge_id, original_owner_ids, key_ids, assertion_ref) ON identity_links "
    "TO tracking_app",
    "GRANT UPDATE (consumed_at) ON identity_handoffs TO tracking_app",
    "GRANT UPDATE (status, closed_reason, ended_at) ON identity_merges TO tracking_app",
    "GRANT UPDATE (last_seq, updated_at) ON identity_feed_state TO tracking_app",
    "GRANT UPDATE (collected_event_id, state, settled_at) ON identity_erasure_holds "
    "TO tracking_app",
    "GRANT UPDATE (identity_floor_at, identity_shared_at) ON collection_subjects TO tracking_app",
    "GRANT UPDATE (identity_excluded_at) ON collected_events TO tracking_app",
)
LIFECYCLE_GRANTS = (
    "GRANT SELECT (id, client_id, collection_subject_id, expires_at, consumed_at) "
    "ON identity_handoffs TO tracking_lifecycle",
    "GRANT DELETE ON identity_handoffs TO tracking_lifecycle",
    "GRANT SELECT (id, client_id, expires_at) ON identity_assertion_receipts TO tracking_lifecycle",
    "GRANT DELETE ON identity_assertion_receipts TO tracking_lifecycle",
    "GRANT SELECT, DELETE ON identity_erasure_holds TO tracking_lifecycle",
    "GRANT UPDATE (collected_event_id, state, settled_at) ON identity_erasure_holds "
    "TO tracking_lifecycle",
    "GRANT SELECT (id, agency_id, client_id, status, completed_at, target_outcomes) "
    "ON deletion_requests TO tracking_lifecycle",
    "GRANT UPDATE (status, completed_at, target_outcomes) ON deletion_requests "
    "TO tracking_lifecycle",
    "GRANT SELECT, INSERT, DELETE ON identity_changes TO tracking_lifecycle",
    "GRANT SELECT, INSERT ON identity_feed_state TO tracking_lifecycle",
    "GRANT UPDATE (last_seq, pruned_through_seq, updated_at) ON identity_feed_state "
    "TO tracking_lifecycle",
    "GRANT SELECT, DELETE ON identity_subjects, identity_keys, identity_assertions, "
    "identity_links, identity_merges TO tracking_lifecycle",
    "GRANT UPDATE (status, merged_into_id, version, journey_revision, updated_at) "
    "ON identity_subjects TO tracking_lifecycle",
    "GRANT UPDATE (subject_id, status, contested_reason, candidate_ids, merge_id) "
    "ON identity_keys TO tracking_lifecycle",
    "GRANT UPDATE (candidate_ids, merge_id, subject_id) ON identity_assertions "
    "TO tracking_lifecycle",
    "GRANT UPDATE (status, subject_id, candidate_ids, eligible_until, closed_reason, "
    "merge_id, provisional_from, original_owner_ids, key_ids, assertion_ref) "
    "ON identity_links TO tracking_lifecycle",
    "GRANT UPDATE (status, closed_reason, ended_at) ON identity_merges TO tracking_lifecycle",
    "GRANT UPDATE (identity_floor_at) ON collection_subjects TO tracking_lifecycle",
)

# The guard functions run for every role, including the migrator: an issuance channel never
# changes, the identity floor never moves back, and the shared and exclusion markers are
# written at most once. first_received_at of an event never changes (R006-24).
GUARDS = (
    """
    CREATE FUNCTION identity_guard_collection_subject() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.issuance_channel IS DISTINCT FROM OLD.issuance_channel THEN
            RAISE EXCEPTION 'issuance_channel is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.identity_floor_at IS NOT NULL AND (NEW.identity_floor_at IS NULL
                OR NEW.identity_floor_at < OLD.identity_floor_at) THEN
            RAISE EXCEPTION 'identity_floor_at is monotonic' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.identity_shared_at IS NOT NULL
                AND NEW.identity_shared_at IS DISTINCT FROM OLD.identity_shared_at THEN
            RAISE EXCEPTION 'identity_shared_at is write-once' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER identity_guard_collection_subject BEFORE UPDATE ON collection_subjects
    FOR EACH ROW EXECUTE FUNCTION identity_guard_collection_subject()
    """,
    """
    CREATE FUNCTION identity_guard_collected_event() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.identity_excluded_at IS NOT NULL
                AND NEW.identity_excluded_at IS DISTINCT FROM OLD.identity_excluded_at THEN
            RAISE EXCEPTION 'identity_excluded_at is write-once' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.first_received_at IS DISTINCT FROM OLD.first_received_at THEN
            RAISE EXCEPTION 'first_received_at is immutable' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER identity_guard_collected_event BEFORE UPDATE ON collected_events
    FOR EACH ROW EXECUTE FUNCTION identity_guard_collected_event()
    """,
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _time(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
    ]


def _client_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id"],
        ["client_workspaces.agency_id", "client_workspaces.id"],
        name=op.f(f"fk_{table}_agency_id_client_workspaces"),
    )


def _scoped_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


def _uuids(name: str) -> sa.Column:
    return sa.Column(name, postgresql.ARRAY(sa.Uuid()), server_default=EMPTY_UUIDS, nullable=False)


def upgrade() -> None:
    _replace_check("audit_events", "valid_action", ACTIONS)
    _replace_check("audit_events", "valid_resource", RESOURCES)
    _replace_check("deletion_tombstones", "valid_match_type", MATCH_TYPES)
    _replace_check("event_diagnostics", "valid_channel", CHANNELS)

    # Existing tables (J7): legacy subjects have unknown issuance (D3).
    op.add_column(
        "collection_subjects",
        sa.Column(
            "issuance_channel", sa.String(length=8), server_default="unknown", nullable=False
        ),
    )
    op.add_column("collection_subjects", _time("identity_floor_at", nullable=True))
    op.add_column("collection_subjects", _time("identity_shared_at", nullable=True))
    op.create_check_constraint(
        op.f("ck_collection_subjects_valid_issuance"),
        "collection_subjects",
        "issuance_channel IN ('browser', 'server', 'unknown')",
    )
    op.add_column("collected_events", _time("identity_excluded_at", nullable=True))
    # R006-23: the named composite target of the erasure-hold foreign key.
    op.create_unique_constraint(
        "uq_collected_events_scope", "collected_events", ["agency_id", "client_id", "id"]
    )
    for table in ("client_grants", "invitation_client_grants"):
        op.add_column(
            table,
            sa.Column(
                "can_view_identities", sa.Boolean(), server_default=sa.text("false"), nullable=False
            ),
        )

    table = "identity_key_secrets"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kek_id", sa.String(length=32), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        _time("created_at", default=True),
        _check(table, "positive_version", "version >= 1"),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "version", name="uq_identity_key_secrets_version"),
    )

    table = "identity_subjects"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("merged_into_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("journey_revision", sa.BigInteger(), server_default="0", nullable=False),
        _time("created_at", default=True),
        _time("updated_at", default=True),
        _time("last_evidence_at"),
        _check(table, "valid_status", "status IN ('active', 'merged')"),
        _check(table, "merge_pointer", "(status = 'merged') = (merged_into_id IS NOT NULL)"),
        _check(table, "not_self_merged", "merged_into_id IS NULL OR merged_into_id <> id"),
        _check(table, "valid_counters", "version >= 1 AND journey_revision >= 0"),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_subjects_scope"),
    )
    op.create_foreign_key(
        "fk_identity_subjects_merged_into_id_identity_subjects",
        table,
        table,
        ["agency_id", "client_id", "merged_into_id"],
        ["agency_id", "client_id", "id"],
    )
    op.create_index(
        "ix_identity_subjects_client_evidence", table, ["client_id", "last_evidence_at"]
    )

    table = "identity_merges"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("survivor_id", sa.Uuid(), nullable=False),
        sa.Column("merged_id", sa.Uuid(), nullable=False),
        sa.Column("reverses_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("closed_reason", sa.String(length=24), nullable=True),
        sa.Column("survivor_version_before", sa.Integer(), nullable=False),
        sa.Column("merged_version_before", sa.Integer(), nullable=False),
        sa.Column("survivor_version_after", sa.Integer(), nullable=False),
        sa.Column("merged_version_after", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_membership_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        _time("created_at", default=True),
        _time("ended_at", nullable=True),
        _check(
            table,
            "valid_kind_status",
            "(kind = 'merge' AND status IN ('active', 'reversed', 'closed')) "
            "OR (kind = 'unmerge' AND status = 'recorded')",
        ),
        _check(table, "closure", "(status = 'closed') = (closed_reason IS NOT NULL)"),
        _check(table, "valid_closed_reason", f"closed_reason IN ({CLOSED_REASONS})"),
        _check(table, "distinct_participants", "survivor_id <> merged_id"),
        _check(table, "reversal_reference", "(kind = 'unmerge') = (reverses_id IS NOT NULL)"),
        _check(table, "valid_reason_code", f"reason_code IN ({REASON_CODES})"),
        _check(table, "fingerprint", f"fingerprint {HEX64}"),
        _check(
            table,
            "ended",
            "(status IN ('active', 'recorded')) = (ended_at IS NULL)",
        ),
        _client_fk(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=op.f(f"fk_{table}_agency_id_agency_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_merges_scope"),
        sa.UniqueConstraint("client_id", "operation_id", name="uq_identity_merges_operation"),
    )
    op.create_foreign_key(
        "fk_identity_merges_reverses_id_identity_merges",
        table,
        table,
        ["agency_id", "client_id", "reverses_id"],
        ["agency_id", "client_id", "id"],
    )
    # At most one active edge per person in each role; disjointness across roles is checked
    # under the client lock.
    for column in ("survivor_id", "merged_id"):
        op.create_index(
            f"uq_identity_merges_active_{column.split('_')[0]}",
            table,
            ["client_id", column],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        )

    table = "identity_keys"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.SmallInteger(), nullable=False),
        sa.Column("normalizer", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contested_reason", sa.String(length=16), nullable=True),
        _uuids("candidate_ids"),
        sa.Column("merge_id", sa.Uuid(), nullable=True),
        _uuids("original_owner_ids"),
        _uuids("anchor_key_ids"),
        sa.Column("method", sa.String(length=32), nullable=False),
        _time("first_verified_at"),
        _time("last_verified_at"),
        _time("created_at", default=True),
        _check(table, "valid_kind", "kind IN ('email', 'phone', 'customer_ref')"),
        _check(
            table,
            "valid_normalizer",
            "(kind = 'email' AND normalizer = 'email:v1') "
            "OR (kind = 'phone' AND normalizer = 'phone:v1') "
            "OR (kind = 'customer_ref' AND normalizer = 'ref:v1')",
        ),
        _check(table, "key_length", "octet_length(key_bytes) = 32"),
        _check(table, "valid_status", "status IN ('owned', 'contested')"),
        _check(table, "owner", "(status = 'owned') = (subject_id IS NOT NULL)"),
        _check(table, "contested", "(status = 'contested') = (contested_reason IS NOT NULL)"),
        _check(table, "valid_contested_reason", "contested_reason IN ('shared', 'unmerged')"),
        _check(table, "positive_key_version", "key_version >= 1"),
        _client_fk(table),
        _scoped_fk(table, "subject_id", "identity_subjects"),
        _scoped_fk(table, "merge_id", "identity_merges"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_keys_scope"),
        sa.UniqueConstraint("client_id", "kind", "key_bytes", name="uq_identity_keys_value"),
    )
    op.create_index("ix_identity_keys_subject_id", table, ["subject_id"])
    op.create_index("ix_identity_keys_merge_id", table, ["merge_id"])
    # A person holds at most one customer reference (R3).
    op.create_index(
        "uq_identity_keys_customer_ref",
        table,
        ["client_id", "subject_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'customer_ref' AND status = 'owned'"),
    )

    table = "identity_assertions"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("collection_subject_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("proof", sa.String(length=8), nullable=False),
        _time("received_at"),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _uuids("candidate_ids"),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("merge_id", sa.Uuid(), nullable=True),
        _check(
            table,
            "valid_outcome",
            "outcome IN ('linked', 'ambiguous', 'contested_identifier', 'suppressed')",
        ),
        _check(table, "valid_reason", f"reason IS NULL OR reason IN ({ASSERTION_REASONS})"),
        _check(table, "valid_proof", "proof IN ('handoff', 'token')"),
        _check(table, "fingerprint_length", "octet_length(fingerprint) = 32"),
        _check(
            table,
            "suppressed_minimal",
            "outcome <> 'suppressed' OR (reason IS NOT NULL AND subject_id IS NULL "
            "AND merge_id IS NULL AND evidence = '[]'::jsonb AND cardinality(candidate_ids) = 0)",
        ),
        _client_fk(table),
        sa.ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
            name=op.f(f"fk_{table}_agency_id_service_credentials"),
        ),
        _scoped_fk(table, "collection_subject_id", "collection_subjects"),
        _scoped_fk(table, "subject_id", "identity_subjects"),
        _scoped_fk(table, "merge_id", "identity_merges"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_assertions_scope"),
        sa.UniqueConstraint("client_id", "assertion_id", name="uq_identity_assertions_assertion"),
    )
    op.create_index(
        "ix_identity_assertions_collection_subject_id", table, ["collection_subject_id"]
    )
    op.create_index("ix_identity_assertions_subject_id", table, ["subject_id"])

    table = "identity_assertion_receipts"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=False),
        _time("received_at"),
        _time("expires_at"),
        _check(table, "window", "expires_at > received_at"),
        _check(table, "fingerprint_length", "octet_length(fingerprint) = 32"),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "assertion_id", name="uq_identity_receipts_assertion"),
    )
    op.create_index("ix_identity_assertion_receipts_expires_at", table, ["expires_at"])

    table = "identity_links"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("collection_subject_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        _uuids("candidate_ids"),
        sa.Column("assertion_ref", sa.Uuid(), nullable=True),
        _time("asserted_at"),
        _time("eligible_from"),
        _time("provisional_from", nullable=True),
        _time("eligible_until", nullable=True),
        sa.Column("closed_reason", sa.String(length=24), nullable=True),
        sa.Column("merge_id", sa.Uuid(), nullable=True),
        _uuids("original_owner_ids"),
        _uuids("key_ids"),
        _time("grant_started_at"),
        _check(table, "valid_status", "status IN ('active', 'ambiguous', 'neutral')"),
        _check(table, "owner", "(status = 'active') = (subject_id IS NOT NULL)"),
        _check(
            table,
            "neutral_minimal",
            "status <> 'neutral' OR (cardinality(candidate_ids) = 0 "
            "AND cardinality(original_owner_ids) = 0 AND cardinality(key_ids) = 0 "
            "AND merge_id IS NULL AND assertion_ref IS NULL)",
        ),
        _check(
            table,
            "ambiguous_candidates",
            "status <> 'ambiguous' OR cardinality(candidate_ids) >= 1",
        ),
        _check(
            table,
            "interval",
            "eligible_from = asserted_at AND (eligible_until IS NULL "
            "OR eligible_until >= eligible_from) AND (provisional_from IS NULL "
            "OR (status = 'active' AND provisional_from <= eligible_from))",
        ),
        _check(table, "closure", "(eligible_until IS NULL) = (closed_reason IS NULL)"),
        _check(table, "valid_closed_reason", f"closed_reason IN ({LINK_CLOSURES})"),
        _client_fk(table),
        _scoped_fk(table, "collection_subject_id", "collection_subjects"),
        _scoped_fk(table, "subject_id", "identity_subjects"),
        _scoped_fk(table, "assertion_ref", "identity_assertions"),
        _scoped_fk(table, "merge_id", "identity_merges"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index("ix_identity_links_collection_subject_id", table, ["collection_subject_id"])
    op.create_index("ix_identity_links_subject_id", table, ["subject_id"])
    op.create_index("ix_identity_links_merge_id", table, ["merge_id"])

    table = "identity_handoffs"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("collection_subject_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("challenge_digest", sa.String(length=64), nullable=False),
        sa.Column("identity_consent_receipt_id", sa.Uuid(), nullable=False),
        _time("expires_at"),
        _time("consumed_at", nullable=True),
        _time("created_at"),
        _check(table, "code_digest", f"code_digest {HEX64}"),
        _check(table, "challenge_digest", f"challenge_digest {HEX64}"),
        _check(table, "window", "expires_at > created_at"),
        _client_fk(table),
        _scoped_fk(table, "collection_subject_id", "collection_subjects"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "code_digest", name="uq_identity_handoffs_code"),
        sa.UniqueConstraint("client_id", "challenge_digest", name="uq_identity_handoffs_challenge"),
    )
    op.create_index("ix_identity_handoffs_collection_subject_id", table, ["collection_subject_id"])
    op.create_index("ix_identity_handoffs_expires_at", table, ["expires_at"])

    table = "identity_feed_state"
    op.create_table(
        table,
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("pruned_through_seq", sa.BigInteger(), server_default="0", nullable=False),
        _time("updated_at", default=True),
        _check(table, "watermarks", "0 <= pruned_through_seq AND pruned_through_seq <= last_seq"),
        _client_fk(table),
        sa.PrimaryKeyConstraint("client_id", name=op.f(f"pk_{table}")),
    )

    table = "identity_changes"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("journey_revision", sa.BigInteger(), nullable=False),
        _time("occurred_at"),
        _check(table, "valid_kind", f"kind IN ({CHANGE_KINDS})"),
        _check(table, "valid_counters", "seq >= 1 AND journey_revision >= 0"),
        _client_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("client_id", "seq", name="uq_identity_changes_seq"),
    )
    op.create_index("ix_identity_changes_occurred_at", table, ["occurred_at"])

    table = "identity_erasure_holds"
    op.create_table(
        table,
        *_scope_columns(),
        sa.Column("deletion_request_id", sa.Uuid(), nullable=False),
        sa.Column("collected_event_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        _time("held_at"),
        _time("settled_at", nullable=True),
        _check(table, "valid_state", f"state IN ({HOLD_STATES})"),
        _check(table, "held_event", "(state = 'held') = (collected_event_id IS NOT NULL)"),
        _check(table, "settlement", "(state = 'held') = (settled_at IS NULL)"),
        _client_fk(table),
        _scoped_fk(table, "deletion_request_id", "deletion_requests"),
        # R006-23: scoped, without cascade, so a held event cannot be deleted before its hold
        # is settled.
        _scoped_fk(table, "collected_event_id", "collected_events"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            "client_id",
            "deletion_request_id",
            "collected_event_id",
            name="uq_identity_erasure_holds_event",
        ),
    )
    op.create_index("ix_identity_erasure_holds_collected_event_id", table, ["collected_event_id"])
    op.create_index("ix_identity_erasure_holds_deletion_request_id", table, ["deletion_request_id"])

    for statement in GUARDS:
        op.execute(statement)
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (
        *TABLES,
        "audit_events",
        "collection_subjects",
        "collected_events",
        "client_grants",
        "invitation_client_grants",
        "deletion_tombstones",
        "event_diagnostics",
    ):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{item}'" for item in NEW_ACTIONS)
    populated = connection.execute(
        sa.text(
            "SELECT "
            + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
            + f" OR EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}))"
            + " OR EXISTS (SELECT 1 FROM audit_events WHERE resource_type = 'identity_subject')"
            + " OR EXISTS (SELECT 1 FROM deletion_tombstones WHERE match_type IN "
            "('identity_key', 'assertion_id', 'assertion_fp'))"
            + " OR EXISTS (SELECT 1 FROM event_diagnostics WHERE channel = 'identity')"
            + " OR EXISTS (SELECT 1 FROM collection_subjects WHERE issuance_channel <> 'unknown'"
            " OR identity_floor_at IS NOT NULL OR identity_shared_at IS NOT NULL)"
            + " OR EXISTS (SELECT 1 FROM collected_events WHERE identity_excluded_at IS NOT NULL)"
            + " OR EXISTS (SELECT 1 FROM client_grants WHERE can_view_identities)"
            + " OR EXISTS (SELECT 1 FROM invitation_client_grants WHERE can_view_identities)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove identity state; use a forward fix.")
    op.execute("DROP TRIGGER identity_guard_collected_event ON collected_events")
    op.execute("DROP FUNCTION identity_guard_collected_event()")
    op.execute("DROP TRIGGER identity_guard_collection_subject ON collection_subjects")
    op.execute("DROP FUNCTION identity_guard_collection_subject()")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    for table in TABLES:
        op.drop_table(table)
    for table in ("client_grants", "invitation_client_grants"):
        op.drop_column(table, "can_view_identities")
    op.drop_constraint("uq_collected_events_scope", "collected_events", type_="unique")
    op.drop_column("collected_events", "identity_excluded_at")
    op.drop_constraint(
        op.f("ck_collection_subjects_valid_issuance"), "collection_subjects", type_="check"
    )
    for column in ("identity_shared_at", "identity_floor_at", "issuance_channel"):
        op.drop_column("collection_subjects", column)
    _replace_check("event_diagnostics", "valid_channel", PREVIOUS_CHANNELS)
    _replace_check("deletion_tombstones", "valid_match_type", PREVIOUS_MATCH_TYPES)
    _replace_check("audit_events", "valid_resource", PREVIOUS_RESOURCES)
    _replace_check("audit_events", "valid_action", PREVIOUS_ACTIONS)
