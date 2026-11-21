"""Specification 015 migrations and privileges on disposable PostgreSQL (D-067 D14 and D15).

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
from app.models import RevenueEvidence

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


def _evidence(world, intake="paymob") -> None:
    moment = datetime(2026, 11, 10, tzinfo=UTC)
    with Session(world.db.migration) as session, session.begin():
        session.add(
            RevenueEvidence(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                delivery_id="synthetic:1",
                source_account_id="paymob-egypt",
                operation_id="1",
                kind="sale",
                classification="confirmed_capture",
                currency="EGP",
                currency_exponent=2,
                amount_minor=100,
                effective_at=moment,
                received_at=moment,
                intake=intake,
                intake_id=None if intake == "manual_entry" else uuid4(),
                content_digest="0" * 64,
            )
        )


def test_0020_privileges(db):
    for privilege in ("SELECT", "INSERT"):
        assert _privilege(db, "tracking_app", "revenue_evidence", privilege)
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not _privilege(db, "tracking_app", "revenue_evidence", privilege)
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert not _privilege(db, "tracking_lifecycle", "revenue_evidence", privilege)


def test_0020_downgrade_refuses_evidence(world):
    head = _version(world.db)
    _evidence(world)
    with pytest.raises(RuntimeError, match="Refuse to remove stored revenue evidence"):
        command.downgrade(CONFIG, "0019_meta_providers")
    assert _version(world.db) == head
    assert "revenue_evidence" in _tables(world.db)


def test_0020_downgrade_and_upgrade_when_empty(db):
    head = _version(db)
    command.downgrade(CONFIG, "0019_meta_providers")
    try:
        assert "revenue_evidence" not in _tables(db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("kind", "payout"),
        ("classification", "confirmed_adjustment"),  # not allowed for a sale
        ("intake", "email"),
        ("currency", "egp"),
        ("amount_minor", 0),
        ("parent_operation_id", "2"),  # a sale has no parent
        ("content_digest", "not-a-digest"),
    ],
)
def test_0020_checks_refuse_invalid_rows(world, column, value):
    with pytest.raises(Exception, match="violates check constraint"):
        with world.db.migration.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO revenue_evidence (id, agency_id, client_id, delivery_id, "
                    "source_account_id, operation_id, kind, classification, currency, "
                    "currency_exponent, amount_minor, effective_at, received_at, intake, "
                    "intake_id, content_digest) VALUES (:id, :agency, :client, 'd', 'a', '1', "
                    "'sale', 'confirmed_capture', 'EGP', 2, 100, now(), now(), 'manual_entry', "
                    "NULL, :digest)"
                ),
                {"id": uuid4(), "agency": world.a, "client": world.a1, "digest": "0" * 64},
            )
            connection.execute(
                text(f"UPDATE revenue_evidence SET {column} = :value"), {"value": value}
            )
