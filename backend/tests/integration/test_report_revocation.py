"""016-C automatic revocation on disposable PostgreSQL (D-095 D7, RV06-RV08).

A 004 subject erasure, a 006 person erasure and the erasure of held events revoke the client's
earlier exports; every cause of disconnection, the operator purge and the archival of a client
revoke the exports they cover. Three cases run with real concurrency: a reservation discarded
by an erasure is built again after it, an erasure waits for the export lock of a reservation,
and an erasure waits for a store in progress and then revokes the stored export.
"""

# ruff: noqa: F811

import threading
import time
from datetime import date, timedelta
from uuid import UUID

import pytest
from report_support import connection
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_identity_admin import (  # noqa: F401
    email,
    erase,
    identity_url,
    idw,
    ok,
    people,
    resolve,
    shared_tablet,
)
from test_report_exports import (  # noqa: F401
    bodies,
    content,
    create,
    created,
    download,
    exports_url,
    fixed_clock,
    instagram,
    row,
)

from app.connector_purge import purge_provider
from app.models import ConnectorConnection, SubjectDeletionRequest
from app.security import now_utc
from app.services.access import Principal, resolve_scope
from app.services.agency_closure import GRACE_PERIOD
from app.services.collection import client_lock_key
from app.services.connectors import start_disconnect
from app.services.report_exports import LOCK_NAMESPACE, ExportRequest, create_export
from app.services.reporting import ReportQuery
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration


def states(w, items) -> dict[str, tuple[str, str | None]]:
    result = {}
    for item in items:
        stored = row(w, item["id"])
        result[item["id"]] = (stored.status, stored.revoked_reason)
    return result


def request_row(w, request_id) -> SubjectDeletionRequest:
    with Session(w.db.migration) as session:
        item = session.get(SubjectDeletionRequest, UUID(str(request_id)))
        assert item is not None
        session.expunge(item)
        return item


def subject_erasure(reader, w, token, client=None):
    response = reader.post(
        f"/agencies/{w.a}/clients/{client or w.a1}/deletion-requests",
        json={"subject_token": token},
    )
    assert response.status_code == 201, response.text
    return response.json()


def waiting(w, locktype: str) -> bool:
    with w.db.migration.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted AND locktype = :kind"),
                {"kind": locktype},
            ).scalar_one()
        )


