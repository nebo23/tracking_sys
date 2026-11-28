"""008-B schema, grants and model versions on disposable PostgreSQL (D-079, AV14 and AV19).

AV14: a populated database at 0028 upgrades to 0029 and keeps its rows; the downgrade refuses
stored attribution rows and new audit values, and leaves the version at head; the runtime role
inserts and reads attribution rows, updates only the publication and scrub columns and never
rewrites an allocation, a share or an amount; the lifecycle role scrubs and deletes but never
rewrites money either. AV19: a new client gets First Click, Last Click and Linear at 30 days
with Linear as its default; the default cannot be retired until another is set; administration
is Owner/Admin, idempotent and audited, with closed codes. Synthetic values only.
"""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from report_support import grant, key_client, service_key
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.models import AttributionModelVersion, AuditEvent, RevenueEvidence

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0034_saas_billing"
TABLES = (
    "attribution_model_versions",
    "attribution_conversions",
    "attribution_runs",
    "attribution_allocations",
    "attribution_credit_changes",
    "attribution_consumer_state",
)


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


def _models_url(w, client=None, suffix="") -> str:
    return f"/agencies/{w.a}/clients/{client or w.a1}/attribution/models{suffix}"


def _seed_rows(w) -> dict:
    """One synthetic conversion, run, allocation and credit change, written by the migrator."""
    ids = {name: uuid4() for name in ("version", "conversion", "run", "allocation", "change")}
    statements = (
        "INSERT INTO attribution_model_versions (id, agency_id, client_id, version_key, model, "
        "window_seconds, rules, is_default, status) VALUES (:version, :agency, :client, "
        "'linear_30d_v1', 'linear', 2592000, '008-A.1', true, 'active')",
        "INSERT INTO attribution_conversions (id, agency_id, client_id, generation, slot_key, "
        "conversion_key, kind, source_account_id, sale_operation_id, effective_at, status) "
        "VALUES (:conversion, :agency, :client, 1, repeat('a', 64), repeat('a', 64) || '.1', "
        "'sale', 'shop', 'S1', now(), 'active')",
        "INSERT INTO attribution_runs (id, agency_id, client_id, generation, conversion_id, "
        "model_version_id, revision, status, basis, causes, currency, currency_exponent, "
        "verified_net_minor, window_start, window_end, ledger_generation, receipt_ordinal, "
        "identity_seq) VALUES (:run, :agency, :client, 1, :conversion, :version, 1, 'complete', "
        "'unknown_fallback', ARRAY['initial'], 'EGP', 2, 10000, now() - interval '30 days', "
        "now(), 1, 1, 0)",
        "INSERT INTO attribution_allocations (id, agency_id, client_id, run_id, ordinal, "
        "credited, recipient, basis, position, share_numerator, share_denominator, "
        "amount_minor) VALUES (:allocation, :agency, :client, :run, 1, true, 'unknown', "
        "'unknown_fallback', 0, 1, 1, 10000)",
        "INSERT INTO attribution_credit_changes (id, agency_id, client_id, run_id, "
        "model_version_id, generation, ordinal, conversion_kind, effective_at, recipient, "
        "delta_share_numerator, delta_share_denominator, delta_minor, currency, "
        "currency_exponent) VALUES (:change, :agency, :client, :run, :version, 1, 1, 'sale', "
        "now(), 'unknown', 1, 1, 10000, 'EGP', 2)",
    )
    with w.db.migration.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), {**ids, "agency": w.a, "client": w.a1})
    return ids


