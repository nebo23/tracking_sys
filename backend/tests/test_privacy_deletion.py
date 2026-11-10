"""DeletionRequest, keyed identifiers, and tombstone admission (specification 003-B)."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.privacy.consent import Decision
from app.privacy.deletion import (
    InvalidTransition,
    RequestStatus,
    ScopeKind,
    TargetStatus,
    Tombstone,
    admission,
    canonical_identifier,
    outcome,
    subject_key,
    tombstone_key,
    transition,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)
CLIENT, OTHER_CLIENT = uuid4(), uuid4()
TOMBSTONE_SECRET = secrets.token_bytes(32)


def tombstone(value, kind="email", *, at=NOW, objected=False):
    return Tombstone(
        id=uuid4(),
        agency_id=uuid4(),
        client_id=CLIENT,
        scope_kind=ScopeKind.SUBJECT,
        match_type=kind,
        match_key=tombstone_key(TOMBSTONE_SECRET, CLIENT, kind, value),
        match_key_id="tombstone-key-1",
        deletion_request_id=uuid4(),
        effective_at=at,
        objected=objected,
    )


def test_request_lifecycle_allows_only_listed_transitions():
    status = RequestStatus.RECEIVED
    for new in (
        RequestStatus.VERIFYING,
        RequestStatus.ACCEPTED,
        RequestStatus.IN_PROGRESS,
        RequestStatus.COMPLETED,
        RequestStatus.VERIFIED,
    ):
        status = transition(status, new)
    with pytest.raises(InvalidTransition):
        transition(RequestStatus.RECEIVED, RequestStatus.COMPLETED)
    with pytest.raises(InvalidTransition):
        transition(RequestStatus.VERIFIED, RequestStatus.IN_PROGRESS)


def test_d4_unsupported_or_failed_targets_are_never_reported_done():
    done = {"raw_events": TargetStatus.DONE, "cache": TargetStatus.NOT_APPLICABLE}
    assert outcome(done) is RequestStatus.COMPLETED
    assert outcome({**done, "provider": TargetStatus.UNSUPPORTED}) is (
        RequestStatus.PARTIALLY_COMPLETED
    )
    assert outcome({**done, "export": TargetStatus.FAILED}) is RequestStatus.PARTIALLY_COMPLETED
    assert outcome({**done, "derived": TargetStatus.PENDING}) is None
    assert outcome({}) is None


def test_identifiers_are_canonicalized_without_provider_rewrites():
    assert canonical_identifier("email", "  First.Last+tag@Example.TEST ") == (
        "first.last+tag@example.test"
    )
    assert canonical_identifier("phone", "+20 100 123 4567") == "+201001234567"
    assert canonical_identifier("phone", "0020 100 123 4567") == "+201001234567"
    assert canonical_identifier("phone", "0100 123 4567", default_country_code="20") == (
        "+201001234567"
    )
    with pytest.raises(ValueError):
        canonical_identifier("phone", "0100 123 4567")


def test_keys_are_domain_and_client_separated():
    value = canonical_identifier("email", "person@example.test")
    client_key = secrets.token_bytes(32)
    subject = subject_key(client_key, CLIENT, "email", value)
    assert subject != tombstone_key(client_key, CLIENT, "email", value)
    assert subject != subject_key(client_key, OTHER_CLIENT, "email", value)
    assert len(subject) == 32
    with pytest.raises(ValueError):
        subject_key(b"short", CLIENT, "email", value)


def test_d5_destroying_a_client_key_makes_old_pseudonyms_unmatchable():
    value = canonical_identifier("email", "person@example.test")
    old = subject_key(secrets.token_bytes(32), CLIENT, "email", value)
    assert subject_key(secrets.token_bytes(32), CLIENT, "email", value) != old


def test_d2_replay_of_a_pre_deletion_event_is_rejected():
    replay = tombstone("event-0001", kind="event_id")
    assert admission(
        subject_tombstones=[],
        replay_tombstones=[replay],
        consent_received_at=NOW + timedelta(days=1),
    ) == Decision(False, "replay_before_deletion")


def test_new_collection_needs_consent_recorded_after_deletion():
    deleted = [tombstone("person@example.test")]
    assert admission(
        subject_tombstones=deleted, replay_tombstones=[], consent_received_at=None
    ) == Decision(False, "no_consent_after_deletion")
    assert admission(
        subject_tombstones=deleted, replay_tombstones=[], consent_received_at=NOW
    ) == Decision(False, "no_consent_after_deletion")
    assert admission(
        subject_tombstones=deleted,
        replay_tombstones=[],
        consent_received_at=NOW + timedelta(seconds=1),
    ) == Decision(True, "consent_after_deletion")


def test_an_objection_blocks_even_with_new_consent():
    assert admission(
        subject_tombstones=[tombstone("person@example.test", objected=True)],
        replay_tombstones=[],
        consent_received_at=NOW + timedelta(days=30),
    ) == Decision(False, "subject_objected")


def test_subjects_without_tombstones_are_admitted():
    assert admission(subject_tombstones=[], replay_tombstones=[], consent_received_at=None) == (
        Decision(True, "not_deleted")
    )