def wait_for(predicate, seconds: float = 1.5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --- RV06: erasures -----------------------------------------------------------------------------


def test_rv06_subject_erasure_revokes_earlier_exports(idw):
    w = idw.w
    owner = idw.owner
    token = idw.browser_subject()["subject_token"]
    idw.event(token)
    families = bodies(w)
    earlier = [created(owner, w, families["social"]), created(owner, w, families["revenue"])]
    elsewhere = created(owner, w, families["revenue"], client=w.a2)
    request = subject_erasure(owner, w, token)
    assert request["target_outcomes"]["report_exports"] == "done"
    assert set(states(w, earlier).values()) == {("revoked", "erasure")}
    assert all(content(w, item["id"]) is None for item in earlier)
    assert row(w, elsewhere["id"]).status == "ready"
    later = created(owner, w, families["revenue"])
    assert download(owner, w, later["id"]).status_code == 200
    # Without a ready export the erasure keeps its 004 outcome set, so nothing changes for it.
    other = idw.browser_subject()["subject_token"]
    idw.event(other)
    owner.delete(f"{exports_url(w)}/{later['id']}")
    second = subject_erasure(owner, w, other)
    assert set(second["target_outcomes"]) == {
        "collected_events",
        "consent_records",
        "collection_subjects",
        "event_diagnostics",
        "booking_links",
    }
    assert row(w, elsewhere["id"]).status == "ready"


def test_rv06_person_erasure_revokes_earlier_exports(idw, db):
    w = idw.w
    owner = idw.owner
    token = idw.browser_subject()["subject_token"]
    idw.event(token)
    ok(idw.via_browser(token, [email(idw, "export-person@example.test")]))
    (person,) = people(db, w.a1)
    families = bodies(w)
    earlier = created(owner, w, families["funnel"])
    elsewhere = created(owner, w, families["revenue"], client=w.a2)
    request = ok(erase(idw, subject_id=str(person)))
    assert request["status"] == "completed"
    assert request["target_outcomes"]["report_exports"] == "done"
    assert states(w, [earlier]) == {earlier["id"]: ("revoked", "erasure")}
    assert row(w, elsewhere["id"]).status == "ready"
    later = created(owner, w, families["funnel"])
    assert row(w, later["id"]).status == "ready"


def test_rv06_held_event_erasure_revokes(idw, db):
    w = idw.w
    owner = idw.owner
    tablet, sara, omar, ali, before, hers, ambiguous = shared_tablet(idw, db)
    first = ok(erase(idw, subject_id=str(sara)))
    assert first["status"] == "on_hold" and "report_exports" not in first["target_outcomes"]
    # An export built while the request is on hold may count its held events.
    between = created(owner, w, bodies(w)["funnel"])
    erased = ok(resolve(idw, first["id"], unresolved_events="erase"), 200)
    assert erased["status"] == "completed"
    assert erased["target_outcomes"]["report_exports"] == "done"
    assert erased["target_outcomes"]["unresolved_events"] == "done"
    assert states(w, [between]) == {between["id"]: ("revoked", "erasure")}


def test_rv06_reservation_during_erasure_is_rebuilt(idw, monkeypatch):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    idw.event(token)
    body = bodies(w)["social"]
    creator, admin = w.signed_in("owner_a"), w.signed_in("admin")
    paused, release, reservations = threading.Event(), threading.Event(), []

    def hook(export_id):
        reservations.append(export_id)
        if len(reservations) == 1:
            paused.set()
            assert release.wait(30)

    monkeypatch.setattr("app.services.report_exports.before_build", hook)
    result = {}
    thread = threading.Thread(target=lambda: result.update(response=create(creator, w, body)))
    thread.start()
    try:
        assert paused.wait(30)
        request = subject_erasure(admin, w, token)
    finally:
        release.set()
        thread.join(60)
    response = result["response"]
    assert response.status_code == 201, response.text
    # The reservation built before the erasure committed was discarded, never stored; the
    # export was built again after the erasure.
    first, stored = reservations
    assert UUID(response.json()["id"]) == stored != first
    assert (row(w, first).status, row(w, first).revoked_reason) == ("discarded", "erasure")
    assert "report_exports" not in request["target_outcomes"]
    erased_at = request_row(w, request["id"]).received_at
    assert row(w, stored).created_at > erased_at and row(w, stored).status == "ready"


def test_rv06_erasure_waits_for_reservation(idw):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    idw.event(token)
    item = created(idw.owner, w, bodies(w)["revenue"])
    admin = w.signed_in("admin")
    result = {}
    with w.db.migration.connect() as holder:
        transaction = holder.begin()
        # A reservation of this client holds the export lock at this moment.
        holder.execute(select(func.pg_advisory_xact_lock(LOCK_NAMESPACE, client_lock_key(w.a1))))
        thread = threading.Thread(
            target=lambda: result.update(request=subject_erasure(admin, w, token))
        )
        thread.start()
        try:
            assert wait_for(lambda: waiting(w, "advisory"))
            assert thread.is_alive() and row(w, item["id"]).status == "ready"
        finally:
            transaction.commit()
            thread.join(30)
    assert result["request"]["target_outcomes"]["report_exports"] == "done"
    assert row(w, item["id"]).status == "revoked"


def test_rv06_erasure_waits_for_store_and_revokes(idw, api):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    idw.event(token)
    admin = w.signed_in("admin")
    query = ReportQuery("revenue", date(2026, 11, 1), date(2026, 11, 3), False)
    result = {}
    with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
        access = resolve_scope(
            session, Principal("user", w.users.owner_a), w.a, w.a1, "finance:read"
        )
        export_id = create_export(
            w.db.runtime,
            session,
            api.config,
            {},
            ExportRequest(access, query, True, w.owner_a),
            audit_actor=None,
        )
        # The store holds the ready row; the erasure's revocation must wait for it.
        thread = threading.Thread(
            target=lambda: result.update(request=subject_erasure(admin, w, token))
        )
        thread.start()
        assert wait_for(lambda: waiting(w, "transactionid"))
        assert thread.is_alive()
    thread.join(30)
    assert result["request"]["target_outcomes"]["report_exports"] == "done"
    stored = row(w, export_id)
    assert (stored.status, stored.revoked_reason) == ("revoked", "erasure")
    assert stored.stored_at is not None and content(w, export_id) is None


# --- RV07: disconnection and purge --------------------------------------------------------------


def test_rv07_disconnection_revokes_its_exports_only(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    families = bodies(w)
    social = created(owner, w, families["social"])
    spend, roas = created(owner, w, families["spend"]), created(owner, w, families["roas"])
    revenue = created(owner, w, families["revenue"])
    other = created(
        owner, w, {"family": "social", "connection_id": str(instagram(w)), "view": "daily"}
    )
    base = f"/agencies/{w.a}/clients/{w.a1}/connections"
    response = owner.post(f"{base}/{families['social']['connection_id']}/disconnect")
    assert response.status_code == 202, response.text
    assert states(w, [social, spend, roas, revenue, other]) == {
        social["id"]: ("revoked", "disconnection"),
        spend["id"]: ("ready", None),
        roas["id"]: ("ready", None),
        revenue["id"]: ("ready", None),
        other["id"]: ("ready", None),
    }
    # A stopped connection exports nothing any more.
    refused = create(owner, w, families["social"])
    assert refused.status_code == 409 and refused.json()["error"] == "source_unavailable"
    response = owner.post(f"{base}/{families['spend']['connection_id']}/disconnect")
    assert response.status_code == 202, response.text
    assert states(w, [spend, roas, revenue]) == {
        spend["id"]: ("revoked", "disconnection"),
        roas["id"]: ("revoked", "disconnection"),
        revenue["id"]: ("ready", None),
    }


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("user_requested", "disconnection"),
        ("authorization_lost", "disconnection"),
        ("deauthorized", "disconnection"),
        ("deletion_requested", "disconnection"),
        ("operator_purged", "connection_purged"),
    ],
)
def test_rv07_every_disconnection_cause_revokes(authenticated_world, api, reason, expected):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)["social"]
    item = created(owner, w, body)
    with Session(w.db.runtime) as session, session.begin():
        target = session.get(ConnectorConnection, UUID(body["connection_id"]), with_for_update=True)
        start_disconnect(session, api.config, target, reason, now_utc())
    assert states(w, [item]) == {item["id"]: ("revoked", expected)}


