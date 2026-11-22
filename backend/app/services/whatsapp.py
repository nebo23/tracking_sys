"""WhatsApp numbers, notification intake and the referral read (015-E, D-068 E7 to E11).

Owner and Admin sessions register, rename, disable or re-activate a client's WhatsApp Business
phone number IDs, each audited. The Meta app secret and verify token are platform settings,
never stored in the database. A verified notification records each inbound message of a
registered, active number of an active client once, keeping only its referral; messages of
unknown numbers are skipped. Nothing here calls Meta or correlates a conversation with a person.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.whatsapp import Message
from app.models import Agency, ClientWorkspace, WhatsappMessage, WhatsappNumber
from app.privacy.providers import feature_allowed, rule
from app.services.tenancy import AccessDenied, TenancyService

PHONE_NUMBER_ID = "^[1-9][0-9]{0,31}$"


class WhatsappError(Exception):
    """A WhatsApp failure with a fixed public code; it never carries a secret or payload."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# The WhatsApp intake is usable only while the setting is on and the whatsapp.cloud_api rule is
# current (E11).
def whatsapp_allowed(settings: Settings, today: date) -> bool:
    return settings.whatsapp_enabled and feature_allowed(rule("whatsapp.cloud_api"), today).allowed


def require_whatsapp(settings: Settings, today: date) -> None:
    if not whatsapp_allowed(settings, today):
        raise WhatsappError("whatsapp_unavailable", 503)


class WhatsappNumberAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _now(self) -> datetime:
        return self.session.scalar(select(func.clock_timestamp()))

    def create(
        self, agency_id: UUID, client_id: UUID, *, phone_number_id: str, name: str
    ) -> WhatsappNumber:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        require_whatsapp(self.settings, self._now().date())
        item = WhatsappNumber(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            phone_number_id=phone_number_id,
            name=self._name(name),
            status="active",
            created_by_membership_id=actor.id,
        )
        self.session.add(item)
        self.session.flush()
        self._audit(agency_id, "whatsapp_number.created", "whatsapp_number", item.id, client_id)
        return item

    def list(self, agency_id: UUID, client_id: UUID) -> list[WhatsappNumber]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(WhatsappNumber)
                .where(WhatsappNumber.agency_id == agency_id, WhatsappNumber.client_id == client_id)
                .order_by(WhatsappNumber.created_at, WhatsappNumber.id)
                .limit(100)
            )
        )

    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        number_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
    ) -> WhatsappNumber:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        item = self.session.scalar(
            select(WhatsappNumber)
            .where(
                WhatsappNumber.agency_id == agency_id,
                WhatsappNumber.client_id == client_id,
                WhatsappNumber.id == number_id,
            )
            .with_for_update()
        )
        if item is None:
            raise AccessDenied()
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("Invalid number status.")
        now = self._now()
        if status == "active" and item.status != "active":
            require_whatsapp(self.settings, now.date())
        if name is not None:
            item.name = self._name(name)
        if status is not None:
            item.status = status
        item.updated_at = now
        self._audit(agency_id, "whatsapp_number.updated", "whatsapp_number", item.id, client_id)
        return item


def _numbers(session: Session, ids: set[str]) -> dict[str, WhatsappNumber]:
    if not ids:
        return {}
    rows = session.scalars(
        select(WhatsappNumber)
        .join(
            ClientWorkspace,
            (ClientWorkspace.agency_id == WhatsappNumber.agency_id)
            & (ClientWorkspace.id == WhatsappNumber.client_id),
        )
        .join(Agency, Agency.id == WhatsappNumber.agency_id)
        .where(
            WhatsappNumber.phone_number_id.in_(ids),
            WhatsappNumber.status == "active",
            ClientWorkspace.status == "active",
            Agency.status == "active",
        )
    )
    return {row.phone_number_id: row for row in rows}


# Record the inbound messages of one verified notification. Returns the counts of stored,
# repeated and skipped (unregistered number) messages.
def receive_messages(session: Session, items: list[Message]) -> dict[str, int]:
    counts = {"stored": 0, "duplicate": 0, "skipped": 0}
    numbers = _numbers(session, {item.phone_number_id for item in items})
    received = session.scalar(select(func.clock_timestamp()))
    for item in items:
        number = numbers.get(item.phone_number_id)
        if number is None:
            counts["skipped"] += 1
            continue
        stored = session.scalar(
            insert(WhatsappMessage)
            .values(
                id=uuid4(),
                agency_id=number.agency_id,
                client_id=number.client_id,
                number_id=number.id,
                message_digest=item.digest,
                message_at=item.message_at,
                received_at=received,
                has_referral=item.has_referral,
                source_type=item.source_type,
                source_id=item.source_id,
                click_id_present=item.click_id_present,
            )
            .on_conflict_do_nothing(constraint="uq_whatsapp_messages_digest")
            .returning(WhatsappMessage.id)
        )
        counts["stored" if stored is not None else "duplicate"] += 1
    return counts


# Messages of one client received in [since, until) UTC days, by referral; messages without a
# referral are counted as unknown and never guessed (E8).
def referrals_view(
    session: Session, agency_id: UUID, client_id: UUID, since: date, until: date
) -> dict[str, Any]:
    if until <= since or (until - since) > timedelta(days=92):
        raise ValueError("Use a range of 1 to 92 days.")
    start = datetime(since.year, since.month, since.day, tzinfo=UTC)
    end = datetime(until.year, until.month, until.day, tzinfo=UTC)
    scope = (
        WhatsappMessage.agency_id == agency_id,
        WhatsappMessage.client_id == client_id,
        WhatsappMessage.received_at >= start,
        WhatsappMessage.received_at < end,
    )
    total = session.scalar(select(func.count()).select_from(WhatsappMessage).where(*scope))
    unknown = session.scalar(
        select(func.count())
        .select_from(WhatsappMessage)
        .where(*scope, ~WhatsappMessage.has_referral)
    )
    rows = session.execute(
        select(
            WhatsappMessage.source_type,
            WhatsappMessage.source_id,
            func.count(),
            func.count().filter(WhatsappMessage.click_id_present),
        )
        .where(*scope, WhatsappMessage.has_referral)
        .group_by(WhatsappMessage.source_type, WhatsappMessage.source_id)
        .order_by(func.count().desc(), WhatsappMessage.source_type, WhatsappMessage.source_id)
        .limit(500)
    )
    return {
        "since": since,
        "until": until,
        "total": total,
        "unknown": unknown,
        "sources": [
            {"source_type": kind, "source_id": source, "messages": number, "with_click_id": clicks}
            for kind, source, number, clicks in rows
        ],
    }
