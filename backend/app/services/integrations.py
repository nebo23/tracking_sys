"""Integration sources and booking intake (specification 015-D, D-068 E2 to E5, E9 to E11).

Owner and Admin sessions create, list, rename, disable or re-activate a client's integration
sources and replace their signing secret, each audited in the caller's transaction. A Cal.com
source takes the secret the client set in Cal.com; a signed webhook source receives a secret
issued once by the platform. Secrets are sealed under the D-025 keyring and never returned again.

A verified delivery is recorded under the client's 004 privacy lock, because a booking may be
linked to a collection subject (E4): the lock orders the link with erasure and consent changes.
A link is effective only while the subject's attribution consent is granted (review finding
R003): app.services.collection.record_consent detaches the subject's bookings when that consent
is withdrawn or denied, or granted again after a lapse, and every read below counts a stored
link only while the consent is granted now, which also covers an expiry. The delivery's digest
makes a repeated delivery a no-op, and a booking's state is derived from its minimal events, so
any delivery order gives the same result. Nothing here writes revenue evidence. Nothing here
calls a provider.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from app.advertising.currencies import decimal_text
from app.collection.contract import Rejected, verify_webhook
from app.config import Settings
from app.integrations.bookings import Event, Invalid, Unsupported, derive_state, parse_calcom
from app.integrations.bookings import parse_contract as parse_booking_contract
from app.integrations.deals import parse_deal
from app.models import (
    Agency,
    Booking,
    BookingEvent,
    ClientWorkspace,
    CollectionSubject,
    CrmDeal,
    CrmStageRule,
    IntegrationDelivery,
    IntegrationSource,
    IntegrationSourceSecret,
    StoredConsentRecord,
)
from app.privacy.consent import ConsentState, Purpose
from app.privacy.providers import feature_allowed, rule
from app.privacy.token_secrets import LocalKeyring, SealedSecret, SecretContext, open_secret, seal
from app.security import new_token
from app.services.collection import consent_view, find_subject, lock_client, require_token_keys
from app.services.revenue import client_ledger
from app.services.tenancy import AccessDenied, TenancyService

SECRET_OVERLAP = timedelta(hours=24)
CLIENT_SECRET = re.compile(r"[!-~]{16,256}")
PUBLIC_KEY = re.compile(r"isk_[A-Za-z0-9_-]{43}")
CALCOM_SIGNATURE = re.compile(r"(?:sha256=)?([0-9a-fA-F]{64})")
CALLBACKS = {
    "cal_com": "/integrations/cal-com/{key}",
    "signed_webhook": "/integrations/webhook/{key}",
}
Kind = Literal["cal_com", "signed_webhook"]


class IntegrationError(Exception):
    """An integration failure with a fixed public code; it never carries a secret or payload."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


class Unverifiable(ValueError):
    """The delivery cannot be verified; the route answers 401 and stores nothing."""


# Whether a source kind may be used today (E11): its setting is on and, for Cal.com, the
# calcom.webhooks rule is current. The signed webhook contract is the project's own, with no
# provider terms, so its setting alone decides.
def kind_allowed(settings: Settings, kind: str, today: date) -> bool:
    if kind == "cal_com":
        return (
            settings.integrations_calcom_enabled
            and feature_allowed(rule("calcom.webhooks"), today).allowed
        )
    if kind == "signed_webhook":
        return settings.integrations_webhook_enabled
    return False


def require_kind(settings: Settings, kind: str, today: date) -> None:
    if not kind_allowed(settings, kind, today):
        raise IntegrationError("integration_unavailable", 503)


def callback_path(source: IntegrationSource) -> str:
    return CALLBACKS[source.kind].format(key=source.public_key)


def _context(source: IntegrationSource, secret_id: UUID, version: int) -> SecretContext:
    return SecretContext(
        source.agency_id, source.client_id, source.id, secret_id, "integration_signing", version
    )


