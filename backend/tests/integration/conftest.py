"""Safety guards and synthetic fixtures for the disposable PostgreSQL service."""

import os
import re
from collections.abc import Iterator
from contextlib import ExitStack
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, LifecycleSettings, MigrationSettings, Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AgencyMembership, PasswordCredential, User
from app.security import now_utc, password_hash
from app.services.mail import process_mail
from app.services.tenancy import Role, tenancy_transaction

TABLES = (
    "audit_events",
    "security_events",
    "external_identities",
    "oauth_transactions",
    "verification_challenges",
    "service_client_grants",
    "invitation_client_grants",
    "service_credentials",
    "agency_invitations",
    "auth_tokens",
    "auth_sessions",
    "password_credentials",
    "mail_outbox",
    "auth_rate_limits",
    "client_grants",
    "agency_memberships",
    "client_workspaces",
    "users",
    "agencies",
)

TEST_PASSWORD = "Synthetic password for tests 123!"


@pytest.fixture(scope="session")
def test_password_hash() -> str:
    return password_hash.hash(TEST_PASSWORD)


@pytest.fixture
def api(db, database_settings, tmp_path: Path):
    config = database_settings.model_copy(
        update={
            "cookie_secure": False,
            "mail_directory": tmp_path / "mail",
            "login_attempts_per_minute": 100,
            "auth_requests_per_minute": 1000,
        }
    )
    with ExitStack() as stack:

        def new_client(settings=None):
            return stack.enter_context(
                TestClient(
                    create_app(settings or config),
                    base_url="http://localhost:8000",
                    headers={"Origin": "http://localhost:8000"},
                )
            )

        def mail_tokens():
            assert process_mail(db.runtime, config)["failed"] == 0
            tokens = []
            for path in sorted(
                config.mail_directory.glob("*.eml"), key=lambda p: p.stat().st_mtime_ns
            ):
                message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
                body = message.get_body().get_content()
                token = re.search(r"#token=([A-Za-z0-9_-]+)|verification code: ([0-9]{6})", body)
                assert token is not None
                value = token.group(1) or token.group(2)
                tokens.append((str(message["To"]), str(message["Subject"]), value))
            return tokens

        def login(client, email, password=TEST_PASSWORD):
            response = client.post("/auth/login", json={"email": email, "password": password})
            assert response.status_code == 200, response.text
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            return response

        yield SimpleNamespace(
            client=new_client(),
            new_client=new_client,
            config=config,
            mail_tokens=mail_tokens,
            login=login,
            password=TEST_PASSWORD,
        )


@pytest.fixture
def authenticated_world(world, api, test_password_hash):
    with Session(world.db.migration) as session, session.begin():
        session.add_all(
            [
                PasswordCredential(user_id=identifier, password_hash=test_password_hash)
                for identifier in vars(world.users).values()
            ]
        )

    def signed_in(name):
        client = api.new_client()
        api.login(client, f"{name}@example.test")
        return client

    world.signed_in = signed_in
    return world


@pytest.fixture(scope="session")
def database_settings() -> Settings:
    if os.environ.get("TRACKING_RUN_DB_TESTS") != "1":
        pytest.skip("Set TRACKING_RUN_DB_TESTS=1 for the disposable database.")
    config = Settings()
    if config.database_name != "tracking_foundation_test" or config.database_port != 55433:
        pytest.fail("Integration tests require tracking_foundation_test on port 55433.")
    if config.database_host != "127.0.0.1":
        pytest.fail("Integration tests require the local disposable PostgreSQL service.")
    return config


