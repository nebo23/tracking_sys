"""Retained report exports (specification 016-C, D-095 decisions D2 to D7).

An export is the direct CSV of one report (016-A, 016-B), built at once and stored sealed
under the token keyring for at most 7 days. It is built and stored in three steps
(design-016c.md section 5):

1. reserve: a short transaction inserts a pending row, then takes the client's export lock and
   counts the client's unexpired exports (at most 50). Its commit releases the lock.
2. build: build_report, report_csv and release_check exactly as the direct CSV, in fresh
   snapshots that begin after the reservation committed.
3. store: in the caller's transaction, the audit event first, then the pending row becomes
   ready and the sealed content is inserted. A reservation revoked during the build has no
   pending row any more; the store is undone and the export is built again once.

Every revoking path calls revoke_exports in its own transaction after its other effects. It
takes the same export lock and turns pending rows into discarded and ready rows into revoked in
one statement, then deletes the revoked rows' content. A revocation therefore either commits
before a reservation takes the lock, so the build's snapshots see it, or discards the
reservation, or revokes the stored export: no export is ever stored after the event that
should revoke it. No lock is held while a report is built.

Visibility (D3): Owners, Admins and Analysts see every export of a client they can read whose
permissions they hold; a client viewer sees only the exports it created and those of schedules
it receives. A download resolves the scope again, needs finance:read when the export holds
financial figures, counts the download and opens the content for exactly its export, agency
and client. Nothing here logs a figure, a name or file content.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from sqlalchemy import Engine, Select, case, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import ConnectorProvider
from app.models import (
    AgencyMembership,
    AuditEvent,
    ConnectorConnection,
    ReportExport,
    ReportExportContent,
    ReportScheduleRecipient,
)
from app.privacy.token_secrets import (
    LocalKeyring,
    SealedSecret,
    SecretContext,
    open_bytes,
    seal_bytes,
)
from app.reporting.common import ReportError
from app.reporting.csv_export import report_csv
from app.security import now_utc
from app.services.access import Principal, ScopedAccess, resolve_scope
from app.services.collection import client_lock_key
from app.services.reporting import (
    FINANCE_SPLIT,
    PERMISSIONS,
    Report,
    ReportQuery,
    build_report,
    release_check,
)
from app.services.tenancy import MANAGERS, AccessDenied, Role, TenancyService

# Advisory namespace of the per-client export lock (016-C); the second key is the 004 client key.
LOCK_NAMESPACE = 16016
EXPORT_LIMIT = 50
PENDING_WINDOW = timedelta(hours=1)
# The parameters each family stores besides compare (design-016c.md section 3.1).
FAMILY_KEYS: Mapping[str, tuple[str, ...]] = {
    "social": ("connection_id", "view", "metrics"),
    "spend": ("connection_id", "level"),
    "revenue": (),
    "attribution": ("group_by", "view", "model_version"),
    "roas": ("connection_id", "level", "model_version"),
    "funnel": ("group_by", "model_version"),
}
UUID_KEYS = frozenset({"connection_id", "model_version"})


class _Superseded(Exception):
    """The reservation was revoked while its export was built."""


def require_keyring(settings: Settings) -> LocalKeyring:
    keyring = settings.token_keys()
    if keyring is None:
        raise ReportError("not_configured", 503)
    return keyring


def export_lock(session: Session, client_id: UUID) -> None:
    session.execute(select(func.pg_advisory_xact_lock(LOCK_NAMESPACE, client_lock_key(client_id))))


def stored_parameters(query: ReportQuery) -> dict[str, Any]:
    """The parameters of a query as stored on an export or a schedule, without dates."""
    values: dict[str, Any] = {"compare": query.compare}
    for key in FAMILY_KEYS[query.family]:
        value = getattr(query, key)
        if key in UUID_KEYS and value is not None:
            value = str(value)
        elif key == "metrics" and value is not None:
            value = list(value)
        values[key] = value
    return values


def query_of(family: str, parameters: Mapping[str, Any], start: date, end: date) -> ReportQuery:
    """The ReportQuery of stored parameters and a period; inverse of stored_parameters."""
    values: dict[str, Any] = {}
    for key in FAMILY_KEYS[family]:
        value = parameters.get(key)
        if key in UUID_KEYS and value is not None:
            value = UUID(value)
        elif key == "metrics" and value is not None:
            value = tuple(value)
        values[key] = value
    query = ReportQuery(family, start, end, bool(parameters.get("compare")), **values)  # type: ignore[arg-type]
    query.periods()
    return query


def includes_financials(family: str, finance: bool) -> bool:
    return PERMISSIONS[family] == "finance:read" or (family in FINANCE_SPLIT and finance)


def seal_context(export: ReportExport | ReportExportContent) -> SecretContext:
    identifier = export.id if isinstance(export, ReportExport) else export.export_id
    return SecretContext(
        export.agency_id, export.client_id, identifier, identifier, "report_export", 1
    )


@dataclass(frozen=True)
class ExportRequest:
    """Who builds one export, for which scope and with which query."""

    access: ScopedAccess
    query: ReportQuery
    finance: bool
    membership_id: UUID
    source: str = "manual"
    schedule_id: UUID | None = None


def _reserve(engine: Engine, settings: Settings, request: ExportRequest) -> UUID:
    query, access = request.query, request.access
    with Session(engine) as session, session.begin():
        # A connection of another client or agency is refused like the report route refuses
        # it, before its foreign key could.
        if query.connection_id is not None and (
            session.scalar(
                select(ConnectorConnection.id).where(
                    ConnectorConnection.agency_id == access.agency_id,
                    ConnectorConnection.client_id == access.client_id,
                    ConnectorConnection.id == query.connection_id,
                )
            )
            is None
        ):
            raise AccessDenied()
        row = ReportExport(
            id=uuid4(),
            agency_id=access.agency_id,
            client_id=access.client_id,
            family=query.family,
            parameters=stored_parameters(query),
            connection_id=query.connection_id,
            period_start=query.start,
            period_end=query.end,
            includes_financials=includes_financials(query.family, request.finance),
            source=request.source,
            schedule_id=request.schedule_id,
            requested_by_membership_id=request.membership_id,
            status="pending",
            created_at=func.now(),
            expires_at=func.now() + timedelta(days=settings.report_export_lifetime_days),
        )
        session.add(row)
        session.flush()
        # The row is inserted before the lock, so a reservation never waits for a row lock
        # while it holds the export lock (design-016c.md section 5).
        export_lock(session, access.client_id)
        held = session.scalar(
            select(func.count())
            .select_from(ReportExport)
            .where(
                ReportExport.agency_id == access.agency_id,
                ReportExport.client_id == access.client_id,
                ReportExport.expires_at > func.now(),
                or_(
                    ReportExport.status == "ready",
                    (ReportExport.status == "pending")
                    & (ReportExport.created_at > func.now() - PENDING_WINDOW),
                ),
            )
        )
        if (held or 0) > EXPORT_LIMIT:
            raise ReportError("export_limit_reached", 409)
        return row.id


def _discard(engine: Engine, export_id: UUID) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(ReportExport)
            .where(ReportExport.id == export_id, ReportExport.status == "pending")
            .values(status="discarded", revoked_at=func.now())
            .execution_options(synchronize_session=False)
        )


# Test hook: called after the reservation committed and before the report is built.
def _no_hook(export_id: UUID) -> None:
    return None


before_build = _no_hook


def _build(
    engine: Engine, registry: Mapping[str, ConnectorProvider], request: ExportRequest
) -> tuple[Report, bytes]:
    now = now_utc()
    report = build_report(
        engine, registry, request.access, request.query, now, finance=request.finance
    )
    data = report_csv(report.body, report.rows(), report.total_rows)
    release_check(
        engine,
        registry,
        request.access.principal,
        request.access,
        request.query,
        report,
        now,
    )
    return report, data


def _store(
    session: Session,
    keyring: LocalKeyring,
    request: ExportRequest,
    export_id: UUID,
    report: Report,
    data: bytes,
    audit_actor: UUID | None,
) -> None:
    access = request.access
    if audit_actor is not None:
        # The audit row is written before the export row is locked: its foreign key may wait
        # for an agency lock, and a revoker holding that lock must not wait for this row.
        session.add(
            AuditEvent(
                agency_id=access.agency_id,
                client_id=access.client_id,
                actor_user_id=audit_actor,
                action="report_export.created",
                resource_type="report_export",
                resource_id=export_id,
            )
        )
        session.flush()
    stored = session.execute(
        update(ReportExport)
        .where(ReportExport.id == export_id, ReportExport.status == "pending")
        .values(
            status="ready",
            stored_at=func.now(),
            row_count=max(0, data.count(b"\r\n") - 1),
            byte_size=len(data),
            report_revision=report.revision,
        )
        .returning(ReportExport.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if stored is None:
        raise _Superseded()
    context = SecretContext(
        access.agency_id, access.client_id, export_id, export_id, "report_export", 1
    )
    sealed = seal_bytes(keyring, data, context)
    session.add(
        ReportExportContent(
            export_id=export_id,
            agency_id=access.agency_id,
            client_id=access.client_id,
            kek_id=sealed.kek_id,
            wrap_nonce=sealed.wrap_nonce,
            wrapped_dek=sealed.wrapped_dek,
            nonce=sealed.nonce,
            ciphertext=sealed.ciphertext,
            alg=sealed.algorithm,
            aad_version=sealed.aad_version,
        )
    )
    session.flush()


def create_export(
    engine: Engine,
    session: Session,
    settings: Settings,
    registry: Mapping[str, ConnectorProvider],
    request: ExportRequest,
    *,
    audit_actor: UUID | None,
    on_stored: Any = None,
) -> UUID:
    """Reserve, build and store one export; the caller's session commits the store.

    on_stored(session, export_id) runs inside the store savepoint (the worker queues its
    notifications there). Raises ReportError for a refused or failed build.
    """
    keyring = require_keyring(settings)
    for _ in range(2):
        export_id = _reserve(engine, settings, request)
        before_build(export_id)
        try:
            report, data = _build(engine, registry, request)
        except BaseException:
            _discard(engine, export_id)
            raise
        try:
            with session.begin_nested():
                _store(session, keyring, request, export_id, report, data, audit_actor)
                if on_stored is not None:
                    on_stored(session, export_id)
        except _Superseded:
            continue
        return export_id
    raise ReportError("report_changed", 409)


def revoke_exports(
    session: Session,
    agency_id: UUID,
    client_id: UUID,
    reason: str,
    *,
    connection_id: UUID | None = None,
    export_id: UUID | None = None,
) -> int:
    """Revoke the client's ready exports in scope and discard its reservations, under the
    export lock; returns the number of ready exports revoked (D7)."""
    export_lock(session, client_id)
    scope = [
        ReportExport.agency_id == agency_id,
        ReportExport.client_id == client_id,
        ReportExport.status.in_(("pending", "ready")),
    ]
    if connection_id is not None:
        scope.append(ReportExport.connection_id == connection_id)
    if export_id is not None:
        scope.append(ReportExport.id == export_id)
    rows = session.execute(
        update(ReportExport)
        .where(*scope)
        .values(
            status=case((ReportExport.status == "ready", "revoked"), else_="discarded"),
            revoked_at=func.now(),
            revoked_reason=reason,
        )
        .returning(ReportExport.id, ReportExport.status)
        .execution_options(synchronize_session=False)
    ).all()
    revoked = [identifier for identifier, status in rows if status == "revoked"]
    if revoked:
        session.execute(
            delete(ReportExportContent)
            .where(ReportExportContent.export_id.in_(revoked))
            .execution_options(synchronize_session=False)
        )
    return len(revoked)


@dataclass(frozen=True)
class Viewer:
    """The live permissions of one browser user for one client's exports."""

    principal: Principal
    member: AgencyMembership
    agency_id: UUID
    client_id: UUID
    finance: bool

    @property
    def manager(self) -> bool:
        return self.member.role in MANAGERS

    @property
    def client_viewer(self) -> bool:
        return self.member.role == Role.CLIENT_VIEWER


