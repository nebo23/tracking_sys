"""Report schedules and the report worker pass (specification 016-C, D-095 D8 to D10).

An Owner or Admin schedules one report of a client: a name, the report family and its
parameters without dates, whether sale values are included (attribution and funnel only), a
daily, weekly or monthly cadence at a local hour in an IANA time zone, and 0-20 member
recipients who can read the report. At most 10 schedules of a client are active; the agency
lock serializes the count. The schedule runs with its owner's permissions; a manager who
resumes it becomes its owner.

The worker pass (run_pass) claims due schedules one at a time with FOR UPDATE SKIP LOCKED,
joined to an active agency and an active client, and moves each to its next slot before it
builds, so two concurrent workers never run one slot twice and a missed slot is never repeated
(design-016c.md section 7). It builds the export as the owner, retries report_changed at most
twice, notifies every recipient who still holds the export's permissions with a report_ready
email in the store transaction, and records the outcome; three consecutive failures pause the
schedule. It returns counts only and logs closed codes only.
"""

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import ConnectorProvider
from app.models import (
    Agency,
    AgencyBranding,
    AgencyMembership,
    ClientWorkspace,
    ConnectorConnection,
    ReportExport,
    ReportSchedule,
    ReportScheduleRecipient,
    User,
)
from app.reporting.catalog import family_of
from app.reporting.common import ReportError
from app.reporting.schedules import Timing
from app.security import now_utc
from app.services.access import Principal, resolve_scope
from app.services.advertising import SPEND_PROVIDERS
from app.services.mail import ReportReady, queue_report_mail
from app.services.report_exports import (
    ExportRequest,
    create_export,
    includes_financials,
    query_of,
    stored_parameters,
)
from app.services.reporting import FINANCE_SPLIT, PERMISSIONS, REPORTABLE_STATUSES, ReportQuery
from app.services.tenancy import MANAGERS, AccessDenied, TenancyService

logger = logging.getLogger(__name__)
ACTIVE_LIMIT = 10
RECIPIENT_LIMIT = 20
FAILURE_LIMIT = 3
ATTEMPTS = 3  # report_changed is retried at most twice in the same pass (D10)
# A placeholder period validates a schedule's parameters like its report route.
PLACEHOLDER = (date(2026, 1, 1), date(2026, 1, 2))
RUN_ERRORS = {
    "report_changed": "report_changed",
    "report_too_large": "report_too_large",
    "export_too_large": "report_too_large",
    "source_unavailable": "source_unavailable",
    "not_a_social_connection": "source_unavailable",
    "not_a_spend_connection": "source_unavailable",
    "report_requires_ledger_upgrade": "source_not_ready",
    "day_zone_unknown": "source_not_ready",
    "not_configured": "not_configured",
    "export_limit_reached": "export_limit_reached",
    "export_refused": "export_refused",
}


@dataclass(frozen=True)
class ScheduleSpec:
    """A validated schedule request from the API."""

    name: str
    query: ReportQuery  # parameters with a placeholder period
    sale_values: bool
    timing: Timing
    recipients: tuple[UUID, ...]


def _valid_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ReportError("invalid_schedule", 422)
    return value


def schedule_query(family: str, parameters: Mapping[str, Any]) -> ReportQuery:
    return query_of(family, parameters, *PLACEHOLDER)


def _timing(schedule: ReportSchedule) -> Timing:
    return Timing(schedule.cadence, schedule.weekday, schedule.hour, schedule.time_zone)


def _financial(family: str, sale_values: bool) -> bool:
    return includes_financials(family, sale_values and family in FINANCE_SPLIT)


# Whether a membership may read a report of the family on the client now, with
# finance:read when the export holds financial figures; None when the member is not live.
def _reader(
    session: Session, agency_id: UUID, client_id: UUID, membership_id: UUID
) -> tuple[AgencyMembership, User] | None:
    found = session.execute(
        select(AgencyMembership, User)
        .join(User, User.id == AgencyMembership.user_id)
        .where(
            AgencyMembership.agency_id == agency_id,
            AgencyMembership.id == membership_id,
            AgencyMembership.status == "active",
            User.status == "active",
            User.email_verified_at.is_not(None),
        )
    ).one_or_none()
    return None if found is None else (found[0], found[1])


def may_read(
    session: Session,
    user_id: UUID,
    agency_id: UUID,
    client_id: UUID,
    family: str,
    financial: bool,
) -> bool:
    principal = Principal("user", user_id)
    try:
        resolve_scope(session, principal, agency_id, client_id, PERMISSIONS[family])
        if financial:
            resolve_scope(session, principal, agency_id, client_id, "finance:read")
    except AccessDenied:
        return False
    return True


