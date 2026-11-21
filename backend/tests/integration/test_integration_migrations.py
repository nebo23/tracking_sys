"""Specification 015-D and 015-E migrations and privileges on disposable PostgreSQL (D-068 E12).

Each revision upgrades on the disposable service only, its downgrade refuses populated state,
and the runtime and lifecycle roles hold only the privileges the design lists. No case touches
the owner's native tracking_sys database.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import CrmStageRule, IntegrationSource

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


def _tables(db) -> set[str]:
    with db.migration.connect() as connection:
        return set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )


BOOKING_TABLES = (
    "integration_sources",
    "integration_source_secrets",
    "integration_deliveries",
    "bookings",
    "booking_events",
)
CRM_TABLES = ("crm_stage_rules", "crm_deals")


def test_0023_and_0024_privileges(db):
    for table in BOOKING_TABLES + CRM_TABLES:
        for privilege in ("SELECT", "INSERT"):
            assert _privilege(db, "tracking_app", table, privilege), (table, privilege)
        for privilege in ("DELETE", "TRUNCATE"):
            assert not _privilege(db, "tracking_app", table, privilege), (table, privilege)
    allowed = {
        "integration_sources": {"name", "status", "updated_at"},
        "integration_source_secrets": {"retires_at"},
        "bookings": {
            "status",
            "event_type_ref",
            "start_at",
            "end_at",
            "reschedule_count",
            "subject_id",
            "linked_at",
            "updated_at",
        },
        "booking_events": {"booking_id"},
        "crm_stage_rules": {"outcome", "status", "updated_at"},
        "crm_deals": {
            "pipeline",
            "stage",
            "previous_stage",
            "stage_at",
            "amount_minor",
            "currency",
            "currency_exponent",
            "payment_reference",
            "updated_at",
        },
    }
    refused = {
        "integration_sources": {"public_key", "kind", "client_id"},
        "integration_source_secrets": {"ciphertext", "version"},
        "integration_deliveries": {"outcome", "delivery_digest"},
        "bookings": {"client_id", "provider", "first_received_at"},
        "booking_events": {"ref", "kind", "occurred_at"},
        "crm_stage_rules": {"pipeline", "stage", "client_id"},
        "crm_deals": {"deal_ref", "source_id", "client_id"},
    }
    for table, columns in allowed.items():
        for column in columns:
            assert _privilege(db, "tracking_app", table, "UPDATE", column), (table, column)
    for table, columns in refused.items():
        for column in columns:
            assert not _privilege(db, "tracking_app", table, "UPDATE", column), (table, column)
    lifecycle = {
        "integration_source_secrets": ("id", "retires_at"),
        "integration_deliveries": ("id", "received_at"),
        "bookings": ("id", "updated_at"),
        "crm_deals": ("id", "updated_at"),
    }
    for table, columns in lifecycle.items():
        assert _privilege(db, "tracking_lifecycle", table, "DELETE"), table
        for column in columns:
            assert _privilege(db, "tracking_lifecycle", table, "SELECT", column), (table, column)
    assert not _privilege(db, "tracking_lifecycle", "bookings", "SELECT", "subject_id")
    assert not _privilege(db, "tracking_lifecycle", "crm_deals", "SELECT", "payment_reference")
    for table in ("integration_sources", "crm_stage_rules", "booking_events"):
        assert not _privilege(db, "tracking_lifecycle", table, "DELETE"), table


def _source(world) -> None:
    with Session(world.db.migration) as session, session.begin():
        session.add(
            IntegrationSource(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                kind="signed_webhook",
                name="Synthetic",
                status="active",
                public_key="isk_" + "A" * 43,
                created_by_membership_id=world.owner_a,
            )
        )


def _rule(world) -> None:
    moment = datetime(2026, 11, 21, tzinfo=UTC)
    with Session(world.db.migration) as session, session.begin():
        session.add(
            CrmStageRule(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                pipeline="sales",
                stage="won",
                outcome="won",
                status="active",
                created_by_membership_id=world.owner_a,
                created_at=moment,
                updated_at=moment,
            )
        )


@pytest.mark.parametrize(
    ("revision", "populate", "message"),
    [
        ("0023_integration_bookings", _rule, "Refuse to remove CRM state"),
        ("0022_revenue_imports", _source, "Refuse to remove integration state"),
    ],
)
def test_downgrades_refuse_populated_state(world, revision, populate, message):
    head = _version(world.db)
    populate(world)
    with pytest.raises(RuntimeError, match=message):
        command.downgrade(CONFIG, revision)
    assert _version(world.db) == head


def test_downgrade_and_upgrade_when_empty(db):
    head = _version(db)
    command.downgrade(CONFIG, "0022_revenue_imports")
    try:
        assert not _tables(db) & set(BOOKING_TABLES + CRM_TABLES)
        assert "revenue_imports" in _tables(db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head
