"""Agency closure by its Owner (017-A, D-092 decisions D8 and D9).

Cases SV10 and SV12-SV14 and the closure part of SV19 of the entry review's verification
matrix, on synthetic data in the disposable database only. SV11 is in
test_agency_closure_stops.py.
"""

from datetime import timedelta
from uuid import UUID

import pytest
from connector_support import make_lab
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app import agency_plans
from app.models import (
    Agency,
    AgencyClosure,
    AuditEvent,
    AuthRateLimit,
    AuthSession,
    PasswordCredential,
)
from app.security import now_utc
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
NAME_A, NAME_B = "Synthetic Agency A", "Synthetic Agency B"


def _status(db, agency) -> str:
    with Session(db.migration) as session:
        return session.scalar(select(Agency.status).where(Agency.id == agency))


def _closures(db, agency) -> list[AgencyClosure]:
    with Session(db.migration) as session:
        return list(
            session.scalars(
                select(AgencyClosure)
                .where(AgencyClosure.agency_id == agency)
                .order_by(AgencyClosure.requested_at)
            )
        )


def _forget_throttles(db) -> None:
    with Session(db.migration) as session, session.begin():
        session.execute(delete(AuthRateLimit))


def _request(client, agency, name, password=None):
    body = {"confirm_name": name}
    if password is not None:
        body["password"] = password
    return client.post(f"/agencies/{agency}/closure", json=body)


def _close(w, api, agency=None, owner="owner_a", name=NAME_A):
    response = _request(w.signed_in(owner), agency or w.a, name, api.password)
    assert response.status_code == 201, response.text
    return response.json()


def _end_grace_period(db, agency) -> None:
    with db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_closures SET requested_at = now() - interval '31 days', "
                "closes_at = now() - interval '1 day' "
                "WHERE agency_id = :agency AND cancelled_at IS NULL AND completed_at IS NULL"
            ),
            {"agency": agency},
        )


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def test_sv10_closure_request_is_owner_only_named_and_reauthenticated(authenticated_world, api):
    w = authenticated_world
    for name in ("admin", "analyst", "viewer", "outsider", "owner_b"):
        refused = _request(w.signed_in(name), w.a, NAME_A, api.password)
        assert (refused.status_code, refused.json()) == (403, {"error": "access_denied"})
    owner = w.signed_in("owner_a")
    for name in ("Synthetic agency a", "Synthetic Agency A ", "Other"):
        refused = _request(owner, w.a, name, api.password)
        assert (refused.status_code, refused.json()) == (422, {"error": "confirmation_mismatch"})
    _forget_throttles(w.db)
    wrong = _request(owner, w.a, NAME_A, "Wrong password for tests 1")
    assert (wrong.status_code, wrong.json()) == (401, {"error": "invalid_credentials"})
    missing = _request(owner, w.a, NAME_A)
    assert (missing.status_code, missing.json()) == (401, {"error": "invalid_credentials"})
    assert _status(w.db, w.a) == "active" and _closures(w.db, w.a) == []
    created = _request(owner, w.a, NAME_A, api.password)
    assert created.status_code == 201, created.text
    assert _status(w.db, w.a) == "closing"
    (closure,) = _closures(w.db, w.a)
    assert closure.closes_at - closure.requested_at == timedelta(days=30)
    assert closure.requested_by_membership_id == w.owner_a and closure.cancelled_at is None
    _forget_throttles(w.db)
    again = _request(owner, w.a, NAME_A, api.password)
    assert (again.status_code, again.json()) == (409, {"error": "closure_in_progress"})
    with Session(w.db.migration) as session:
        (audit,) = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "agency.closure_requested")
        )
    assert (audit.agency_id, audit.actor_kind, audit.actor_user_id) == (
        w.a,
        "user",
        w.users.owner_a,
    )
    assert (audit.resource_type, audit.resource_id) == ("agency_closure", closure.id)
    assert _status(w.db, w.b) == "active"


def test_sv10_the_closure_throttle_and_the_reauthentication_without_a_password(
    authenticated_world, api
):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    for _ in range(3):
        assert _request(owner, w.a, "Not the name", api.password).status_code == 422
    throttled = _request(owner, w.a, NAME_A, api.password)
    assert throttled.status_code == 429 and int(throttled.headers["retry-after"]) > 0
    assert _status(w.db, w.a) == "active"
    _forget_throttles(w.db)
    # An account without a password needs a session created within the reauthentication
    # window (account closure, D-024).
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            delete(PasswordCredential).where(PasswordCredential.user_id == w.users.owner_a)
        )
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == w.users.owner_a)
            .values(created_at=now_utc() - timedelta(minutes=11))
        )
    stale = _request(owner, w.a, NAME_A)
    assert (stale.status_code, stale.json()) == (403, {"error": "reauthentication_required"})
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == w.users.owner_a)
            .values(created_at=now_utc())
        )
    assert _request(owner, w.a, NAME_A).status_code == 201
    assert _status(w.db, w.a) == "closing"