def _store_secret(
    session: Session, keyring: LocalKeyring, source: IntegrationSource, raw: str, version: int
) -> None:
    secret_id = uuid4()
    sealed = seal(keyring, raw, _context(source, secret_id, version))
    session.add(
        IntegrationSourceSecret(
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


def _client_secret(kind: str, value: str | None) -> str | None:
    if kind == "cal_com":
        if not isinstance(value, str) or not CLIENT_SECRET.fullmatch(value):
            raise ValueError("A Cal.com secret must be 16-256 printable characters, no spaces.")
        return value
    if value is not None:
        raise ValueError("A signed webhook source receives a secret issued by the platform.")
    return None


# Owner/Admin administration of integration sources (E10); audited in the caller's transaction.
class IntegrationAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _now(self) -> datetime:
        return self.session.scalar(select(func.clock_timestamp()))

    def _source(self, agency_id: UUID, client_id: UUID, source_id: UUID) -> IntegrationSource:
        item = self.session.scalar(
            select(IntegrationSource)
            .where(
                IntegrationSource.agency_id == agency_id,
                IntegrationSource.client_id == client_id,
                IntegrationSource.id == source_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    # Create a source; a signed webhook source returns its issued secret once.
    def create(
        self, agency_id: UUID, client_id: UUID, *, kind: str, name: str, secret: str | None
    ) -> tuple[IntegrationSource, str | None]:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        if kind not in CALLBACKS:
            raise ValueError("Unsupported integration kind.")
        raw = _client_secret(kind, secret)
        require_kind(self.settings, kind, self._now().date())
        keyring = require_token_keys(self.settings)
        source = IntegrationSource(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            kind=kind,
            name=self._name(name),
            status="active",
            public_key="isk_" + new_token(),
            created_by_membership_id=actor.id,
        )
        self.session.add(source)
        self.session.flush()
        issued = None
        if raw is None:
            raw = issued = "whsec_" + new_token()
        _store_secret(self.session, keyring, source, raw, 1)
        self._audit(agency_id, "integration.created", "integration_source", source.id, client_id)
        return source, issued

    def list(self, agency_id: UUID, client_id: UUID) -> list[IntegrationSource]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(IntegrationSource)
                .where(
                    IntegrationSource.agency_id == agency_id,
                    IntegrationSource.client_id == client_id,
                )
                .order_by(IntegrationSource.created_at, IntegrationSource.id)
                .limit(100)
            )
        )

    # A new signing secret version; the previous versions stay valid for SECRET_OVERLAP. A Cal.com
    # source takes the client's new secret; a signed webhook source returns a new issued one.
    def replace_secret(
        self, agency_id: UUID, client_id: UUID, source_id: UUID, secret: str | None
    ) -> tuple[IntegrationSource, str | None]:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        raw = _client_secret(source.kind, secret)
        keyring = require_token_keys(self.settings)
        now = self._now()
        versions = list(
            self.session.scalars(
                select(IntegrationSourceSecret).where(
                    IntegrationSourceSecret.source_id == source.id
                )
            )
        )
        for item in versions:
            if item.retires_at is None:
                item.retires_at = now + SECRET_OVERLAP
        issued = None
        if raw is None:
            raw = issued = "whsec_" + new_token()
        _store_secret(
            self.session, keyring, source, raw, max((v.version for v in versions), default=0) + 1
        )
        source.updated_at = now
        self._audit(
            agency_id, "integration.secret_replaced", "integration_source", source.id, client_id
        )
        return source, issued

    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        source_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
    ) -> IntegrationSource:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("Invalid source status.")
        now = self._now()
        if status == "active" and source.status != "active":
            require_kind(self.settings, source.kind, now.date())
        if name is not None:
            source.name = self._name(name)
        if status is not None:
            source.status = status
        source.updated_at = now
        self._audit(agency_id, "integration.updated", "integration_source", source.id, client_id)
        return source


# The active source of an active client and agency behind a public key and kind, or None.
def live_source(session: Session, kind: str, public_key: str) -> IntegrationSource | None:
    if not PUBLIC_KEY.fullmatch(public_key):
        return None
    return session.scalar(
        select(IntegrationSource)
        .join(
            ClientWorkspace,
            (ClientWorkspace.agency_id == IntegrationSource.agency_id)
            & (ClientWorkspace.id == IntegrationSource.client_id),
        )
        .join(Agency, Agency.id == IntegrationSource.agency_id)
        .where(
            IntegrationSource.public_key == public_key,
            IntegrationSource.kind == kind,
            IntegrationSource.status == "active",
            ClientWorkspace.status == "active",
            Agency.status == "active",
        )
        .execution_options(populate_existing=True)
    )


# Every secret version of a source still valid at now; no version is dropped by a count limit.
def live_secrets(
    session: Session, settings: Settings, source: IntegrationSource, now: datetime
) -> list[str]:
    keyring = require_token_keys(settings)
    rows = session.scalars(
        select(IntegrationSourceSecret)
        .where(
            IntegrationSourceSecret.source_id == source.id,
            (IntegrationSourceSecret.retires_at.is_(None))
            | (IntegrationSourceSecret.retires_at > now),
        )
        .order_by(IntegrationSourceSecret.version.desc())
    )
    return [
        open_secret(
            keyring,
            SealedSecret(row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext),
            _context(source, row.id, row.version),
        )
        for row in rows
    ]


def parse_object(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise Unverifiable("invalid_body") from error
    if not isinstance(payload, dict):
        raise Unverifiable("invalid_body")
    return payload


# Cal.com signs the payload with HMAC-SHA256 under the client's secret (W-1); the hexadecimal
# encoding over the raw body is read here and is unverified until a live check. Every live secret
# is tried in constant time.
def verify_calcom(body: bytes, header: str | None, secrets: list[str]) -> Mapping[str, Any]:
    match = CALCOM_SIGNATURE.fullmatch(header or "")
    if match is None:
        raise Unverifiable("missing_signature")
    expected = match.group(1).lower().encode()
    matched = False
    for secret in secrets:
        computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest().encode()
        matched = hmac.compare_digest(computed, expected) | matched
    if not matched:
        raise Unverifiable("invalid_signature")
    return parse_object(body)


# The signed webhook contract uses the 004 signature (t=<unix>,v1=<hex HMAC-SHA256 of "t.body">)
# within its five-minute window.
def verify_signed(
    body: bytes, header: str | None, secrets: list[str], now: datetime
) -> Mapping[str, Any]:
    try:
        verify_webhook(header, body, secrets, now)
    except Rejected as rejection:
        raise Unverifiable(rejection.reason) from rejection
    return parse_object(body)


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _delivered(session: Session, source: IntegrationSource, digest: str) -> bool:
    return (
        session.scalar(
            select(IntegrationDelivery.id).where(
                IntegrationDelivery.source_id == source.id,
                IntegrationDelivery.delivery_digest == digest,
            )
        )
        is not None
    )


def _record(
    session: Session,
    source: IntegrationSource,
    digest: str,
    received: datetime,
    outcome: str,
    reason: str | None,
) -> str:
    session.execute(
        insert(IntegrationDelivery)
        .values(
            id=uuid4(),
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            delivery_digest=digest,
            received_at=received,
            outcome=outcome,
            reason=reason,
        )
        .on_conflict_do_nothing(constraint="uq_integration_deliveries_digest")
    )
    return outcome


def _link(session: Session, booking: Booking, token: str, received: datetime) -> str:
    subject = find_subject(session, booking.client_id, token)
    if subject is None:
        return "subject_unknown"
    if consent_view(session, subject, received).states[Purpose.ATTRIBUTION] is not (
        ConsentState.GRANTED
    ):
        return "consent_missing"
    booking.subject_id, booking.linked_at = subject.id, received
    return "linked"


# The subjects of one client whose attribution consent is granted at `now`: the latest
# attribution record per subject, by receipt time and then ID exactly as
# app.privacy.consent.current_state orders them, is a grant that has not expired (R003).
def granted_subjects(client_id: UUID, now: datetime) -> Select:
    latest = (
        select(
            StoredConsentRecord.subject_id,
            StoredConsentRecord.state,
            StoredConsentRecord.expires_at,
        )
        .where(
            StoredConsentRecord.client_id == client_id,
            StoredConsentRecord.purpose == Purpose.ATTRIBUTION.value,
        )
        .ext(distinct_on(StoredConsentRecord.subject_id))
        .order_by(
            StoredConsentRecord.subject_id,
            StoredConsentRecord.received_at.desc(),
            StoredConsentRecord.id.desc(),
        )
        .subquery()
    )
    return select(latest.c.subject_id).where(
        latest.c.state == ConsentState.GRANTED.value,
        or_(latest.c.expires_at.is_(None), latest.c.expires_at > now),
    )


# Whether one subject's attribution consent is granted at `now` (the 003 evaluation).
def _granted(session: Session, subject_id: UUID, now: datetime) -> bool:
    subject = session.get(CollectionSubject, subject_id)
    return (
        subject is not None
        and consent_view(session, subject, now).states[Purpose.ATTRIBUTION] is ConsentState.GRANTED
    )


# Whether a booking's stored link is effective now: its subject's attribution is granted.
def effective_link(client_id: UUID, now: datetime) -> ColumnElement[bool]:
    return and_(
        Booking.subject_id.is_not(None), Booking.subject_id.in_(granted_subjects(client_id, now))
    )


# A booking ID belongs to the source that delivered it: a chain is found, extended and merged only
# among that source's events (review finding R006). Two signed webhook sources of one client may
# reuse the same local ID, and a reschedule or cancellation from one never reaches the other.
def _apply_booking(
    session: Session, source: IntegrationSource, event: Event, received: datetime
) -> str | None:
    refs = {event.ref} | ({event.previous_ref} if event.previous_ref else set())
    chains = set(
        session.scalars(
            select(BookingEvent.booking_id).where(
                BookingEvent.source_id == source.id,
                BookingEvent.ref.in_(refs),
            )
        )
    ) | set(
        session.scalars(
            select(BookingEvent.booking_id).where(
                BookingEvent.source_id == source.id,
                BookingEvent.previous_ref.in_(refs),
            )
        )
    )
    merged = False
    if chains:
        # A later event can connect two chains, for example a cancellation received before its
        # booking's creation; the events of the later chains move into the earliest one.
        found = sorted(
            (session.get(Booking, item, with_for_update=True) for item in chains),
            key=lambda row: (row.first_received_at, str(row.id)),
        )
        booking = found[0]
        for other in found[1:]:
            session.execute(
                update(BookingEvent)
                .where(BookingEvent.booking_id == other.id)
                .values(booking_id=booking.id)
            )
            # A link moves with the merged events only while it is effective (R003).
            if (
                booking.subject_id is None
                and other.subject_id is not None
                and _granted(session, other.subject_id, received)
            ):
                booking.subject_id, booking.linked_at = other.subject_id, other.linked_at
            other.subject_id = other.linked_at = None
            other.status, other.reschedule_count, other.updated_at = "merged", 0, received
            merged = True
        session.flush()
    else:
        booking = Booking(
            id=uuid4(),
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            provider=source.kind,
            status="requested",
            reschedule_count=0,
            first_received_at=received,
            updated_at=received,
        )
        session.add(booking)
        session.flush()
    session.execute(
        insert(BookingEvent)
        .values(
            id=uuid4(),
            agency_id=source.agency_id,
            client_id=source.client_id,
            booking_id=booking.id,
            source_id=source.id,
            provider=source.kind,
            kind=event.kind,
            ref=event.ref,
            previous_ref=event.previous_ref,
            event_type_ref=event.event_type_ref,
            occurred_at=event.occurred_at,
            start_at=event.start_at,
            end_at=event.end_at,
        )
        .on_conflict_do_nothing(constraint="uq_booking_events_event")
    )
    rows = session.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id))
    state = derive_state(
        Event(
            row.kind,
            row.ref,
            row.previous_ref,
            row.event_type_ref,
            row.occurred_at,
            row.start_at,
            row.end_at,
        )
        for row in rows
    )
    booking.status = state.status
    booking.event_type_ref = state.event_type_ref
    booking.start_at, booking.end_at = state.start_at, state.end_at
    booking.reschedule_count = state.reschedule_count
    booking.updated_at = received
    reason = "merged" if merged else None
    if event.subject_token is not None and booking.subject_id is None:
        reason = _link(session, booking, event.subject_token, received)
    session.flush()
    return reason


