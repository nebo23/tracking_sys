"""Migration 0032_report_delivery on disposable PostgreSQL (specification 016-C, D-095 D12,
RV18): the upgrade from a populated 0031, the grants of D12 and the downgrade that refuses
stored rows. The model metadata comparison is test_tenancy's test_migration_matches_model_metadata
and the data policy rows are checked by test_data_policy_schema.
"""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import BACKEND_ROOT

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0033_agency_offboarding"
PREVIOUS = "0031_saas_plans"
NEW_TABLES = (
    "report_exports",
    "report_export_contents",
    "report_schedules",
    "report_schedule_recipients",
    "agency_branding",
)
REFUSAL = "stored export, schedule or branding state"


def _version(db) -> str:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _privilege(db, role, table, privilege, column=None) -> bool:
    with db.migration.connect() as connection:
        if column is None:
            return connection.execute(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            ).scalar_one()
        return connection.execute(
            text("SELECT has_column_privilege(:r, :t, :c, :p)"),
            {"r": role, "t": table, "c": column, "p": privilege},
        ).scalar_one()


def _count(db, statement: str) -> int:
    with db.migration.connect() as connection:
        return connection.execute(text(statement)).scalar_one()


def test_rv18_upgrade_from_populated_0031(world):
    w = world
    assert _version(w.db) == HEAD
    before = {
        table: _count(w.db, f"SELECT count(*) FROM {table}")
        for table in ("agencies", "client_workspaces", "agency_memberships", "audit_events")
    }
    command.downgrade(CONFIG, PREVIOUS)
    try:
        with w.db.migration.begin() as connection:
            present = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
            assert present.isdisjoint(NEW_TABLES)
            with pytest.raises(Exception, match="valid_purpose"):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
                            "VALUES (:id, 'report_ready', 'synthetic')"
                        ),
                        {"id": uuid4()},
                    )
            connection.execute(
                text(
                    "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
                    "VALUES (:id, 'invitation', 'synthetic')"
                ),
                {"id": uuid4()},
            )
        command.upgrade(CONFIG, "head")
        assert _version(w.db) == HEAD
        for table, count in before.items():
            assert _count(w.db, f"SELECT count(*) FROM {table}") == count
        assert _count(w.db, "SELECT count(*) FROM mail_outbox WHERE purpose = 'invitation'") == 1
        for table in NEW_TABLES:
            assert _count(w.db, f"SELECT count(*) FROM {table}") == 0
        with w.db.migration.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
                    "VALUES (:id, 'report_ready', 'synthetic')"
                ),
                {"id": uuid4()},
            )
            connection.execute(text("DELETE FROM mail_outbox"))
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")


def test_rv18_grants(db):
    app_role, lifecycle = "tracking_app", "tracking_lifecycle"
    for table in NEW_TABLES:
        assert _privilege(db, app_role, table, "SELECT")
        assert _privilege(db, app_role, table, "INSERT")
        assert not _privilege(db, app_role, table, "TRUNCATE")
        assert not _privilege(db, lifecycle, table, "INSERT")
        assert not _privilege(db, lifecycle, table, "UPDATE")
    # Exports: state, store and download columns only; rows are never deleted by the runtime.
    assert not _privilege(db, app_role, "report_exports", "DELETE")
    for column in (
        "status",
        "revoked_at",
        "revoked_reason",
        "stored_at",
        "row_count",
        "byte_size",
        "report_revision",
        "download_count",
        "last_downloaded_at",
    ):
        assert _privilege(db, app_role, "report_exports", "UPDATE", column)
    for column in (
        "agency_id",
        "client_id",
        "family",
        "parameters",
        "connection_id",
        "period_start",
        "includes_financials",
        "source",
        "schedule_id",
        "requested_by_membership_id",
        "created_at",
        "expires_at",
    ):
        assert not _privilege(db, app_role, "report_exports", "UPDATE", column)
    assert _privilege(db, app_role, "report_export_contents", "DELETE")
    assert not _privilege(db, app_role, "report_export_contents", "UPDATE")
    for table in ("report_schedules", "report_schedule_recipients"):
        assert _privilege(db, app_role, table, "DELETE")
    for column in ("name", "status", "next_run_at", "owner_membership_id", "last_error_code"):
        assert _privilege(db, app_role, "report_schedules", "UPDATE", column)
    for column in ("id", "agency_id", "client_id", "family", "created_at"):
        assert not _privilege(db, app_role, "report_schedules", "UPDATE", column)
    assert not _privilege(db, app_role, "report_schedule_recipients", "UPDATE")
    for column in ("display_name", "accent_color", "logo", "logo_width", "logo_height"):
        assert _privilege(db, app_role, "agency_branding", "UPDATE", column)
    assert not _privilege(db, app_role, "agency_branding", "UPDATE", "agency_id")
    assert not _privilege(db, app_role, "agency_branding", "DELETE")
    # The lifecycle role reads only the expiry columns and deletes exports and contents.
    for column in ("id", "status", "created_at", "expires_at"):
        assert _privilege(db, lifecycle, "report_exports", "SELECT", column)
    for column in ("agency_id", "client_id", "parameters", "family", "report_revision"):
        assert not _privilege(db, lifecycle, "report_exports", "SELECT", column)
    assert _privilege(db, lifecycle, "report_exports", "DELETE")
    assert _privilege(db, lifecycle, "report_export_contents", "SELECT", "export_id")
    assert not _privilege(db, lifecycle, "report_export_contents", "SELECT", "ciphertext")
    assert _privilege(db, lifecycle, "report_export_contents", "DELETE")
    for table in ("report_schedules", "report_schedule_recipients", "agency_branding"):
        assert not _privilege(db, lifecycle, table, "SELECT")
        assert not _privilege(db, lifecycle, table, "DELETE")


