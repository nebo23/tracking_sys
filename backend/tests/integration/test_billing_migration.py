"""Migration 0034_saas_billing (specification 017-C, D-103 D13; BL21 and the schema half of BL15).

The upgrade from a populated 0033 (the billing_hold plan, complimentary standings for every
agency that is not purged), the grants, the constraints of the eight tables, the purge
function's billing steps and its pending-action guard, the exact restoration of the 0033 function
and the downgrade that refuses stored billing state, on synthetic data in the disposable
database only. The model comparison is test_tenancy's test_migration_matches_model_metadata and
the data policy rows are checked by test_data_policy_schema.
"""

import secrets
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from app.config import BACKEND_ROOT

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))
HEAD = "0034_saas_billing"
PREVIOUS = "0033_agency_offboarding"
NEW_TABLES = (
    "billing_prices",
    "agency_billing",
    "agency_subscriptions",
    "billing_checkouts",
    "billing_events",
    "billing_payments",
    "billing_adjustments",
    "billing_actions",
)
FUNCTION = "purge_agency_batch(uuid, integer)"
REFUSAL = "stored billing state"


def paddle(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(13)}"


def _version(db) -> str:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _value(db, statement: str, **values):
    with db.migration.connect() as connection:
        return connection.execute(text(statement), values).scalar_one()


def _execute(db, statement: str, **values) -> None:
    with db.migration.begin() as connection:
        connection.execute(text(statement), values)


def _privilege(db, role, table, privilege, column=None) -> bool:
    if column is None:
        return _value(db, "SELECT has_table_privilege(:r, :t, :p)", r=role, t=table, p=privilege)
    return _value(
        db,
        "SELECT has_column_privilege(:r, :t, :c, :p)",
        r=role,
        t=table,
        c=column,
        p=privilege,
    )


def _definition(db) -> str:
    return _value(db, "SELECT prosrc FROM pg_proc WHERE oid = CAST(:f AS regprocedure)", f=FUNCTION)


def _plan(db, key: str):
    return _value(db, "SELECT id FROM saas_plans WHERE key = :k", k=key)


def _price(db, **overrides):
    values = {
        "id": uuid4(),
        "plan": _plan(db, "development"),
        "pid": paddle("pri"),
        "amount": 2900,
        "interval": "month",
        **overrides,
    }
    _execute(
        db,
        "INSERT INTO billing_prices (id, plan_id, provider, provider_price_id, currency, "
        "amount_cents, billing_interval) VALUES (:id, :plan, 'paddle', :pid, 'USD', :amount, "
        ":interval)",
        **values,
    )
    return values["id"]


def _subscription(db, agency, *, status="active", duplicate=False):
    identifier = uuid4()
    _execute(
        db,
        "INSERT INTO agency_subscriptions (id, agency_id, provider, provider_subscription_id, "
        "status, duplicate, last_event_at) VALUES (:id, :a, 'paddle', :sid, :status, :dup, now())",
        id=identifier,
        a=agency,
        sid=paddle("sub"),
        status=status,
        dup=duplicate,
    )
    return identifier


# The complimentary standing of an agency, as create_agency records it while billing is
# disabled (an existing row is kept).
def _standings(db, *agencies) -> None:
    for agency in agencies:
        _execute(
            db,
            "INSERT INTO agency_billing (agency_id, standing, reason) "
            "VALUES (:a, 'complimentary', 'billing_disabled') ON CONFLICT DO NOTHING",
            a=agency,
        )


def _owner(db, agency):
    return _value(
        db,
        "SELECT id FROM agency_memberships WHERE agency_id = :a AND role = 'owner'",
        a=agency,
    )