def test_av14_populated_upgrade_guarded_downgrade_and_privileges(world):
    w = world
    command.downgrade(CONFIG, "0028_revenue_identity")
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO revenue_evidence (id, agency_id, client_id, delivery_id, "
                "source_account_id, operation_id, kind, classification, currency, "
                "currency_exponent, amount_minor, effective_at, received_at, intake, intake_id, "
                "content_digest) VALUES (:id, :agency, :client, 'legacy:1', 'shop', 'L1', "
                "'sale', 'confirmed_capture', 'EGP', 2, 1000, now(), now(), 'csv_import', "
                ":intake, :digest)"
            ),
            {"id": uuid4(), "agency": w.a, "client": w.a1, "intake": uuid4(), "digest": "a" * 64},
        )
    command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD
    with Session(w.db.migration) as session:
        assert len(list(session.scalars(select(RevenueEvidence)))) == 1
    for table in TABLES:
        assert _privilege(w.db, "tracking_app", table, "SELECT")
        assert _privilege(w.db, "tracking_app", table, "INSERT")
        assert not _privilege(w.db, "tracking_app", table, "DELETE")
        assert not _privilege(w.db, "tracking_app", table, "TRUNCATE")
        assert _privilege(w.db, "tracking_lifecycle", table, "SELECT")
    for column in ("share_numerator", "share_denominator", "amount_minor", "recipient", "basis"):
        assert not _privilege(w.db, "tracking_app", "attribution_allocations", "UPDATE", column)
        assert not _privilege(
            w.db, "tracking_lifecycle", "attribution_allocations", "UPDATE", column
        )
    for column in ("touchpoint_id", "occurred_at"):
        assert _privilege(w.db, "tracking_app", "attribution_allocations", "UPDATE", column)
        assert _privilege(w.db, "tracking_lifecycle", "attribution_allocations", "UPDATE", column)
    for column in ("verified_net_minor", "currency", "revision", "causes", "window_end"):
        assert not _privilege(w.db, "tracking_app", "attribution_runs", "UPDATE", column)
    for column in ("delta_minor", "delta_share_numerator", "effective_at", "campaign_ref"):
        assert not _privilege(w.db, "tracking_app", "attribution_credit_changes", "UPDATE", column)
        assert not _privilege(
            w.db, "tracking_lifecycle", "attribution_credit_changes", "UPDATE", column
        )
    for column in ("model", "window_seconds", "rules", "version_key"):
        assert not _privilege(w.db, "tracking_app", "attribution_model_versions", "UPDATE", column)
    for column in ("kind", "slot_key", "source_account_id", "effective_at", "generation"):
        expected = column == "slot_key"  # the scrub replaces a lead's slot key
        assert (
            _privilege(w.db, "tracking_app", "attribution_conversions", "UPDATE", column)
            is expected
        )
    for table in ("attribution_conversions", "attribution_runs"):
        assert _privilege(w.db, "tracking_lifecycle", table, "DELETE")
        assert not _privilege(w.db, "tracking_lifecycle", table, "INSERT")
    # A refused downgrade rolls back, and the version stays at head; the consumer state alone
    # is bookkeeping and does not block it.
    _seed_rows(w)
    try:
        with pytest.raises(RuntimeError, match="persisted attribution state"):
            command.downgrade(CONFIG, "0028_revenue_identity")
        assert _version(w.db) == HEAD
        with w.db.migration.begin() as connection:
            for table in TABLES[::-1][1:]:
                connection.execute(text(f"DELETE FROM {table}"))
            connection.execute(
                text(
                    "INSERT INTO audit_events (id, agency_id, client_id, actor_user_id, action, "
                    "resource_type, resource_id) VALUES (:id, :agency, :client, :actor, "
                    "'attribution.model_retired', 'attribution_model', :id)"
                ),
                {"id": uuid4(), "agency": w.a, "client": w.a1, "actor": w.users.owner_a},
            )
        with pytest.raises(RuntimeError, match="persisted attribution state"):
            command.downgrade(CONFIG, "0028_revenue_identity")
        assert _version(w.db) == HEAD
        with w.db.migration.begin() as connection:
            connection.execute(text("DELETE FROM audit_events WHERE action LIKE 'attribution.%'"))
            connection.execute(
                text(
                    "INSERT INTO attribution_consumer_state (client_id, agency_id) "
                    "VALUES (:client, :agency)"
                ),
                {"client": w.a1, "agency": w.a},
            )
        command.downgrade(CONFIG, "0028_revenue_identity")
        assert _version(w.db) == "0028_revenue_identity"
    finally:
        command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD


def test_av14_runtime_role_cannot_rewrite_allocations_or_amounts(world, lifecycle_engine):
    w = world
    ids = _seed_rows(w)
    denied = [
        (w.db.runtime, "UPDATE attribution_allocations SET amount_minor = 1"),
        (w.db.runtime, "UPDATE attribution_allocations SET share_numerator = 2"),
        (w.db.runtime, "UPDATE attribution_allocations SET recipient = 'campaign'"),
        (w.db.runtime, "UPDATE attribution_runs SET verified_net_minor = 1"),
        (w.db.runtime, "UPDATE attribution_runs SET revision = 2"),
        (w.db.runtime, "UPDATE attribution_credit_changes SET delta_minor = 1"),
        (w.db.runtime, "UPDATE attribution_model_versions SET window_seconds = 86400"),
        (w.db.runtime, "UPDATE attribution_conversions SET kind = 'lead'"),
        (w.db.runtime, "DELETE FROM attribution_runs"),
        (w.db.runtime, "DELETE FROM attribution_credit_changes"),
        (lifecycle_engine, "UPDATE attribution_allocations SET amount_minor = 1"),
        (lifecycle_engine, "UPDATE attribution_credit_changes SET delta_minor = 1"),
        (lifecycle_engine, "UPDATE attribution_runs SET verified_net_minor = 1"),
        (lifecycle_engine, "UPDATE attribution_model_versions SET is_default = false"),
    ]
    for engine, statement in denied:
        with pytest.raises(DBAPIError) as caught:
            with engine.begin() as connection:
                connection.execute(text(statement))
        assert "permission denied" in str(caught.value.orig).lower(), statement
    # The scrub columns are writable by both roles.
    for engine in (w.db.runtime, lifecycle_engine):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE attribution_allocations SET touchpoint_id = NULL WHERE id = :id"),
                {"id": ids["allocation"]},
            )
    with w.db.migration.connect() as connection:
        amount = connection.execute(
            text("SELECT amount_minor FROM attribution_allocations WHERE id = :id"),
            {"id": ids["allocation"]},
        ).scalar_one()
    assert amount == 10000


def test_av19_defaults_and_a_retired_default_is_refused(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    listed = owner.get(_models_url(w))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [
        (item["version_key"], item["model"], item["window_days"]) for item in body["versions"]
    ] == [
        ("first_click_30d_v1", "first_click", 30),
        ("last_click_30d_v1", "last_click", 30),
        ("linear_30d_v1", "linear", 30),
    ]
    linear = next(item for item in body["versions"] if item["model"] == "linear")
    assert body["default_version_id"] == linear["id"] and linear["is_default"]
    assert body["active_limit"] == 6
    assert all(
        item["rules"] == "008-A.1" and item["status"] == "active" for item in body["versions"]
    )
    # A second read seeds nothing new.
    assert len(owner.get(_models_url(w)).json()["versions"]) == 3
    refused = owner.post(
        _models_url(w, suffix=f"/{linear['id']}/retire"), json={"operation_id": str(uuid4())}
    )
    assert (refused.status_code, refused.json()) == (409, {"error": "model_version_conflict"})
    first = body["versions"][0]
    operation = str(uuid4())
    made = owner.post(
        _models_url(w, suffix=f"/{first['id']}/default"), json={"operation_id": operation}
    )
    assert made.status_code == 201, made.text
    assert made.json()["is_default"] is True
    replay = owner.post(
        _models_url(w, suffix=f"/{first['id']}/default"), json={"operation_id": operation}
    )
    assert replay.status_code == 200
    retired = owner.post(
        _models_url(w, suffix=f"/{linear['id']}/retire"), json={"operation_id": str(uuid4())}
    )
    assert retired.status_code == 201, retired.text
    assert retired.json()["status"] == "retired" and retired.json()["retired_at"]
    after = owner.get(_models_url(w)).json()
    assert after["default_version_id"] == first["id"]
    assert sum(item["is_default"] for item in after["versions"]) == 1
    # Another client of the same agency still starts with its own defaults.
    other = owner.get(_models_url(w, client=w.a2)).json()
    assert {item["version_key"] for item in other["versions"]} == {
        "first_click_30d_v1",
        "last_click_30d_v1",
        "linear_30d_v1",
    }
    assert not {item["id"] for item in other["versions"]} & {
        item["id"] for item in after["versions"]
    }


def test_model_administration_codes_idempotency_and_audit(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    owner.get(_models_url(w))
    for days in (0, 91):
        response = owner.post(
            _models_url(w),
            json={"operation_id": str(uuid4()), "model": "linear", "window_days": days},
        )
        assert (response.status_code, response.json()) == (422, {"error": "invalid_window"})
    duplicate = owner.post(
        _models_url(w), json={"operation_id": str(uuid4()), "model": "linear", "window_days": 30}
    )
    assert (duplicate.status_code, duplicate.json()) == (409, {"error": "model_version_conflict"})
    operation = str(uuid4())
    created = owner.post(
        _models_url(w), json={"operation_id": operation, "model": "linear", "window_days": 7}
    )
    assert created.status_code == 201, created.text
    assert created.json()["version_key"] == "linear_7d_v1"
    replay = owner.post(
        _models_url(w), json={"operation_id": operation, "model": "linear", "window_days": 7}
    )
    assert (replay.status_code, replay.json()) == (200, created.json())
    reused = owner.post(
        _models_url(w), json={"operation_id": operation, "model": "linear", "window_days": 8}
    )
    assert (reused.status_code, reused.json()) == (409, {"error": "operation_conflict"})
    admin = w.signed_in("admin")
    for days in (14, 60):
        response = admin.post(
            _models_url(w),
            json={"operation_id": str(uuid4()), "model": "first_click", "window_days": days},
        )
        assert response.status_code == 201, response.text
    limit = admin.post(
        _models_url(w), json={"operation_id": str(uuid4()), "model": "last_click", "window_days": 1}
    )
    assert (limit.status_code, limit.json()) == (409, {"error": "model_version_limit"})
    # A retired definition can be added again as a new version with its own history.
    seven = created.json()["id"]
    assert (
        admin.post(
            _models_url(w, suffix=f"/{seven}/retire"), json={"operation_id": str(uuid4())}
        ).status_code
        == 201
    )
    again = admin.post(
        _models_url(w), json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7}
    )
    assert again.status_code == 201 and again.json()["version_key"] == "linear_7d_v2"
    gone = admin.post(
        _models_url(w, suffix=f"/{seven}/default"), json={"operation_id": str(uuid4())}
    )
    assert (gone.status_code, gone.json()) == (409, {"error": "model_version_conflict"})
    # Analysts and viewers read the models but never administer them.
    analyst = w.signed_in("analyst")
    assert analyst.get(_models_url(w)).status_code == 200
    denied = analyst.post(
        _models_url(w), json={"operation_id": str(uuid4()), "model": "linear", "window_days": 3}
    )
    assert denied.status_code == 403
    viewer = w.signed_in("viewer")
    assert viewer.get(_models_url(w, client=w.a2)).status_code == 403
    with Session(w.db.migration) as session:
        actions = sorted(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.resource_type == "attribution_model")
            )
        )
        stored = session.scalars(
            select(AttributionModelVersion).where(AttributionModelVersion.client_id == w.a1)
        ).all()
    assert actions == [
        "attribution.model_created",
        "attribution.model_created",
        "attribution.model_created",
        "attribution.model_created",
        "attribution.model_retired",
    ]
    assert sum(row.status == "active" for row in stored) == 6


def test_service_read_keys_reach_the_models_of_granted_clients_only(authenticated_world, api):
    w = authenticated_world
    reader = key_client(api, service_key(w, api, [grant(w.a1)]))
    assert reader.get(_models_url(w)).status_code == 200
    assert reader.get(_models_url(w, client=w.a2)).status_code == 403
    assert (
        reader.post(
            _models_url(w),
            json={"operation_id": str(uuid4()), "model": "linear", "window_days": 3},
        ).status_code
        == 401
    )


REPORT_INDEXES = (
    "ix_attribution_conversions_client_effective",
    "ix_collected_events_client_link_received",
)


def _report_indexes(db) -> dict[str, str]:
    with db.migration.connect() as connection:
        return dict(
            connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN (:a, :b)"),
                {"a": REPORT_INDEXES[0], "b": REPORT_INDEXES[1]},
            ).all()
        )


def test_bv20_0030_upgrade_from_populated_0029_and_downgrade(world):
    # 016-B (D-089 D12): 0030 adds two indexes over populated 0029 tables and drops them again;
    # the stored rows stay untouched either way.
    w = world
    command.downgrade(CONFIG, "0029_attribution_persistence")
    try:
        assert _report_indexes(w.db) == {}
        ids = _seed_rows(w)
        command.upgrade(CONFIG, "head")
        assert _version(w.db) == HEAD
        found = _report_indexes(w.db)
        assert found[REPORT_INDEXES[0]].endswith(
            "ON public.attribution_conversions USING btree (client_id, effective_at, id)"
        )
        assert found[REPORT_INDEXES[1]].endswith(
            "ON public.collected_events USING btree (client_id, first_received_at) "
            "WHERE (link_id IS NOT NULL)"
        )
        command.downgrade(CONFIG, "0029_attribution_persistence")
        assert _version(w.db) == "0029_attribution_persistence"
        assert _report_indexes(w.db) == {}
        with w.db.migration.connect() as connection:
            assert connection.execute(
                text("SELECT id FROM attribution_conversions")
            ).scalars().all() == [ids["conversion"]]
    finally:
        with w.db.migration.begin() as connection:
            for table in TABLES[::-1][1:]:
                connection.execute(text(f"DELETE FROM {table}"))
        command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD
    assert set(_report_indexes(w.db)) == set(REPORT_INDEXES)
