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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import PaymentSource, RevenueEvidence, RevenueImport

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
    # Later revisions refuse their own intakes first, so the check starts at 0020.
    head = _version(world.db)
    command.downgrade(CONFIG, "0020_revenue_evidence")
    try:
        _evidence(world, "manual_entry")
        with pytest.raises(RuntimeError, match="Refuse to remove stored revenue evidence"):
            command.downgrade(CONFIG, "0019_meta_providers")
        assert _version(world.db) == "0020_revenue_evidence"
        assert "revenue_evidence" in _tables(world.db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(world.db) == head


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


PAYMENT_TABLES = ("payment_sources", "payment_source_secrets", "payment_callback_diagnostics")


def test_0021_privileges(db):
    for table in PAYMENT_TABLES:
        for privilege in ("SELECT", "INSERT"):
            assert _privilege(db, "tracking_app", table, privilege), (table, privilege)
        assert not _privilege(db, "tracking_app", table, "DELETE"), table
        assert not _privilege(db, "tracking_app", table, "TRUNCATE"), table
    for column in ("name", "status", "live_integration_ids", "updated_at"):
        assert _privilege(db, "tracking_app", "payment_sources", "UPDATE", column)
    for column in ("public_key", "client_id", "provider", "region"):
        assert not _privilege(db, "tracking_app", "payment_sources", "UPDATE", column)
    assert _privilege(db, "tracking_app", "payment_source_secrets", "UPDATE", "retires_at")
    for column in ("ciphertext", "version", "source_id"):
        assert not _privilege(db, "tracking_app", "payment_source_secrets", "UPDATE", column)
    assert not _privilege(db, "tracking_app", "payment_callback_diagnostics", "UPDATE")
    lifecycle = {
        "payment_source_secrets": ("id", "retires_at"),
        "payment_callback_diagnostics": ("id", "received_at"),
    }
    for table, columns in lifecycle.items():
        assert _privilege(db, "tracking_lifecycle", table, "DELETE")
        for column in columns:
            assert _privilege(db, "tracking_lifecycle", table, "SELECT", column)
    assert not _privilege(
        db, "tracking_lifecycle", "payment_source_secrets", "SELECT", "ciphertext"
    )
    assert not _privilege(
        db, "tracking_lifecycle", "payment_callback_diagnostics", "SELECT", "delivery_digest"
    )
    assert not _privilege(db, "tracking_lifecycle", "payment_sources", "SELECT")
    assert not _privilege(db, "tracking_lifecycle", "payment_sources", "DELETE")


def _source(world, live=(4_097_558,)) -> None:
    with Session(world.db.migration) as session, session.begin():
        session.add(
            PaymentSource(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                provider="paymob",
                region="egypt",
                name="Synthetic",
                status="active",
                public_key="ppk_" + "A" * 43,
                live_integration_ids=list(live),
                created_by_membership_id=world.owner_a,
            )
        )


def test_0021_live_integration_check(world):
    # D-070: 1 to 20 positive live integration IDs, never a null element, enforced by the
    # database as well as the API.
    for live in ((), (0,), (-1,), (1, None), tuple(range(1, 22))):
        with pytest.raises(IntegrityError, match="ck_payment_sources_valid_live_integrations"):
            _source(world, live)
    _source(world, tuple(range(1, 21)))
    with world.db.migration.begin() as connection:
        connection.execute(text("DELETE FROM payment_sources"))


def test_0021_downgrade_refuses_payment_state(world):
    head = _version(world.db)
    _source(world)
    with pytest.raises(RuntimeError, match="Refuse to remove payment source state"):
        command.downgrade(CONFIG, "0020_revenue_evidence")
    assert _version(world.db) == head
    with world.db.migration.begin() as connection:
        connection.execute(text("DELETE FROM payment_sources"))
    _evidence(world, "paymob")
    with pytest.raises(RuntimeError, match="Refuse to remove payment source state"):
        command.downgrade(CONFIG, "0020_revenue_evidence")
    assert _version(world.db) == head


def test_0021_downgrade_and_upgrade_when_empty(db):
    head = _version(db)
    command.downgrade(CONFIG, "0020_revenue_evidence")
    try:
        assert not _tables(db) & set(PAYMENT_TABLES)
        assert "revenue_evidence" in _tables(db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head


def test_0022_privileges(db):
    for privilege in ("SELECT", "INSERT"):
        assert _privilege(db, "tracking_app", "revenue_imports", privilege)
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not _privilege(db, "tracking_app", "revenue_imports", privilege)
    assert _privilege(db, "tracking_lifecycle", "revenue_imports", "DELETE")
    for column in ("id", "committed_at"):
        assert _privilege(db, "tracking_lifecycle", "revenue_imports", "SELECT", column)
    for column in ("file_digest", "client_id", "stored_rows"):
        assert not _privilege(db, "tracking_lifecycle", "revenue_imports", "SELECT", column)


def test_0022_downgrade_refuses_import_state(world):
    head = _version(world.db)
    with Session(world.db.migration) as session, session.begin():
        session.add(
            RevenueImport(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                file_digest="a" * 64,
                total_rows=1,
                stored_rows=1,
                duplicate_rows=0,
                rejected_rows=0,
                committed_by_membership_id=world.owner_a,
                committed_at=datetime(2026, 11, 21, tzinfo=UTC),
            )
        )
    with pytest.raises(RuntimeError, match="Refuse to remove revenue import state"):
        command.downgrade(CONFIG, "0021_payment_sources")
    assert _version(world.db) == head
    with world.db.migration.begin() as connection:
        connection.execute(text("DELETE FROM revenue_imports"))
    for intake in ("csv_import", "manual_entry"):
        _evidence(world, intake)
        with pytest.raises(RuntimeError, match="Refuse to remove revenue import state"):
            command.downgrade(CONFIG, "0021_payment_sources")
        assert _version(world.db) == head
        with world.db.migration.begin() as connection:
            connection.execute(text("DELETE FROM revenue_evidence"))


def test_0022_downgrade_and_upgrade_when_empty(db):
    head = _version(db)
    command.downgrade(CONFIG, "0021_payment_sources")
    try:
        assert "revenue_imports" not in _tables(db)
        assert {"revenue_evidence", "payment_sources"} <= _tables(db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head
