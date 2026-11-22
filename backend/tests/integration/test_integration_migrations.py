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
from app.models import CrmStageRule, IntegrationSource, WhatsappNumber

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
            "amount_at",
            "payment_reference",
            "payment_reference_at",
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
        "bookings": ("id", "updated_at", "client_id", "subject_id"),
        "crm_deals": ("id", "updated_at"),
    }
    for table, columns in lifecycle.items():
        assert _privilege(db, "tracking_lifecycle", table, "DELETE"), table
        for column in columns:
            assert _privilege(db, "tracking_lifecycle", table, "SELECT", column), (table, column)
    # R002 (D-070): the lifecycle role clears a booking's link columns together and nothing else.
    for column in ("subject_id", "linked_at"):
        assert _privilege(db, "tracking_lifecycle", "bookings", "UPDATE", column), column
    for column in ("status", "start_at", "updated_at", "client_id", "provider", "event_type_ref"):
        assert not _privilege(db, "tracking_lifecycle", "bookings", "UPDATE", column), column
    for column in ("start_at", "end_at", "event_type_ref", "status", "linked_at"):
        assert not _privilege(db, "tracking_lifecycle", "bookings", "SELECT", column), column
    assert not _privilege(db, "tracking_lifecycle", "booking_events", "UPDATE")
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
        assert not _tables(db) & {
            *BOOKING_TABLES,
            *CRM_TABLES,
            "whatsapp_numbers",
            "whatsapp_messages",
        }
        assert "revenue_imports" in _tables(db)
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head


def test_0025_privileges_and_downgrade(world):
    db = world.db
    for table in ("whatsapp_numbers", "whatsapp_messages"):
        for privilege in ("SELECT", "INSERT"):
            assert _privilege(db, "tracking_app", table, privilege), (table, privilege)
        for privilege in ("DELETE", "TRUNCATE"):
            assert not _privilege(db, "tracking_app", table, privilege), (table, privilege)
    for column in ("name", "status", "verified_at", "updated_at"):
        assert _privilege(db, "tracking_app", "whatsapp_numbers", "UPDATE", column)
    for column in ("phone_number_id", "client_id", "created_by_membership_id"):
        assert not _privilege(db, "tracking_app", "whatsapp_numbers", "UPDATE", column), column
    assert not _privilege(db, "tracking_app", "whatsapp_messages", "UPDATE")
    assert _privilege(db, "tracking_lifecycle", "whatsapp_messages", "DELETE")
    for column in ("id", "received_at"):
        assert _privilege(db, "tracking_lifecycle", "whatsapp_messages", "SELECT", column)
    assert not _privilege(db, "tracking_lifecycle", "whatsapp_messages", "SELECT", "source_id")
    assert not _privilege(db, "tracking_lifecycle", "whatsapp_numbers", "DELETE")
    head = _version(db)
    with Session(db.migration) as session, session.begin():
        session.add(
            WhatsappNumber(
                id=uuid4(),
                agency_id=world.a,
                client_id=world.a1,
                phone_number_id="106540352242922",
                name="Synthetic",
                status="pending",
                created_by_membership_id=world.owner_a,
            )
        )
    with pytest.raises(RuntimeError, match="Refuse to remove WhatsApp state"):
        command.downgrade(CONFIG, "0024_crm_deals")
    assert _version(db) == head


# --- D-070: the in-place amendments upgrade a populated predecessor database ----------------

PREDECESSOR_TABLES = (
    "agencies",
    "client_workspaces",
    "agency_memberships",
    "users",
    "audit_events",
    "collection_subjects",
    "consent_records",
)


def _counts(db, tables) -> dict[str, int]:
    with db.migration.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in tables
        }


def test_amended_migrations_upgrade_a_populated_predecessor_database(world):
    # D-070 amended 0021 and 0023 to 0025 in place. From a database at 0019_meta_providers that
    # holds tenancy, audit, subject and consent rows, the amended revisions upgrade to head
    # without touching that data, and their new columns, constraints and grants apply at once.
    from app.privacy.consent import ConsentSource, ConsentState, Purpose
    from app.services.collection import record_consent

    db = world.db
    head = _version(db)
    with Session(db.runtime) as session, session.begin():
        record_consent(
            session,
            world.a,
            world.a1,
            source=ConsentSource.API,
            notice_sha256="a" * 64,
            choices={Purpose.ATTRIBUTION: ConsentState.GRANTED},
            subject_token=None,
            captured_at=None,
            recheck=lambda: None,
        )
    command.downgrade(CONFIG, "0019_meta_providers")
    try:
        assert _version(db) == "0019_meta_providers"
        assert "payment_sources" not in _tables(db) and "bookings" not in _tables(db)
        before = _counts(db, PREDECESSOR_TABLES)
        assert before["collection_subjects"] == 1 and before["agencies"] == 2
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(db) == head
    assert _counts(db, PREDECESSOR_TABLES) == before
    with db.migration.connect() as connection:
        columns = {
            (table, column)
            for table, column in connection.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND (table_name, column_name) IN ("
                    "('payment_sources', 'live_integration_ids'), ('bookings', 'source_id'), "
                    "('booking_events', 'source_id'), ('crm_deals', 'amount_at'), "
                    "('crm_deals', 'payment_reference_at'), ('whatsapp_numbers', 'verified_at'))"
                )
            )
        }
        indexes = set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'whatsapp_numbers' "
                    "AND indexname IN ('uq_whatsapp_numbers_verified', 'uq_whatsapp_numbers_claim')"
                )
            ).scalars()
        )
    assert len(columns) == 6 and len(indexes) == 2
    assert _privilege(db, "tracking_lifecycle", "bookings", "UPDATE", "linked_at")
    assert _privilege(db, "tracking_app", "payment_sources", "UPDATE", "live_integration_ids")
    # A pending claim is the registration default on the upgraded schema.
    with Session(db.migration) as session, session.begin():
        claim = WhatsappNumber(
            id=uuid4(),
            agency_id=world.a,
            client_id=world.a1,
            phone_number_id="106540352242955",
            name="Synthetic",
            created_by_membership_id=world.owner_a,
        )
        session.add(claim)
        session.flush()
        session.refresh(claim)
        assert (claim.status, claim.verified_at) == ("pending", None)