def test_sv12_cancellation_restores_the_agency_and_its_connections(lab, api):
    w = lab.w
    connection = lab.connect("owner_a", w.a, w.a1)
    assert lab.worker()["sync"] == {"succeeded": 1}
    state = _close(w, api)
    assert state["agency_status"] == "closing" and state["closure"]["id"]
    owner = w.signed_in("owner_a")
    # The connection is not revoked; the agency stops.
    assert lab.row(connection).status == "active"
    assert all(lab.provider.token_usable(token) for token in lab.tokens(connection).values())
    assert owner.get(f"/agencies/{w.a}").status_code == 403
    read = owner.get(f"/agencies/{w.a}/closure")
    assert read.status_code == 200 and read.json() == state
    listed = {item["agency_id"]: item for item in owner.get("/agencies").json()}
    assert listed[str(w.a)] == {"agency_id": str(w.a), "role": "owner", "status": "closing"}
    admin = w.signed_in("admin")
    assert str(w.a) not in {item["agency_id"] for item in admin.get("/agencies").json()}
    assert admin.get(f"/agencies/{w.a}/closure").status_code == 403
    assert admin.delete(f"/agencies/{w.a}/closure").status_code == 403
    # An Owner cancels within the grace period.
    assert owner.delete(f"/agencies/{w.a}/closure").status_code == 204
    assert _status(w.db, w.a) == "active"
    assert owner.get(f"/agencies/{w.a}/closure").json() == {
        "agency_id": str(w.a),
        "agency_status": "active",
        "closure": None,
    }
    (closure,) = _closures(w.db, w.a)
    assert closure.cancelled_by_membership_id == w.owner_a and closure.completed_at is None
    again = owner.delete(f"/agencies/{w.a}/closure")
    assert (again.status_code, again.json()) == (409, {"error": "closure_not_open"})
    # The connection works again without a reconnect.
    assert lab.sync("owner_a", w.a, w.a1, connection).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}
    with Session(w.db.migration) as session:
        actions = list(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.action.like("agency.closure_%"))
            )
        )
    assert sorted(actions) == ["agency.closure_cancelled", "agency.closure_requested"]
    # After closes_at the closure can no longer be cancelled, even before the runner ran.
    _forget_throttles(w.db)
    _close(w, api)
    _end_grace_period(w.db, w.a)
    late = owner.delete(f"/agencies/{w.a}/closure")
    assert (late.status_code, late.json()) == (409, {"error": "grace_period_ended"})
    assert _status(w.db, w.a) == "closing"


def test_sv13_lifecycle_completes_due_closures_once_and_in_bounded_batches(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    _close(w, api)
    _close(w, api, w.b, "owner_b", NAME_B)
    closes_at = {agency: _closures(w.db, agency)[0].closes_at for agency in (w.a, w.b)}
    early = min(closes_at.values()) - timedelta(microseconds=1)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=early)
    assert "agency_closures_completed" not in result["deleted"]
    assert _status(w.db, w.a) == _status(w.db, w.b) == "closing"
    # Bounded: one closure per batch and one batch per run.
    later = max(closes_at.values())
    small = lifecycle_settings.model_copy(update={"lifecycle_batch_size": 1})
    first = run_lifecycle(lifecycle_engine, small, cutoff=later, max_batches=1)
    assert first["deleted"]["agency_closures_completed"] == 1
    assert "agency_closures" in first["incomplete"]
    second = run_lifecycle(lifecycle_engine, small, cutoff=later, max_batches=1)
    assert second["deleted"]["agency_closures_completed"] == 1
    assert _status(w.db, w.a) == _status(w.db, w.b) == "closed"
    for agency in (w.a, w.b):
        (closure,) = _closures(w.db, agency)
        assert closure.completed_at == later and closure.cancelled_at is None
    # Idempotent: nothing is completed twice.
    third = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=later + timedelta(days=1))
    assert "agency_closures_completed" not in third["deleted"]
    assert third["status"] == "completed"
    # A closed agency is refused for everyone, also its Owners, and nothing reopens it.
    owner = w.signed_in("owner_a")
    for method in ("get", "delete"):
        assert getattr(owner, method)(f"/agencies/{w.a}/closure").status_code == 403
    assert _request(owner, w.a, NAME_A, api.password).status_code == 403
    assert owner.get(f"/agencies/{w.a}").status_code == 403
    assert owner.get("/agencies").json() == []
    assert agency_plans.run(w.db.runtime, "reactivate", agency=w.a) == (
        1,
        {"error": "not_suspended", "status": "closed"},
    )
    assert agency_plans.run(w.db.runtime, "suspend", agency=w.a)[1]["error"] == "not_active"
    assert agency_plans.run(
        w.db.runtime, "assign", agency=w.a, plan="development", reason="correction"
    ) == (1, {"error": "agency_closed"})


def test_sv13_a_cancellation_holding_the_agency_lock_leaves_the_step_incomplete(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    _close(w, api)
    (closure,) = _closures(w.db, w.a)
    with w.db.runtime.connect() as holder:
        holder.execute(select(Agency.id).where(Agency.id == w.a).with_for_update())
        result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=closure.closes_at)
        holder.rollback()
    assert "agency_closures" in result["incomplete"] and result["status"] == "partial"
    assert _status(w.db, w.a) == "closing"
    done = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=closure.closes_at)
    assert done["deleted"]["agency_closures_completed"] == 1


def _close_account(client, password):
    return client.post("/auth/close-account", json={"password": password})


@pytest.mark.parametrize("status", ["active", "suspended", "closing", "closed"])
def test_sv14_sole_owner_account_closure_by_agency_status(
    authenticated_world, api, lifecycle_engine, lifecycle_settings, status
):
    w = authenticated_world  # owner_b is the sole Owner of agency B
    if status == "suspended":
        assert agency_plans.run(w.db.runtime, "suspend", agency=w.b)[0] == 0
    elif status in {"closing", "closed"}:
        _close(w, api, w.b, "owner_b", NAME_B)
        if status == "closed":
            (closure,) = _closures(w.db, w.b)
            run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=closure.closes_at)
    assert _status(w.db, w.b) == status
    response = _close_account(w.signed_in("owner_b"), api.password)
    if status in {"active", "suspended"}:
        assert (response.status_code, response.json()) == (409, {"error": "state_conflict"})
        return
    assert response.status_code == 204
    with Session(w.db.migration) as session:
        statuses = dict(
            session.execute(
                text(
                    "SELECT u.status, m.status FROM users u JOIN agency_memberships m "
                    "ON m.user_id = u.id WHERE u.id = :user"
                ),
                {"user": w.users.owner_b},
            ).all()
        )
    assert statuses == {"disabled": "disabled"}
    # A closing agency left without an Owner completes at closes_at.
    if status == "closing":
        (closure,) = _closures(w.db, w.b)
        run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=closure.closes_at)
        assert _status(w.db, w.b) == "closed"


def test_sv14_a_sole_owner_is_still_held_by_another_active_agency(authenticated_world, api):
    w = authenticated_world
    # owner_b is the sole Owner of agency B and of a new agency C.
    with tenancy_transaction(w.db.runtime, w.users.owner_b) as service:
        agency_c = service.create_agency("Synthetic Agency C").id
    _close(w, api, w.b, "owner_b", NAME_B)
    held = _close_account(w.signed_in("owner_b"), api.password)
    assert (held.status_code, held.json()) == (409, {"error": "state_conflict"})
    _forget_throttles(w.db)
    _close(w, api, agency_c, "owner_b", "Synthetic Agency C")
    assert _close_account(w.signed_in("owner_b"), api.password).status_code == 204


def test_sv19_closure_isolation_and_logs(authenticated_world, api, capfd):
    w = authenticated_world
    other = w.signed_in("owner_b")
    assert _request(other, w.a, NAME_A, api.password).status_code == 403
    _close(w, api)
    assert other.get(f"/agencies/{w.a}/closure").status_code == 403
    assert other.delete(f"/agencies/{w.a}/closure").status_code == 403
    assert other.get(f"/agencies/{w.b}/closure").json()["agency_status"] == "active"
    assert other.get(f"/agencies/{w.b}").status_code == 200
    assert _status(w.db, w.a) == "closing"
    captured = capfd.readouterr()
    for private in (api.password, "@example.test", NAME_A, "tracking_session="):
        assert private not in captured.out + captured.err
    assert isinstance(UUID(str(w.a)), UUID)
