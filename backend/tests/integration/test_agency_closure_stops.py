"""A suspended or closing agency stops everywhere (017-A, D-092; SV09 and SV11).

Each case runs twice: with agency A suspended by the platform operator (SV09) and with agency A
closing at its Owner's request (SV11). Every member route, key, intake path and worker refuses
or skips the agency exactly as before, agency B is unaffected, and after reactivation or
cancellation the same probe works again. Fixture imports deliberately expose the existing
collection, link, payment, integration, WhatsApp and delivery fixtures to pytest.
"""

# ruff: noqa: F811

from datetime import timedelta

import pytest
from connector_support import make_lab
from integration_senders import calcom, uid
from paymob_callbacks import sale
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_bookings_crm import _bookings
from test_bookings_crm import lab as booking_lab  # noqa: F401
from test_collection import c, envelope, events  # noqa: F401
from test_conversion_delivery import (
    _deliver,
    _enqueue,
    _rows,
    _sale,
    _setup,
    capi,  # noqa: F401
)
from test_links import links, new_link, visit  # noqa: F401
from test_paymob import _evidence, pay  # noqa: F401
from test_whatsapp import NUMBER, _messages, wa  # noqa: F401
from whatsapp_sender import message, notification

from app import agency_plans
from app.ledger import calculate
from app.models import ConnectorSyncRun
from app.security import now_utc
from app.services import attribution_store
from app.services.delivery import candidates_from_ledger

pytestmark = pytest.mark.integration
STOPS = ("suspended", "closing")
NAME_A = "Synthetic Agency A"


def _stop(w, api, stop: str) -> None:
    if stop == "suspended":
        assert agency_plans.run(w.db.runtime, "suspend", agency=w.a)[0] == 0
        return
    response = w.signed_in("owner_a").post(
        f"/agencies/{w.a}/closure", json={"confirm_name": NAME_A, "password": api.password}
    )
    assert response.status_code == 201, response.text


def _restore(w, stop: str) -> None:
    if stop == "suspended":
        assert agency_plans.run(w.db.runtime, "reactivate", agency=w.a)[0] == 0
        return
    assert w.signed_in("owner_a").delete(f"/agencies/{w.a}/closure").status_code == 204


@pytest.fixture
def connector_lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_member_routes_and_keys_stop(authenticated_world, api, stop):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    keys = {}
    for kind in ("read", "ingest"):
        issued = owner.post(
            f"/agencies/{w.a}/service-credentials",
            json={"name": f"Stop {kind}", "kind": kind, "clients": [{"client_id": str(w.a1)}]},
        )
        assert issued.status_code == 201
        keys[kind] = api.new_client()
        keys[kind].headers["Authorization"] = "Bearer " + issued.json()["key"]
    base = f"/agencies/{w.a}"
    members = {name: w.signed_in(name) for name in ("owner_a", "admin", "analyst", "viewer")}

    def answers():
        found = {}
        for name, client in members.items():
            found[name] = (
                client.get(base).status_code,
                client.get(f"{base}/clients").status_code,
                client.get(f"{base}/clients/{w.a1}").status_code,
            )
        found["admin_write"] = (
            members["admin"].post(f"{base}/clients", json={"name": "Stop probe"}).status_code
        )
        found["plan"] = members["owner_a"].get(f"{base}/plan").status_code
        found["read_key"] = keys["read"].get(f"{base}/clients/{w.a1}").status_code
        found["ingest_key"] = (
            keys["ingest"]
            .post(f"{base}/clients/{w.a1}/events", json={"schema_version": 1})
            .status_code
        )
        return found

    before = answers()
    assert before["owner_a"] == (200, 200, 200) and before["read_key"] == 200
    _stop(w, api, stop)
    stopped = answers()
    for name in ("owner_a", "admin", "analyst", "viewer"):
        assert stopped[name] == (403, 403, 403), name
    assert stopped["admin_write"] == stopped["plan"] == 403
    assert stopped["read_key"] == stopped["ingest_key"] == 401
    listed = {item["agency_id"]: item for item in members["owner_a"].get("/agencies").json()}
    if stop == "closing":
        assert listed[str(w.a)]["status"] == "closing"
    else:
        assert str(w.a) not in listed
    assert str(w.a) not in {item["agency_id"] for item in members["admin"].get("/agencies").json()}
    # Agency B is unaffected.
    assert w.signed_in("owner_b").get(f"/agencies/{w.b}/clients").status_code == 200
    _restore(w, stop)
    restored = answers()
    assert restored["owner_a"] == (200, 200, 200)
    assert restored["read_key"] == 200 and restored["ingest_key"] == 422


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_collection_stops(c, stop):
    w = c.w
    token = c.subject()
    assert c.send(envelope(token)).status_code == 201
    accepted = len(events(c))
    _stop(w, c.api, stop)
    assert c.send(envelope(token)).status_code == 401
    public = c.collect(envelope(token))
    assert public.status_code not in {200, 201, 202}
    hook = c.webhook(envelope(token))
    assert hook.status_code not in {200, 201, 202}
    assert len(events(c)) == accepted
    _restore(w, stop)
    assert c.send(envelope(token)).status_code == 201
    assert len(events(c)) == accepted + 1


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_redirects_stop(links, stop):
    new_link(links, "stop-probe")
    visitor = links.api.new_client()
    assert visit(visitor, "stop-probe").status_code in {302, 303, 307}
    _stop(links.w, links.api, stop)
    assert visit(visitor, "stop-probe").status_code == 404
    _restore(links.w, stop)
    assert visit(visitor, "stop-probe").status_code in {302, 303, 307}


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_payments_stop(pay, stop):
    w = pay.w
    _stop(w, pay.api, stop)
    refused = pay.send(sale())
    assert (refused.status_code, refused.json()) == (401, {"error": "invalid_signature"})
    assert _evidence(w) == []
    _restore(w, stop)
    assert pay.send(sale()).status_code == 200
    assert len(_evidence(w)) == 1


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_integrations_stop(booking_lab, stop):
    w = booking_lab.w
    _stop(w, booking_lab.api, stop)
    refused = booking_lab.cal(calcom("BOOKING_CREATED", uid()))
    assert (refused.status_code, refused.json()) == (401, {"error": "invalid_signature"})
    assert _bookings(w) == []
    _restore(w, stop)
    assert booking_lab.cal(calcom("BOOKING_CREATED", uid())).status_code == 200
    assert len(_bookings(w)) == 1


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_whatsapp_stops(wa, stop):
    w = wa.w
    _stop(w, wa.api, stop)
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert _messages(w) == []
    _restore(w, stop)
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert len(_messages(w)) == 1


