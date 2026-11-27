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
    # 014-A adds ad_accounts, ad_objects and ad_spend_facts (0017); 014-B adds the
    # destination, delivery and acknowledgement tables (0018); 015-A adds revenue_evidence
    # (0020), 015-B the payment source, secret and diagnostic tables (0021) and 015-C
    # revenue_imports (0022); 015-D the integration, booking and CRM tables (0023, 0024);
    # 015-E the WhatsApp tables (0025); 006 the eleven identity tables (0026, D-075); 007-B the
    # five ledger tables (0027); 007-C revenue_identity_bindings (0028); 008-B the six
    # attribution tables (0029); 017-A the plan, assignment, closure and agreement tables
    # (0031), whose user_agreements.user_id is the eleventh single-column user reference;
    # 016-C the export, content, schedule, recipient and branding tables (0032).
    assert len(schema) == 96
    assert len(references) == 11
    assert registry_problems(schema, [tuple(row) for row in references]) == []
