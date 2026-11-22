"""Synthetic report fixtures for the 016-A integration tests (specification 016-A, D-072).

Rows are inserted directly into the guarded disposable database with the migration engine, so
each case controls dates, values, coverage, synchronization state and provisional ends exactly.
Every identity, account, metric and amount is synthetic; no provider adapter is called.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import (
    AdAccount,
    AdSpendFact,
    AgencyMembership,
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
)
from app.services.access import AccessService, ClientPermission
from app.services.revenue import append_evidence, lock_revenue

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
EGP = Currency("EGP", 2)
USD = Currency("USD", 2)


def midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), UTC)


def membership(w, agency: UUID) -> UUID:
    with Session(w.db.migration) as session:
        return session.scalar(
            select(AgencyMembership.id)
            .where(AgencyMembership.agency_id == agency, AgencyMembership.role == "owner")
            .order_by(AgencyMembership.created_at)
            .limit(1)
        )


def connection(w, client_id, provider, agency=None, *, day_zone=None, account=None) -> UUID:
    agency = agency or w.a
    with Session(w.db.migration) as session, session.begin():
        row = ConnectorConnection(
            agency_id=agency,
            client_id=client_id,
            provider=provider,
            external_account_id=account or f"syn-{uuid4().hex[:12]}",
            account_label="Synthetic label",
            created_by_membership_id=membership(w, agency),
            last_successful_sync_at=NOW - timedelta(hours=2),
            day_zone=day_zone,
        )
        session.add(row)
        session.flush()
        return row.id


def _scope(session, connection_id):
    row = session.get(ConnectorConnection, connection_id)
    return row.agency_id, row.client_id, row.generation


def run(w, connection_id, stream, *, status="succeeded", finished=None) -> UUID:
    finished = finished or NOW - timedelta(hours=1)
    with Session(w.db.migration) as session, session.begin():
        agency, client, generation = _scope(session, connection_id)
        item = ConnectorSyncRun(
            agency_id=agency,
            client_id=client,
            connection_id=connection_id,
            connection_generation=generation,
            status=status,
            stream=stream,
            created_at=finished - timedelta(minutes=5),
            started_at=finished - timedelta(minutes=4),
            finished_at=finished if status in {"succeeded", "failed", "canceled"} else None,
        )
        session.add(item)
        session.flush()
        return item.id


def checkpoint(w, connection_id, stream, covered_from, complete_through, cursor=None) -> None:
    with Session(w.db.migration) as session, session.begin():
        agency, client, _ = _scope(session, connection_id)
        session.add(
            ConnectorCheckpoint(
                agency_id=agency,
                client_id=client,
                connection_id=connection_id,
                stream=stream,
                covered_from=covered_from,
                complete_through=complete_through,
                cursor=cursor,
            )
        )


def records(w, connection_id, items) -> None:
    """items: dicts with stream, object_id, observed_at, metrics and optional fields."""
    with Session(w.db.migration) as session, session.begin():
        agency, client, generation = _scope(session, connection_id)
        for item in items:
            attributes = item.get("attributes") or {}
            session.add(
                ConnectorRecord(
                    agency_id=agency,
                    client_id=client,
                    connection_id=connection_id,
                    connection_generation=generation,
                    stream=item["stream"],
                    provider_object_id=item["object_id"],
                    observed_at=item["observed_at"],
                    fetched_at=item.get("fetched_at", NOW - timedelta(hours=1)),
                    metrics=item.get("metrics", {}),
                    unavailable=item.get("unavailable", {}),
                    product_type=item.get("product_type"),
                    attributes=attributes,
                    attributes_refreshed_at=NOW - timedelta(hours=1) if attributes else None,
                    provisional_until=item.get("provisional_until"),
                )
            )


def instagram_days(w, connection_id, days, **metrics_by_day) -> None:
    records(
        w,
        connection_id,
        [
            {
                "stream": "account",
                "object_id": f"day-{day}",
                "observed_at": midnight(day),
                "metrics": {name: values[index] for name, values in metrics_by_day.items()},
            }
            for index, day in enumerate(days)
        ],
    )


def ad_account(w, connection_id, currency="EGP", zone="Africa/Cairo") -> None:
    with Session(w.db.migration) as session, session.begin():
        agency, client, _ = _scope(session, connection_id)
        session.add(
            AdAccount(
                agency_id=agency,
                client_id=client,
                connection_id=connection_id,
                account_id="act_1001",
                name="Synthetic ad account",
                currency=currency,
                time_zone=zone,
            )
        )


def spend_facts(w, connection_id, items) -> None:
    """items: dicts with ad, day, currency, minor and optional fields."""
    with Session(w.db.migration) as session, session.begin():
        agency, client, _ = _scope(session, connection_id)
        session.add_all(
            [
                AdSpendFact(
                    agency_id=agency,
                    client_id=client,
                    connection_id=connection_id,
                    ad_id=item["ad"],
                    adset_id=item.get("adset"),
                    campaign_id=item.get("campaign"),
                    spend_date=item["day"],
                    time_zone=item.get("zone", "Africa/Cairo"),
                    currency=item.get("currency"),
                    spend_minor=item.get("minor"),
                    impressions=item.get("impressions", 10),
                    clicks=item.get("clicks", 1),
                    refusal=item.get("refusal"),
                    provisional_until=item.get("provisional_until", NOW - timedelta(days=1)),
                )
                for item in items
            ]
        )


def evidence(
    w,
    operation,
    kind=OperationKind.SALE,
    minor=10_000,
    *,
    when,
    currency=EGP,
    parent=None,
    classification=None,
    client=None,
    agency=None,
    order=None,
    reason=None,
    delivery=None,
) -> Evidence:
    classes = {
        OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
        OperationKind.REFUND: EvidenceClass.CONFIRMED_ADJUSTMENT,
    }
    return Evidence(
        delivery or f"synthetic:{operation}:{kind.value}:{minor}",
        agency or w.a,
        client or w.a1,
        "paymob-egypt",
        operation,
        kind,
        classification or classes[kind],
        Money(minor, currency),
        when,
        when,
        parent_operation_id=parent,
        reason=reason,
        source_reference=f"paymob:4097558:8{order or parent or operation}",
    )


def append(w, items, intake="paymob") -> None:
    for item in items:
        with Session(w.db.runtime) as session, session.begin():
            received = lock_revenue(session, item.client_id)
            stored = replace(item, received_at=received)
            append_evidence(session, stored, intake, None if intake == "manual_entry" else uuid4())


def service_key(w, api, grants, kind="read", actor=None, agency=None) -> str:
    with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
        _, raw = AccessService(session, actor or w.users.owner_a, api.config).issue_service_key(
            agency or w.a, f"Synthetic {kind}", grants, kind=kind
        )
    return raw


def key_client(api, raw):
    client = api.new_client()
    client.headers["Authorization"] = f"Bearer {raw}"
    return client


def report_url(w, family, *, agency=None, client=None, **query) -> str:
    agency = agency or w.a
    client = client or w.a1
    values = {key: value for key, value in query.items() if value is not None}
    return f"/agencies/{agency}/clients/{client}/reports/{family}?{urlencode(values)}"


def grant(permission_client, financial=False):
    return ClientPermission(permission_client, financial)