def test_bl21_upgrade_from_a_populated_0033(world):
    w = world
    assert _version(w.db) == HEAD
    agencies = _value(w.db, "SELECT count(*) FROM agencies")
    command.downgrade(CONFIG, PREVIOUS)
    try:
        with w.db.migration.connect() as connection:
            present = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert present.isdisjoint(NEW_TABLES)
        assert _value(w.db, "SELECT count(*) FROM saas_plans WHERE key = 'billing_hold'") == 0
        assert "billing_actions" not in _definition(w.db)
        # A purged agency at 0033 receives no standing.
        purged = uuid4()
        _execute(
            w.db,
            "INSERT INTO agencies (id, name, status, purged_at) "
            "VALUES (:id, 'Closed agency', 'closed', now())",
            id=purged,
        )
        command.upgrade(CONFIG, "head")
        assert _version(w.db) == HEAD
        with w.db.migration.connect() as connection:
            hold = connection.execute(
                text(
                    "SELECT name, clients_limit, seats_limit, connections_limit, "
                    "managed_links_limit, tracked_events_limit, is_default, reason "
                    "FROM saas_plans WHERE key = 'billing_hold'"
                )
            ).one()
            standings = connection.execute(
                text("SELECT agency_id, standing, reason, version FROM agency_billing")
            ).all()
        assert tuple(hold) == ("Billing hold", 0, 0, 0, 0, 0, False, "seed")
        assert len(standings) == agencies and purged not in {row[0] for row in standings}
        assert {tuple(row[1:]) for row in standings} == {("complimentary", "migration", 1)}
        assert _value(w.db, "SELECT key FROM saas_plans WHERE is_default") == "development"
        for table in NEW_TABLES[2:]:
            assert _value(w.db, f"SELECT count(*) FROM {table}") == 0
        assert "billing_actions" in _definition(w.db)
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")
        _execute(w.db, "DELETE FROM agencies WHERE purged_at IS NOT NULL")


def test_bl21_grants(db):
    app_role, lifecycle = "tracking_app", "tracking_lifecycle"
    for table in NEW_TABLES:
        assert _privilege(db, app_role, table, "SELECT")
        assert _privilege(db, app_role, table, "INSERT")
        assert not _privilege(db, app_role, table, "DELETE")
        assert not _privilege(db, app_role, table, "TRUNCATE")
        assert not _privilege(db, lifecycle, table, "UPDATE")
    updatable = {
        "billing_prices": {"offered", "retired_at"},
        "agency_billing": {
            "standing",
            "reason",
            "trial_ends_at",
            "trial_reminded_at",
            "grant_ends_at",
            "hold_started_at",
            "hold_notified_at",
            "provider_customer_id",
            "version",
            "updated_at",
        },
        "agency_subscriptions": {
            "price_id",
            "provider_price_id",
            "status",
            "current_period_starts_at",
            "current_period_ends_at",
            "next_billed_at",
            "scheduled_action",
            "scheduled_at",
            "cancel_origin",
            "canceled_at",
            "last_event_at",
            "reconciled_at",
            "updated_at",
        },
        "billing_checkouts": {"status", "completed_at"},
        "billing_events": set(),
        "billing_payments": {
            "subscription_id",
            "status",
            "origin",
            "currency",
            "subtotal_cents",
            "tax_cents",
            "total_cents",
            "billed_at",
            "invoice_number",
            "last_event_at",
            "updated_at",
        },
        "billing_adjustments": {
            "payment_id",
            "status",
            "currency",
            "total_cents",
            "last_event_at",
            "updated_at",
        },
        "billing_actions": {"status", "attempts", "next_attempt_at", "last_error", "completed_at"},
    }
    with db.migration.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY (:t)"
            ),
            {"t": list(NEW_TABLES)},
        ).all()
    for table, column in columns:
        assert _privilege(db, app_role, table, "UPDATE", column) == (column in updatable[table]), (
            table,
            column,
        )
    # The lifecycle role: retention of events and expired checkouts, and the closure
    # completion's cancellation (reads three subscription columns, inserts actions).
    for table in ("billing_events", "billing_checkouts"):
        assert _privilege(db, lifecycle, table, "DELETE")
    for table in set(NEW_TABLES) - {"billing_events", "billing_checkouts"}:
        assert not _privilege(db, lifecycle, table, "DELETE")
    assert _privilege(db, lifecycle, "billing_actions", "INSERT")
    for table in set(NEW_TABLES) - {"billing_actions"}:
        assert not _privilege(db, lifecycle, table, "INSERT")
    readable = {
        "billing_events": {"id", "received_at"},
        "billing_checkouts": {"id", "status", "expires_at"},
        "agency_subscriptions": {"id", "agency_id", "status"},
    }
    for table, column in columns:
        assert _privilege(db, lifecycle, table, "SELECT", column) == (
            column in readable.get(table, set())
        ), (table, column)