SCHEDULE = (
    "INSERT INTO report_schedules (id, agency_id, client_id, name, family, parameters, "
    "cadence, hour, time_zone, owner_membership_id, next_run_at) VALUES (:schedule, :agency, "
    ":client, 'Synthetic schedule', 'revenue', '{}'::jsonb, 'daily', 6, 'UTC', :member, now())"
)
EXPORT = (
    "INSERT INTO report_exports (id, agency_id, client_id, family, parameters, period_start, "
    "period_end, includes_financials, source, requested_by_membership_id, status, expires_at) "
    "VALUES (:export, :agency, :client, 'revenue', '{}'::jsonb, '2026-11-01', '2026-11-03', "
    "true, 'manual', :member, 'pending', now() + interval '1 day')"
)


def test_rv18_downgrade_refuses_stored_rows(world):
    w = world
    values = {"agency": w.a, "client": w.a1, "member": w.owner_a, "user": w.users.owner_a}
    stored = [
        ([SCHEDULE], "DELETE FROM report_schedules"),
        (
            [
                SCHEDULE,
                "INSERT INTO report_schedule_recipients (schedule_id, membership_id, agency_id, "
                "client_id) VALUES (:schedule, :member, :agency, :client)",
            ],
            "DELETE FROM report_schedules",
        ),
        ([EXPORT], "DELETE FROM report_exports"),
        (
            [
                EXPORT,
                "UPDATE report_exports SET status = 'ready', stored_at = now(), row_count = 1, "
                "byte_size = 10, report_revision = repeat('a', 64)",
                "INSERT INTO report_export_contents (export_id, agency_id, client_id, kek_id, "
                "wrap_nonce, wrapped_dek, nonce, ciphertext, alg, aad_version) VALUES (:export, "
                ":agency, :client, 'k1', decode(repeat('00', 12), 'hex'), "
                "decode(repeat('00', 48), 'hex'), decode(repeat('00', 12), 'hex'), "
                "decode(repeat('00', 26), 'hex'), 'A256GCM-ENV-v1', 1)",
            ],
            "DELETE FROM report_export_contents; DELETE FROM report_exports",
        ),
        (
            [
                "INSERT INTO agency_branding (agency_id, display_name, accent_color, "
                "updated_by_membership_id) VALUES (:agency, 'Synthetic', '#112233', :member)"
            ],
            "DELETE FROM agency_branding",
        ),
        (
            [
                "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
                "VALUES (:export, 'report_ready', 'synthetic')"
            ],
            "DELETE FROM mail_outbox WHERE purpose = 'report_ready'",
        ),
        (
            [
                "INSERT INTO audit_events (id, agency_id, actor_user_id, action, "
                "resource_type, resource_id) VALUES (:export, :agency, :user, "
                "'branding.updated', 'agency_branding', :agency)"
            ],
            "DELETE FROM audit_events WHERE action = 'branding.updated'",
        ),
    ]
    try:
        for statements, cleanup in stored:
            identifiers = {"schedule": uuid4(), "export": uuid4()}
            with w.db.migration.begin() as connection:
                for statement in statements:
                    connection.execute(text(statement), {**values, **identifiers})
            with pytest.raises(RuntimeError, match=REFUSAL):
                command.downgrade(CONFIG, PREVIOUS)
            assert _version(w.db) == HEAD
            with w.db.migration.begin() as connection:
                for statement in cleanup.split("; "):
                    connection.execute(text(statement))
        command.downgrade(CONFIG, PREVIOUS)
        assert _version(w.db) == PREVIOUS
        with w.db.migration.connect() as connection:
            present = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert present.isdisjoint(NEW_TABLES)
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD
