"""DeletionRequest contract, keyed identifiers, and tombstone admission (specification 003-B).

D-025 decision 10: anything identified as received before a deletion is blocked if replayed;
new collection about a deleted subject is admitted only with consent recorded after the
deletion, unless the subject objected; subject tombstones last for the workspace lifetime and
are not purged by the lifecycle runner (only client offboarding in 017 removes them). Blocking
uses server receipt times and event, idempotency, or provider object keys, never client time.
"""

import hashlib
import hmac
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.privacy.consent import Decision
from app.security import normalize_email

SUBJECT_DOMAIN = "subject:v1"
TOMBSTONE_DOMAIN = "tombstone:v1"


class ScopeKind(StrEnum):
    SUBJECT = "subject"
    CONNECTOR = "connector"
    CLIENT = "client"
    AGENCY = "agency"
    USER_ACCOUNT = "user_account"


class RequesterKind(StrEnum):
    CLIENT_ADMIN = "client_admin"
    AGENCY_ADMIN = "agency_admin"
    PROVIDER_CALLBACK = "provider_callback"
    PLATFORM_OPERATOR = "platform_operator"
    CONSENT_WITHDRAWAL = "consent_withdrawal"
    # The holder of a pseudonymous subject token erasing that subject (004, D-027).
    DATA_SUBJECT = "data_subject"


class RequestStatus(StrEnum):
    RECEIVED = "received"
    VERIFYING = "verifying"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PAUSED_FOR_CLARIFICATION = "paused_for_clarification"
    ON_HOLD = "on_hold"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    VERIFIED = "verified"


class TargetStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


S = RequestStatus
TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    S.RECEIVED: frozenset({S.VERIFYING, S.REJECTED}),
    S.VERIFYING: frozenset({S.ACCEPTED, S.REJECTED, S.PAUSED_FOR_CLARIFICATION}),
    S.PAUSED_FOR_CLARIFICATION: frozenset({S.VERIFYING, S.REJECTED}),
    S.ACCEPTED: frozenset({S.IN_PROGRESS, S.ON_HOLD}),
    S.ON_HOLD: frozenset({S.IN_PROGRESS}),
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.PARTIALLY_COMPLETED, S.ON_HOLD}),
    S.COMPLETED: frozenset({S.VERIFIED}),
    S.PARTIALLY_COMPLETED: frozenset({S.IN_PROGRESS}),
    S.REJECTED: frozenset(),
    S.VERIFIED: frozenset(),
}


class InvalidTransition(ValueError):
    pass


def transition(current: RequestStatus, new: RequestStatus) -> RequestStatus:
    if new not in TRANSITIONS[current]:
        raise InvalidTransition(f"{current.value} -> {new.value}")
    return new


# Result of a run over the request's targets: None while any target is pending; completed
# only when every target is done or not applicable. Unsupported and failed targets make the
# request partially completed and are reported, never counted as done.
def outcome(targets: Mapping[str, TargetStatus]) -> RequestStatus | None:
    statuses = set(targets.values())
    if not statuses or TargetStatus.PENDING in statuses:
        return None
    if statuses <= {TargetStatus.DONE, TargetStatus.NOT_APPLICABLE}:
        return RequestStatus.COMPLETED
    return RequestStatus.PARTIALLY_COMPLETED


# Canonical identifier for keyed matching, separate from any provider normalizer. Email:
# the account convention (trimmed, lowercased, no dot or plus rewriting). Phone: "+" and the
# digits of an international number ("+" or "00" prefix), or of a national number with the
# client's default country code after one leading trunk zero is removed; the trunk-zero rule
# is a candidate for review in specification 006.
def canonical_identifier(
    kind: Literal["email", "phone"], value: str, *, default_country_code: str | None = None
) -> str:
    if kind == "email":
        return normalize_email(value.strip())
    text = value.strip()
    digits = "".join(character for character in text if character.isdigit())
    if text.startswith("+"):
        national = digits
    elif digits.startswith("00"):
        national = digits[2:]
    elif default_country_code and default_country_code.isdigit():
        national = default_country_code + (digits[1:] if digits.startswith("0") else digits)
    else:
        raise ValueError("A phone number needs an international prefix or country code.")
    if not 8 <= len(national) <= 15:
        raise ValueError("A phone number must have 8 to 15 digits.")
    return "+" + national


# HMAC-SHA256 over a length-prefixed encoding of domain, client, kind, and canonical value.
# The client ID is part of the message, so keys never link subjects across clients.
def keyed_identifier(key: bytes, domain: str, client_id: UUID, kind: str, value: str) -> bytes:
    if len(key) < 32:
        raise ValueError("Keyed identifiers need at least 32 key bytes.")
    message = b"".join(
        len(part).to_bytes(4, "big") + part
        for part in (domain.encode(), client_id.bytes, kind.encode(), value.encode())
    )
    return hmac.new(key, message, hashlib.sha256).digest()


# Internal subject key under a random per-client key; destroying that key makes every
# pseudonym of the client unlinkable.
def subject_key(client_key: bytes, client_id: UUID, kind: str, canonical: str) -> bytes:
    return keyed_identifier(client_key, SUBJECT_DOMAIN, client_id, kind, canonical)


# Tombstone match key under the independent tombstone key, for subjects ("email", "phone")
# and for replay keys ("event_id", "idempotency_key", "provider_object").
def tombstone_key(tombstone_secret: bytes, client_id: UUID, kind: str, value: str) -> bytes:
    return keyed_identifier(tombstone_secret, TOMBSTONE_DOMAIN, client_id, kind, value)


@dataclass(frozen=True)
class Tombstone:
    id: UUID
    agency_id: UUID
    client_id: UUID
    scope_kind: ScopeKind
    match_type: str
    match_key: bytes
    match_key_id: str
    deletion_request_id: UUID
    effective_at: datetime
    objected: bool = False


# Admission check at ingestion, identity linking, enqueue, delivery, and imports (E2-E6).
# subject_tombstones are the tombstones matching the event's subject keys; replay_keys are
# the tombstone keys of the event's own ID, idempotency key, or provider object ID.
def admission(
    *,
    subject_tombstones: Iterable[Tombstone],
    replay_tombstones: Iterable[Tombstone],
    consent_received_at: datetime | None,
) -> Decision:
    if any(True for _ in replay_tombstones):
        return Decision(False, "replay_before_deletion")
    subjects = list(subject_tombstones)
    if not subjects:
        return Decision(True, "not_deleted")
    if any(item.objected for item in subjects):
        return Decision(False, "subject_objected")
    latest = max(item.effective_at for item in subjects)
    if consent_received_at is None or consent_received_at <= latest:
        return Decision(False, "no_consent_after_deletion")
    return Decision(True, "consent_after_deletion")