class ScheduleService(TenancyService):
    """Browser-session schedule operations; the request session commits."""

    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _active_client(self, agency_id: UUID, client_id: UUID) -> None:
        self.get_client(agency_id, client_id)

    def _check_connection(self, agency_id: UUID, client_id: UUID, query: ReportQuery) -> None:
        if query.connection_id is None:
            return
        connection = self.session.scalar(
            select(ConnectorConnection).where(
                ConnectorConnection.agency_id == agency_id,
                ConnectorConnection.client_id == client_id,
                ConnectorConnection.id == query.connection_id,
            )
        )
        if connection is None:
            raise AccessDenied()
        if query.family == "social" and family_of(connection.provider) is None:
            raise ReportError("not_a_social_connection", 422)
        if query.family in {"spend", "roas"} and connection.provider not in SPEND_PROVIDERS:
            raise ReportError("not_a_spend_connection", 422)
        if connection.status not in REPORTABLE_STATUSES:
            raise ReportError("source_unavailable", 409)

    def _check_recipients(self, agency_id: UUID, client_id: UUID, spec: ScheduleSpec) -> list[UUID]:
        recipients = list(spec.recipients)
        if len(recipients) > RECIPIENT_LIMIT or len(set(recipients)) != len(recipients):
            raise ReportError("invalid_recipient", 422)
        financial = _financial(spec.query.family, spec.sale_values)
        for membership_id in recipients:
            found = _reader(self.session, agency_id, client_id, membership_id)
            if found is None or not may_read(
                self.session, found[1].id, agency_id, client_id, spec.query.family, financial
            ):
                raise ReportError("invalid_recipient", 422)
        return recipients

    def _active_count(self, agency_id: UUID, client_id: UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(ReportSchedule)
                .where(
                    ReportSchedule.agency_id == agency_id,
                    ReportSchedule.client_id == client_id,
                    ReportSchedule.status == "active",
                )
            )
            or 0
        )

    def _replace_recipients(self, schedule: ReportSchedule, recipients: Iterable[UUID]) -> None:
        self.session.execute(
            delete(ReportScheduleRecipient).where(
                ReportScheduleRecipient.schedule_id == schedule.id
            )
        )
        self.session.add_all(
            ReportScheduleRecipient(
                schedule_id=schedule.id,
                membership_id=membership_id,
                agency_id=schedule.agency_id,
                client_id=schedule.client_id,
            )
            for membership_id in recipients
        )
        self.session.flush()

    def _validate(self, agency_id: UUID, client_id: UUID, spec: ScheduleSpec) -> list[UUID]:
        if spec.sale_values and spec.query.family not in FINANCE_SPLIT:
            raise ReportError("invalid_schedule", 422)
        self._check_connection(agency_id, client_id, spec.query)
        return self._check_recipients(agency_id, client_id, spec)

    def create(self, agency_id: UUID, client_id: UUID, spec: ScheduleSpec) -> ReportSchedule:
        actor = self._manager(agency_id, write=True)
        self._active_client(agency_id, client_id)
        name = _valid_name(spec.name)
        recipients = self._validate(agency_id, client_id, spec)
        if self._active_count(agency_id, client_id) >= ACTIVE_LIMIT:
            raise ReportError("schedule_limit_reached", 409)
        now = now_utc()
        schedule = ReportSchedule(
            agency_id=agency_id,
            client_id=client_id,
            name=name,
            family=spec.query.family,
            parameters=stored_parameters(spec.query),
            sale_values=spec.sale_values,
            compare=spec.query.compare,
            cadence=spec.timing.cadence,
            weekday=spec.timing.weekday,
            hour=spec.timing.hour,
            time_zone=spec.timing.zone,
            status="active",
            owner_membership_id=actor.id,
            next_run_at=spec.timing.next_after(now)[1],
            created_at=now,
            updated_at=now,
        )
        self.session.add(schedule)
        self.session.flush()
        self._replace_recipients(schedule, recipients)
        self._audit(agency_id, "report_schedule.created", "report_schedule", schedule.id, client_id)
        return schedule

    def _locked(self, agency_id: UUID, client_id: UUID, schedule_id: UUID) -> ReportSchedule:
        schedule = self.session.scalar(
            select(ReportSchedule)
            .where(
                ReportSchedule.agency_id == agency_id,
                ReportSchedule.client_id == client_id,
                ReportSchedule.id == schedule_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if schedule is None:
            raise AccessDenied()
        return schedule

    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        schedule_id: UUID,
        changes: Mapping[str, Any],
    ) -> ReportSchedule:
        actor = self._manager(agency_id, write=True)
        self._active_client(agency_id, client_id)
        schedule = self._locked(agency_id, client_id, schedule_id)
        query = changes.get("query") or schedule_query(schedule.family, schedule.parameters)
        if query.family != schedule.family:
            raise ReportError("invalid_schedule", 422)
        timing = Timing(
            changes.get("cadence", schedule.cadence),
            changes.get("weekday", schedule.weekday)
            if "weekday" in changes or "cadence" not in changes
            else None,
            changes.get("hour", schedule.hour),
            changes.get("time_zone", schedule.time_zone),
        )
        current = [
            item.membership_id
            for item in self.session.scalars(
                select(ReportScheduleRecipient).where(
                    ReportScheduleRecipient.schedule_id == schedule.id
                )
            )
        ]
        spec = ScheduleSpec(
            changes.get("name", schedule.name),
            query,
            changes.get("sale_values", schedule.sale_values),
            timing,
            tuple(changes.get("recipients", current)),
        )
        recipients = self._validate(agency_id, client_id, spec)
        now = now_utc()
        status = changes.get("status", schedule.status)
        resumed = status == "active" and schedule.status != "active"
        retimed = timing != _timing(schedule)
        if resumed and self._active_count(agency_id, client_id) >= ACTIVE_LIMIT:
            raise ReportError("schedule_limit_reached", 409)
        schedule.name = _valid_name(spec.name)
        schedule.parameters = stored_parameters(query)
        schedule.compare = query.compare
        schedule.sale_values = spec.sale_values
        schedule.cadence, schedule.weekday = timing.cadence, timing.weekday
        schedule.hour, schedule.time_zone = timing.hour, timing.zone
        if status == "paused":
            schedule.status, schedule.next_run_at = "paused", None
            schedule.pause_reason = schedule.pause_reason or "manual"
        else:
            if resumed:
                schedule.status, schedule.pause_reason = "active", None
                schedule.owner_membership_id = actor.id
                schedule.consecutive_failures = 0
            if resumed or retimed or schedule.next_run_at is None:
                schedule.next_run_at = timing.next_after(now)[1]
        schedule.updated_at = now
        if "recipients" in changes:
            self._replace_recipients(schedule, recipients)
        self._audit(agency_id, "report_schedule.updated", "report_schedule", schedule.id, client_id)
        return schedule

    def delete(self, agency_id: UUID, client_id: UUID, schedule_id: UUID) -> None:
        self._manager(agency_id, write=True)
        schedule = self._locked(agency_id, client_id, schedule_id)
        self.session.delete(schedule)
        self.session.flush()
        self._audit(agency_id, "report_schedule.deleted", "report_schedule", schedule_id, client_id)

    # The member and whether it manages the agency; readers also need the client itself.
    def _reader_member(self, agency_id: UUID, client_id: UUID) -> AgencyMembership:
        member = self._membership(agency_id)
        resolve_scope(self.session, Principal("user", self.actor_user_id), agency_id, client_id)
        return member

    def _visible(self, member: AgencyMembership, agency_id: UUID, client_id: UUID):
        query = select(ReportSchedule).where(
            ReportSchedule.agency_id == agency_id, ReportSchedule.client_id == client_id
        )
        if member.role not in MANAGERS:
            query = query.where(
                ReportSchedule.id.in_(
                    select(ReportScheduleRecipient.schedule_id).where(
                        ReportScheduleRecipient.agency_id == agency_id,
                        ReportScheduleRecipient.membership_id == member.id,
                    )
                )
            )
        return query.execution_options(populate_existing=True)

    def listing(
        self, agency_id: UUID, client_id: UUID, *, limit: int, offset: int
    ) -> tuple[AgencyMembership, list[ReportSchedule]]:
        member = self._reader_member(agency_id, client_id)
        items = list(
            self.session.scalars(
                self._visible(member, agency_id, client_id)
                .order_by(ReportSchedule.created_at, ReportSchedule.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return member, items

    def get(
        self, agency_id: UUID, client_id: UUID, schedule_id: UUID
    ) -> tuple[AgencyMembership, ReportSchedule]:
        member = self._reader_member(agency_id, client_id)
        schedule = self.session.scalar(
            self._visible(member, agency_id, client_id).where(ReportSchedule.id == schedule_id)
        )
        if schedule is None:
            raise AccessDenied()
        return member, schedule

    def recipients(self, schedule: ReportSchedule) -> list[UUID]:
        return list(
            self.session.scalars(
                select(ReportScheduleRecipient.membership_id)
                .where(ReportScheduleRecipient.schedule_id == schedule.id)
                .order_by(ReportScheduleRecipient.membership_id)
            )
        )

    def leave(self, agency_id: UUID, client_id: UUID, schedule_id: UUID) -> None:
        member = self._membership(agency_id)
        removed = self.session.execute(
            delete(ReportScheduleRecipient)
            .where(
                ReportScheduleRecipient.agency_id == agency_id,
                ReportScheduleRecipient.client_id == client_id,
                ReportScheduleRecipient.schedule_id == schedule_id,
                ReportScheduleRecipient.membership_id == member.id,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if not removed:
            raise AccessDenied()
        self._audit(agency_id, "report_schedule.updated", "report_schedule", schedule_id, client_id)


def schedule_spec(
    name: str,
    query: ReportQuery,
    sale_values: bool,
    cadence: str,
    weekday: int | None,
    hour: int,
    time_zone: str,
    recipients: Sequence[UUID],
) -> ScheduleSpec:
    return ScheduleSpec(
        name, query, sale_values, Timing(cadence, weekday, hour, time_zone), tuple(recipients)
    )


# --- worker pass --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    schedule_id: UUID
    agency_id: UUID
    client_id: UUID
    name: str
    family: str
    parameters: dict[str, Any]
    sale_values: bool
    owner_membership_id: UUID
    owner_user_id: UUID | None
    start: date | None = None
    end: date | None = None
    paused: bool = False


def _claim(engine: Engine, now: datetime, seen: set[UUID]) -> Claim | None:
    with Session(engine) as session, session.begin():
        query = (
            select(ReportSchedule)
            .join(Agency, Agency.id == ReportSchedule.agency_id)
            .join(
                ClientWorkspace,
                (ClientWorkspace.agency_id == ReportSchedule.agency_id)
                & (ClientWorkspace.id == ReportSchedule.client_id),
            )
            .where(
                ReportSchedule.status == "active",
                ReportSchedule.next_run_at <= now,
                Agency.status == "active",
                ClientWorkspace.status == "active",
            )
            .order_by(ReportSchedule.next_run_at, ReportSchedule.id)
            .limit(1)
            .with_for_update(of=ReportSchedule, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if seen:
            query = query.where(ReportSchedule.id.not_in(list(seen)))
        schedule = session.scalar(query)
        if schedule is None:
            return None
        owner = _reader(
            session, schedule.agency_id, schedule.client_id, schedule.owner_membership_id
        )
        claim = Claim(
            schedule.id,
            schedule.agency_id,
            schedule.client_id,
            schedule.name,
            schedule.family,
            dict(schedule.parameters),
            schedule.sale_values,
            schedule.owner_membership_id,
            None if owner is None else owner[1].id,
            paused=owner is None or owner[0].role not in MANAGERS,
        )
        if claim.paused:
            _pause(schedule, "owner_access_lost", now)
            return claim
        timing = _timing(schedule)
        period = timing.period(timing.latest_at(now)[0])
        # The schedule moves to its next slot before anything is built (D10).
        schedule.next_run_at = timing.next_after(now)[1]
        schedule.updated_at = now
        return replace(claim, start=period.start, end=period.end)


def _pause(schedule: ReportSchedule, reason: str, now: datetime) -> None:
    schedule.status, schedule.pause_reason, schedule.next_run_at = "paused", reason, None
    schedule.updated_at = now


def _display_name(session: Session, agency_id: UUID) -> str:
    branded = session.scalar(
        select(AgencyBranding.display_name).where(AgencyBranding.agency_id == agency_id)
    )
    if branded is not None:
        return branded
    return session.scalar(select(Agency.name).where(Agency.id == agency_id)) or ""


def _notify(
    session: Session,
    settings: Settings,
    claim: Claim,
    query: ReportQuery,
    financial: bool,
    export_id: UUID,
    counts: dict[str, int],
) -> None:
    export = session.get(ReportExport, export_id, populate_existing=True)
    assert export is not None
    display = _display_name(session, claim.agency_id)
    recipients = session.scalars(
        select(ReportScheduleRecipient.membership_id)
        .where(ReportScheduleRecipient.schedule_id == claim.schedule_id)
        .order_by(ReportScheduleRecipient.membership_id)
    ).all()
    for membership_id in recipients:
        found = _reader(session, claim.agency_id, claim.client_id, membership_id)
        if found is None or not may_read(
            session, found[1].id, claim.agency_id, claim.client_id, claim.family, financial
        ):
            counts["skipped"] += 1
            continue
        queue_report_mail(
            session,
            settings,
            found[1].email_normalized,
            ReportReady(
                display_name=display,
                schedule_name=claim.name,
                family=claim.family,
                period_start=query.start,
                period_end=query.end,
                agency_id=claim.agency_id,
                client_id=claim.client_id,
                export_id=export_id,
                expires_at=export.expires_at,
            ),
        )
        counts["notified"] += 1


@dataclass
class Outcome:
    built: bool = False
    paused: bool = False
    error: str | None = None
    notified: int = 0
    skipped: int = 0


def _build(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    claim: Claim,
) -> Outcome:
    outcome = Outcome()
    assert claim.start is not None and claim.end is not None
    assert claim.owner_user_id is not None
    try:
        query = query_of(claim.family, claim.parameters, claim.start, claim.end)
    except ReportError as error:
        return Outcome(error=RUN_ERRORS.get(error.code, "build_failed"))
    finance = claim.sale_values and claim.family in FINANCE_SPLIT
    financial = _financial(claim.family, claim.sale_values)
    principal = Principal("user", claim.owner_user_id)
    for attempt in range(ATTEMPTS):
        counts = {"notified": 0, "skipped": 0}
        try:
            with Session(engine) as session, session.begin():
                access = resolve_scope(
                    session, principal, claim.agency_id, claim.client_id, PERMISSIONS[claim.family]
                )
                if finance:
                    resolve_scope(
                        session, principal, claim.agency_id, claim.client_id, "finance:read"
                    )
                request = ExportRequest(
                    access,
                    query,
                    finance,
                    claim.owner_membership_id,
                    source="schedule",
                    schedule_id=claim.schedule_id,
                )
                create_export(
                    engine,
                    session,
                    settings,
                    registry,
                    request,
                    audit_actor=None,
                    on_stored=lambda inner, export_id, counts=counts: _notify(
                        inner, settings, claim, query, financial, export_id, counts
                    ),
                )
        except AccessDenied:
            return Outcome(paused=True)
        except ReportError as error:
            code = RUN_ERRORS.get(error.code, "build_failed")
            if code == "report_changed" and attempt + 1 < ATTEMPTS:
                continue
            return Outcome(error=code)
        except SQLAlchemyError:
            return Outcome(error="build_failed")
        outcome.built = True
        outcome.notified, outcome.skipped = counts["notified"], counts["skipped"]
        return outcome
    return Outcome(error="report_changed")  # pragma: no cover


def _record(engine: Engine, claim: Claim, outcome: Outcome, now: datetime) -> bool:
    """Record a run's outcome; returns whether the schedule was paused."""
    with Session(engine) as session, session.begin():
        schedule = session.get(ReportSchedule, claim.schedule_id, with_for_update=True)
        if schedule is None:
            return False
        if outcome.paused:
            if schedule.status == "active":
                _pause(schedule, "owner_access_lost", now)
            return True
        schedule.last_run_at = now
        schedule.last_notified, schedule.last_skipped = outcome.notified, outcome.skipped
        schedule.updated_at = now
        if outcome.built:
            schedule.last_outcome, schedule.last_error_code = "built", None
            schedule.consecutive_failures = 0
            return False
        schedule.last_outcome, schedule.last_error_code = "failed", outcome.error
        schedule.consecutive_failures = min(FAILURE_LIMIT, schedule.consecutive_failures + 1)
        if schedule.consecutive_failures >= FAILURE_LIMIT and schedule.status == "active":
            _pause(schedule, "repeated_failures", now)
            return True
        return False


def run_pass(
    engine: Engine,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    *,
    limit: int = 25,
    clock: Callable[[], datetime] = now_utc,
) -> dict[str, int]:
    """One bounded pass over due schedules; returns counts only."""
    if not 1 <= limit <= 100:
        raise ValueError("The report worker batch size must be between 1 and 100.")
    counts = dict.fromkeys(("due", "built", "notified", "skipped", "failed", "paused"), 0)
    seen: set[UUID] = set()
    for _ in range(limit):
        claim = _claim(engine, clock(), seen)
        if claim is None:
            break
        seen.add(claim.schedule_id)
        counts["due"] += 1
        if claim.paused:
            counts["paused"] += 1
            logger.info("report_schedule_paused", extra={"outcome": "owner_access_lost"})
            continue
        outcome = _build(engine, settings, registry, claim)
        paused = _record(engine, claim, outcome, clock())
        if outcome.built:
            counts["built"] += 1
            counts["notified"] += outcome.notified
            counts["skipped"] += outcome.skipped
        elif not outcome.paused:
            counts["failed"] += 1
            logger.info("report_schedule_failed", extra={"outcome": outcome.error})
        if paused:
            counts["paused"] += 1
    return counts
