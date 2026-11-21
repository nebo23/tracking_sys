"""Specification 014 migrations, privileges and retention on disposable PostgreSQL (D-064 D13).

Each revision upgrades on the disposable service only, its downgrade refuses populated state,
the runtime and lifecycle roles hold only the column privileges the design lists, the
lifecycle runner removes spend facts 730 days after their spend date, and at most one
delivery per client and event ID holds that ID (D-065). No case touches the owner's native
tracking_sys database.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import (
    AdSpendFact,
    ConnectorConnection,
    ConversionAcknowledgement,
    ConversionDelivery,
    ConversionDestination,
)
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))


def _version(db) -> str:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _privilege(db, role: str, table: str, privilege: str, column: str | None = None) -> bool:
    with db.migration.connect() as connection:
        if column is None:
            query = "SELECT has_table_privilege(:role, :table, :privilege)"
            arguments = {"role": role, "table": table, "privilege": privilege}
        else:
            query = "SELECT has_column_privilege(:role, :table, :column, :privilege)"
            arguments = {"role": role, "table": table, "column": column, "privilege": privilege}
        return bool(connection.execute(text(query), arguments).scalar_one())


def _spend_connection(world) -> ConnectorConnection:
    with Session(world.db.migration, expire_on_commit=False) as session, session.begin():
        connection = ConnectorConnection(
            id=uuid4(),
            agency_id=world.a,
            client_id=world.a1,
            provider="synthetic_meta_ads",
            external_account_id="act_1001",
            status="active",
            generation=1,
            created_by_membership_id=world.owner_a,
            day_zone="America/New_York",
        )
        session.add(connection)
    return connection


def _fact(world, connection, day: date) -> None:
    with Session(world.db.migration) as session, session.begin():
        session.add(
            AdSpendFact(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                connection_id=connection.id,
                ad_id="311001",
                spend_date=day,
                time_zone="America/New_York",
                currency="USD",
                spend_minor=1000,
                provisional_until=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )


def test_0017_privileges(db):
    app, lifecycle = "tracking_app", "tracking_lifecycle"
    for table in ("ad_accounts", "ad_objects", "ad_spend_facts"):
        for privilege in ("SELECT", "INSERT", "DELETE"):
            assert _privilege(db, app, table, privilege), (table, privilege)
        assert not _privilege(db, app, table, "TRUNCATE")
    # Re-reads change values, never the keys or the first observation.
    for column in ("spend_minor", "currency", "refusal", "revisions", "provisional_until"):
        assert _privilege(db, app, "ad_spend_facts", "UPDATE", column), column
    for column in ("ad_id", "spend_date", "connection_id", "client_id", "first_observed_at"):
        assert not _privilege(db, app, "ad_spend_facts", "UPDATE", column), column
    assert not _privilege(db, app, "ad_objects", "UPDATE", "object_id")
    assert not _privilege(db, app, "ad_accounts", "UPDATE", "account_id")
    assert _privilege(db, app, "connector_connections", "UPDATE", "day_zone")
    # The lifecycle role deletes old facts and reads only what that needs.
    assert _privilege(db, lifecycle, "ad_spend_facts", "DELETE")
    assert _privilege(db, lifecycle, "ad_spend_facts", "SELECT", "spend_date")
    for column in ("spend_minor", "currency", "ad_id"):
        assert not _privilege(db, lifecycle, "ad_spend_facts", "SELECT", column), column
    for table in ("ad_accounts", "ad_objects"):
        assert not _privilege(db, lifecycle, table, "SELECT")
        assert not _privilege(db, lifecycle, table, "DELETE")


def test_lifecycle_deletes_spend_after_730_days(world, lifecycle_engine, lifecycle_settings):
    connection = _spend_connection(world)
    today = datetime.now(UTC).date()
    _fact(world, connection, today - timedelta(days=731))
    _fact_day = today - timedelta(days=729)
    with Session(world.db.migration) as session, session.begin():
        session.add(
            AdSpendFact(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                connection_id=connection.id,
                ad_id="321001",
                spend_date=_fact_day,
                time_zone="America/New_York",
                currency="USD",
                spend_minor=1000,
                provisional_until=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["ad_spend_facts"] == 1
    with Session(world.db.migration) as session:
        assert session.scalars(select(AdSpendFact.spend_date)).all() == [_fact_day]


def test_0017_downgrade_refuses_spend_state(world):
    head = _version(world.db)
    connection = _spend_connection(world)
    with pytest.raises(RuntimeError, match="Refuse to remove populated spend state"):
        command.downgrade(CONFIG, "0016_youtube_provider")
    assert _version(world.db) == head
    _fact(world, connection, date(2026, 11, 1))
    with pytest.raises(RuntimeError, match="Refuse to remove populated spend state"):
        command.downgrade(CONFIG, "0016_youtube_provider")
    assert _version(world.db) == head
    with Session(world.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(AdSpendFact)) == 1


def test_0017_downgrade_and_upgrade_when_empty(db):
    head = _version(db)
    command.downgrade(CONFIG, "0016_youtube_provider")
    try:
        with db.migration.connect() as connection:
            tables = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert not tables & {"ad_accounts", "ad_objects", "ad_spend_facts"}
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head


def test_0018_privileges(db):
    app, lifecycle = "tracking_app", "tracking_lifecycle"
    tables = ("conversion_destinations", "conversion_deliveries", "conversion_acknowledgements")
    for table in tables:
        assert _privilege(db, app, table, "SELECT") and _privilege(db, app, table, "INSERT")
        assert not _privilege(db, app, table, "DELETE"), table
    for column in ("status", "reason", "ciphertext", "value_minor", "attempts", "ended_at"):
        assert _privilege(db, app, "conversion_deliveries", "UPDATE", column), column
    # The event ID, event time, deadline, consent basis and keys never change after enqueue.
    for column in ("event_id", "event_time", "deadline", "consent_basis", "client_id"):
        assert not _privilege(db, app, "conversion_deliveries", "UPDATE", column), column
    assert not _privilege(db, app, "conversion_acknowledgements", "UPDATE", "outcome")
    assert _privilege(db, app, "conversion_destinations", "UPDATE", "enabled")
    assert not _privilege(db, app, "conversion_destinations", "UPDATE", "connection_id")
    for table in ("conversion_deliveries", "conversion_acknowledgements"):
        assert _privilege(db, lifecycle, table, "DELETE"), table
    assert _privilege(db, lifecycle, "conversion_deliveries", "SELECT", "ended_at")
    assert _privilege(db, lifecycle, "conversion_acknowledgements", "SELECT", "delivery_id")
    for column in ("value_minor", "ciphertext", "event_id"):
        assert not _privilege(db, lifecycle, "conversion_deliveries", "SELECT", column), column
    assert not _privilege(db, lifecycle, "conversion_acknowledgements", "SELECT", "trace_id")
    assert not _privilege(db, lifecycle, "conversion_destinations", "SELECT")


def _delivery_rows(world, ended_at):
    connection = _spend_connection(world)
    with Session(world.db.migration, expire_on_commit=False) as session, session.begin():
        session.execute(
            text(
                "UPDATE connector_connections SET provider = 'synthetic_meta_capi' WHERE id = :id"
            ),
            {"id": connection.id},
        )
        destination = ConversionDestination(
            id=uuid4(),
            agency_id=world.a,
            client_id=world.a1,
            connection_id=connection.id,
            created_by_membership_id=world.owner_a,
        )
        session.add(destination)
        session.flush()
        rows = []
        for index, ended in enumerate(ended_at):
            event_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
            delivery = ConversionDelivery(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                destination_id=destination.id,
                connection_id=connection.id,
                event_id=f"{index:064x}",
                event_name="Purchase",
                action_source="system_generated",
                event_time=event_time,
                deadline=event_time + timedelta(days=6, hours=23),
                currency="USD",
                currency_exponent=2,
                value_minor=100,
                status="delivered",
                attempts=1,
                consent_basis=[],
                policy_version="003-B.1",
                delivered_at=ended,
                ended_at=ended,
            )
            session.add(delivery)
            session.flush()
            session.add(
                ConversionAcknowledgement(
                    id=uuid4(),
                    agency_id=world.a,
                    client_id=world.a1,
                    delivery_id=delivery.id,
                    attempt=1,
                    outcome="accepted",
                    events_received=1,
                    trace_id="SYNTRACE",
                )
            )
            rows.append(delivery.id)
    return rows


def test_lifecycle_deletes_ended_deliveries_after_30_days(
    world, lifecycle_engine, lifecycle_settings
):
    now = datetime.now(UTC)
    old, recent = _delivery_rows(world, [now - timedelta(days=31), now - timedelta(days=29)])
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["conversion_acknowledgements"] == 1
    assert result["deleted"]["conversion_deliveries"] == 1
    assert result["status"] == "completed"
    with Session(world.db.migration) as session:
        assert session.scalars(select(ConversionDelivery.id)).all() == [recent]
        assert session.scalars(select(ConversionAcknowledgement.delivery_id)).all() == [recent]
    assert old != recent


def test_0018_downgrade_refuses_delivery_state(world):
    head = _version(world.db)
    _delivery_rows(world, [datetime.now(UTC)])
    with pytest.raises(RuntimeError, match="Refuse to remove populated delivery state"):
        command.downgrade(CONFIG, "0017_ad_spend")
    assert _version(world.db) == head


def test_0019_admits_and_protects_the_live_meta_providers(world):
    head = _version(world.db)
    connection = _spend_connection(world)
    for provider in ("meta_ads", "meta_capi"):
        with Session(world.db.migration) as session, session.begin():
            session.execute(
                text("UPDATE connector_connections SET provider = :provider WHERE id = :id"),
                {"provider": provider, "id": connection.id},
            )
        with pytest.raises(RuntimeError, match="Refuse to remove live Meta connector state"):
            command.downgrade(CONFIG, "0018_conversion_delivery")
        assert _version(world.db) == head


def _capi_destination(world, account: str) -> tuple:
    with Session(world.db.migration, expire_on_commit=False) as session, session.begin():
        connection = ConnectorConnection(
            id=uuid4(),
            agency_id=world.a,
            client_id=world.a1,
            provider="synthetic_meta_capi",
            external_account_id=account,
            status="active",
            generation=1,
            created_by_membership_id=world.owner_a,
        )
        session.add(connection)
        session.flush()
        destination = ConversionDestination(
            id=uuid4(),
            agency_id=world.a,
            client_id=world.a1,
            connection_id=connection.id,
            created_by_membership_id=world.owner_a,
        )
        session.add(destination)
    return connection.id, destination.id


def _delivery(world, target, event_id, *, status="queued", reason=None, attempts=0):
    connection_id, destination_id = target
    now = datetime.now(UTC)
    ended = status != "queued"
    material = {
        "kek_id": "synthetic",
        "wrap_nonce": b"n",
        "wrapped_dek": b"d",
        "nonce": b"n",
        "ciphertext": b"c",
    }
    return ConversionDelivery(
        id=uuid4(),
        agency_id=world.a,
        client_id=world.a1,
        destination_id=destination_id,
        connection_id=connection_id,
        event_id=event_id,
        event_name="Purchase",
        action_source="system_generated",
        event_time=now - timedelta(hours=1),
        deadline=now + timedelta(days=6),
        currency="USD",
        currency_exponent=2,
        value_minor=100,
        status=status,
        reason=reason,
        attempts=attempts,
        consent_basis=[],
        policy_version="003-B.1",
        delivered_at=now if status == "delivered" else None,
        ended_at=now if ended else None,
        **({} if ended else material),
    )


def _insert(world, *rows) -> None:
    with Session(world.db.migration) as session, session.begin():
        for row in rows:
            session.add(row)
            session.flush()


def test_0018_one_delivery_per_client_and_event_id(world):
    # R014-01 (d), D-065: the database refuses a second delivery with the same client and event
    # ID under any destination. Only a delivery cancelled before any attempt because its
    # destination was disabled or its connection ended does not hold the ID.
    first, second = _capi_destination(world, "880001"), _capi_destination(world, "880002")
    _insert(world, _delivery(world, first, "a" * 64, status="delivered", attempts=1))
    with pytest.raises(IntegrityError, match="uq_conversion_deliveries_event"):
        _insert(world, _delivery(world, second, "a" * 64))
    _insert(
        world,
        _delivery(world, first, "b" * 64, status="cancelled", reason="destination_disabled"),
        _delivery(world, second, "b" * 64, status="cancelled", reason="connection_ended"),
        _delivery(world, second, "b" * 64),
    )
    for event_id, reason, attempts in (
        ("c" * 64, "connection_ended", 1),
        ("d" * 64, "destination_disabled", 2),
        ("e" * 64, "sale_reversed", 0),
    ):
        _insert(
            world,
            _delivery(world, first, event_id, status="cancelled", reason=reason, attempts=attempts),
        )
        with pytest.raises(IntegrityError, match="uq_conversion_deliveries_event"):
            _insert(world, _delivery(world, second, event_id))
    with Session(world.db.migration) as session:
        held = session.scalars(
            select(ConversionDelivery.status).where(ConversionDelivery.event_id == "b" * 64)
        ).all()
    assert sorted(held) == ["cancelled", "cancelled", "queued"]