def test_bl21_constraints(world):
    w = world
    _standings(w.db, w.a, w.b)
    price = _price(w.db)
    # Prices: USD only, positive amounts, month or year, Paddle's ID form, one offered price
    # per plan and interval, and final retirement.
    for overrides in (
        {"amount": 0},
        {"interval": "week"},
        {"pid": "pri_Uppercase0000000000000000"},
    ):
        with pytest.raises(IntegrityError):
            _price(w.db, **overrides)
    with pytest.raises(IntegrityError):
        _execute(
            w.db,
            "INSERT INTO billing_prices (id, plan_id, provider, provider_price_id, currency, "
            "amount_cents, billing_interval) VALUES (:id, :plan, 'paddle', :pid, 'EUR', 100, "
            "'year')",
            id=uuid4(),
            plan=_plan(w.db, "development"),
            pid=paddle("pri"),
        )
    with pytest.raises(IntegrityError, match="uq_billing_prices_offered"):
        _price(w.db)
    with pytest.raises(IntegrityError, match="retirement"):
        _execute(w.db, "UPDATE billing_prices SET offered = false WHERE id = :p", p=price)
    # Standings: the reason matches the standing; a trial has an end; a hold has a start.
    for statement in (
        "UPDATE agency_billing SET standing = 'hold', reason = 'trial_ended' WHERE agency_id = :a",
        "UPDATE agency_billing SET standing = 'trialing', reason = 'new_agency' "
        "WHERE agency_id = :a",
        "UPDATE agency_billing SET reason = 'payment_failed' WHERE agency_id = :a",
        "UPDATE agency_billing SET grant_ends_at = now() WHERE agency_id = :a",
    ):
        with pytest.raises(IntegrityError):
            _execute(w.db, statement, a=w.a)
    # One primary subscription that has not ended per agency; duplicates are flagged.
    first = _subscription(w.db, w.a)
    with pytest.raises(IntegrityError, match="uq_agency_subscriptions_primary"):
        _subscription(w.db, w.a)
    _subscription(w.db, w.a, duplicate=True)
    _execute(w.db, "UPDATE agency_subscriptions SET status = 'canceled' WHERE id = :s", s=first)
    _subscription(w.db, w.a)
    # One open checkout per agency, at most 24 hours.
    checkout = (
        "INSERT INTO billing_checkouts (id, agency_id, price_id, requested_by_membership_id, "
        "provider_transaction_id, expires_at) VALUES (:id, :a, :p, :m, :t, now() + :life)"
    )
    owner = _owner(w.db, w.a)
    _execute(
        w.db,
        checkout,
        id=uuid4(),
        a=w.a,
        p=price,
        m=owner,
        t=paddle("txn"),
        life="24 hours",
    )
    with pytest.raises(IntegrityError, match="uq_billing_checkouts_open"):
        _execute(
            w.db,
            checkout,
            id=uuid4(),
            a=w.a,
            p=price,
            m=owner,
            t=paddle("txn"),
            life="1 hour",
        )
    with pytest.raises(IntegrityError, match="lifetime"):
        _execute(
            w.db,
            checkout,
            id=uuid4(),
            a=w.b,
            p=price,
            m=_owner(w.db, w.b),
            t=paddle("txn"),
            life="25 hours",
        )
    # A checkout's membership belongs to its agency.
    with pytest.raises(IntegrityError):
        _execute(
            w.db,
            checkout,
            id=uuid4(),
            a=w.b,
            p=price,
            m=owner,
            t=paddle("txn"),
            life="1 hour",
        )
    # Events: Paddle's event ID form by source, unique per provider; an unmatched event has no
    # agency, an applied one has one.
    event = (
        "INSERT INTO billing_events (id, provider, provider_event_id, source, event_type, "
        "occurred_at, agency_id, outcome) VALUES (:id, 'paddle', :e, :s, 'subscription.updated', "
        "now(), :a, :o)"
    )
    stored = paddle("evt")
    _execute(w.db, event, id=uuid4(), e=stored, s="webhook", a=w.a, o="applied")
    with pytest.raises(IntegrityError, match="uq_billing_events_provider_event"):
        _execute(w.db, event, id=uuid4(), e=stored, s="webhook", a=w.a, o="stale")
    for values in (
        {"e": paddle("evt"), "s": "reconciliation", "a": w.a, "o": "applied"},
        {"e": f"rec_{uuid4().hex}", "s": "webhook", "a": w.a, "o": "applied"},
        {"e": paddle("evt"), "s": "webhook", "a": w.a, "o": "unmatched"},
        {"e": paddle("evt"), "s": "webhook", "a": None, "o": "applied"},
    ):
        with pytest.raises(IntegrityError):
            _execute(w.db, event, id=uuid4(), **values)
    _execute(w.db, event, id=uuid4(), e=f"rec_{uuid4().hex}", s="reconciliation", a=w.a, o="stale")
    # Actions pair each action with its reason.
    subscription = _value(
        w.db,
        "SELECT id FROM agency_subscriptions WHERE agency_id = :a AND NOT duplicate "
        "AND status <> 'canceled'",
        a=w.a,
    )
    action = (
        "INSERT INTO billing_actions (id, agency_id, subscription_id, action, reason) "
        "VALUES (:id, :a, :s, :action, :reason)"
    )
    _execute(
        w.db,
        action,
        id=uuid4(),
        a=w.a,
        s=subscription,
        action="cancel_now",
        reason="closure_completed",
    )
    with pytest.raises(IntegrityError, match="valid_action"):
        _execute(
            w.db,
            action,
            id=uuid4(),
            a=w.a,
            s=subscription,
            action="cancel_now",
            reason="closure_requested",
        )
    # The plan assignment values of billing.
    with pytest.raises(IntegrityError, match="reason_matches"):
        _execute(
            w.db,
            "INSERT INTO agency_plan_assignments (id, agency_id, plan_id, revision, assigned_by, "
            "reason) VALUES (:id, :a, :p, 9, 'billing', 'plan_change')",
            id=uuid4(),
            a=w.a,
            p=_plan(w.db, "billing_hold"),
        )


