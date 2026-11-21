"""Specification 014 migrations, privileges and retention on disposable PostgreSQL (D-064 D13, D14).

Each revision upgrades on the disposable service only, its downgrade refuses populated state,
the runtime and lifecycle roles hold only the column privileges the design lists, and the
lifecycle runner removes spend facts 730 days after their spend date. No case touches the
owner's native tracking_sys database.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import AdSpendFact, ConnectorConnection
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