def test_rv07_purge_revokes(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    youtube = connection(w, w.a1, "synthetic_youtube")
    kept = instagram(w)
    purged = created(owner, w, {"family": "social", "connection_id": str(youtube), "view": "daily"})
    other = created(owner, w, {"family": "social", "connection_id": str(kept), "view": "daily"})
    counts = purge_provider(w.db.runtime, api.config, {}, "synthetic_youtube")
    assert counts["stopped"] == 1
    assert states(w, [purged, other]) == {
        purged["id"]: ("revoked", "connection_purged"),
        other["id"]: ("ready", None),
    }


# --- RV08: archival and closure -----------------------------------------------------------------


def test_rv08_archival_revokes(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    families = bodies(w)
    archived = [created(owner, w, families["social"]), created(owner, w, families["revenue"])]
    elsewhere = created(owner, w, families["revenue"], client=w.a2)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a1, name="Synthetic renamed client")
    assert {state for state, _ in states(w, archived).values()} == {"ready"}
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a1, status="archived")
    assert set(states(w, archived).values()) == {("revoked", "client_archived")}
    assert row(w, elsewhere["id"]).status == "ready"
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a1, status="active")
    assert set(states(w, archived).values()) == {("revoked", "client_archived")}
    listed = {item["status"] for item in owner.get(exports_url(w)).json()["exports"]}
    assert listed == {"revoked"}


def test_rv08_closing_agency_exports_unreachable(authenticated_world, api):
    w = authenticated_world
    owner, viewer = w.signed_in("owner_a"), w.signed_in("viewer")
    item = created(viewer, w, bodies(w)["social"])
    with w.db.migration.begin() as connection:
        connection.execute(text("UPDATE agencies SET status = 'closing' WHERE id = :a"), {"a": w.a})
    try:
        for reader in (owner, viewer):
            assert reader.get(exports_url(w)).status_code == 403
            assert download(reader, w, item["id"]).status_code == 403
        assert create(owner, w, bodies(w)["revenue"]).status_code == 403
    finally:
        with w.db.migration.begin() as connection:
            connection.execute(
                text("UPDATE agencies SET status = 'active' WHERE id = :a"), {"a": w.a}
            )
    # Every export expires before a closing agency's grace period ends.
    assert timedelta(days=api.config.report_export_lifetime_days) < GRACE_PERIOD
    limit = type(api.config).model_fields["report_export_lifetime_days"].metadata
    assert any(getattr(bound, "le", None) == 7 for bound in limit)