def _closed_and_waiting(db, agency) -> None:
    _execute(
        db,
        "INSERT INTO agency_closures (id, agency_id, requested_by_membership_id, requested_at, "
        "closes_at, completed_at) VALUES (:id, :a, :m, now() - interval '31 days', "
        "now() - interval '1 day', now() - interval '1 hour')",
        id=uuid4(),
        a=agency,
        m=_owner(db, agency),
    )
    _execute(db, "UPDATE agencies SET status = 'closed' WHERE id = :a", a=agency)
    _execute(
        db,
        "INSERT INTO agency_purges (agency_id, state, closure_requested_at, closes_at, "
        "closure_completed_at, offboarding_completed_at) VALUES (:a, 'waiting', "
        "now() - interval '31 days', now() - interval '1 day', now(), now())",
        a=agency,
    )


def _purge(engine, agency, budget=5000):
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT purge_agency_batch(:a, :b)"), {"a": agency, "b": budget}
        ).scalar_one()


def test_bl15_purge_waits_for_actions_and_keeps_financial_records(world, lifecycle_engine):
    w = world
    _standings(w.db, w.a, w.b)
    price = _price(w.db)
    subscription = _subscription(w.db, w.a)
    payment = uuid4()
    _execute(
        w.db,
        "INSERT INTO billing_payments (id, agency_id, subscription_id, provider_transaction_id, "
        "status, origin, currency, subtotal_cents, tax_cents, total_cents, last_event_at) "
        "VALUES (:id, :a, :s, :t, 'completed', 'web', 'USD', 2900, 290, 3190, now())",
        id=payment,
        a=w.a,
        s=subscription,
        t=paddle("txn"),
    )
    _execute(
        w.db,
        "INSERT INTO billing_adjustments (id, agency_id, payment_id, provider_adjustment_id, "
        "provider_transaction_id, action, status, currency, total_cents, last_event_at) "
        "VALUES (:id, :a, :p, :adj, :t, 'refund', 'approved', 'USD', 3190, now())",
        id=uuid4(),
        a=w.a,
        p=payment,
        adj=paddle("adj"),
        t=paddle("txn"),
    )
    _execute(
        w.db,
        "INSERT INTO billing_checkouts (id, agency_id, price_id, requested_by_membership_id, "
        "provider_transaction_id, status, expires_at, completed_at) VALUES (:id, :a, :p, :m, :t, "
        "'completed', now() + interval '1 hour', now())",
        id=uuid4(),
        a=w.a,
        p=price,
        m=_owner(w.db, w.a),
        t=paddle("txn"),
    )
    _execute(
        w.db,
        "INSERT INTO billing_events (id, provider, provider_event_id, source, event_type, "
        "occurred_at, agency_id, subscription_id, outcome) VALUES (:id, 'paddle', :e, 'webhook', "
        "'subscription.activated', now(), :a, :s, 'applied')",
        id=uuid4(),
        e=paddle("evt"),
        a=w.a,
        s=subscription,
    )
    action = uuid4()
    _execute(
        w.db,
        "INSERT INTO billing_actions (id, agency_id, subscription_id, action, reason) "
        "VALUES (:id, :a, :s, 'cancel_now', 'closure_completed')",
        id=action,
        a=w.a,
        s=subscription,
    )
    _closed_and_waiting(w.db, w.a)
    # A pending provider action keeps the agency waiting, like a teardown before its deadline.
    with pytest.raises(DBAPIError) as raised:
        _purge(lifecycle_engine, w.a)
    assert raised.value.orig.diag.message_primary == "teardown_pending"
    assert _value(w.db, "SELECT count(*) FROM billing_actions WHERE agency_id = :a", a=w.a) == 1
    _execute(
        w.db,
        "UPDATE billing_actions SET status = 'done', completed_at = now() WHERE id = :id",
        id=action,
    )
    result = _purge(lifecycle_engine, w.a)
    assert result["state"] == "purged"
    for table in ("agency_billing", "billing_checkouts", "billing_events", "billing_actions"):
        assert result["deleted"][table] >= 1, table
        assert _value(w.db, f"SELECT count(*) FROM {table} WHERE agency_id = :a", a=w.a) == 0
    for table in ("agency_subscriptions", "billing_payments", "billing_adjustments"):
        assert table not in result["deleted"]
        assert _value(w.db, f"SELECT count(*) FROM {table} WHERE agency_id = :a", a=w.a) == 1
    # The other agency is untouched (BL20).
    assert _value(w.db, "SELECT count(*) FROM agency_billing WHERE agency_id = :b", b=w.b) == 1
    _execute(w.db, "DELETE FROM agency_purges WHERE agency_id = :a", a=w.a)


def test_bl21_downgrade_restores_0033_and_refuses_stored_state(world):
    w = world
    _standings(w.db, w.a, w.b)
    command.downgrade(CONFIG, PREVIOUS)
    original = _definition(w.db)
    command.upgrade(CONFIG, "head")
    assert _definition(w.db) != original
    # Each kind of stored billing state refuses the downgrade, and nothing is removed.
    states = (
        (
            "INSERT INTO billing_prices (id, plan_id, provider, provider_price_id, currency, "
            "amount_cents, billing_interval) SELECT gen_random_uuid(), id, 'paddle', "
            f"'{paddle('pri')}', 'USD', 100, 'month' FROM saas_plans WHERE key = 'development'",
            "DELETE FROM billing_prices",
        ),
        (
            "UPDATE agency_billing SET standing = 'trialing', reason = 'new_agency', "
            f"trial_ends_at = now() WHERE agency_id = '{w.a}'",
            "UPDATE agency_billing SET standing = 'complimentary', reason = 'billing_disabled', "
            f"trial_ends_at = NULL WHERE agency_id = '{w.a}'",
        ),
        (
            "INSERT INTO agency_plan_assignments (id, agency_id, plan_id, revision, assigned_by, "
            f"reason) SELECT gen_random_uuid(), '{w.a}', id, 7, 'billing', 'billing_hold' "
            "FROM saas_plans WHERE key = 'billing_hold'",
            "DELETE FROM agency_plan_assignments WHERE assigned_by = 'billing'",
        ),
        (
            "INSERT INTO audit_events (id, agency_id, actor_kind, actor_user_id, action, "
            "resource_type, resource_id) VALUES (gen_random_uuid(), NULL, 'platform_operator', "
            "NULL, 'billing_price.registered', 'billing_price', gen_random_uuid())",
            "DELETE FROM audit_events WHERE resource_type = 'billing_price'",
        ),
        (
            "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
            "VALUES (gen_random_uuid(), 'billing_hold', 'synthetic')",
            "DELETE FROM mail_outbox WHERE purpose = 'billing_hold'",
        ),
    )
    for stored, cleanup in states:
        _execute(w.db, stored)
        try:
            with pytest.raises(RuntimeError, match=REFUSAL):
                command.downgrade(CONFIG, PREVIOUS)
            assert _version(w.db) == HEAD
        finally:
            _execute(w.db, cleanup)
    try:
        command.downgrade(CONFIG, PREVIOUS)
        assert _version(w.db) == PREVIOUS
        # The 0033 function is restored exactly, and the hold plan and the checks are gone.
        assert _definition(w.db) == original
        assert _value(w.db, "SELECT count(*) FROM saas_plans WHERE key = 'billing_hold'") == 0
        with pytest.raises(IntegrityError, match="valid_purpose"):
            _execute(
                w.db,
                "INSERT INTO mail_outbox (id, purpose, encrypted_payload) "
                "VALUES (gen_random_uuid(), 'trial_ending', 'synthetic')",
            )
        with pytest.raises(ProgrammingError):
            _execute(w.db, "SELECT 1 FROM billing_prices")
    finally:
        if _version(w.db) != HEAD:
            command.upgrade(CONFIG, "head")
    assert _version(w.db) == HEAD
