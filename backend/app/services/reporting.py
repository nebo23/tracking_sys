"""Report orchestration over stored facts (specification 016-A, D-072 decisions D2, D7 and D8).

Each report request runs in this order:

1. The route authenticates the caller and resolves the client scope with the family's
   permission (social: client:read; spend and revenue: finance:read).
2. read_*_inputs reads every input once inside a separate short READ ONLY REPEATABLE READ
   transaction (report_snapshot), configured before its first statement, so all inputs,
   counts, statuses and both comparison periods come from one snapshot. Every query is scoped
   by agency, client and, where one applies, the connection. The input bounds are counted
   (cap + 1 rows at most) before anything is loaded or calculated.
3. The pure report families compute the complete filtered result, the revision is derived and
   checked against expected_revision, and the page or the bounded CSV is built in memory.
4. release_check runs in a fresh snapshot taken after the result was built: it resolves the
   caller's scope again and rereads the inputs. Revoked access, an archived client, an ended
   or changed connection, or any changed, added or deleted input refuses the response, so no
   byte of an outdated or unauthorized result is sent. before_release is a test hook between
   steps 3 and 4.

No transaction or result is kept across requests, nothing is written, no provider is called
and no synchronization is triggered.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.connectors.contracts import ConnectorProvider
from app.models import (
    AdAccount,
    AdSpendFact,
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
    RevenueEvidence,
)
from app.reporting.catalog import CATALOG_VERSION, Family, family_of
from app.reporting.common import (
    CONTRACT_VERSION,
    DEPENDENCIES,
    MAX_EVIDENCE_ROWS,
    MAX_SOURCE_ROWS,
    PageRequest,
    ReportError,
    page_of,
)
from app.reporting.digest import Digest, digest_of
from app.reporting.periods import Period
from app.reporting.revenue import RevenueInputs, RevenueResult, revenue_report
from app.reporting.social import (
    SocialInputs,
    SocialRecord,
    SocialResult,
    StreamState,
    social_report,
)
from app.reporting.spend import (
    DAILY_STREAM,
    SpendFactInput,
    SpendInputs,
    SpendResult,
    spend_report,
)
from app.services.access import Principal, ScopedAccess, resolve_scope
from app.services.advertising import SPEND_PROVIDERS
from app.services.connector_coverage import _sync_state
from app.services.revenue import client_ledger
from app.services.tenancy import AccessDenied

Family_ = Literal["social", "spend", "revenue"]
PERMISSIONS: Mapping[str, Literal["client:read", "finance:read"]] = {
    "social": "client:read",
    "spend": "finance:read",
    "revenue": "finance:read",
}
REPORTABLE_STATUSES = frozenset({"active", "reconnect_required"})


# Test hook: called after the result is built and before the release check, with the family.
def _no_hook(family: str) -> None:
    return None


before_release: Callable[[str], None] = _no_hook


@contextmanager
def report_snapshot(engine: Engine) -> Iterator[Session]:
    with engine.connect() as raw:
        connection = raw.execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        )
        with Session(bind=connection, autoflush=False) as session, session.begin():
            yield session


def _bounded(session: Session, query: Any, cap: int) -> int:
    return int(
        session.scalar(select(func.count()).select_from(query.limit(cap + 1).subquery())) or 0
    )


def _connection(session: Session, access: ScopedAccess, connection_id: UUID) -> ConnectorConnection:
    connection = session.scalar(
        select(ConnectorConnection).where(
            ConnectorConnection.agency_id == access.agency_id,
            ConnectorConnection.client_id == access.client_id,
            ConnectorConnection.id == connection_id,
        )
    )
    if connection is None:
        raise AccessDenied()
    return connection


def _require_reportable(connection: ConnectorConnection) -> None:
    if connection.status not in REPORTABLE_STATUSES:
        raise ReportError("source_unavailable", 409)


@dataclass(frozen=True)
class _StreamRows:
    checkpoint: ConnectorCheckpoint | None
    latest: ConnectorSyncRun | None
    success: datetime | None


# The checkpoint, the latest run and the latest successful run time of each named stream.
def _stream_rows(
    session: Session, access: ScopedAccess, connection_id: UUID, names: Sequence[str]
) -> dict[str, _StreamRows]:
    checkpoints = {
        row.stream: row
        for row in session.scalars(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.agency_id == access.agency_id,
                ConnectorCheckpoint.client_id == access.client_id,
                ConnectorCheckpoint.connection_id == connection_id,
                ConnectorCheckpoint.stream.in_(list(names)),
            )
        )
    }
    runs = (
        ConnectorSyncRun.agency_id == access.agency_id,
        ConnectorSyncRun.client_id == access.client_id,
        ConnectorSyncRun.connection_id == connection_id,
    )
    found = {}
    for name in sorted(set(names)):
        latest = session.scalar(
            select(ConnectorSyncRun)
            .where(*runs, ConnectorSyncRun.stream == name)
            .order_by(ConnectorSyncRun.created_at.desc(), ConnectorSyncRun.id.desc())
            .limit(1)
        )
        success = session.scalar(
            select(func.max(ConnectorSyncRun.finished_at)).where(
                *runs,
                ConnectorSyncRun.stream == name,
                ConnectorSyncRun.status == "succeeded",
            )
        )
        found[name] = _StreamRows(checkpoints.get(name), latest, success)
    return found


def _stream_states(rows: Mapping[str, _StreamRows], now: datetime) -> dict[str, StreamState]:
    states = {}
    for name, item in rows.items():
        point = item.checkpoint
        if point is None and item.latest is None and item.success is None:
            continue
        states[name] = StreamState(
            stream=name,
            covered_from=None if point is None else point.covered_from,
            complete_through=None if point is None else point.complete_through,
            in_progress=bool(point is not None and point.cursor),
            last_success_at=item.success,
            sync=_sync_state(item.latest, now),
        )
    return states


def _stream_digest(target: Digest, rows: Mapping[str, _StreamRows]) -> None:
    for name in sorted(rows):
        item = rows[name]
        point, latest = item.checkpoint, item.latest
        target.add(
            [
                "stream",
                name,
                None
                if point is None
                else [point.covered_from, point.complete_through, point.cursor],
                None
                if latest is None
                else [latest.id, latest.status, latest.error_kind, latest.kind, latest.not_before],
                item.success,
            ]
        )


def _connection_digest(target: Digest, connection: ConnectorConnection, adapter: Any) -> None:
    target.add(
        [
            "connection",
            connection.id,
            connection.agency_id,
            connection.client_id,
            connection.provider,
            connection.status,
            connection.generation,
            connection.last_successful_sync_at,
            connection.account_kind,
            connection.day_zone,
            None if adapter is None else adapter.capability.version,
        ]
    )


def _published(value: object) -> datetime | None:
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _social_record(row: ConnectorRecord, published: datetime | None) -> SocialRecord:
    return SocialRecord(
        stream=row.stream,
        object_id=row.provider_object_id,
        observed_at=row.observed_at,
        fetched_at=row.fetched_at,
        metrics=dict(row.metrics),
        unavailable=dict(row.unavailable),
        product_type=row.product_type,
        provisional_until=row.provisional_until,
        published_at=published,
    )


def _record_digest(record: SocialRecord) -> list[Any]:
    return [
        "record",
        record.stream,
        record.object_id,
        record.present,
        record.observed_at,
        record.fetched_at,
        record.metrics,
        record.unavailable,
        record.product_type,
        record.provisional_until,
        record.published_at,
    ]


def read_social_inputs(
    session: Session,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    connection_id: UUID,
    view: str,
    periods: Sequence[Period],
    now: datetime,
) -> SocialInputs:
    connection = _connection(session, access, connection_id)
    family: Family | None = family_of(connection.provider)
    if family is None:
        raise ReportError("not_a_social_connection", 422)
    _require_reportable(connection)
    adapter = registry.get(connection.provider)
    if view == "daily":
        names = [family.daily_stream]
    else:
        names = list(family.content_streams)
        if family.publication_stream is not None:
            names.append(family.publication_stream)
    low = min(period.bounds(family.day_zone)[0] for period in periods)
    high = max(period.bounds(family.day_zone)[1] for period in periods)
    in_connection = (
        (ConnectorRecord.agency_id == access.agency_id)
        & (ConnectorRecord.client_id == access.client_id)
        & (ConnectorRecord.connection_id == connection.id)
    )
    records: list[SocialRecord] = []
    publication_unknown = 0
    if view == "daily" or family.publication_stream is None:
        streams = [family.daily_stream] if view == "daily" else list(family.content_streams)
        query = select(ConnectorRecord.id).where(
            in_connection,
            ConnectorRecord.stream.in_(streams),
            ConnectorRecord.observed_at >= low,
            ConnectorRecord.observed_at < high,
        )
        source_rows = _bounded(session, query, MAX_SOURCE_ROWS)
        if source_rows > MAX_SOURCE_ROWS:
            raise ReportError("report_too_large", 422)
        for row in session.scalars(
            select(ConnectorRecord)
            .where(
                in_connection,
                ConnectorRecord.stream.in_(streams),
                ConnectorRecord.observed_at >= low,
                ConnectorRecord.observed_at < high,
            )
            .order_by(ConnectorRecord.stream, ConnectorRecord.provider_object_id)
        ):
            published = row.observed_at if view != "daily" else None
            records.append(_social_record(row, published))
    else:
        listing = family.publication_stream
        listed = _bounded(
            session,
            select(ConnectorRecord.id).where(in_connection, ConnectorRecord.stream == listing),
            MAX_SOURCE_ROWS,
        )
        if listed > MAX_SOURCE_ROWS:
            raise ReportError("report_too_large", 422)
        cohort: dict[str, datetime] = {}
        for object_id, attributes in session.execute(
            select(ConnectorRecord.provider_object_id, ConnectorRecord.attributes)
            .where(in_connection, ConnectorRecord.stream == listing)
            .order_by(ConnectorRecord.provider_object_id)
        ):
            published = _published((attributes or {}).get("published_at"))
            if published is None:
                publication_unknown += 1
            elif low <= published < high:
                cohort[object_id] = published
        source_rows = listed + len(cohort)
        if source_rows > MAX_SOURCE_ROWS:
            raise ReportError("report_too_large", 422)
        found: dict[tuple[str, str], ConnectorRecord] = {}
        ids = sorted(cohort)
        for start in range(0, len(ids), 1000):
            for row in session.scalars(
                select(ConnectorRecord).where(
                    in_connection,
                    ConnectorRecord.stream.in_(list(family.content_streams)),
                    ConnectorRecord.provider_object_id.in_(ids[start : start + 1000]),
                )
            ):
                found[row.stream, row.provider_object_id] = row
        for stream in sorted(family.content_streams):
            for object_id in ids:
                row = found.get((stream, object_id))
                if row is None:
                    records.append(
                        SocialRecord(
                            stream=stream,
                            object_id=object_id,
                            observed_at=None,
                            fetched_at=None,
                            published_at=cohort[object_id],
                            present=False,
                        )
                    )
                else:
                    records.append(_social_record(row, cohort[object_id]))
    stream_rows = _stream_rows(session, access, connection.id, names)
    target = Digest("social-inputs")
    _connection_digest(target, connection, adapter)
    _stream_digest(target, stream_rows)
    target.add(["view", view, low, high, publication_unknown, source_rows])
    for record in records:
        target.add(_record_digest(record))
    return SocialInputs(
        family=family,
        connection_id=connection.id,
        provider=connection.provider,
        status=connection.status,
        generation=connection.generation,
        adapter_available=adapter is not None,
        adapter_version=None if adapter is None else adapter.capability.version,
        connection_last_success=connection.last_successful_sync_at,
        streams=_stream_states(stream_rows, now),
        records=tuple(records),
        source_rows=source_rows,
        digest=target.hexdigest(),
        publication_unknown=publication_unknown,
    )


def _local_date(instant: datetime | None, zone: str) -> date | None:
    return None if instant is None else instant.astimezone(ZoneInfo(zone)).date()


def read_spend_inputs(
    session: Session,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    connection_id: UUID,
    periods: Sequence[Period],
    now: datetime,
) -> SpendInputs:
    connection = _connection(session, access, connection_id)
    if connection.provider not in SPEND_PROVIDERS:
        raise ReportError("not_a_spend_connection", 422)
    _require_reportable(connection)
    adapter = registry.get(connection.provider)
    account = session.scalar(
        select(AdAccount).where(
            AdAccount.agency_id == access.agency_id,
            AdAccount.client_id == access.client_id,
            AdAccount.connection_id == connection.id,
        )
    )
    zone = account.time_zone if account is not None else connection.day_zone
    low = min(period.start for period in periods)
    high = max(period.end for period in periods)
    scope = (
        AdSpendFact.agency_id == access.agency_id,
        AdSpendFact.client_id == access.client_id,
        AdSpendFact.connection_id == connection.id,
        AdSpendFact.spend_date >= low,
        AdSpendFact.spend_date < high,
    )
    source_rows = _bounded(session, select(AdSpendFact.id).where(*scope), MAX_SOURCE_ROWS)
    if source_rows > MAX_SOURCE_ROWS:
        raise ReportError("report_too_large", 422)
    rows = list(
        session.scalars(
            select(AdSpendFact).where(*scope).order_by(AdSpendFact.spend_date, AdSpendFact.ad_id)
        )
    )
    stream_rows = _stream_rows(session, access, connection.id, [DAILY_STREAM])
    checkpoint = stream_rows[DAILY_STREAM].checkpoint
    covered_from = complete_through = None
    if checkpoint is not None and zone is not None and checkpoint.complete_through is not None:
        covered_from = _local_date(checkpoint.covered_from, zone)
        through = _local_date(checkpoint.complete_through, zone)
        complete_through = None if through is None else through - timedelta(days=1)
    state = _stream_states(stream_rows, now).get(DAILY_STREAM)
    target = Digest("spend-inputs")
    _connection_digest(target, connection, adapter)
    _stream_digest(target, stream_rows)
    account_view = None
    if account is not None:
        account_view = {
            "currency": account.currency,
            "time_zone": account.time_zone,
            "previous_currency": account.previous_currency,
            "currency_changed_at": account.currency_changed_at,
            "previous_time_zone": account.previous_time_zone,
            "time_zone_changed_at": account.time_zone_changed_at,
        }
    target.add(["account", account_view, zone, low, high, source_rows])
    facts = []
    for row in rows:
        target.add(
            [
                "fact",
                row.id,
                row.ad_id,
                row.adset_id,
                row.campaign_id,
                row.spend_date,
                row.time_zone,
                row.currency,
                row.spend_minor,
                row.impressions,
                row.clicks,
                row.refusal,
                row.provisional_until,
                row.revisions,
                row.last_observed_at,
            ]
        )
        facts.append(
            SpendFactInput(
                ad_id=row.ad_id,
                adset_id=row.adset_id,
                campaign_id=row.campaign_id,
                spend_date=row.spend_date,
                time_zone=row.time_zone,
                currency=row.currency,
                spend_minor=row.spend_minor,
                impressions=row.impressions,
                clicks=row.clicks,
                refusal=row.refusal,
                provisional_until=row.provisional_until,
            )
        )
    return SpendInputs(
        connection_id=connection.id,
        provider=connection.provider,
        status=connection.status,
        generation=connection.generation,
        adapter_available=adapter is not None,
        adapter_version=None if adapter is None else adapter.capability.version,
        zone=zone,
        account=account_view,
        covered_from=covered_from,
        complete_through=complete_through,
        in_progress=bool(state and state.in_progress),
        last_success_at=None if state is None else state.last_success_at,
        sync=dict(state.sync) if state is not None else {"state": "idle", "reason": None},
        connection_last_success=connection.last_successful_sync_at,
        facts=tuple(facts),
        source_rows=source_rows,
        digest=target.hexdigest(),
    )


# The bounded count and the digest of a client's evidence rows in receipt order. The release
# check needs only this: evidence is append-only, and any added or removed row changes it.
def revenue_digest(session: Session, access: ScopedAccess) -> tuple[int, str]:
    scope = (
        RevenueEvidence.agency_id == access.agency_id,
        RevenueEvidence.client_id == access.client_id,
    )
    count = _bounded(session, select(RevenueEvidence.id).where(*scope), MAX_EVIDENCE_ROWS)
    if count > MAX_EVIDENCE_ROWS:
        raise ReportError("report_requires_ledger_upgrade", 409)
    target = Digest("revenue-inputs")
    target.add(["scope", access.agency_id, access.client_id, count])
    for row in session.execute(
        select(
            RevenueEvidence.id,
            RevenueEvidence.sequence,
            RevenueEvidence.content_digest,
            RevenueEvidence.received_at,
            RevenueEvidence.intake,
        )
        .where(*scope)
        .order_by(RevenueEvidence.received_at, RevenueEvidence.sequence)
    ):
        target.add(["evidence", *row])
    return count, target.hexdigest()


def read_revenue_inputs(session: Session, access: ScopedAccess) -> RevenueInputs:
    count, digest = revenue_digest(session, access)
    ledger = client_ledger(session, access.agency_id, access.client_id)
    return RevenueInputs(
        calculation=ledger.calculation,
        held=ledger.held,
        evidence_rows=count,
        digest=digest,
        agency_id=access.agency_id,
        client_id=access.client_id,
    )


@dataclass(frozen=True)
class ReportQuery:
    """A validated report request; normalized() excludes pagination and format."""

    family: Family_
    start: date
    end: date
    compare: bool
    connection_id: UUID | None = None
    view: str | None = None
    level: str | None = None
    metrics: tuple[str, ...] | None = None

    def normalized(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "start": self.start,
            "end": self.end,
            "compare": "previous" if self.compare else None,
            "connection_id": self.connection_id,
            "view": self.view,
            "level": self.level,
            "metrics": None if self.metrics is None else sorted(self.metrics),
        }

    # The requested period and the previous one; a content cohort is never compared (D3).
    def periods(self) -> tuple[Period, Period | None]:
        period = Period(self.start, self.end)
        if self.compare and self.view == "content_cohort":
            raise ReportError("comparison_unsupported", 422)
        return period, (period.previous() if self.compare else None)


@dataclass
class Report:
    """A built report: the response body without rows, its revision and its ordered rows."""

    body: dict[str, Any]
    revision: str
    total_rows: int
    rows: Callable[[], Iterator[dict[str, Any]]]
    inputs_digest: str


def _inputs(
    session: Session,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    query: ReportQuery,
    now: datetime,
) -> Any:
    period, previous = query.periods()
    periods = [period] + ([previous] if previous is not None else [])
    if query.family == "social":
        assert query.connection_id is not None and query.view is not None
        return read_social_inputs(
            session, registry, access, query.connection_id, query.view, periods, now
        )
    if query.family == "spend":
        assert query.connection_id is not None
        return read_spend_inputs(session, registry, access, query.connection_id, periods, now)
    return read_revenue_inputs(session, access)


def _revision(
    access: ScopedAccess, query: ReportQuery, source: Any, inputs_digest: str, semantic: Any
) -> str:
    return digest_of(
        "report-revision",
        {
            "principal": [access.principal.kind, access.principal.identifier],
            "agency_id": access.agency_id,
            "client_id": access.client_id,
            "permission": access.permission,
            "query": query.normalized(),
            "contract_version": CONTRACT_VERSION,
            "catalog_version": CATALOG_VERSION,
            "source": source,
            "inputs": inputs_digest,
            "semantic": semantic,
        },
    )


def build_report(
    engine: Engine,
    registry: Mapping[str, ConnectorProvider],
    access: ScopedAccess,
    query: ReportQuery,
    now: datetime,
) -> Report:
    if access.permission != PERMISSIONS[query.family]:
        raise AccessDenied()
    period, previous = query.periods()
    with report_snapshot(engine) as session:
        inputs = _inputs(session, registry, access, query, now)
    base: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "family": query.family,
        "client_id": access.client_id,
        "connection_id": query.connection_id,
        "period": period.as_dict(),
        "comparison_period": None if previous is None else previous.as_dict(),
        "generated_at": now,
    }
    source: Any
    if query.family == "social":
        result: SocialResult = social_report(
            inputs, query.view or "", period, previous, query.metrics, now
        )
        source = [inputs.connection_id, inputs.generation, inputs.status, inputs.provider]
        body = {
            **base,
            "view": result.view,
            "day_zone": result.day_zone,
            "basis": result.basis,
            "catalog_version": CATALOG_VERSION,
            "totals": result.totals,
            "comparison": result.comparison,
            "source_status": result.source_status,
        }
        semantic, total_rows, rows = result.semantic, result.total_rows, result.rows
    elif query.family == "spend":
        spend: SpendResult = spend_report(inputs, query.level or "", period, previous, now)
        source = [inputs.connection_id, inputs.generation, inputs.status, inputs.provider]
        body = {
            **base,
            "level": spend.level,
            "day_zone": spend.day_zone,
            "basis": "account_local_daily_spend",
            "totals": spend.totals,
            "comparison": spend.comparison,
            "source_status": spend.source_status,
        }
        semantic, total_rows, rows = spend.semantic, spend.total_rows, spend.rows
    else:
        revenue: RevenueResult = revenue_report(inputs, period, previous)
        source = ["ledger", inputs.evidence_rows]
        body = {
            **base,
            "day_zone": "UTC",
            "basis": "posting_effective_time",
            "totals": revenue.totals,
            "comparison": revenue.comparison,
            "unresolved": revenue.unresolved,
        }
        semantic, total_rows, rows = revenue.semantic, revenue.total_rows, revenue.rows
    revision = _revision(access, query, source, inputs.digest, semantic)
    body["revision"] = revision
    body["dependencies"] = [dict(item) for item in DEPENDENCIES]
    return Report(body, revision, total_rows, rows, inputs.digest)


# Check the caller's revision against the built report: a later page needs one, and any
# difference refuses the whole response with no rows or totals.
def check_revision(report: Report, expected: str | None, page: PageRequest | None) -> None:
    if expected is not None and expected != report.revision:
        raise ReportError("report_changed", 409)
    if page is not None and page.page > 1 and expected is None:
        raise ReportError("revision_required", 422)


def page_rows(report: Report, page: PageRequest) -> tuple[list[dict[str, Any]], dict[str, int]]:
    return page_of(report.rows(), report.total_rows, page)


# The final release check (D7): a fresh snapshot after the result was built resolves the
# caller's scope again and rereads every input. Any change refuses the response.
def release_check(
    engine: Engine,
    registry: Mapping[str, ConnectorProvider],
    principal: Principal,
    access: ScopedAccess,
    query: ReportQuery,
    report: Report,
    now: datetime,
) -> None:
    before_release(query.family)
    with report_snapshot(engine) as session:
        current = resolve_scope(
            session, principal, access.agency_id, access.client_id, PERMISSIONS[query.family]
        )
        if current != access:
            raise AccessDenied()
        try:
            if query.family == "revenue":
                digest = revenue_digest(session, access)[1]
            else:
                digest = _inputs(session, registry, access, query, now).digest
        except ReportError as error:
            if error.code in {"report_too_large", "report_requires_ledger_upgrade"}:
                raise ReportError("report_changed", 409) from error
            raise
    if digest != report.inputs_digest:
        raise ReportError("report_changed", 409)