@pytest.fixture(scope="session")
def migration_engine(database_settings: Settings) -> Iterator[Engine]:
    config = MigrationSettings()
    assert (config.database_host, config.database_port, config.database_name) == (
        database_settings.database_host,
        database_settings.database_port,
        database_settings.database_name,
    )
    engine = create_database_engine(config)
    try:
        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                ).scalars()
            )
            assert tables <= set(TABLES) | {"alembic_version"}, "Unexpected test database schema."
            for table in tables - {"alembic_version"}:
                assert not connection.execute(
                    text(f"SELECT EXISTS (SELECT 1 FROM {table})")
                ).scalar_one(), "Refuse a prepopulated database; use fresh disposable storage."
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def lifecycle_settings(database_settings: Settings, tmp_path_factory) -> LifecycleSettings:
    config = LifecycleSettings()
    assert (config.database_host, config.database_port, config.database_name) == (
        database_settings.database_host,
        database_settings.database_port,
        database_settings.database_name,
    )
    assert config.database_user == "tracking_lifecycle"
    # Never point mail cleanup at the workspace's own local-data/mail captures.
    return config.model_copy(update={"mail_directory": tmp_path_factory.mktemp("lifecycle-mail")})


@pytest.fixture(scope="session")
def lifecycle_engine(
    lifecycle_settings: LifecycleSettings, migration_engine: Engine
) -> Iterator[Engine]:
    engine = create_database_engine(lifecycle_settings, pool_size=2)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def runtime_engine(database_settings: Settings, migration_engine: Engine) -> Iterator[Engine]:
    engine = create_database_engine(database_settings)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(runtime_engine: Engine, migration_engine: Engine) -> Iterator[SimpleNamespace]:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    try:
        yield SimpleNamespace(runtime=runtime_engine, migration=migration_engine)
    finally:
        # Only data created in this explicitly guarded, initially empty test run is removed.
        with migration_engine.begin() as connection:
            for table in TABLES:
                connection.execute(text(f"DELETE FROM {table}"))


@pytest.fixture
def world(db: SimpleNamespace) -> SimpleNamespace:
    names = ("owner_a", "owner_b", "admin", "analyst", "viewer", "outsider", "second_owner")
    with Session(db.migration, expire_on_commit=False) as session, session.begin():
        users = {
            name: User(
                email_normalized=f"{name}@example.test",
                display_name=name,
                email_verified_at=now_utc(),
            )
            for name in names
        }
        session.add_all(users.values())
        session.flush()
        ids = {name: user.id for name, user in users.items()}
    with tenancy_transaction(db.runtime, ids["owner_a"]) as service:
        agency_a = service.create_agency("Synthetic Agency A")
        a1 = service.create_client(agency_a.id, "Synthetic Client A1")
        a2 = service.create_client(agency_a.id, "Synthetic Client A2")
        admin = service.add_member(agency_a.id, ids["admin"], Role.ADMIN)
        analyst = service.add_member(agency_a.id, ids["analyst"], Role.ANALYST)
        viewer = service.add_member(agency_a.id, ids["viewer"], Role.CLIENT_VIEWER)
        service.grant_client(agency_a.id, a1.id, analyst.id)
        service.grant_client(agency_a.id, a1.id, viewer.id)
        owner_a = service.session.scalar(
            select(AgencyMembership).where(
                AgencyMembership.agency_id == agency_a.id,
                AgencyMembership.user_id == ids["owner_a"],
            )
        )
        assert owner_a is not None
    with tenancy_transaction(db.runtime, ids["owner_b"]) as service:
        agency_b = service.create_agency("Synthetic Agency B")
        b1 = service.create_client(agency_b.id, "Synthetic Client B1")
        b2 = service.create_client(agency_b.id, "Synthetic Client B2")
        other_member = service.add_member(agency_b.id, ids["outsider"], Role.CLIENT_VIEWER)
        service.grant_client(agency_b.id, b2.id, other_member.id)
        service.add_member(agency_b.id, ids["analyst"], Role.ADMIN)
    return SimpleNamespace(
        db=db,
        users=SimpleNamespace(**ids),
        a=agency_a.id,
        b=agency_b.id,
        a1=a1.id,
        a2=a2.id,
        b1=b1.id,
        b2=b2.id,
        owner_a=owner_a.id,
        admin=admin.id,
        analyst=analyst.id,
        viewer=viewer.id,
        other_member=other_member.id,
    )
