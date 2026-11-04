"""Run migrations with separate credentials; never put passwords in alembic.ini."""

from alembic import context

from app import models  # noqa: F401 -- Register all approved model metadata.
from app.config import MigrationSettings
from app.database import Base, create_database_engine
from app.logging_config import configure_logging

# Alembic imports this module for every command. Settings use the dedicated migrator role, and
# the shared metadata lets autogenerate/comparison see every registered model.
configure_logging()
settings = MigrationSettings()
target_metadata = Base.metadata


# Offline mode renders SQL with literal binds instead of connecting; used to review scripts.
def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Online mode connects with the bounded migrator engine, runs pending revisions in one
# transaction per Alembic invocation, and always disposes of the engine afterward.
def run_migrations_online() -> None:
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
