"""Client-scoped identity evidence, segments, merges and the change feed (specification 006).

D-075 (joint decisions J2-J7) approves the schema of design revision 4 section 12.1 as amended
by the joint addendum, in migration 0026_identity_journey. Every table carries agency and
client scope with composite foreign keys, so a key, link, merge or hold can never reference a
row of another client. No column holds a raw email address, phone number, account reference,
subject token, handoff code or challenge: identifiers are HMAC pseudonyms under a per-client
matching key, and codes and challenges are stored as SHA-256 digests. UUID arrays (candidate,
original-owner and key references) are validated against the same client under the client
privacy lock; they are not foreign keys. Reference queries below are manual read-only
diagnostics for an authorized operator; replace the synthetic literals before use. Key bytes,
fingerprints, digests and sealed material are omitted.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
EMPTY_UUIDS = text("'{}'::uuid[]")
HEX64 = "~ '^[0-9a-f]{64}$'"


def _scoped(table: str, column: str, target: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["agency_id", "client_id", column],
        [f"{target}.agency_id", f"{target}.client_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}"[:63],
    )


def _uuids() -> Any:
    return mapped_column(ARRAY(Uuid), server_default=EMPTY_UUIDS)


# The per-client matching key, sealed with the token envelope (kind identity_matching_key) under
# the D-025 local development keyring. Created once per client under its privacy lock; a rewrap
# preserves its bytes, so keys and identity_key tombstones keep matching.
# SELECT id, client_id, version, kek_id, created_at
# FROM public.identity_key_secrets
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid;
class IdentityKeySecret(Base):
    __tablename__ = "identity_key_secrets"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "version", name="uq_identity_key_secrets_version"),
        CheckConstraint("version >= 1", name="positive_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    kek_id: Mapped[str] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One client-scoped person. It carries no identifier value. version is the optimistic
# concurrency counter of corrections; journey_revision changes once per transaction that
# changes the visible journey (design section 9.1).
# SELECT id, status, merged_into_id, version, journey_revision, last_evidence_at
# FROM public.identity_subjects
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY last_evidence_at DESC, id LIMIT 100;
class IdentitySubject(Base):
    __tablename__ = "identity_subjects"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_subjects_scope"),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "merged_into_id"],
            [
                "identity_subjects.agency_id",
                "identity_subjects.client_id",
                "identity_subjects.id",
            ],
            name="fk_identity_subjects_merged_into_id_identity_subjects",
        ),
        CheckConstraint("status IN ('active', 'merged')", name="valid_status"),
        CheckConstraint("(status = 'merged') = (merged_into_id IS NOT NULL)", name="merge_pointer"),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="not_self_merged"),
        CheckConstraint("version >= 1 AND journey_revision >= 0", name="valid_counters"),
        Index("ix_identity_subjects_client_evidence", "client_id", "last_evidence_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    merged_into_id: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    journey_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# The merge ledger (D10): disjoint pointer merges and their reversals, idempotent by operation
# ID. Participants are historical references validated under the client lock (no foreign key),
# so a closed entry can outlive a participant that lost its evidence.
# SELECT id, operation_id, kind, survivor_id, merged_id, reverses_id, status, closed_reason,
#        reason_code, created_at, ended_at
# FROM public.identity_merges
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at DESC, id LIMIT 100;
class IdentityMerge(Base):
    __tablename__ = "identity_merges"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "actor_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        ForeignKeyConstraint(
            ["agency_id", "client_id", "reverses_id"],
            ["identity_merges.agency_id", "identity_merges.client_id", "identity_merges.id"],
            name="fk_identity_merges_reverses_id_identity_merges",
        ),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_merges_scope"),
        UniqueConstraint("client_id", "operation_id", name="uq_identity_merges_operation"),
        Index(
            "uq_identity_merges_active_survivor",
            "client_id",
            "survivor_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_identity_merges_active_merged",
            "client_id",
            "merged_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "(kind = 'merge' AND status IN ('active', 'reversed', 'closed')) "
            "OR (kind = 'unmerge' AND status = 'recorded')",
            name="valid_kind_status",
        ),
        CheckConstraint("(status = 'closed') = (closed_reason IS NOT NULL)", name="closure"),
        CheckConstraint(
            "closed_reason IN ('participant_expired', 'participant_withdrew', "
            "'participant_erased')",
            name="valid_closed_reason",
        ),
        CheckConstraint("survivor_id <> merged_id", name="distinct_participants"),
        CheckConstraint(
            "(kind = 'unmerge') = (reverses_id IS NOT NULL)", name="reversal_reference"
        ),
        CheckConstraint(
            "reason_code IN ('same_person_confirmed_by_client', 'duplicate_account', "
            "'data_correction')",
            name="valid_reason_code",
        ),
        CheckConstraint(f"fingerprint {HEX64}", name="fingerprint"),
        CheckConstraint("(status IN ('active', 'recorded')) = (ended_at IS NULL)", name="ended"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    survivor_id: Mapped[UUID] = mapped_column(Uuid)
    merged_id: Mapped[UUID] = mapped_column(Uuid)
    reverses_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    closed_reason: Mapped[str | None] = mapped_column(String(24))
    survivor_version_before: Mapped[int] = mapped_column(Integer)
    merged_version_before: Mapped[int] = mapped_column(Integer)
    survivor_version_after: Mapped[int] = mapped_column(Integer)
    merged_version_after: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_membership_id: Mapped[UUID] = mapped_column(Uuid)
    reason_code: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One keyed identifier of one client (kind and normalizer version, never the value). An owned
# key names its original owner; a contested key names nobody and keeps its candidates.
# SELECT id, kind, normalizer, status, contested_reason, subject_id, merge_id, method,
#        last_verified_at
# FROM public.identity_keys
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
#   AND subject_id = '00000000-0000-0000-0000-000000000101'::uuid;
class IdentityKey(Base):
    __tablename__ = "identity_keys"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("identity_keys", "subject_id", "identity_subjects"),
        _scoped("identity_keys", "merge_id", "identity_merges"),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_keys_scope"),
        UniqueConstraint("client_id", "kind", "key_bytes", name="uq_identity_keys_value"),
        Index("ix_identity_keys_subject_id", "subject_id"),
        Index("ix_identity_keys_merge_id", "merge_id"),
        Index(
            "uq_identity_keys_customer_ref",
            "client_id",
            "subject_id",
            unique=True,
            postgresql_where=text("kind = 'customer_ref' AND status = 'owned'"),
        ),
        CheckConstraint("kind IN ('email', 'phone', 'customer_ref')", name="valid_kind"),
        CheckConstraint(
            "(kind = 'email' AND normalizer = 'email:v1') "
            "OR (kind = 'phone' AND normalizer = 'phone:v1') "
            "OR (kind = 'customer_ref' AND normalizer = 'ref:v1')",
            name="valid_normalizer",
        ),
        CheckConstraint("octet_length(key_bytes) = 32", name="key_length"),
        CheckConstraint("status IN ('owned', 'contested')", name="valid_status"),
        CheckConstraint("(status = 'owned') = (subject_id IS NOT NULL)", name="owner"),
        CheckConstraint(
            "(status = 'contested') = (contested_reason IS NOT NULL)", name="contested"
        ),
        CheckConstraint(
            "contested_reason IN ('shared', 'unmerged')", name="valid_contested_reason"
        ),
        CheckConstraint("key_version >= 1", name="positive_key_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    key_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(SmallInteger)
    normalizer: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    contested_reason: Mapped[str | None] = mapped_column(String(16))
    candidate_ids: Mapped[list[UUID]] = _uuids()
    merge_id: Mapped[UUID | None] = mapped_column(Uuid)
    original_owner_ids: Mapped[list[UUID]] = _uuids()
    # The keys whose ownership anchored this key's creation; re-evaluated after an unmerge.
    anchor_key_ids: Mapped[list[UUID]] = _uuids()
    method: Mapped[str] = mapped_column(String(32))
    first_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Evidence of one applied (or suppressed) identity assertion: sender ID, credential, collection
# subject, keyed request fingerprint, per-identifier evidence (key ID, kind, method, verified_at,
# original owner) and the internal outcome. A suppressed row is minimal and links nobody.
# SELECT id, assertion_id, collection_subject_id, proof, received_at, outcome, reason,
#        subject_id, candidate_ids
# FROM public.identity_assertions
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY received_at DESC, id LIMIT 100;
class IdentityAssertion(Base):
    __tablename__ = "identity_assertions"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "credential_id"],
            ["service_credentials.agency_id", "service_credentials.id"],
        ),
        _scoped("identity_assertions", "collection_subject_id", "collection_subjects"),
        _scoped("identity_assertions", "subject_id", "identity_subjects"),
        _scoped("identity_assertions", "merge_id", "identity_merges"),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_identity_assertions_scope"),
        UniqueConstraint("client_id", "assertion_id", name="uq_identity_assertions_assertion"),
        Index("ix_identity_assertions_collection_subject_id", "collection_subject_id"),
        Index("ix_identity_assertions_subject_id", "subject_id"),
        CheckConstraint(
            "outcome IN ('linked', 'ambiguous', 'contested_identifier', 'suppressed')",
            name="valid_outcome",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN ('replay_before_deletion', 'assertion_id_reused', "
            "'no_consent_after_deletion', 'subject_objected')",
            name="valid_reason",
        ),
        CheckConstraint("proof IN ('handoff', 'token')", name="valid_proof"),
        CheckConstraint("octet_length(fingerprint) = 32", name="fingerprint_length"),
        CheckConstraint(
            "outcome <> 'suppressed' OR (reason IS NOT NULL AND subject_id IS NULL "
            "AND merge_id IS NULL AND evidence = '[]'::jsonb AND cardinality(candidate_ids) = 0)",
            name="suppressed_minimal",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    assertion_id: Mapped[UUID] = mapped_column(Uuid)
    credential_id: Mapped[UUID] = mapped_column(Uuid)
    collection_subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary)
    proof: Mapped[str] = mapped_column(String(8))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(32))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    candidate_ids: Mapped[list[UUID]] = _uuids()
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    merge_id: Mapped[UUID | None] = mapped_column(Uuid)


# Public retry receipt (D7/D12): assertion ID, keyed fingerprint and a 24-hour window. It names
# no person, key, collection subject, outcome or reason and survives W1 and erasure.
# SELECT id, assertion_id, received_at, expires_at
# FROM public.identity_assertion_receipts
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY expires_at LIMIT 100;
class IdentityAssertionReceipt(Base):
    __tablename__ = "identity_assertion_receipts"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "assertion_id", name="uq_identity_receipts_assertion"),
        Index("ix_identity_assertion_receipts_expires_at", "expires_at"),
        CheckConstraint("expires_at > received_at", name="window"),
        CheckConstraint("octet_length(fingerprint) = 32", name="fingerprint_length"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    assertion_id: Mapped[UUID] = mapped_column(Uuid)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# One segment of a collection subject (design section 4.4): owned (status active, one person),
# ambiguous (candidates only) or neutral (names nobody). eligible_from is the assertion receipt;
# provisional_from is the adopted provisional prefix (R006-27); eligible_until is the exclusive
# end of a closed segment.
# SELECT id, collection_subject_id, status, subject_id, candidate_ids, asserted_at,
#        provisional_from, eligible_until, closed_reason, merge_id
# FROM public.identity_links
# WHERE collection_subject_id = '00000000-0000-0000-0000-000000000010'::uuid
# ORDER BY asserted_at, id LIMIT 100;
class IdentityLink(Base):
    __tablename__ = "identity_links"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("identity_links", "collection_subject_id", "collection_subjects"),
        _scoped("identity_links", "subject_id", "identity_subjects"),
        _scoped("identity_links", "assertion_ref", "identity_assertions"),
        _scoped("identity_links", "merge_id", "identity_merges"),
        Index("ix_identity_links_collection_subject_id", "collection_subject_id"),
        Index("ix_identity_links_subject_id", "subject_id"),
        Index("ix_identity_links_merge_id", "merge_id"),
        CheckConstraint("status IN ('active', 'ambiguous', 'neutral')", name="valid_status"),
        CheckConstraint("(status = 'active') = (subject_id IS NOT NULL)", name="owner"),
        CheckConstraint(
            "status <> 'neutral' OR (cardinality(candidate_ids) = 0 "
            "AND cardinality(original_owner_ids) = 0 AND cardinality(key_ids) = 0 "
            "AND merge_id IS NULL AND assertion_ref IS NULL)",
            name="neutral_minimal",
        ),
        CheckConstraint(
            "status <> 'ambiguous' OR cardinality(candidate_ids) >= 1",
            name="ambiguous_candidates",
        ),
        CheckConstraint(
            "eligible_from = asserted_at AND (eligible_until IS NULL "
            "OR eligible_until >= eligible_from) AND (provisional_from IS NULL "
            "OR (status = 'active' AND provisional_from <= eligible_from))",
            name="interval",
        ),
        CheckConstraint("(eligible_until IS NULL) = (closed_reason IS NULL)", name="closure"),
        CheckConstraint(
            "closed_reason IN ('switched', 'ambiguous', 'neutral_boundary', 'consent_ended', "
            "'merge_reversed', 'participant_lost', 'erased')",
            name="valid_closed_reason",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    collection_subject_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    candidate_ids: Mapped[list[UUID]] = _uuids()
    assertion_ref: Mapped[UUID | None] = mapped_column(Uuid)
    asserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eligible_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provisional_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(String(24))
    merge_id: Mapped[UUID | None] = mapped_column(Uuid)
    original_owner_ids: Mapped[list[UUID]] = _uuids()
    key_ids: Mapped[list[UUID]] = _uuids()
    grant_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# A one-time browser handoff (D3): digests of the code and the backend challenge, bound to one
# browser-issued collection subject and the identity grant receipt in force at issuance.
# SELECT id, collection_subject_id, identity_consent_receipt_id, expires_at, consumed_at
# FROM public.identity_handoffs
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY expires_at LIMIT 100;
class IdentityHandoff(Base):
    __tablename__ = "identity_handoffs"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("identity_handoffs", "collection_subject_id", "collection_subjects"),
        UniqueConstraint("client_id", "code_digest", name="uq_identity_handoffs_code"),
        UniqueConstraint("client_id", "challenge_digest", name="uq_identity_handoffs_challenge"),
        Index("ix_identity_handoffs_collection_subject_id", "collection_subject_id"),
        Index("ix_identity_handoffs_expires_at", "expires_at"),
        CheckConstraint(f"code_digest {HEX64}", name="code_digest"),
        CheckConstraint(f"challenge_digest {HEX64}", name="challenge_digest"),
        CheckConstraint("expires_at > created_at", name="window"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    collection_subject_id: Mapped[UUID] = mapped_column(Uuid)
    code_digest: Mapped[str] = mapped_column(String(64))
    challenge_digest: Mapped[str] = mapped_column(String(64))
    identity_consent_receipt_id: Mapped[UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# One client's change-feed watermarks (design section 11.1): the committed high watermark and
# the highest sequence removed by retention. Survives an empty feed and every erasure.
# SELECT client_id, last_seq, pruned_through_seq, updated_at
# FROM public.identity_feed_state
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid;
class IdentityFeedState(Base):
    __tablename__ = "identity_feed_state"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        CheckConstraint(
            "0 <= pruned_through_seq AND pruned_through_seq <= last_seq", name="watermarks"
        ),
    )
    client_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    last_seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    pruned_through_seq: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# One change record per affected person and revision, in contiguous per-client sequence order.
# A removal record survives the deletion of its person.
# SELECT seq, person_id, kind, journey_revision, occurred_at
# FROM public.identity_changes
# WHERE client_id = '00000000-0000-0000-0000-000000000003'::uuid AND seq > 0
# ORDER BY seq LIMIT 100;
class IdentityChange(Base):
    __tablename__ = "identity_changes"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        UniqueConstraint("client_id", "seq", name="uq_identity_changes_seq"),
        Index("ix_identity_changes_occurred_at", "occurred_at"),
        CheckConstraint(
            "kind IN ('linked', 'unlinked', 'contested', 'merged', 'unmerged', 'merge_closed', "
            "'erased', 'withdrawn', 'expired', 'events_changed')",
            name="valid_kind",
        ),
        CheckConstraint("seq >= 1 AND journey_revision >= 0", name="valid_counters"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    seq: Mapped[int] = mapped_column(BigInteger)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    journey_revision: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# One event held by one erasure request (design section 7.2). A settled row keeps its state and
# times but no event reference; the scoped foreign key refuses deletion of a held event.
# SELECT id, deletion_request_id, state, held_at, settled_at
# FROM public.identity_erasure_holds
# WHERE deletion_request_id = '00000000-0000-0000-0000-000000000501'::uuid
# ORDER BY held_at, id LIMIT 100;
class IdentityErasureHold(Base):
    __tablename__ = "identity_erasure_holds"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        _scoped("identity_erasure_holds", "deletion_request_id", "deletion_requests"),
        _scoped("identity_erasure_holds", "collected_event_id", "collected_events"),
        UniqueConstraint(
            "client_id",
            "deletion_request_id",
            "collected_event_id",
            name="uq_identity_erasure_holds_event",
        ),
        Index("ix_identity_erasure_holds_collected_event_id", "collected_event_id"),
        Index("ix_identity_erasure_holds_deletion_request_id", "deletion_request_id"),
        CheckConstraint(
            "state IN ('held', 'erased', 'retained', 'expired', 'erased_elsewhere')",
            name="valid_state",
        ),
        CheckConstraint("(state = 'held') = (collected_event_id IS NOT NULL)", name="held_event"),
        CheckConstraint("(state = 'held') = (settled_at IS NULL)", name="settlement"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    deletion_request_id: Mapped[UUID] = mapped_column(Uuid)
    collected_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(16))
    held_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