# Record one verified booking delivery of a source: a repeated delivery is a no-op, an
# unsupported event or unreadable booking stores nothing but its diagnostic row.
def receive_booking(
    session: Session, source: IntegrationSource, payload: Mapping[str, Any], digest: str
) -> str:
    received = lock_client(session, source.client_id)
    if _delivered(session, source, digest):
        return "duplicate"
    try:
        event = (parse_calcom if source.kind == "cal_com" else parse_booking_contract)(payload)
    except Unsupported:
        return _record(session, source, digest, received, "ignored", "unsupported_event")
    except Invalid:
        return _record(session, source, digest, received, "invalid", "invalid_booking")
    reason = _apply_booking(session, source, event, received)
    return _record(session, source, digest, received, "applied", reason)


# Bookings of one client for client:read readers (E10): totals by status and the newest bookings.
# A booking counts as linked only while its subject's attribution consent is granted now (R003).
def bookings_view(session: Session, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
    now = session.scalar(select(func.clock_timestamp()))
    linked_now = effective_link(client_id, now)
    scope = (
        Booking.agency_id == agency_id,
        Booking.client_id == client_id,
        Booking.status != "merged",
    )
    totals = dict.fromkeys(("requested", "scheduled", "cancelled", "rejected", "completed"), 0)
    for status, number in session.execute(
        select(Booking.status, func.count()).where(*scope).group_by(Booking.status)
    ):
        totals[status] = number
    linked = session.scalar(select(func.count()).select_from(Booking).where(*scope, linked_now))
    rows = session.execute(
        select(Booking, linked_now.label("linked"))
        .where(*scope)
        .order_by(Booking.updated_at.desc(), Booking.id)
        .limit(500)
    )
    return {
        "totals": {**totals, "linked": linked},
        "bookings": [
            {
                "id": row.id,
                "provider": row.provider,
                "status": row.status,
                "event_type_ref": row.event_type_ref,
                "start_at": row.start_at,
                "end_at": row.end_at,
                "reschedule_count": row.reschedule_count,
                "linked": bool(effective),
                "updated_at": row.updated_at,
            }
            for row, effective in rows
        ],
    }


# --- CRM stage changes (E5, E6) -------------------------------------------------------------


# Total orders of the parts of a deal change: the occurrence time first, then the values, so two
# changes at the same instant resolve the same way in any delivery order (R007).
def _stage_key(occurred_at: datetime, stage: str, pipeline: str, previous: str | None) -> tuple:
    return (occurred_at, stage, pipeline, previous or "")


# Record one verified deal stage change: a repeated delivery is a no-op. A change is a partial
# update (review finding R007): it always carries the stage, and optionally the amount with its
# currency and a payment reference. Each part keeps the value of the change with the latest
# occurrence time that supplied it (ties broken by the value), and an omitted part keeps the
# latest supplied value, so every delivery order of the same changes ends in the same deal
# (T-58). The amount and its currency always move together. A stage change never writes revenue
# evidence (E6).
def receive_deal(
    session: Session, source: IntegrationSource, payload: Mapping[str, Any], digest: str
) -> str:
    received = lock_client(session, source.client_id)
    if _delivered(session, source, digest):
        return "duplicate"
    try:
        change = parse_deal(payload)
    except Unsupported:
        return _record(session, source, digest, received, "ignored", "unsupported_event")
    except Invalid:
        return _record(session, source, digest, received, "invalid", "invalid_deal")
    deal = session.scalar(
        select(CrmDeal)
        .where(CrmDeal.source_id == source.id, CrmDeal.deal_ref == change.deal_ref)
        .with_for_update()
    )
    incoming = _stage_key(change.occurred_at, change.stage, change.pipeline, change.previous_stage)
    changed = False
    if deal is None:
        deal = CrmDeal(
            id=uuid4(),
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            deal_ref=change.deal_ref,
            first_received_at=received,
        )
        session.add(deal)
    if deal.stage_at is None or incoming > _stage_key(
        deal.stage_at, deal.stage, deal.pipeline, deal.previous_stage
    ):
        deal.pipeline, deal.stage, deal.previous_stage = (
            change.pipeline,
            change.stage,
            change.previous_stage,
        )
        deal.stage_at = change.occurred_at
        changed = True
    amount = change.amount
    if amount is not None and (
        deal.amount_at is None
        or (change.occurred_at, amount.currency.code, amount.minor)
        > (deal.amount_at, deal.currency, deal.amount_minor)
    ):
        deal.amount_minor = amount.minor
        deal.currency = amount.currency.code
        deal.currency_exponent = amount.currency.exponent
        deal.amount_at = change.occurred_at
        changed = True
    reference = change.payment_reference
    if reference is not None and (
        deal.payment_reference_at is None
        or (change.occurred_at, reference) > (deal.payment_reference_at, deal.payment_reference)
    ):
        deal.payment_reference, deal.payment_reference_at = reference, change.occurred_at
        changed = True
    if changed:
        deal.updated_at = received
        session.flush()
    return _record(session, source, digest, received, "applied", None)


def _rule_text(value: str) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(value) <= 128 or not value.isprintable():
        raise ValueError("A pipeline or stage name has 1-128 printable characters.")
    return value


# Owner/Admin administration of won and lost stage rules (E6); audited.
class CrmRuleAdmin(TenancyService):
    def create(
        self, agency_id: UUID, client_id: UUID, *, pipeline: str, stage: str, outcome: str
    ) -> CrmStageRule:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        if outcome not in {"won", "lost"}:
            raise ValueError("A stage rule is won or lost.")
        item = CrmStageRule(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            pipeline=_rule_text(pipeline),
            stage=_rule_text(stage),
            outcome=outcome,
            status="active",
            created_by_membership_id=actor.id,
        )
        self.session.add(item)
        self.session.flush()
        self._audit(agency_id, "crm_rule.created", "crm_rule", item.id, client_id)
        return item

    def list(self, agency_id: UUID, client_id: UUID) -> list[CrmStageRule]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(CrmStageRule)
                .where(CrmStageRule.agency_id == agency_id, CrmStageRule.client_id == client_id)
                .order_by(CrmStageRule.pipeline, CrmStageRule.stage)
                .limit(500)
            )
        )

    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        rule_id: UUID,
        *,
        outcome: str | None = None,
        status: str | None = None,
    ) -> CrmStageRule:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        item = self.session.scalar(
            select(CrmStageRule)
            .where(
                CrmStageRule.agency_id == agency_id,
                CrmStageRule.client_id == client_id,
                CrmStageRule.id == rule_id,
            )
            .with_for_update()
        )
        if item is None:
            raise AccessDenied()
        if outcome is not None and outcome not in {"won", "lost"}:
            raise ValueError("A stage rule is won or lost.")
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("Invalid rule status.")
        if outcome is not None:
            item.outcome = outcome
        if status is not None:
            item.status = status
        item.updated_at = self.session.scalar(select(func.clock_timestamp()))
        self._audit(agency_id, "crm_rule.updated", "crm_rule", item.id, client_id)
        return item


