"""Migration 0033_agency_offboarding and the guarded purge function (017-B, D-098 D9 and D12).

Cases OV09 (the function's table list), OV12 (the guard) and OV18 (the upgrade from a populated
0032, the grants and the downgrade that refuses stored rows) of the entry review's verification
matrix, on synthetic data in the disposable database only. The model metadata comparison is
test_tenancy's test_migration_matches_model_metadata and the data policy rows are checked by
test_data_policy_schema.
"""

import re
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from connector_support import make_lab
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import AgencyMembership

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0034_saas_billing"
PREVIOUS = "0032_report_delivery"
NEW_TABLES = ("agency_exports", "agency_export_parts", "agency_purges")
# The plan history and the purge record (017-B D8), and since 017-C (D-103 D10) the agency's
# subscriptions, payments and adjustments, kept as financial records without personal data.
KEPT = {
    "agency_plan_assignments",
    "agency_purges",
    "agency_subscriptions",
    "billing_payments",
    "billing_adjustments",
}
FUNCTION = "purge_agency_batch(uuid, integer)"
REFUSAL = "stored offboarding state"


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


def _value(db, statement: str, **values):
    with db.migration.connect() as connection:
        return connection.execute(text(statement), values).scalar_one()


def _count(db, statement: str, **values) -> int:
    return int(_value(db, statement, **values))


def _owner_membership(db, agency) -> object:
    with Session(db.migration) as session:
        return session.scalar(
            select(AgencyMembership.id).where(
                AgencyMembership.agency_id == agency, AgencyMembership.role == "owner"
            )
        )


# A completed closure: the agency is closed and its closure row completed an hour ago.
def _closed(db, agency) -> None:
    with db.migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agency_closures (id, agency_id, requested_by_membership_id, "
                "requested_at, closes_at, completed_at) VALUES (:id, :agency, :member, "
                "now() - interval '31 days', now() - interval '1 day', now() - interval '1 hour')"
            ),
            {"id": uuid4(), "agency": agency, "member": _owner_membership(db, agency)},
        )
        connection.execute(
            text("UPDATE agencies SET status = 'closed' WHERE id = :agency"), {"agency": agency}
        )


def _record(db, agency, state: str) -> None:
    times = {
        "offboarding": "NULL, NULL, NULL, NULL",
        "waiting": "now(), NULL, NULL, NULL",
        "purging": "now(), now(), now(), NULL",
    }[state]
    with db.migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agency_purges (agency_id, state, closure_requested_at, closes_at, "
                "closure_completed_at, offboarding_completed_at, teardown_settled_at, "
                f"purge_started_at, purge_completed_at) VALUES (:agency, :state, "
                f"now() - interval '31 days', now() - interval '1 day', now(), {times})"
            ),
            {"agency": agency, "state": state},
        )


def _purge(engine, agency, budget=500):
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT purge_agency_batch(:agency, :budget)"),
            {"agency": agency, "budget": budget},
        ).scalar_one()


def _refused(engine, agency, budget=500) -> str:
    with pytest.raises(DBAPIError) as raised:
        _purge(engine, agency, budget)
    assert raised.value.orig.sqlstate == "P0001"
    return raised.value.orig.diag.message_primary


def _rows(db, agency) -> int:
    # Rows of the agency in a few tables the world fixture fills, for "nothing was deleted".
    return sum(
        _count(db, f"SELECT count(*) FROM {table} WHERE agency_id = :a", a=agency)
        for table in ("client_workspaces", "agency_memberships", "client_grants", "audit_events")
    )


def _function_tables(db) -> list[str]:
    with db.migration.connect() as connection:
        definition = connection.execute(
            text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": FUNCTION}
        ).scalar_one()
    order: list[str] = []
    for table in re.findall(r"DELETE FROM public\.(\w+)", definition):
        if table not in order:
            order.append(table)
    return order


