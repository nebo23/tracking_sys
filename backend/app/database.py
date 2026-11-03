"""Bounded PostgreSQL connections and schema-aware readiness checks."""

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase

from app.config import BACKEND_ROOT, DatabaseSettings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def create_database_engine(settings: DatabaseSettings, *, pool_size: int = 5) -> Engine:
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=2,
        hide_parameters=True,
        connect_args={
            "connect_timeout": settings.database_connect_timeout,
            "options": (
                f"-c statement_timeout={settings.database_statement_timeout_ms} "
                "-c lock_timeout=3000 -c timezone=UTC"
            ),
        },
    )


def expected_revision() -> str:
    revision = ScriptDirectory(str(BACKEND_ROOT / "migrations")).get_current_head()
    if revision is None:
        raise RuntimeError("The migration baseline is missing.")
    return revision


def readiness_failure(engine: Engine, revision: str) -> str | None:
    database_reached = False
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database_reached = True
            revisions = set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
            if revisions != {revision}:
                return "schema_mismatch"
    except SQLAlchemyError:
        # Deliberately omit database exception text, URLs, and credentials from diagnostics.
        return "schema_unavailable" if database_reached else "database_unavailable"
    return None
