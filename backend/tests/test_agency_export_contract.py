"""The offboarding export catalog against the mapped metadata (017-B, D-098 D4; OV02).

The catalog is an allowlist: each exported table lists its exported columns and the module
names every other column of the table as excluded, so a new column is never exported before it
is reviewed. Every table that carries agency_id or client_id is either exported or excluded
with the reason recorded in design-017b.md section 1.2.
"""

import re

from sqlalchemy import LargeBinary

import app.models  # noqa: F401  (registers every mapped table)
from app.database import Base
from app.privacy.token_secrets import AAD_VERSION, ALGORITHM
from app.services import agency_exports

TABLES = Base.metadata.tables
SCOPED = {
    name
    for name, table in TABLES.items()
    if {"agency_id", "client_id"} & {column.name for column in table.columns}
}
# The reviewed exclusions of design-017b.md section 1.2 (provider data and state, secrets,
# keys, digests and tokens, the audit log, erasure records, diagnostics and processing state,
# earlier report files, agency administration, and the export and purge rows themselves).
EXCLUDED_TABLES = {
    "agency_export_parts",
    "agency_exports",
    "agency_purges",
    "report_export_contents",
    "report_exports",
    "agency_branding",
    "agency_closures",
    "agency_plan_assignments",
    "attribution_consumer_state",
    "ledger_projection_state",
    "identity_erasure_holds",
    "identity_changes",
    "identity_feed_state",
    "identity_handoffs",
    "identity_assertion_receipts",
    "identity_assertions",
    "identity_keys",
    "identity_key_secrets",
    "integration_deliveries",
    "integration_source_secrets",
    "revenue_imports",
    "payment_callback_diagnostics",
    "payment_source_secrets",
    "conversion_acknowledgements",
    "conversion_deliveries",
    "conversion_destinations",
    "ad_spend_facts",
    "ad_objects",
    "ad_accounts",
    "connector_records",
    "connector_usage_records",
    "connector_checkpoints",
    "connector_sync_runs",
    "connector_token_secrets",
    "connector_oauth_transactions",
    "connector_connections",
    "deletion_tombstones",
    "deletion_requests",
    "event_diagnostics",
    "ingestion_source_secrets",
    "audit_events",
    "service_client_grants",
    "invitation_client_grants",
    "service_credentials",
    "agency_invitations",
    "client_grants",
    "agency_memberships",
}
DIGEST = re.compile(r"digest|sha256|fingerprint|secret|token|key_bytes|ciphertext|public_key")


def test_every_scoped_table_is_exported_or_excluded():
    exported = [table for table, _ in agency_exports.CATALOG]
    assert len(exported) == len(set(exported)) == 36
    assert set(exported) | EXCLUDED_TABLES == SCOPED
    assert set(exported).isdisjoint(EXCLUDED_TABLES)
    assert exported[0] == "client_workspaces"


def test_each_exported_table_lists_or_excludes_every_column():
    for table, columns in agency_exports.CATALOG:
        names = [column.name for column in TABLES[table].columns]
        excluded = agency_exports.EXCLUDED_COLUMNS.get(table, ())
        assert len(columns) == len(set(columns)), table
        assert set(columns) | set(excluded) == set(names), table
        assert set(columns).isdisjoint(excluded), table
    assert set(agency_exports.EXCLUDED_COLUMNS) <= {table for table, _ in agency_exports.CATALOG}


def test_no_binary_digest_key_or_token_column_is_exported():
    for table, columns in agency_exports.CATALOG:
        for name in columns:
            column = TABLES[table].columns[name]
            assert not isinstance(column.type, LargeBinary), (table, name)
            assert not DIGEST.search(name), (table, name)
    # Every excluded column is a digest, a keyed digest or a routing key.
    excluded = {name for names in agency_exports.EXCLUDED_COLUMNS.values() for name in names}
    assert all(DIGEST.search(name) or name in {"slot_key", "conversion_key"} for name in excluded)


def test_a_part_is_bound_to_its_agency_export_and_number():
    from uuid import uuid4

    agency, export = uuid4(), uuid4()
    first = agency_exports.seal_context(agency, export, 1)
    assert (first.kind, first.version, first.secret_id) == ("agency_export", 1, export)
    assert agency_exports.seal_context(agency, export, 2) != first
    assert agency_exports.seal_context(uuid4(), export, 1) != first
    assert (ALGORITHM, AAD_VERSION) == ("A256GCM-ENV-v1", 1)
    # The bounds stay within the 0033 checks: 64 parts of 8 MiB hold 512 MiB.
    assert agency_exports.MAX_BYTES <= 64 * agency_exports.PART_BYTES
    assert agency_exports.PART_BYTES == 8 * 1024 * 1024
    assert agency_exports.MAX_ROWS == 2_000_000