def test_ov09_function_covers_every_scoped_table(db):
    order = _function_tables(db)
    with db.migration.connect() as connection:
        scoped = set(
            connection.execute(
                text(
                    "SELECT DISTINCT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name IN ('agency_id', 'client_id')"
                )
            ).scalars()
        )
        references = connection.execute(
            text(
                "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
                "WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
            )
        ).all()
    # Every table that carries agency_id or client_id is purged, except the record that stays.
    assert len(order) == len(set(order)) == 85
    assert set(order) == scoped - KEPT
    assert KEPT <= scoped
    # Children first: a referencing table comes before the table it references.
    position = {table: index for index, table in enumerate(order)}
    for child, parent in references:
        if child in position and parent in position and child != parent:
            assert position[child] < position[parent], (child, parent)
    # Only the two self-referencing tables delete leaves first.
    with db.migration.connect() as connection:
        definition = connection.execute(
            text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": FUNCTION}
        ).scalar_one()
    assert re.findall(r"FROM public\.(\w+) r WHERE", definition) == [
        "identity_merges",
        "identity_subjects",
    ]


def test_ov12_function_refuses_agencies_not_closed_and_offboarded(
    authenticated_world, api, tmp_path, lifecycle_engine
):
    w = authenticated_world
    lab = make_lab(w, api, tmp_path)
    before = _rows(w.db, w.a)
    assert _refused(lifecycle_engine, w.a) == "agency_not_closed"
    for status in ("suspended", "closing"):
        with w.db.migration.begin() as connection:
            connection.execute(
                text("UPDATE agencies SET status = :s WHERE id = :a"), {"s": status, "a": w.a}
            )
        assert _refused(lifecycle_engine, w.a) == "agency_not_closed"
    with w.db.migration.begin() as connection:
        connection.execute(text("UPDATE agencies SET status = 'active' WHERE id = :a"), {"a": w.a})
    assert _rows(w.db, w.a) == before
    # A live connection, and then a teardown before its deadline, both keep a closed agency.
    connection_id = lab.connect("owner_a", w.a, w.a1)
    before = _rows(w.db, w.a)  # the connect added its audit row
    _closed(w.db, w.a)
    assert _refused(lifecycle_engine, w.a) == "offboarding_not_completed"
    _record(w.db, w.a, "offboarding")
    assert _refused(lifecycle_engine, w.a) == "offboarding_not_completed"
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_purges SET state = 'waiting', offboarding_completed_at = now() "
                "WHERE agency_id = :a"
            ),
            {"a": w.a},
        )
    assert _refused(lifecycle_engine, w.a) == "offboarding_not_completed"
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE connector_connections SET status = 'disconnecting', "
                "status_reason = 'agency_closed', disconnect_requested_at = now(), "
                "purge_due_at = now() + interval '72 hours', revocation_status = 'pending', "
                "destruction_status = 'pending', purge_status = 'pending' WHERE id = :c"
            ),
            {"c": connection_id},
        )
    assert _refused(lifecycle_engine, w.a) == "teardown_pending"
    for budget in (0, -1, 10_001):
        assert _refused(lifecycle_engine, w.a, budget) == "invalid_budget"
    # A closed agency without any connection is still refused while its offboarding runs.
    b_before = _rows(w.db, w.b)
    _closed(w.db, w.b)
    _record(w.db, w.b, "offboarding")
    assert _refused(lifecycle_engine, w.b) == "offboarding_not_completed"
    assert _rows(w.db, w.b) == b_before
    # Nothing was deleted by any refused call, and the other agency was never touched.
    assert _rows(w.db, w.a) == before
    assert _value(w.db, "SELECT state FROM agency_purges WHERE agency_id = :a", a=w.a) == "waiting"
    assert _value(w.db, "SELECT state FROM agency_purges WHERE agency_id = :a", a=w.b) == (
        "offboarding"
    )


