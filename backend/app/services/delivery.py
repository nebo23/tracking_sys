"""Conversion destinations, the delivery outbox and the worker's delivery step (014-B).

D-064 decisions D6 to D10 and D13; design in specs/014-ad-spend-capi/design-014.md, section 5.

Conversion source (D6, D8). candidates_from_ledger and candidates_from_feed turn posted 007-A
sale transactions, or the closing sale states of a ledger_feed journal, into candidates: the
authoritative sale state (instant, verified net in minor units, currency) and the evidence
classes of the sale. A synthetic journey adds the converting person, the collection subjects
(subject_ref, the subject token digest of 003-B), the click identifiers (an fbclid with its
first receipt time and its 004 event ID) and the sale's action source. There is no HTTP route
for enqueueing; the 007-B journal replaces this source later.

Enqueue (E4, D7 to D9). Only a sale whose evidence is a confirmed capture or settlement is
enqueued, with a net above zero, before its deadline (the 7-day age limit less 1 hour), with an
fbc built from the latest fbclid received at or before the sale, and with the fields its action
source requires; website events need client_user_agent, which is never collected, so they are
refused as provider_field_missing (V-9). Under the client's privacy lock (004), admission with
the subject and replay tombstones and require_all of ads.measurement and sale_or_share for every
subject must allow it; GPC denies both purposes. A refusal stores nothing and is counted. An
admitted sale becomes one delivery per enabled destination with a deterministic event ID (a
keyed digest of client, destination and sale operation), the consent basis and policy version,
and a payload sealed under the D-025 keyring (fbc, subject references, replay keys), destroyed
when the delivery ends. A repeated enqueue is a no-op, a changed net updates a delivery not yet
sent, and a net of zero cancels it (sale_reversed). A delivered sale is never sent again.

Worker (run_deliveries). Overdue deliveries expire first. A claim takes a due delivery of an
enabled destination, an active delivery connection of a registered delivery provider and an
active agency and client, FOR UPDATE SKIP LOCKED, takes the client's privacy lock and repeats E5
from the payload in the same transaction. A denial blocks the delivery and destroys the payload.
Otherwise the attempt counter rises, a 2-minute lease starts, and the event is validated
locally and sent with no lock held. The result is written only while the delivery is still
sending under the same attempt, locking the connection before the delivery like the teardown;
each attempt stores an acknowledgement. Retryable answers retry at most 5 attempts in a cycle
(30 seconds doubling to 15 minutes, or the provider's wait); a retry that would start after the
deadline expires the delivery instead. An invalid token makes the delivery connection
reconnect_required and the delivery waits. A permission or dataset rejection (configuration)
keeps the payload for an audited requeue, at most 3 times; an invalid parameter (payload) ends
the delivery. Answers and logs never contain fbc, fbclid, a payload, the event ID or a trace ID.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, tuple_, update
from sqlalchemy.orm import Session

from app.advertising.currencies import decimal_text
from app.advertising.outbox import DESTROYED, cancel_open
from app.attribution import JournalItem, SaleState
from app.collection.keys import TombstoneKeyring
from app.config import Settings
from app.connectors.contracts import ConnectorProvider, DeliveryAnswer, ErrorKind, ProviderError
from app.ledger import LedgerCalculation, LedgerScope, MovementType, OperationKind
from app.models import (
    Agency,
    ClientWorkspace,
    CollectionSubject,
    ConnectorConnection,
)
from app.models.delivery import (
    ACTION_SOURCES,
    ConversionAcknowledgement,
    ConversionDelivery,
    ConversionDestination,
)
from app.privacy import consent, deletion
from app.privacy.consent import Decision, Purpose
from app.privacy.token_secrets import (
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_secret,
    seal,
)
from app.security import keyed_digest, now_utc
from app.services.access import ScopedAccess
from app.services.collection import _tombstones, consent_view, lock_client, require_tombstone_keys
from app.services.connectors import (
    LIVE,
    ConnectorError,
    _live_secrets,
    _locked_connection,
    _mark_reconnect_required,
    _open,
    require_keys,
)
from app.services.tenancy import AccessDenied, TenancyService

PURPOSES = (Purpose.ADS_MEASUREMENT, Purpose.SALE_OR_SHARE)
VERIFIED = frozenset({"confirmed_capture", "confirmed_settlement"})
AGE_LIMIT = timedelta(days=7)
MARGIN = timedelta(hours=1)
MAX_ATTEMPTS = 5
REQUEUE_LIMIT = 3
RETRY_BASE = timedelta(seconds=30)
RETRY_CAP = timedelta(minutes=15)
RATE_CAP = timedelta(hours=1)
LEASE = timedelta(minutes=2)
# Values are sent as JSON numbers; below 10**15 minor units every value is exact as a float.
MAX_VALUE_MINOR = 10**15
PAYLOAD_KIND = "conversion_payload"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
FBCLID = re.compile(r"[A-Za-z0-9_-]{1,512}")
SUBJECT_REF = re.compile(r"[0-9a-f]{64}")
REFUSALS = (
    "not_verified",
    "sale_reversed",
    "too_old",
    "value_out_of_range",
    "unsupported_action_source",
    "no_match_key",
    "provider_field_missing",
)


# --- Conversion source --------------------------------------------------------------------


@dataclass(frozen=True)
class ClickIdentifier:
    """An fbclid collected under attribution consent, its first receipt and its 004 event."""

    fbclid: str = field(repr=False)
    received_at: datetime
    event_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.fbclid, str) or not FBCLID.fullmatch(self.fbclid):
            raise ValueError("invalid_click_identifier")
        if not isinstance(self.received_at, datetime) or self.received_at.utcoffset() is None:
            raise ValueError("invalid_click_time")


@dataclass(frozen=True)
class SyntheticJourney:
    """The synthetic journey of a sale (006 is not implemented): person, subjects and clicks."""

    person_id: str
    subject_refs: tuple[str, ...] = field(repr=False)
    clicks: tuple[ClickIdentifier, ...] = field(repr=False)
    action_source: str = "system_generated"
    event_ids: tuple[UUID, ...] = field(default=(), repr=False)
    event_source_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(ref, str) and SUBJECT_REF.fullmatch(ref) for ref in self.subject_refs
        ):
            raise ValueError("invalid_subject_ref")


@dataclass(frozen=True)
class SaleCandidate:
    scope: LedgerScope
    transaction_id: str
    sale: SaleState
    evidence_classes: frozenset[str]
    journey: SyntheticJourney


JourneyKey = tuple[LedgerScope, str]


# Candidates of the posted transactions of a 007-A calculation that have a journey. Purchase
# signals and manual declarations never post, so they are never candidates (AC2).
def candidates_from_ledger(
    ledger: LedgerCalculation, journeys: Mapping[JourneyKey, SyntheticJourney]
) -> tuple[SaleCandidate, ...]:
    candidates = []
    for transaction in ledger.transactions:
        journey = journeys.get((transaction.scope, transaction.operation_id))
        if journey is None:
            continue
        classes = frozenset(item.classification.value for item in transaction.sale.evidence)
        state = SaleState(
            transaction.scope,
            transaction.operation_id,
            transaction.currency,
            transaction.sale.effective_at,
            transaction.totals.net,
        )
        candidates.append(
            SaleCandidate(transaction.scope, transaction.operation_id, state, classes, journey)
        )
    return tuple(candidates)


# Candidates of a ledger_feed journal: the latest closing sale state of each journeyed sale,
# with the evidence classes of the postings that made it a sale.
def candidates_from_feed(
    items: Iterable[JournalItem], journeys: Mapping[JourneyKey, SyntheticJourney]
) -> tuple[SaleCandidate, ...]:
    classes: dict[JourneyKey, set[str]] = {}
    latest: dict[JourneyKey, SaleState] = {}
    for item in items:
        movement = item.movement
        if (
            movement is not None
            and movement.kind is OperationKind.SALE
            and movement.movement is MovementType.POSTING
        ):
            key = (movement.scope, movement.transaction_id)
            classes.setdefault(key, set()).add(movement.trigger.classification.value)
        for state in item.sales:
            latest[state.key] = state
    return tuple(
        SaleCandidate(key[0], key[1], state, frozenset(classes.get(key, ())), journeys[key])
        for key, state in sorted(latest.items(), key=lambda pair: (pair[0][0], pair[0][1]))
        if key in journeys
    )


# --- Shared checks ------------------------------------------------------------------------


def _milliseconds(instant: datetime) -> int:
    return (instant.astimezone(UTC) - EPOCH) // timedelta(milliseconds=1)


# The fbc of the latest click received at or before the sale (V-10): fb.1.<ms>.<fbclid>.
def match_key(clicks: Iterable[ClickIdentifier], sale_instant: datetime) -> ClickIdentifier | None:
    usable = [click for click in clicks if click.received_at <= sale_instant]
    return max(usable, key=lambda click: (click.received_at, str(click.event_id)), default=None)


def fbc(click: ClickIdentifier) -> str:
    return f"fb.1.{_milliseconds(click.received_at)}.{click.fbclid}"


def deadline_of(event_time: datetime) -> datetime:
    return event_time + AGE_LIMIT - MARGIN


# The first reason a candidate cannot be enqueued before its privacy checks, or None.
def refusal(candidate: SaleCandidate, now: datetime) -> str | None:
    journey, sale = candidate.journey, candidate.sale
    if not candidate.evidence_classes or not candidate.evidence_classes <= VERIFIED:
        return "not_verified"
    if sale.net_minor <= 0:
        return "sale_reversed"
    if now >= deadline_of(sale.effective_at):
        return "too_old"
    if sale.net_minor >= MAX_VALUE_MINOR:
        return "value_out_of_range"
    if journey.action_source not in ACTION_SOURCES:
        return "unsupported_action_source"
    if match_key(journey.clicks, sale.effective_at) is None:
        return "no_match_key"
    # Website events need client_user_agent (V-9), which is never collected (D8).
    if journey.action_source == "website":
        return "provider_field_missing"
    return None


# E4 and E5: replay tombstones first, then each subject's tombstones and current consent for
# ads.measurement and sale_or_share, then admission. Returns the decision and the consent basis
# (the latest record IDs of both purposes for every subject).
def privacy(
    session: Session,
    keys: TombstoneKeyring,
    client_id: UUID,
    subject_refs: Iterable[str],
    replay_ids: Iterable[str],
    now: datetime,
) -> tuple[Decision, tuple[UUID, ...]]:
    replays = []
    for value in replay_ids:
        replays += _tombstones(
            session, client_id, "event_id", keys.candidates(client_id, "event_id", value)
        )
    if replays:
        return Decision(False, "replay_before_deletion"), ()
    refs = list(subject_refs)
    if not refs:
        return Decision(False, "consent_unknown"), ()
    tombstones, basis, receipts = [], [], []
    for ref in refs:
        found = _tombstones(
            session, client_id, "subject_token", keys.candidates(client_id, "subject_token", ref)
        )
        subject = session.scalar(
            select(CollectionSubject).where(
                CollectionSubject.client_id == client_id, CollectionSubject.token_digest == ref
            )
        )
        if subject is None:
            return Decision(False, "subject_deleted" if found else "subject_unknown"), ()
        tombstones += found
        view = consent_view(session, subject, now)
        decision = consent.require_all(PURPOSES, view.states)
        if not decision.allowed:
            return decision, ()
        for purpose in PURPOSES:
            record = view.latest[purpose]
            basis.append(record.id)
            receipts.append(record.received_at)
    gate = deletion.admission(
        subject_tombstones=tombstones, replay_tombstones=(), consent_received_at=min(receipts)
    )
    if not gate.allowed:
        return gate, ()
    return Decision(True, "granted"), tuple(sorted(set(basis)))


def event_id_of(
    settings: Settings, client_id: UUID, destination_id: UUID, scope: LedgerScope, operation: str
) -> str:
    message = "\0".join((str(client_id), str(destination_id), scope.source_account_id, operation))
    return keyed_digest(settings, "conversion-event", message)


def _context(row: ConversionDelivery) -> SecretContext:
    return SecretContext(
        row.agency_id,
        row.client_id,
        row.destination_id,
        row.id,
        PAYLOAD_KIND,
        1,  # type: ignore[arg-type]
    )


def _payload(keyring: LocalKeyring, row: ConversionDelivery) -> dict:
    assert row.kek_id and row.wrap_nonce and row.wrapped_dek and row.nonce and row.ciphertext
    sealed = SealedSecret(row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext)
    return json.loads(open_secret(keyring, sealed, _context(row)))


# End a delivery in the caller's transaction, destroying its payload.
def _end(row: ConversionDelivery, status: str, reason: str | None, now: datetime, **values) -> None:
    row.status, row.reason, row.ended_at, row.updated_at = status, reason, now, now
    for name, value in {**DESTROYED, **values}.items():
        setattr(row, name, value)


# --- Enqueue (E4) -------------------------------------------------------------------------


def _client_active(session: Session, agency_id: UUID, client_id: UUID) -> bool:
    agency = session.scalar(select(Agency.status).where(Agency.id == agency_id))
    client = session.scalar(
        select(ClientWorkspace.status).where(
            ClientWorkspace.agency_id == agency_id, ClientWorkspace.id == client_id
        )
    )
    return agency == "active" and client == "active"


# A repeated enqueue of a sale already in the outbox: a delivery not yet sent follows the
# current net; anything else is left as it is.
def _follow(row: ConversionDelivery, candidate: SaleCandidate, now: datetime) -> str:
    waiting = row.ended_at is None and row.status in {"queued", "rejected"}
    if not waiting:
        return "unchanged"
    net = candidate.sale.net_minor
    if net <= 0:
        _end(row, "cancelled", "sale_reversed", now, rejection_class=None)
        return "cancelled"
    if net != row.value_minor and net < MAX_VALUE_MINOR:
        row.value_minor, row.updated_at = net, now
        return "updated"
    return "unchanged"


def _enqueue_one(
    engine: Engine,
    settings: Settings,
    keys: TombstoneKeyring,
    keyring: LocalKeyring,
    candidate: SaleCandidate,
    fixed: datetime | None,
) -> list[str]:
    scope, journey, sale = candidate.scope, candidate.journey, candidate.sale
    with Session(engine) as session, session.begin():
        now = fixed or lock_client(session, scope.client_id)
        if fixed is not None:
            lock_client(session, scope.client_id)
        if not _client_active(session, scope.agency_id, scope.client_id):
            return ["client_inactive"]
        destinations = list(
            session.scalars(
                select(ConversionDestination)
                .join(
                    ConnectorConnection,
                    ConnectorConnection.id == ConversionDestination.connection_id,
                )
                .where(
                    ConversionDestination.agency_id == scope.agency_id,
                    ConversionDestination.client_id == scope.client_id,
                    ConversionDestination.enabled.is_(True),
                    ConnectorConnection.status.in_(LIVE),
                )
                .order_by(ConversionDestination.created_at, ConversionDestination.id)
            )
        )
        if not destinations:
            return ["no_destination"]
        results: list[str] = []
        checked: tuple[str | None, tuple[UUID, ...]] | None = None
        for destination in destinations:
            event_id = event_id_of(
                settings, scope.client_id, destination.id, scope, candidate.transaction_id
            )
            existing = session.scalar(
                select(ConversionDelivery)
                .where(
                    ConversionDelivery.destination_id == destination.id,
                    ConversionDelivery.event_id == event_id,
                )
                .with_for_update()
            )
            if existing is not None:
                results.append(_follow(existing, candidate, now))
                continue
            if checked is None:
                reason = refusal(candidate, now)
                basis: tuple[UUID, ...] = ()
                if reason is None:
                    click = match_key(journey.clicks, sale.effective_at)
                    replay = [str(item.event_id) for item in journey.clicks]
                    replay += [str(item) for item in journey.event_ids]
                    decision, basis = privacy(
                        session, keys, scope.client_id, journey.subject_refs, replay, now
                    )
                    reason = None if decision.allowed else decision.reason
                checked = (reason, basis)
            reason, basis = checked
            if reason is not None:
                results.append(reason)
                continue
            click = match_key(journey.clicks, sale.effective_at)
            assert click is not None
            row = ConversionDelivery(
                id=uuid4(),
                agency_id=scope.agency_id,
                client_id=scope.client_id,
                destination_id=destination.id,
                connection_id=destination.connection_id,
                event_id=event_id,
                event_name=destination.event_name,
                action_source=journey.action_source,
                event_time=sale.effective_at,
                deadline=deadline_of(sale.effective_at),
                currency=sale.currency.code,
                currency_exponent=sale.currency.exponent,
                value_minor=sale.net_minor,
                status="queued",
                attempts=0,
                retries=0,
                requeues=0,
                consent_basis=list(basis),
                policy_version=consent.POLICY_VERSION,
                created_at=now,
                updated_at=now,
            )
            payload = {
                "fbc": fbc(click),
                "subjects": list(journey.subject_refs),
                "replay": [str(item.event_id) for item in journey.clicks]
                + [str(item) for item in journey.event_ids],
                "event_source_url": journey.event_source_url,
            }
            sealed = seal(keyring, json.dumps(payload, sort_keys=True), _context(row))
            row.kek_id, row.wrap_nonce, row.wrapped_dek = (
                sealed.kek_id,
                sealed.wrap_nonce,
                sealed.wrapped_dek,
            )
            row.nonce, row.ciphertext = sealed.nonce, sealed.ciphertext
            session.add(row)
            session.flush()
            results.append("queued")
        return results


# Enqueue each candidate for every enabled destination of its client, one transaction per
# candidate. Returns counts of the outcomes and closed refusal reasons only.
def enqueue_conversions(
    engine: Engine,
    settings: Settings,
    candidates: Iterable[SaleCandidate],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    keyring, keys = require_keys(settings), require_tombstone_keys(settings)
    counts: dict[str, int] = {}
    for candidate in candidates:
        for outcome in _enqueue_one(engine, settings, keys, keyring, candidate, now):
            counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# --- Worker (E5, sending, acknowledgements) -------------------------------------------------


@dataclass(frozen=True)
class _Send:
    delivery_id: UUID
    attempt: int
    connection_id: UUID
    generation: int
    provider: str
    dataset: str = field(repr=False)
    token: str = field(repr=False)
    test_event_code: str | None = field(repr=False)
    event: dict = field(repr=False)


def _event(row: ConversionDelivery, payload: Mapping[str, object]) -> dict:
    value = float(decimal_text(row.value_minor, row.currency_exponent))
    event: dict[str, object] = {
        "event_name": row.event_name,
        "event_time": int(row.event_time.timestamp()),
        "event_id": row.event_id,
        "action_source": row.action_source,
        "user_data": {"fbc": payload["fbc"]},
        "custom_data": {"value": value, "currency": row.currency},
    }
    if row.action_source == "website":
        event["event_source_url"] = payload.get("event_source_url")
    return event


# The local validation of D9 before a send: value, currency and the action source's fields.
def _invalid(row: ConversionDelivery, payload: Mapping[str, object]) -> bool:
    fbc_value = payload.get("fbc")
    return (
        not 0 < row.value_minor < MAX_VALUE_MINOR
        or not re.fullmatch(r"[A-Z]{3}", row.currency)
        or not isinstance(fbc_value, str)
        or not fbc_value.startswith("fb.1.")
        or row.action_source not in ACTION_SOURCES
        or row.action_source == "website"
    )


def expire_overdue(engine: Engine, now: datetime) -> int:
    with Session(engine) as session, session.begin():
        result = session.execute(
            update(ConversionDelivery)
            .where(
                ConversionDelivery.ended_at.is_(None),
                ConversionDelivery.deadline <= now,
                (ConversionDelivery.status.in_(("queued", "rejected")))
                | (
                    (ConversionDelivery.status == "sending")
                    & (ConversionDelivery.lease_expires_at < now)
                ),
            )
            .values(
                status="expired",
                reason="deadline_passed",
                rejection_class=None,
                ended_at=now,
                updated_at=now,
                **DESTROYED,
            )
        )
        return result.rowcount


def _claim(
    engine: Engine,
    keyring: LocalKeyring,
    keys: TombstoneKeyring,
    providers: tuple[str, ...],
    now: datetime,
) -> _Send | str | None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        row = session.scalar(
            select(ConversionDelivery)
            .join(
                ConversionDestination,
                ConversionDestination.id == ConversionDelivery.destination_id,
            )
            .join(ConnectorConnection, ConnectorConnection.id == ConversionDelivery.connection_id)
            .join(Agency, Agency.id == ConversionDelivery.agency_id)
            .join(
                ClientWorkspace,
                (ClientWorkspace.agency_id == ConversionDelivery.agency_id)
                & (ClientWorkspace.id == ConversionDelivery.client_id),
            )
            .where(
                (
                    (ConversionDelivery.status == "queued")
                    & (
                        ConversionDelivery.not_before.is_(None)
                        | (ConversionDelivery.not_before <= now)
                    )
                )
                | (
                    (ConversionDelivery.status == "sending")
                    & (ConversionDelivery.lease_expires_at < now)
                ),
                ConversionDelivery.ended_at.is_(None),
                ConversionDelivery.deadline > now,
                ConversionDestination.enabled.is_(True),
                ConnectorConnection.status == "active",
                ConnectorConnection.provider.in_(providers),
                Agency.status == "active",
                ClientWorkspace.status == "active",
            )
            .order_by(ConversionDelivery.created_at, ConversionDelivery.id)
            .limit(1)
            .with_for_update(of=ConversionDelivery, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        # E5 under the client's privacy lock, in the claiming transaction (D7).
        lock_client(session, row.client_id)
        payload = _payload(keyring, row)
        decision, _ = privacy(
            session, keys, row.client_id, payload["subjects"], payload["replay"], now
        )
        if not decision.allowed:
            _end(row, "blocked", decision.reason, now)
            return "blocked"
        if _invalid(row, payload):
            _end(row, "rejected", "invalid_event", now, rejection_class="payload")
            return "rejected"
        connection = session.get(ConnectorConnection, row.connection_id)
        destination = session.get(ConversionDestination, row.destination_id)
        assert connection is not None and destination is not None
        access = next(
            (item for item in _live_secrets(session, connection.id) if item.kind == "access_token"),
            None,
        )
        if access is None or connection.external_account_id is None:
            return "skipped"
        row.status, row.attempts = "sending", row.attempts + 1
        row.lease_expires_at, row.not_before, row.updated_at = now + LEASE, None, now
        return _Send(
            row.id,
            row.attempts,
            connection.id,
            connection.generation,
            connection.provider,
            connection.external_account_id,
            _open(keyring, access),
            destination.test_event_code,
            _event(row, payload),
        )


Outcome = Literal[
    "accepted",
    "count_mismatch",
    "retryable",
    "rate_limited",
    "unauthorized",
    "configuration",
    "payload",
]


def _classify(error: ProviderError) -> tuple[Outcome, str]:
    if error.kind is ErrorKind.UNAUTHORIZED:
        return "unauthorized", "invalid_token"
    if error.kind is ErrorKind.FORBIDDEN:
        return "configuration", "permission_missing"
    if error.kind is ErrorKind.RATE_LIMITED:
        return "rate_limited", "rate_limited"
    if error.kind in {ErrorKind.RETRYABLE, ErrorKind.BUDGET_EXHAUSTED}:
        return "retryable", "retryable"
    if error.provider_code == "dataset_unavailable":
        return "configuration", "dataset_unavailable"
    return "payload", "invalid_parameter"


def _retry_delay(row: ConversionDelivery, retry_after: int | None) -> timedelta:
    delay = min(RETRY_BASE * 2 ** max(row.retries - 1, 0), RETRY_CAP)
    if retry_after is not None:
        delay = max(delay, min(timedelta(seconds=max(retry_after, 1)), RATE_CAP))
    return delay


# Write the result of one attempt: only while the delivery is still sending under that attempt.
# The connection is locked before the delivery, as the teardown does.
def _record(
    engine: Engine,
    send: _Send,
    outcome: Outcome,
    code: str | None,
    answer: DeliveryAnswer | None,
    retry_after: int | None,
    now: datetime,
) -> str:
    with Session(engine) as session, session.begin():
        connection = _locked_connection(session, send.connection_id)
        row = session.scalar(
            select(ConversionDelivery)
            .where(ConversionDelivery.id == send.delivery_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != "sending" or row.attempts != send.attempt:
            return "superseded"
        session.add(
            ConversionAcknowledgement(
                id=uuid4(),
                agency_id=row.agency_id,
                client_id=row.client_id,
                delivery_id=row.id,
                attempt=send.attempt,
                occurred_at=now,
                outcome=outcome,
                provider_code=code,
                events_received=answer.events_received if answer else None,
                trace_id=(answer.trace_id or "")[:64] or None if answer else None,
            )
        )
        if outcome == "accepted":
            row.delivered_at = now
            _end(row, "delivered", None, now)
            return "delivered"
        if outcome == "unauthorized":
            _mark_reconnect_required(session, connection, send.generation, "provider_revoked", now)
            row.status, row.reason, row.lease_expires_at, row.updated_at = (
                "queued",
                "invalid_token",
                None,
                now,
            )
            return "waiting"
        if outcome == "configuration":
            row.status, row.reason, row.rejection_class = "rejected", code, "configuration"
            row.lease_expires_at, row.updated_at = None, now
            return "rejected"
        if outcome == "payload":
            _end(row, "rejected", code, now, rejection_class="payload")
            return "rejected"
        row.retries += 1
        if row.retries >= MAX_ATTEMPTS:
            _end(row, "undeliverable", "retries_exhausted", now)
            return "undeliverable"
        following = now + _retry_delay(row, retry_after)
        if following >= row.deadline:
            _end(row, "expired", "deadline_passed", now)
            return "expired"
        row.status, row.reason, row.not_before = "queued", code, following
        row.lease_expires_at, row.updated_at = None, now
        return "deferred"


def _attempt(
    engine: Engine,
    registry: Mapping[str, ConnectorProvider],
    send: _Send,
    clock: Callable[[], datetime],
) -> str:
    provider = registry[send.provider]
    try:
        answer = provider.send_event(
            send.token,
            dataset=send.dataset,
            event=send.event,
            test_event_code=send.test_event_code,
        )
    except ProviderError as error:
        outcome, code = _classify(error)
        return _record(engine, send, outcome, code, None, error.retry_after, clock())
    if answer.events_received != 1:
        return _record(engine, send, "count_mismatch", "count_mismatch", answer, None, clock())
    return _record(engine, send, "accepted", None, answer, None, clock())


# One bounded delivery pass: expire overdue deliveries, then claim and send at most `limit`.
# Returns outcome counts only. A fixed `now` (tests) is used for every step.
def run_deliveries(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> dict[str, int]:
    providers = tuple(sorted(name for name, item in registry.items() if item.capability.delivery))
    if not providers:
        return {}
    keyring, keys = require_keys(settings), require_tombstone_keys(settings)

    def clock() -> datetime:
        return now if now is not None else now_utc()

    counts: dict[str, int] = {}
    expired = expire_overdue(engine, clock())
    if expired:
        counts["expired"] = expired
    for _ in range(limit):
        claimed = _claim(engine, keyring, keys, providers, clock())
        if claimed is None:
            break
        outcome = (
            claimed if isinstance(claimed, str) else _attempt(engine, registry, claimed, clock)
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# --- Administration and reads (D10) ---------------------------------------------------------


EVENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
TEST_CODE = re.compile(r"[A-Za-z0-9]{1,32}")


class DestinationAdmin(TenancyService):
    def __init__(
        self,
        session: Session,
        actor_user_id: UUID,
        settings: Settings,
        registry: Mapping[str, ConnectorProvider],
    ) -> None:
        super().__init__(session, actor_user_id)
        self.settings, self.registry = settings, registry

    def _destination(self, agency_id: UUID, client_id: UUID, destination_id: UUID):
        item = self.session.scalar(
            select(ConversionDestination)
            .where(
                ConversionDestination.agency_id == agency_id,
                ConversionDestination.client_id == client_id,
                ConversionDestination.id == destination_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    def _delivery(self, agency_id: UUID, client_id: UUID, delivery_id: UUID):
        item = self.session.scalar(
            select(ConversionDelivery)
            .where(
                ConversionDelivery.agency_id == agency_id,
                ConversionDelivery.client_id == client_id,
                ConversionDelivery.id == delivery_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    @staticmethod
    def _names(event_name: str | None, test_event_code: str | None) -> None:
        if event_name is not None and not EVENT_NAME.fullmatch(event_name):
            raise ConnectorError("invalid_event_name", 422)
        if test_event_code is not None and not TEST_CODE.fullmatch(test_event_code):
            raise ConnectorError("invalid_test_event_code", 422)

    # Create the destination of one delivery connection of the client, disabled (D10).
    def create(
        self,
        agency_id: UUID,
        client_id: UUID,
        connection_id: UUID,
        event_name: str = "Purchase",
        test_event_code: str | None = None,
    ) -> ConversionDestination:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        self._names(event_name, test_event_code)
        connection = self.session.scalar(
            select(ConnectorConnection)
            .where(
                ConnectorConnection.agency_id == agency_id,
                ConnectorConnection.client_id == client_id,
                ConnectorConnection.id == connection_id,
            )
            .with_for_update()
        )
        if connection is None:
            raise AccessDenied()
        provider = self.registry.get(connection.provider)
        if provider is None or not provider.capability.delivery:
            raise ConnectorError("not_a_delivery_connection", 422)
        if connection.status not in LIVE:
            raise ConnectorError("connection_not_active", 409)
        if self.session.scalar(
            select(ConversionDestination.id).where(
                ConversionDestination.connection_id == connection.id
            )
        ):
            raise ConnectorError("destination_exists", 409)
        destination = ConversionDestination(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            connection_id=connection.id,
            event_name=event_name,
            test_event_code=test_event_code,
            enabled=False,
            created_by_membership_id=actor.id,
        )
        self.session.add(destination)
        self.session.flush()
        self._audit(agency_id, "destination.created", "destination", destination.id, client_id)
        return destination

    # Change a destination. Disabling cancels its open deliveries and destroys their payloads.
    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        destination_id: UUID,
        *,
        enabled: bool | None = None,
        event_name: str | None = None,
        test_event_code: str | None = None,
        clear_test_event_code: bool = False,
        now: datetime | None = None,
    ) -> ConversionDestination:
        self._manager(agency_id, write=True)
        self._names(event_name, test_event_code)
        destination = self._destination(agency_id, client_id, destination_id)
        now = now or now_utc()
        if event_name is not None:
            destination.event_name = event_name
        if clear_test_event_code:
            destination.test_event_code = None
        elif test_event_code is not None:
            destination.test_event_code = test_event_code
        if enabled is not None:
            if destination.enabled and not enabled:
                cancel_open(
                    self.session,
                    reason="destination_disabled",
                    now=now,
                    destination_id=destination.id,
                )
            destination.enabled = enabled
        destination.updated_at = now
        self._audit(agency_id, "destination.updated", "destination", destination.id, client_id)
        return destination

    # Requeue a configuration rejection after its repair, at most 3 times, before the deadline,
    # with the same event ID (D9). Nothing requeues automatically.
    def requeue(
        self, agency_id: UUID, client_id: UUID, delivery_id: UUID, now: datetime | None = None
    ) -> ConversionDelivery:
        self._manager(agency_id, write=True)
        now = now or now_utc()
        row = self._delivery(agency_id, client_id, delivery_id)
        destination = self.session.get(ConversionDestination, row.destination_id)
        connection = self.session.get(ConnectorConnection, row.connection_id)
        if not requeueable(row, now) or not (
            destination is not None
            and destination.enabled
            and connection is not None
            and connection.status == "active"
        ):
            raise ConnectorError("requeue_not_available", 409)
        row.status, row.reason, row.rejection_class = "queued", None, None
        row.retries, row.requeues, row.not_before, row.updated_at = 0, row.requeues + 1, None, now
        self._audit(agency_id, "delivery.requeued", "delivery", row.id, client_id)
        return row

    # Dismiss a rejected or undeliverable delivery; its payload is destroyed.
    def dismiss(
        self, agency_id: UUID, client_id: UUID, delivery_id: UUID, now: datetime | None = None
    ) -> ConversionDelivery:
        self._manager(agency_id, write=True)
        now = now or now_utc()
        row = self._delivery(agency_id, client_id, delivery_id)
        if not dismissable(row):
            raise ConnectorError("dismiss_not_available", 409)
        row.status, row.updated_at = "dismissed", now
        if row.ended_at is None:
            row.ended_at = now
        for name, value in DESTROYED.items():
            setattr(row, name, value)
        self._audit(agency_id, "delivery.dismissed", "delivery", row.id, client_id)
        return row


def requeueable(row: ConversionDelivery, now: datetime) -> bool:
    return (
        row.status == "rejected"
        and row.rejection_class == "configuration"
        and row.requeues < REQUEUE_LIMIT
        and row.deadline > now
    )


def dismissable(row: ConversionDelivery) -> bool:
    return row.status in {"rejected", "undeliverable"}


def list_destinations(session: Session, access: ScopedAccess) -> list[ConversionDestination]:
    return list(
        session.scalars(
            select(ConversionDestination)
            .where(
                ConversionDestination.agency_id == access.agency_id,
                ConversionDestination.client_id == access.client_id,
            )
            .order_by(ConversionDestination.created_at, ConversionDestination.id)
            .limit(100)
        )
    )


# Deliveries of one client, newest first, for readers with finance:read (D10).
def list_deliveries(
    session: Session,
    access: ScopedAccess,
    *,
    destination_id: UUID | None = None,
    status: str | None = None,
    after: UUID | None = None,
    limit: int = 100,
) -> list[ConversionDelivery]:
    if access.permission != "finance:read":
        raise AccessDenied()
    query = select(ConversionDelivery).where(
        ConversionDelivery.agency_id == access.agency_id,
        ConversionDelivery.client_id == access.client_id,
    )
    if destination_id is not None:
        query = query.where(ConversionDelivery.destination_id == destination_id)
    if status is not None:
        query = query.where(ConversionDelivery.status == status)
    if after is not None:
        anchor = session.scalar(
            select(ConversionDelivery.created_at).where(
                ConversionDelivery.client_id == access.client_id, ConversionDelivery.id == after
            )
        )
        if anchor is not None:
            query = query.where(
                tuple_(ConversionDelivery.created_at, ConversionDelivery.id) < (anchor, after)
            )
    return list(
        session.scalars(
            query.order_by(
                ConversionDelivery.created_at.desc(), ConversionDelivery.id.desc()
            ).limit(limit)
        )
    )


def delivery_view(row: ConversionDelivery, *, manage: bool, now: datetime) -> dict[str, object]:
    return {
        "id": row.id,
        "destination_id": row.destination_id,
        "event_name": row.event_name,
        "action_source": row.action_source,
        "event_time": row.event_time,
        "status": row.status,
        "reason": row.reason,
        "rejection_class": row.rejection_class,
        "value": decimal_text(row.value_minor, row.currency_exponent),
        "currency": row.currency,
        "attempts": row.attempts,
        "requeues": row.requeues,
        "next_attempt_at": row.not_before,
        "deadline": row.deadline,
        "created_at": row.created_at,
        "delivered_at": row.delivered_at,
        "ended_at": row.ended_at,
        "actions": {
            "requeue": manage and requeueable(row, now),
            "dismiss": manage and dismissable(row),
        },
    }


def destination_view(row: ConversionDestination, *, manage: bool) -> dict[str, object]:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "event_name": row.event_name,
        "test_event_code": row.test_event_code,
        "enabled": row.enabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "actions": {"update": manage},
    }


__all__ = [
    "ClickIdentifier",
    "DestinationAdmin",
    "SaleCandidate",
    "SyntheticJourney",
    "candidates_from_feed",
    "candidates_from_ledger",
    "delivery_view",
    "destination_view",
    "enqueue_conversions",
    "expire_overdue",
    "list_deliveries",
    "list_destinations",
    "run_deliveries",
]
