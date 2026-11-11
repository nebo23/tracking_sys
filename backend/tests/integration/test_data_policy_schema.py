"""Data-class registry against the migrated disposable PostgreSQL schema."""

import pytest
from sqlalchemy import text

from app.data_policy import registry_problems

pytestmark = pytest.mark.integration


def test_migrated_schema_matches_registry(db):
    with db.migration.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )
        ).all()
        references = connection.execute(
            text(
                "SELECT c.conrelid::regclass::text, a.attname "
                "FROM pg_constraint c "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
                "WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace "
                "AND c.confrelid = 'public.users'::regclass AND cardinality(c.conkey) = 1"
            )
        ).all()
    schema: dict[str, list[str]] = {}
    for table, column in columns:
        schema.setdefault(table, []).append(column)
    assert len(schema) == 35
    assert len(references) == 10
    assert registry_problems(schema, [tuple(row) for row in references]) == []