def test_ov12_lifecycle_role_cannot_delete_tenant_configuration(db, world, lifecycle_engine):
    w = world
    for table in (
        "client_workspaces",
        "agency_memberships",
        "client_grants",
        "managed_links",
        "link_campaigns",
        "audit_events",
        "agency_purges",
        "agency_exports",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with lifecycle_engine.begin() as connection:
                connection.execute(text(f"DELETE FROM {table} WHERE agency_id = :a"), {"a": w.a})
    with pytest.raises(ProgrammingError, match="permission denied"):
        with lifecycle_engine.begin() as connection:
            connection.execute(text("UPDATE agencies SET name = 'x' WHERE id = :a"), {"a": w.a})
    # Only the lifecycle role may call the function; the runtime and PUBLIC may not.
    with pytest.raises(ProgrammingError, match="permission denied"):
        with w.db.runtime.begin() as connection:
            connection.execute(text("SELECT purge_agency_batch(:a, 1)"), {"a": w.a})
    assert _rows(w.db, w.a) > 0


def test_ov18_upgrade_from_populated_0032(world):
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
            assert not connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agencies' AND column_name = 'purged_at')"
                )
            ).scalar_one()
            assert not connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'purge_agency_batch')")
            ).scalar_one()
            with pytest.raises(Exception, match="valid_action"):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO audit_events (id, agency_id, actor_user_id, action, "
                            "resource_type, resource_id) VALUES (:id, :a, :u, "
                            "'agency.export_requested', 'agency', :a)"
                        ),
                        {"id": uuid4(), "a": w.a, "u": w.users.owner_a},
                    )
        command.upgrade(CONFIG, "head")
        assert _version(w.db) == HEAD
        for table, count in before.items():
            assert _count(w.db, f"SELECT count(*) FROM {table}") == count
        for table in NEW_TABLES:
            assert _count(w.db, f"SELECT count(*) FROM {table}") == 0
        assert _count(w.db, "SELECT count(*) FROM agencies WHERE purged_at IS NOT NULL") == 0
        with w.db.migration.connect() as connection:
            security, setting = connection.execute(
                text(
                    "SELECT prosecdef, proconfig FROM pg_proc WHERE oid = CAST(:f AS regprocedure)"
                ),
                {"f": FUNCTION},
            ).one()
            owner = connection.execute(
                text(
                    "SELECT pg_get_userbyid(proowner) FROM pg_proc "
                    "WHERE oid = CAST(:f AS regprocedure)"
                ),
                {"f": FUNCTION},
            ).scalar_one()
            migrator = connection.execute(text("SELECT current_user")).scalar_one()
        assert security is True and owner == migrator
        assert setting == ["search_path=pg_catalog, pg_temp"]
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")


def test_ov18_grants(db):
    app_role, lifecycle = "tracking_app", "tracking_lifecycle"
    for table in NEW_TABLES:
        assert _privilege(db, app_role, table, "SELECT")
        assert _privilege(db, app_role, table, "INSERT")
        assert not _privilege(db, app_role, table, "TRUNCATE")
        assert not _privilege(db, lifecycle, table, "INSERT")
        assert not _privilege(db, lifecycle, table, "UPDATE")
    # Exports: state, outcome and download columns only; the runtime never deletes a row.
    assert not _privilege(db, app_role, "agency_exports", "DELETE")
    for column in (
        "status",
        "error_code",
        "ready_at",
        "revoked_at",
        "part_count",
        "byte_size",
        "row_count",
        "row_counts",
        "manifest_sha256",
        "download_count",
        "last_downloaded_at",
    ):
        assert _privilege(db, app_role, "agency_exports", "UPDATE", column)
    for column in ("id", "agency_id", "requested_by_membership_id", "requested_at", "expires_at"):
        assert not _privilege(db, app_role, "agency_exports", "UPDATE", column)
    assert _privilege(db, app_role, "agency_export_parts", "DELETE")
    assert not _privilege(db, app_role, "agency_export_parts", "UPDATE")
    # Purge records: the runtime moves only offboarding to waiting and writes the summary.
    for column in ("state", "offboarding_completed_at", "export_summary"):
        assert _privilege(db, app_role, "agency_purges", "UPDATE", column)
    for column in (
        "agency_id",
        "teardown_settled_at",
        "purge_started_at",
        "purge_completed_at",
        "deleted_counts",
        "closure_completed_at",
    ):
        assert not _privilege(db, app_role, "agency_purges", "UPDATE", column)
    assert not _privilege(db, app_role, "agency_purges", "DELETE")
    # The lifecycle role reads a purge state and an export expiry, and deletes expired parts.
    for column in ("agency_id", "state"):
        assert _privilege(db, lifecycle, "agency_purges", "SELECT", column)
    for column in ("export_summary", "deleted_counts", "closes_at"):
        assert not _privilege(db, lifecycle, "agency_purges", "SELECT", column)
    for column in ("id", "expires_at"):
        assert _privilege(db, lifecycle, "agency_exports", "SELECT", column)
    for column in ("agency_id", "status", "row_counts", "manifest_sha256"):
        assert not _privilege(db, lifecycle, "agency_exports", "SELECT", column)
    assert _privilege(db, lifecycle, "agency_export_parts", "SELECT", "export_id")
    assert not _privilege(db, lifecycle, "agency_export_parts", "SELECT", "ciphertext")
    assert _privilege(db, lifecycle, "agency_export_parts", "DELETE")
    assert not _privilege(db, lifecycle, "agency_exports", "DELETE")
    assert not _privilege(db, lifecycle, "agency_purges", "DELETE")
    # The agency row: the lifecycle role still reads only the ID and status.
    assert not _privilege(db, lifecycle, "agencies", "SELECT", "purged_at")
    assert not _privilege(db, lifecycle, "agencies", "SELECT", "name")
    assert not _privilege(db, lifecycle, "agencies", "UPDATE", "name")
    with db.migration.connect() as connection:
        execute = {
            role: connection.execute(
                text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                {"r": role, "f": FUNCTION},
            ).scalar_one()
            for role in (app_role, lifecycle)
        }
        public = connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_proc, aclexplode(proacl) AS item "
                "WHERE oid = CAST(:f AS regprocedure) AND item.grantee = 0)"
            ),
            {"f": FUNCTION},
        ).scalar_one()
    assert execute == {app_role: False, lifecycle: True}
    assert public is False