def _runs(lab, connection):
    with Session(lab.w.db.migration) as session:
        return [
            (run.status, run.error_kind)
            for run in session.scalars(
                select(ConnectorSyncRun)
                .where(ConnectorSyncRun.connection_id == connection)
                .order_by(ConnectorSyncRun.created_at)
            )
        ]


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_connector_worker_stops(connector_lab, api, stop):
    lab = connector_lab
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k3 = lab.connect("owner_b", w.b, w.b1)
    t0 = now_utc()
    assert lab.worker(now=t0)["sync"] == {"succeeded": 2}
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    _stop(w, api, stop)
    # The queued run of the stopped agency is cancelled; nothing is revoked.
    assert lab.worker(now=t0 + timedelta(minutes=1))["sync"] == {"canceled": 1}
    assert _runs(lab, k1)[-1] == ("canceled", "client_inactive")
    assert lab.row(k1).status == "active"
    # Scheduling queues agency B's due connection only.
    later = t0 + timedelta(hours=25)
    result = lab.worker(now=later, schedule=True)
    assert (result["schedule"], result["sync"]) == ({"queued": 1}, {"succeeded": 1})
    assert _runs(lab, k3)[-1] == ("succeeded", None)
    assert _runs(lab, k1)[-1] == ("canceled", "client_inactive")
    _restore(w, stop)
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    assert lab.worker(now=later + timedelta(minutes=1))["sync"] == {"succeeded": 1}


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_delivery_worker_stops(capi, api, stop):
    capi.api_new_client = lambda: api.new_client(capi.config)
    _, _, token = _setup(capi)
    records, journeys = _sale(capi, token)
    candidates = candidates_from_ledger(calculate(records), journeys)
    assert _enqueue(capi, candidates) == {"queued": 1}
    _stop(capi.w, api, stop)
    assert _deliver(capi) == {}
    assert [row.status for row in _rows(capi)] == ["queued"]
    records, journeys = _sale(capi, token, "sale-2")
    assert _enqueue(capi, candidates_from_ledger(calculate(records), journeys)) == {
        "client_inactive": 1
    }
    _restore(capi.w, stop)
    assert _deliver(capi) == {"delivered": 1}


@pytest.mark.parametrize("stop", STOPS)
def test_sv11_attribution_worker_skips_the_agency(authenticated_world, api, stop):
    w = authenticated_world
    assert attribution_store.run_pass(w.db.runtime)["clients"] == 4
    _stop(w, api, stop)
    assert attribution_store.run_pass(w.db.runtime)["clients"] == 2
    _restore(w, stop)
    assert attribution_store.run_pass(w.db.runtime)["clients"] == 4
