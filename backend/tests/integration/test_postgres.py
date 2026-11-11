"""Run only against an explicitly enabled disposable foundation database."""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.config import BACKEND_ROOT, Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_postgresql_migration_cycle_and_runtime_permissions(
    database_settings: Settings, migration_engine: Engine
) -> None:
    try:
        with migration_engine.connect() as connection:
            tables = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
            assert tables <= {
                "alembic_version",
                "agencies",
                "users",
                "agency_memberships",
                "client_workspaces",
                "client_grants",
                "audit_events",
                "password_credentials",
                "auth_sessions",
                "auth_tokens",
                "auth_rate_limits",
                "security_events",
                "mail_outbox",
                "agency_invitations",
                "invitation_client_grants",
                "service_credentials",
                "service_client_grants",
                "external_identities",
                "oauth_transactions",
                "verification_challenges",
                "ingestion_sources",
                "ingestion_source_secrets",
                "collection_forms",
                "collection_subjects",
                "consent_records",
                "collected_events",
                "event_diagnostics",
                "deletion_requests",
                "deletion_tombstones",
                "link_campaigns",
                "link_content_references",
                "link_utm_templates",
                "link_destination_origins",
                "link_domains",
                "managed_links",
            }, "Refuse an unknown database schema."
            for table in tables - {"alembic_version"}:
                assert not connection.execute(
                    text(f"SELECT EXISTS (SELECT 1 FROM {table})")
                ).scalar_one(), "Refuse to downgrade a populated database."
            version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
            assert 180000 <= version < 190000

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.downgrade(config, "base")

        with TestClient(create_app(database_settings)) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 503

            command.upgrade(config, "head")
            command.upgrade(config, "head")
            assert client.get("/health/ready").status_code == 200

            with client.app.state.engine.connect() as connection:
                role = connection.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                ).one()
                assert tuple(role) == (False, False, False, False)
                assert (
                    connection.execute(
                        text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
                    ).scalar_one()
                    is False
                )
                assert (
                    connection.execute(
                        text(
                            "SELECT has_table_privilege(current_user, 'alembic_version', 'UPDATE')"
                        )
                    ).scalar_one()
                    is False
                )

            with pytest.raises(DBAPIError):
                with client.app.state.engine.begin() as connection:
                    connection.execute(text("UPDATE alembic_version SET version_num = 'tampered'"))

            command.downgrade(config, "base")
            assert client.get("/health/ready").status_code == 503
            command.upgrade(config, "head")
            assert client.get("/health/ready").status_code == 200
    finally:
        migration_engine.dispose()