def test_ov18_downgrade_refuses_stored_rows(world):
    w = world
    values = {"agency": w.a, "client": w.a1, "member": w.owner_a, "user": w.users.owner_a}
    export = (
        "INSERT INTO agency_exports (id, agency_id, requested_by_membership_id, expires_at) "
        "VALUES (:export, :agency, :member, now() + interval '7 days')"
    )
    ready = (
        "UPDATE agency_exports SET status = 'ready', ready_at = now(), part_count = 1, "
        "byte_size = 10, row_count = 0, row_counts = '{}'::jsonb, "
        "manifest_sha256 = repeat('a', 64) WHERE id = :export"
    )
    part = (
        "INSERT INTO agency_export_parts (export_id, part, agency_id, kek_id, wrap_nonce, "
        "wrapped_dek, nonce, ciphertext, alg, aad_version) VALUES (:export, 1, :agency, 'k1', "
        "decode(repeat('00', 12), 'hex'), decode(repeat('00', 48), 'hex'), "
        "decode(repeat('00', 12), 'hex'), decode(repeat('00', 26), 'hex'), 'A256GCM-ENV-v1', 1)"
    )
    stored = [
        ([export], "DELETE FROM agency_exports"),
        ([export, ready, part], "DELETE FROM agency_export_parts; DELETE FROM agency_exports"),
        (
            [
                "UPDATE agencies SET status = 'closed' WHERE id = :agency",
                "INSERT INTO agency_purges (agency_id, state, closure_requested_at, closes_at, "
                "closure_completed_at) VALUES (:agency, 'offboarding', now() - interval '2 days', "
                "now() - interval '1 day', now())",
            ],
            "DELETE FROM agency_purges; UPDATE agencies SET status = 'active'",
        ),
        (
            ["UPDATE agencies SET status = 'closed', purged_at = now() WHERE id = :agency"],
            "UPDATE agencies SET status = 'active', purged_at = NULL",
        ),
        (
            [
                "INSERT INTO connector_connections (id, agency_id, client_id, provider, "
                "external_account_id, status, status_reason, created_by_membership_id) VALUES "
                "(:export, :agency, :client, 'synthetic', 'syn-acct-1', 'active', "
                "'agency_closed', :member)"
            ],
            "DELETE FROM connector_connections",
        ),
        (
            [
                "INSERT INTO report_exports (id, agency_id, client_id, family, parameters, "
                "period_start, period_end, includes_financials, source, "
                "requested_by_membership_id, status, revoked_at, revoked_reason, stored_at, "
                "expires_at) VALUES (:export, :agency, :client, 'revenue', '{}'::jsonb, "
                "'2026-11-01', '2026-11-03', true, 'manual', :member, 'revoked', now(), "
                "'agency_closed', now(), now() + interval '1 day')"
            ],
            "DELETE FROM report_exports",
        ),
        (
            [
                "INSERT INTO audit_events (id, agency_id, actor_user_id, action, "
                "resource_type, resource_id) VALUES (:export, :agency, :user, "
                "'agency.export_requested', 'agency_export', :export)"
            ],
            "DELETE FROM audit_events WHERE action = 'agency.export_requested'",
        ),
    ]
    try:
        for statements, cleanup in stored:
            identifiers = {"export": uuid4()}
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