class ExportService(TenancyService):
    """Browser-session operations on one client's exports; the request session commits."""

    # The database clock that expiries are set and checked with.
    def clock(self) -> datetime:
        return self.session.scalar(select(func.now()))

    def viewer(self, agency_id: UUID, client_id: UUID) -> Viewer:
        principal = Principal("user", self.actor_user_id)
        resolve_scope(self.session, principal, agency_id, client_id, "client:read")
        try:
            resolve_scope(self.session, principal, agency_id, client_id, "finance:read")
            finance = True
        except AccessDenied:
            finance = False
        member = self._membership(agency_id)
        return Viewer(principal, member, agency_id, client_id, finance)

    @staticmethod
    def visible(viewer: Viewer) -> Select[tuple[ReportExport]]:
        query = select(ReportExport).where(
            ReportExport.agency_id == viewer.agency_id,
            ReportExport.client_id == viewer.client_id,
            ReportExport.status.in_(("ready", "revoked")),
        )
        if not viewer.finance:
            query = query.where(ReportExport.includes_financials.is_(False))
        if viewer.client_viewer:
            received = select(ReportScheduleRecipient.schedule_id).where(
                ReportScheduleRecipient.agency_id == viewer.agency_id,
                ReportScheduleRecipient.client_id == viewer.client_id,
                ReportScheduleRecipient.membership_id == viewer.member.id,
            )
            query = query.where(
                or_(
                    ReportExport.requested_by_membership_id == viewer.member.id,
                    ReportExport.schedule_id.in_(received),
                )
            )
        return query.execution_options(populate_existing=True)

    def list(
        self, agency_id: UUID, client_id: UUID, *, limit: int, offset: int
    ) -> list[ReportExport]:
        viewer = self.viewer(agency_id, client_id)
        return list(
            self.session.scalars(
                self.visible(viewer)
                .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def _visible_one(self, viewer: Viewer, export_id: UUID) -> ReportExport:
        item = self.session.scalar(self.visible(viewer).where(ReportExport.id == export_id))
        if item is None:
            raise AccessDenied()
        return item

    def get(self, agency_id: UUID, client_id: UUID, export_id: UUID) -> ReportExport:
        return self._visible_one(self.viewer(agency_id, client_id), export_id)

    def download(
        self, settings: Settings, agency_id: UUID, client_id: UUID, export_id: UUID
    ) -> tuple[ReportExport, bytes]:
        viewer = self.viewer(agency_id, client_id)
        item = self._visible_one(viewer, export_id)
        if item.status != "ready":
            raise ReportError("export_gone", 410)
        keyring = require_keyring(settings)
        # Serialized with a concurrent revocation by the row lock: a revoked or expired row
        # matches nothing, and a revoker waits until this request commits.
        counted = self.session.execute(
            update(ReportExport)
            .where(
                ReportExport.id == export_id,
                ReportExport.agency_id == agency_id,
                ReportExport.client_id == client_id,
                ReportExport.status == "ready",
                ReportExport.expires_at > func.now(),
            )
            .values(
                download_count=ReportExport.download_count + 1,
                last_downloaded_at=func.now(),
            )
            .returning(ReportExport.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if counted is None:
            raise ReportError("export_gone", 410)
        content = self.session.get(ReportExportContent, export_id, populate_existing=True)
        if content is None:
            raise ReportError("export_gone", 410)
        sealed = SealedSecret(
            content.kek_id,
            content.wrap_nonce,
            content.wrapped_dek,
            content.nonce,
            content.ciphertext,
            content.alg,
            content.aad_version,
        )
        try:
            data = open_bytes(keyring, sealed, seal_context(item))
        except (InvalidTag, KeyError, ValueError) as error:
            raise ReportError("export_unreadable", 500) from error
        self.session.refresh(item)
        return item, data

    def revoke(self, agency_id: UUID, client_id: UUID, export_id: UUID) -> ReportExport:
        viewer = self.viewer(agency_id, client_id)
        item = self._visible_one(viewer, export_id)
        if not viewer.manager and item.requested_by_membership_id != viewer.member.id:
            raise AccessDenied()
        if item.status == "ready":
            if revoke_exports(self.session, agency_id, client_id, "manual", export_id=item.id):
                self._audit(agency_id, "report_export.revoked", "report_export", item.id, client_id)
            self.session.refresh(item)
        return item
