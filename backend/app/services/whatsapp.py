"""WhatsApp numbers, notification intake and the referral read (015-E, D-068 E7 to E11).

Owner and Admin sessions register, rename, disable or re-activate a client's WhatsApp Business
phone number IDs, each audited. The Meta app secret and verify token are platform settings,
never stored in the database. A verified notification records each inbound message of a
registered, active number of an active client once, keeping only its referral; messages of
unknown numbers are skipped. Nothing here calls Meta or correlates a conversation with a person.

A registration is only a claim (D-070, review finding R004): every notification reaches the one
shared Meta app, so an agency that knew another business's phone number ID could otherwise
capture its messages, and the number's uniqueness then blocked the real owner. A claim starts
pending and routes nothing. The platform operator, outside the agency roles, checks out of band
that the number belongs to the client's WhatsApp Business Account and verifies the claim with
python -m app.whatsapp_binding (verify_claim), which makes it active. Each number has at most
one verified binding, so verifying another client's claim requires revoking the current binding
first (transfer). Agencies may disable and re-activate only a verified binding; a pending or
revoked claim stays as it is. Several clients may hold pending claims for one number.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
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
            status="pending",
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
        # Only a verified binding changes between active and disabled (D-070).
        if status is not None and item.status == "pending":
            raise WhatsappError("verification_required", 409)
        if status is not None and item.status == "revoked":
            raise WhatsappError("claim_revoked", 409)
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


# --- Platform operator binding (D-070) -------------------------------------------------------


def _claim(session: Session, claim_id: UUID) -> WhatsappNumber:
    item = session.scalar(
        select(WhatsappNumber)
        .where(WhatsappNumber.id == claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise WhatsappError("claim_not_found", 404)
    return item


# Verify one pending claim after the operator's out-of-band ownership check: it becomes the
# number's active binding. Another verified binding of the number refuses it (revoke it first);
# the partial unique index enforces the same rule against a concurrent verification.
def verify_claim(session: Session, claim_id: UUID) -> WhatsappNumber:
    item = _claim(session, claim_id)
    if item.status != "pending":
        raise WhatsappError("claim_not_pending", 409)
    holder = session.scalar(
        select(WhatsappNumber.id).where(
            WhatsappNumber.phone_number_id == item.phone_number_id,
            WhatsappNumber.status.in_(("active", "disabled")),
        )
    )
    if holder is not None:
        raise WhatsappError("number_already_bound", 409)
    now = session.scalar(select(func.clock_timestamp()))
    item.status, item.verified_at, item.updated_at = "active", now, now
    try:
        session.flush()
    except IntegrityError as error:  # a concurrent verification of the same number won
        raise WhatsappError("number_already_bound", 409) from error
    return item


# Revoke a claim or a binding: it routes nothing from then on and frees the number for another
# verified binding. Messages already stored keep their client until their own retention.
def revoke_claim(session: Session, claim_id: UUID) -> WhatsappNumber:
    item = _claim(session, claim_id)
    if item.status == "revoked":
        raise WhatsappError("claim_revoked", 409)
    item.status = "revoked"
    item.updated_at = session.scalar(select(func.clock_timestamp()))
    session.flush()
    return item


# Claims for the operator's review, oldest first: identifiers, number, status and times only.
def list_claims(session: Session, status: str | None = "pending") -> list[WhatsappNumber]:
    query = select(WhatsappNumber).order_by(WhatsappNumber.created_at, WhatsappNumber.id)
    if status is not None:
        query = query.where(WhatsappNumber.status == status)
    return list(session.scalars(query.limit(500)))


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
