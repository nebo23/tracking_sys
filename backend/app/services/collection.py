"""Event admission, consent, erasure, and collection administration (specification 004, D-027).

Every operation that reads or changes a client's privacy state (event admission, consent
changes, erasure) first takes one transaction-scoped advisory lock for that client, then reads
the receipt time from the database clock, re-resolves live scope, and only then reads consent
and tombstones. A withdrawal or erasure therefore either commits before an event's check, which
then observes it, or waits for the event to commit and then removes or supersedes it. Lock order:
an agency row lock (audited administration) may come before the client lock; while the client
lock is held, only rows of the 004 tables are locked.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Engine, delete, exists, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.collection.contract import (
    POLICY_VERSION,
    REQUIRED_PURPOSES,
    TRUST_RANK,
    Envelope,
    FormDefinition,
    Rejected,
    check_occurred_at,
    fingerprint,
    is_exact_origin,
    minimize_payload,
    parse_payload,
    traffic_label,
)
from app.collection.keys import TombstoneKeyring
from app.config import Settings
from app.models import (
    Agency,
    ClientWorkspace,
    CollectedEvent,
    CollectionForm,
    CollectionSubject,
    EventDiagnostic,
    IngestionSource,
    IngestionSourceSecret,
    ManagedLink,
    StoredConsentRecord,
    StoredTombstone,
    SubjectDeletionRequest,
)
from app.privacy import consent, deletion
from app.privacy.consent import ConsentRecord, ConsentSource, ConsentState, Profile, Purpose
from app.privacy.deletion import RequesterKind, RequestStatus, TargetStatus, Tombstone
from app.privacy.token_secrets import (
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_secret,
    seal,
)
from app.security import digest, new_token
from app.services.tenancy import AccessDenied, TenancyService

# Two-key advisory namespace of specification 004 (003 uses 3003); the second key is derived
# from the client ID. A shared hash only serializes two clients; it never authorizes.
LOCK_NAMESPACE = 4004
LOCK_TIMEOUT = "2s"
EVENT_RETENTION = timedelta(days=395)
CONSENT_VALIDITY = timedelta(days=365)
SECRET_OVERLAP = timedelta(hours=24)
# For opaque random subject tokens the SHA-256 token digest is the ConsentRecord subject_ref:
# it cannot be enumerated, so no key is involved. Keyed identifiers for email or phone are 006.
SUBJECT_REF_KEY_ID = "sha256-token"
PURPOSES = tuple(purpose for purpose in Purpose if purpose is not Purpose.NECESSARY)


# A collection failure with a public code and HTTP status; the API maps it to {"error": code}.
class CollectionError(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Channel:
    kind: Literal["browser", "server", "webhook"]
    source_id: UUID | None = None
    credential_id: UUID | None = None

    @property
    def trust_rank(self) -> int:
        return TRUST_RANK[self.kind]


@dataclass(frozen=True)
class Admission:
    outcome: Literal["accepted", "duplicate", "conflict", "upgraded", "rejected", "suppressed"]
    reason: str
    revision: int | None = None


@dataclass(frozen=True)
class ConsentView:
    states: dict[Purpose, ConsentState]
    latest: dict[Purpose, ConsentRecord] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsentResult:
    subject_token: str | None
    receipts: list[UUID]
    states: dict[Purpose, ConsentState]


# Current consent of a token holder (005 consent-state); "unknown" for a missing or erased
# subject, without saying which.
@dataclass(frozen=True)
class ConsentStateView:
    status: Literal["active", "unknown"]
    states: dict[Purpose, ConsentState]
    expires_at: dict[Purpose, datetime]
    server_time: datetime


def require_tombstone_keys(settings: Settings) -> TombstoneKeyring:
    keys = settings.tombstone_keys()
    if keys is None:
        raise CollectionError("collection_not_configured", 503)
    return keys


def require_token_keys(settings: Settings) -> LocalKeyring:
    keys = settings.token_keys()
    if keys is None:
        raise CollectionError("collection_not_configured", 503)
    return keys


# Second key of a client's privacy lock in namespace LOCK_NAMESPACE. Admission, consent changes,
# erasure, and lifecycle expiry of collected data all use it (D-027 decision 10).
def client_lock_key(client_id: UUID) -> int:
    return int.from_bytes(client_id.bytes[:4], "big", signed=True)


# Take the client's privacy lock (waiting at most LOCK_TIMEOUT; a timeout surfaces as a
# retryable database error) and return the database clock read after the lock is held, which
# orders receipts in the order the lock serialized them.
def lock_client(session: Session, client_id: UUID) -> datetime:
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    session.execute(select(func.pg_advisory_xact_lock(LOCK_NAMESPACE, client_lock_key(client_id))))
    return session.scalar(select(func.clock_timestamp()))


# Increment one daily counter (closed reason codes only; never a subject or content).
def count(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    day: date,
    channel: str,
    outcome: str,
    reason: str,
    amount: int = 1,
) -> None:
    statement = insert(EventDiagnostic).values(
        id=uuid4(),
        agency_id=agency_id,
        client_id=client_id,
        day=day,
        channel=channel,
        outcome=outcome,
        reason=reason,
        count=amount,
    )
    session.execute(
        statement.on_conflict_do_update(
            constraint="uq_event_diagnostics_key",
            set_={"count": EventDiagnostic.count + amount},
        )
    )


# An active source of the given kind whose client and agency are active, by public key or ID.
def live_source(
    session: Session,
    kind: Literal["browser", "webhook"],
    *,
    public_key: str | None = None,
    source_id: UUID | None = None,
) -> IngestionSource | None:
    query = (
        select(IngestionSource)
        .join(
            ClientWorkspace,
            (ClientWorkspace.agency_id == IngestionSource.agency_id)
            & (ClientWorkspace.id == IngestionSource.client_id),
        )
        .join(Agency, Agency.id == IngestionSource.agency_id)
        .where(
            IngestionSource.kind == kind,
            IngestionSource.status == "active",
            ClientWorkspace.status == "active",
            Agency.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if public_key is not None:
        query = query.where(IngestionSource.public_key == public_key)
    elif source_id is not None:
        query = query.where(IngestionSource.id == source_id)
    else:
        return None
    return session.scalar(query)


# Registered Origins of the active browser source behind a public key, in a short read-only
# unit of work; empty for unknown or inactive sources. Used to answer CORS preflights.
def browser_origins(engine: Engine, public_key: str) -> frozenset[str]:
    with Session(engine) as session:
        source = live_source(session, "browser", public_key=public_key)
        return frozenset(source.allowed_origins or ()) if source is not None else frozenset()


def require_live_source(session: Session, kind: Literal["browser", "webhook"], source_id: UUID):
    if live_source(session, kind, source_id=source_id) is None:
        raise CollectionError("source_unavailable", 404)


# The subject of a token in this client, locked against concurrent lifecycle deletion. A
# token of another client is unknown here.
def find_subject(session: Session, client_id: UUID, token: str) -> CollectionSubject | None:
    return session.scalar(
        select(CollectionSubject)
        .where(
            CollectionSubject.client_id == client_id,
            CollectionSubject.token_digest == digest(token),
        )
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


def _tombstones(
    session: Session, client_id: UUID, match_type: str, candidates: list[bytes]
) -> list[Tombstone]:
    rows = session.scalars(
        select(StoredTombstone).where(
            StoredTombstone.client_id == client_id,
            StoredTombstone.match_type == match_type,
            StoredTombstone.match_key.in_(candidates),
        )
    )
    return [
        Tombstone(
            id=row.id,
            agency_id=row.agency_id,
            client_id=row.client_id,
            scope_kind=deletion.ScopeKind(row.scope_kind),
            match_type=row.match_type,
            match_key=row.match_key,
            match_key_id=row.match_key_id,
            deletion_request_id=row.deletion_request_id,
            effective_at=row.effective_at,
            objected=row.objected,
        )
        for row in rows
    ]


def _contract_record(row: StoredConsentRecord, subject: CollectionSubject) -> ConsentRecord:
    return ConsentRecord(
        id=row.id,
        agency_id=row.agency_id,
        client_id=row.client_id,
        subject_ref=subject.token_digest,
        key_id=SUBJECT_REF_KEY_ID,
        purpose=Purpose(row.purpose),
        state=ConsentState(row.state),
        source=ConsentSource(row.source),
        jurisdiction_profile=Profile(row.jurisdiction_profile),
        policy_version=row.policy_version,
        notice_snapshot_hash=row.notice_sha256,
        received_at=row.received_at,
        captured_at=row.captured_at,
        expires_at=row.expires_at,
        supersedes_id=row.supersedes_id,
    )


# Current consent of a subject: the latest record per purpose by server receipt (ties broken
# by ID, as in the contract), evaluated by app.privacy.consent at time now.
def consent_view(session: Session, subject: CollectionSubject, now: datetime) -> ConsentView:
    rows = session.scalars(
        select(StoredConsentRecord)
        .where(StoredConsentRecord.subject_id == subject.id)
        .ext(distinct_on(StoredConsentRecord.purpose))
        .order_by(
            StoredConsentRecord.purpose,
            StoredConsentRecord.received_at.desc(),
            StoredConsentRecord.id.desc(),
        )
    )
    records = [_contract_record(row, subject) for row in rows]
    latest = {record.purpose: record for record in records}
    states = {purpose: consent.current_state(records, purpose, now) for purpose in PURPOSES}
    return ConsentView(states, latest)


# Record explicit consent choices (D-027 decision 3). Without a token, a request that grants a
# purpose creates the subject and returns its token once; one that grants nothing stores
# nothing. Each record passes the 003 ConsentRecord contract before it is stored.
def record_consent(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    *,
    source: ConsentSource,
    notice_sha256: str,
    choices: dict[Purpose, ConsentState],
    subject_token: str | None,
    captured_at: datetime | None,
    recheck,
) -> ConsentResult:
    now = lock_client(session, client_id)
    recheck()
    created: str | None = None
    if subject_token is not None:
        subject = find_subject(session, client_id, subject_token)
        if subject is None:
            count(
                session, agency_id, client_id, now.date(), "consent", "rejected", "unknown_subject"
            )
            raise CollectionError("unknown_subject", 422)
    elif ConsentState.GRANTED not in choices.values():
        count(session, agency_id, client_id, now.date(), "consent", "suppressed", "nothing_granted")
        return ConsentResult(None, [], {purpose: ConsentState.UNKNOWN for purpose in PURPOSES})
    else:
        created = "sbj_" + new_token()
        subject = CollectionSubject(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            token_digest=digest(created),
            created_at=now,
            last_activity_at=now,
        )
        session.add(subject)
        session.flush()
    receipts = []
    for purpose, state in sorted(choices.items()):
        record = ConsentRecord(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            subject_ref=subject.token_digest,
            key_id=SUBJECT_REF_KEY_ID,
            purpose=purpose,
            state=state,
            source=source,
            jurisdiction_profile=Profile.STRICT_OPT_IN,
            policy_version=consent.POLICY_VERSION,
            notice_snapshot_hash=notice_sha256,
            received_at=now,
            captured_at=captured_at,
            expires_at=now + CONSENT_VALIDITY if state is ConsentState.GRANTED else None,
        )
        session.add(
            StoredConsentRecord(
                id=record.id,
                agency_id=agency_id,
                client_id=client_id,
                subject_id=subject.id,
                purpose=record.purpose.value,
                state=record.state.value,
                source=record.source.value,
                jurisdiction_profile=record.jurisdiction_profile.value,
                policy_version=record.policy_version,
                notice_sha256=record.notice_snapshot_hash,
                received_at=record.received_at,
                captured_at=record.captured_at,
                expires_at=record.expires_at,
            )
        )
        receipts.append(record.id)
    subject.last_activity_at = now
    session.flush()
    count(session, agency_id, client_id, now.date(), "consent", "accepted", "recorded")
    return ConsentResult(created, receipts, consent_view(session, subject, now).states)


# Read a subject's current consent without changing anything (specification 005, D-033): no
# token is issued, no record appended, no expiry renewed, and last_activity_at is untouched. It
# takes the client privacy lock, so it observes consent changes and erasure in their commit
# order. Missing and erased subjects both read as unknown.
def read_consent_state(
    session: Session, client_id: UUID, *, subject_token: str, recheck
) -> ConsentStateView:
    now = lock_client(session, client_id)
    recheck()
    unknown = {purpose: ConsentState.UNKNOWN for purpose in PURPOSES}
    subject = find_subject(session, client_id, subject_token)
    if subject is None:
        return ConsentStateView("unknown", unknown, {}, now)
    view = consent_view(session, subject, now)
    expiries = {
        purpose: view.latest[purpose].expires_at
        for purpose, state in view.states.items()
        if state is ConsentState.GRANTED and view.latest[purpose].expires_at is not None
    }
    return ConsentStateView("active", view.states, expiries, now)


# True when a managed link of this client has the given ID. Any status counts: a disabled or
# expired link still identifies historical provenance, although it no longer redirects.
def link_belongs_to_client(
    session: Session, agency_id: UUID, client_id: UUID, link_id: UUID
) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    ManagedLink.agency_id == agency_id,
                    ManagedLink.client_id == client_id,
                    ManagedLink.id == link_id,
                )
            )
        )
    )


# Admit one event through the D-027 transaction (design section 8). Returns the outcome with a
# closed reason code; rejected and suppressed events store nothing but a counter. recheck
# re-resolves the live source or key after the lock and raises when it is no longer valid.
def admit(
    session: Session,
    settings: Settings,
    agency_id: UUID,
    client_id: UUID,
    channel: Channel,
    envelope: Envelope,
    *,
    recheck,
    user_agent: str = "",
) -> Admission:
    keys = require_tombstone_keys(settings)
    now = lock_client(session, client_id)
    recheck()
    day = now.date()

    def finish(outcome, reason: str, revision: int | None = None) -> Admission:
        count(session, agency_id, client_id, day, channel.kind, outcome, reason)
        return Admission(outcome, reason, revision)

    try:
        check_occurred_at(envelope.occurred_at, now)
        if envelope.internal and channel.kind == "browser":
            raise Rejected("internal_flag_untrusted")
        parsed = parse_payload(envelope)
    except Rejected as rejection:
        return finish("rejected", rejection.reason)
    subject = find_subject(session, client_id, envelope.subject_token)
    if subject is None:
        token_digest = digest(envelope.subject_token)
        deleted = _tombstones(
            session,
            client_id,
            "subject_token",
            keys.candidates(client_id, "subject_token", token_digest),
        )
        return finish("rejected", "subject_deleted" if deleted else "unknown_subject")
    replays = _tombstones(
        session,
        client_id,
        "event_id",
        keys.candidates(client_id, "event_id", str(envelope.event_id)),
    )
    gate = deletion.admission(
        subject_tombstones=[], replay_tombstones=replays, consent_received_at=None
    )
    if not gate.allowed:
        return finish("rejected", gate.reason)
    view = consent_view(session, subject, now)
    required = REQUIRED_PURPOSES[envelope.event_type]
    decision = consent.require_all(required, view.states)
    if not decision.allowed:
        return finish("suppressed", decision.reason)
    if envelope.link_id is not None and not link_belongs_to_client(
        session, agency_id, client_id, envelope.link_id
    ):
        return finish("rejected", "unknown_link")
    granted = {purpose for purpose, state in view.states.items() if state is ConsentState.GRANTED}
    form = None
    if envelope.event_type == "form_submit":
        stored = session.scalar(
            select(CollectionForm).where(
                CollectionForm.client_id == client_id,
                CollectionForm.form_key == getattr(parsed, "form_key", None),
                CollectionForm.status == "active",
            )
        )
        form = FormDefinition.model_validate(stored.fields) if stored is not None else None
    try:
        minimized = minimize_payload(parsed, granted, form)
    except Rejected as rejection:
        return finish("rejected", rejection.reason)
    label = traffic_label(channel.kind, envelope.internal, user_agent)
    print_ = fingerprint(
        envelope.event_type,
        envelope.occurred_at,
        subject.id,
        minimized.payload,
        envelope.internal,
        envelope.link_id,
    )
    basis = sorted(view.latest[purpose].id for purpose in required)
    content = {
        "channel": channel.kind,
        "source_id": channel.source_id,
        "credential_id": channel.credential_id,
        "trust_rank": channel.trust_rank,
        "occurred_at": envelope.occurred_at,
        "payload": minimized.payload,
        "fingerprint": print_,
        "consent_basis": basis,
        "traffic_label": label,
        "policy_version": POLICY_VERSION,
        "link_id": envelope.link_id,
    }
    inserted = session.scalar(
        insert(CollectedEvent)
        .values(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            subject_id=subject.id,
            first_received_at=now,
            last_received_at=now,
            expires_at=now + EVENT_RETENTION,
            **content,
        )
        .on_conflict_do_nothing(constraint="uq_collected_events_client_event")
        .returning(CollectedEvent.id)
    )
    for reason, amount in sorted(minimized.dropped.items()):
        count(session, agency_id, client_id, day, channel.kind, "minimized", reason, amount)
    if inserted is not None:
        subject.last_activity_at = now
        return finish("accepted", "new", 1)
    existing = session.scalar(
        select(CollectedEvent)
        .where(CollectedEvent.client_id == client_id, CollectedEvent.event_id == envelope.event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is None:
        # The conflicting row expired and was deleted after the insert saw it; retry.
        raise CollectionError("temporarily_unavailable", 503)
    same_identity = existing.event_type == envelope.event_type and existing.subject_id == subject.id
    if same_identity and channel.trust_rank > existing.trust_rank:
        for name, value in content.items():
            setattr(existing, name, value)
        existing.revision += 1
        existing.last_received_at = now
        subject.last_activity_at = now
        return finish("upgraded", "trusted_copy", existing.revision)
    if existing.fingerprint == print_:
        existing.last_received_at = now
        subject.last_activity_at = now
        return finish("duplicate", "identical", existing.revision)
    existing.conflict_count += 1
    existing.last_conflict_at = now
    return finish("conflict", "changed_content" if same_identity else "identity_mismatch")


# Erase one subject of a client in one transaction (D-027 decision 11): tombstones for the
# subject token and every deleted event ID, then deletion of its events, consent records, and
# subject row, with per-store outcomes. Returns None when no such subject exists.
def erase_subject(
    session: Session,
    settings: Settings,
    agency_id: UUID,
    client_id: UUID,
    *,
    requester: RequesterKind,
    user_id: UUID | None = None,
    subject_token: str | None = None,
    event_id: UUID | None = None,
    objected: bool = False,
) -> SubjectDeletionRequest | None:
    keys = require_tombstone_keys(settings)
    now = lock_client(session, client_id)
    subject = None
    if subject_token is not None:
        subject = find_subject(session, client_id, subject_token)
    elif event_id is not None:
        subject = session.scalar(
            select(CollectionSubject)
            .join(CollectedEvent, CollectedEvent.subject_id == CollectionSubject.id)
            .where(CollectedEvent.client_id == client_id, CollectedEvent.event_id == event_id)
            .with_for_update(of=CollectionSubject)
        )
    if subject is None:
        count(session, agency_id, client_id, now.date(), "erasure", "rejected", "unknown_subject")
        return None
    status = RequestStatus.RECEIVED
    # Possession of the token or the authorized manager request is the verification here.
    for step in (RequestStatus.VERIFYING, RequestStatus.ACCEPTED, RequestStatus.IN_PROGRESS):
        status = deletion.transition(status, step)
    request = SubjectDeletionRequest(
        id=uuid4(),
        agency_id=agency_id,
        client_id=client_id,
        requester_kind=requester.value,
        requested_by_user_id=user_id,
        status=status.value,
        objected=objected,
        received_at=now,
    )
    session.add(request)
    session.flush()
    event_ids = list(
        session.scalars(
            select(CollectedEvent.event_id).where(CollectedEvent.subject_id == subject.id)
        )
    )
    matches = [("subject_token", subject.token_digest)] + [
        ("event_id", str(item)) for item in event_ids
    ]
    for match_type, value in matches:
        match_key, key_id = keys.seal(client_id, match_type, value)
        session.add(
            StoredTombstone(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                deletion_request_id=request.id,
                match_type=match_type,
                match_key=match_key,
                match_key_id=key_id,
                effective_at=now,
                objected=objected and match_type == "subject_token",
            )
        )
    session.flush()
    session.execute(delete(CollectedEvent).where(CollectedEvent.subject_id == subject.id))
    session.execute(delete(StoredConsentRecord).where(StoredConsentRecord.subject_id == subject.id))
    session.execute(delete(CollectionSubject).where(CollectionSubject.id == subject.id))
    targets = {
        "collected_events": TargetStatus.DONE,
        "consent_records": TargetStatus.DONE,
        "collection_subjects": TargetStatus.DONE,
        "event_diagnostics": TargetStatus.NOT_APPLICABLE,
    }
    final = deletion.outcome(targets)
    if final is None:
        raise RuntimeError("Every erasure target has an outcome.")
    request.status = deletion.transition(status, final).value
    request.completed_at = now
    request.target_outcomes = {name: value.value for name, value in targets.items()}
    count(session, agency_id, client_id, now.date(), "erasure", "accepted", "completed")
    return request


def _secret_context(source: IngestionSource, secret_id: UUID, version: int) -> SecretContext:
    return SecretContext(
        source.agency_id, source.client_id, source.id, secret_id, "webhook_signing", version
    )


# Create and seal one webhook signing secret version; the raw secret is returned once.
def issue_webhook_secret(
    session: Session, keyring: LocalKeyring, source: IngestionSource, version: int
) -> str:
    raw = "whsec_" + new_token()
    secret_id = uuid4()
    sealed = seal(keyring, raw, _secret_context(source, secret_id, version))
    session.add(
        IngestionSourceSecret(
            id=secret_id,
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            version=version,
            kek_id=sealed.kek_id,
            wrap_nonce=sealed.wrap_nonce,
            wrapped_dek=sealed.wrapped_dek,
            nonce=sealed.nonce,
            ciphertext=sealed.ciphertext,
        )
    )
    return raw


# Every secret version of a webhook source that is still valid at now, newest first, opened
# lazily so verification can stop at the first match. No version is dropped by a count limit:
# each rotated-out version stays valid until its own retires_at (D-027, review finding
# R004-03). The work is bounded by the versions rotated within one overlap period, and the
# rows have already been read, so a lazy open adds no further query.
def live_webhook_secrets(
    session: Session, keyring: LocalKeyring, source: IngestionSource, now: datetime
) -> Iterator[str]:
    rows = list(
        session.scalars(
            select(IngestionSourceSecret)
            .where(
                IngestionSourceSecret.source_id == source.id,
                (IngestionSourceSecret.retires_at.is_(None))
                | (IngestionSourceSecret.retires_at > now),
            )
            .order_by(IngestionSourceSecret.version.desc())
        )
    )
    for row in rows:
        yield open_secret(
            keyring,
            SealedSecret(row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext),
            _secret_context(source, row.id, row.version),
        )


# Owner/Admin administration of sources, forms, and erasure requests; audited in the caller's
# transaction. Erasure takes the agency write lock before the client privacy lock.
class CollectionAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _source(self, agency_id: UUID, client_id: UUID, source_id: UUID) -> IngestionSource:
        item = self.session.scalar(
            select(IngestionSource)
            .where(
                IngestionSource.agency_id == agency_id,
                IngestionSource.client_id == client_id,
                IngestionSource.id == source_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    @staticmethod
    def _origins(origins: list[str]) -> list[str]:
        if not 1 <= len(origins) <= 10 or len(set(origins)) != len(origins):
            raise ValueError("Provide 1-10 distinct origins.")
        if not all(is_exact_origin(origin) for origin in origins):
            raise ValueError("Origins must be exact HTTP(S) origins.")
        return origins

    def create_source(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        kind: Literal["browser", "webhook"],
        name: str,
        allowed_origins: list[str] | None = None,
        notice_sha256: str | None = None,
    ) -> tuple[IngestionSource, str | None]:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = IngestionSource(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            creator_membership_id=actor.id,
            kind=kind,
            name=self._name(name),
        )
        if kind == "browser":
            if allowed_origins is None or notice_sha256 is None:
                raise ValueError("A browser source needs origins and a notice digest.")
            source.public_key = "pk_" + new_token()
            source.allowed_origins = self._origins(allowed_origins)
            source.notice_sha256 = notice_sha256
        elif allowed_origins is not None or notice_sha256 is not None:
            raise ValueError("A webhook source has no origins or notice digest.")
        self.session.add(source)
        self.session.flush()
        secret = None
        if kind == "webhook":
            secret = issue_webhook_secret(
                self.session, require_token_keys(self.settings), source, 1
            )
        self._audit(agency_id, "source.created", "source", source.id, client_id)
        return source, secret

    def list_sources(self, agency_id: UUID, client_id: UUID) -> list[IngestionSource]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(IngestionSource)
                .where(
                    IngestionSource.agency_id == agency_id, IngestionSource.client_id == client_id
                )
                .order_by(IngestionSource.created_at, IngestionSource.id)
                .limit(100)
            )
        )

    def update_source(
        self,
        agency_id: UUID,
        client_id: UUID,
        source_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        allowed_origins: list[str] | None = None,
        notice_sha256: str | None = None,
    ) -> IngestionSource:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("Invalid source status.")
        if source.kind == "webhook" and (allowed_origins is not None or notice_sha256 is not None):
            raise ValueError("A webhook source has no origins or notice digest.")
        if name is not None:
            source.name = self._name(name)
        if status is not None:
            source.status = status
        if allowed_origins is not None:
            source.allowed_origins = self._origins(allowed_origins)
        if notice_sha256 is not None:
            source.notice_sha256 = notice_sha256
        self._audit(agency_id, "source.updated", "source", source.id, client_id)
        return source

    # New signing secret version; the previous versions stay valid for SECRET_OVERLAP.
    def rotate_secret(self, agency_id: UUID, client_id: UUID, source_id: UUID) -> str:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        if source.kind != "webhook":
            raise ValueError("Only webhook sources have signing secrets.")
        keyring = require_token_keys(self.settings)
        now = self.session.scalar(select(func.clock_timestamp()))
        versions = list(
            self.session.scalars(
                select(IngestionSourceSecret).where(IngestionSourceSecret.source_id == source.id)
            )
        )
        for item in versions:
            if item.retires_at is None:
                item.retires_at = now + SECRET_OVERLAP
        secret = issue_webhook_secret(
            self.session, keyring, source, max(item.version for item in versions) + 1
        )
        self._audit(agency_id, "source.secret_rotated", "source", source.id, client_id)
        return secret

    def put_form(
        self, agency_id: UUID, client_id: UUID, form_key: str, definition: FormDefinition
    ) -> CollectionForm:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        form = self.session.scalar(
            select(CollectionForm)
            .where(CollectionForm.client_id == client_id, CollectionForm.form_key == form_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        fields = definition.model_dump(mode="json")
        if form is None:
            form = CollectionForm(
                id=uuid4(), agency_id=agency_id, client_id=client_id, form_key=form_key, version=1
            )
            form.fields = fields
            self.session.add(form)
        else:
            form.version += 1
            form.fields = fields
            form.status = "active"
        self.session.flush()
        self._audit(agency_id, "form.updated", "form", form.id, client_id)
        return form

    def list_forms(self, agency_id: UUID, client_id: UUID) -> list[CollectionForm]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(CollectionForm)
                .where(CollectionForm.client_id == client_id)
                .order_by(CollectionForm.form_key)
                .limit(100)
            )
        )

    def request_erasure(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        subject_token: str | None,
        event_id: UUID | None,
        objected: bool,
    ) -> SubjectDeletionRequest:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        if (subject_token is None) == (event_id is None):
            raise ValueError("Identify the subject by exactly one of token or event ID.")
        request = erase_subject(
            self.session,
            self.settings,
            agency_id,
            client_id,
            requester=RequesterKind.AGENCY_ADMIN,
            user_id=self.actor_user_id,
            subject_token=subject_token,
            event_id=event_id,
            objected=objected,
        )
        if request is None:
            raise AccessDenied()
        self._audit(agency_id, "deletion.requested", "deletion_request", request.id, client_id)
        return request

    def list_requests(self, agency_id: UUID, client_id: UUID) -> list[SubjectDeletionRequest]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(SubjectDeletionRequest)
                .where(
                    SubjectDeletionRequest.agency_id == agency_id,
                    SubjectDeletionRequest.client_id == client_id,
                )
                .order_by(SubjectDeletionRequest.received_at.desc(), SubjectDeletionRequest.id)
                .limit(100)
            )
        )


# Daily counters of one client over at most 31 days (caller authorizes client:read first).
def diagnostics(
    session: Session, agency_id: UUID, client_id: UUID, start: date, end: date
) -> list[EventDiagnostic]:
    if end < start or (end - start).days > 30:
        raise ValueError("Use a range of at most 31 days.")
    return list(
        session.scalars(
            select(EventDiagnostic)
            .where(
                EventDiagnostic.agency_id == agency_id,
                EventDiagnostic.client_id == client_id,
                EventDiagnostic.day >= start,
                EventDiagnostic.day <= end,
            )
            .order_by(
                EventDiagnostic.day,
                EventDiagnostic.channel,
                EventDiagnostic.outcome,
                EventDiagnostic.reason,
            )
            .limit(1000)
        )
    )


# Metadata of one accepted event (caller authorizes client:read first); never payload or subject.
def event_metadata(
    session: Session, agency_id: UUID, client_id: UUID, event_id: UUID
) -> CollectedEvent:
    row = session.scalar(
        select(CollectedEvent).where(
            CollectedEvent.agency_id == agency_id,
            CollectedEvent.client_id == client_id,
            CollectedEvent.event_id == event_id,
        )
    )
    if row is None:
        raise AccessDenied()
    return row