# A client's deals (E6, E10). The status comes from the active rules: no rule is open, a lost rule
# is lost, and a won rule is won_verified only when the payment reference matches a verified
# ledger sale of the same client, otherwise won_unverified. Amounts and the linked sale are
# returned only to finance:read readers.
def deals_view(
    session: Session, agency_id: UUID, client_id: UUID, *, include_amounts: bool
) -> dict[str, Any]:
    rules = {
        (row.pipeline, row.stage): row.outcome
        for row in session.scalars(
            select(CrmStageRule).where(
                CrmStageRule.agency_id == agency_id,
                CrmStageRule.client_id == client_id,
                CrmStageRule.status == "active",
            )
        )
    }
    rows = list(
        session.scalars(
            select(CrmDeal)
            .where(CrmDeal.agency_id == agency_id, CrmDeal.client_id == client_id)
            .order_by(CrmDeal.updated_at.desc(), CrmDeal.id)
            .limit(500)
        )
    )
    sales: set[str] = set()
    if any(row.payment_reference for row in rows):
        ledger = client_ledger(session, agency_id, client_id)
        sales = {item.operation_id for item in ledger.calculation.transactions}
    totals = dict.fromkeys(("open", "won_verified", "won_unverified", "lost"), 0)
    deals = []
    for row in rows:
        outcome = rules.get((row.pipeline, row.stage))
        if outcome is None:
            status = "open"
        elif outcome == "lost":
            status = "lost"
        else:
            status = "won_verified" if row.payment_reference in sales else "won_unverified"
        totals[status] += 1
        item: dict[str, Any] = {
            "id": row.id,
            "deal_ref": row.deal_ref,
            "pipeline": row.pipeline,
            "stage": row.stage,
            "previous_stage": row.previous_stage,
            "stage_at": row.stage_at,
            "status": status,
        }
        if include_amounts:
            item["amount"] = (
                decimal_text(row.amount_minor, row.currency_exponent)
                if row.amount_minor is not None
                else None
            )
            item["currency"] = row.currency
            item["linked_sale"] = row.payment_reference if status == "won_verified" else None
        deals.append(item)
    return {"totals": totals, "deals": deals}
