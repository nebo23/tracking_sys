"""Provider webhooks on disposable PostgreSQL (specification 009-D, D-049).

Uses the synthetic lab of connector_support: K1 (agency A, client A1), K2 (A, A2), and K3
(agency B, client B1) all connect syn-acct-777. Deliveries are signed by the synthetic provider
with the Spec 004 scheme and posted to the public route without any session or credential.
"""

import json
import threading
from datetime import timedelta

import pytest
from connector_support import ACCOUNT, make_lab
from connector_support import archive as _archive
from connector_support import fail_connection as _fail_k
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.collection.contract import sign_webhook
from app.connectors.contracts import WebhookDelivery
from app.models import ConnectorSyncRun, ConnectorWebhookDelivery
from app.security import now_utc
from app.services.connector_webhooks import event_digest, receive_delivery
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
PATH = "/connectors/webhooks/synthetic"


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _body(event_id, account=ACCOUNT):
    return json.dumps({"event_id": event_id, "account_id": account}).encode()


def _post(client, body, signature):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Synthetic-Signature"] = signature
    return client.post(PATH, content=body, headers=headers)


def _deliver(lab, client, event_id, account=ACCOUNT):
    body = _body(event_id, account)
    return _post(client, body, lab.provider.sign_delivery(body, int(now_utc().timestamp())))


def _open_runs(lab, *connections):
    with Session(lab.w.db.migration) as session:
        return [
            session.scalar(
                select(func.count())
                .select_from(ConnectorSyncRun)
                .where(
                    ConnectorSyncRun.connection_id == connection_id,
                    ConnectorSyncRun.status.in_(("queued", "running")),
                )
            )
            for connection_id in connections
        ]


def _deliveries(lab):
    with Session(lab.w.db.migration) as session:
        rows = session.scalars(
            select(ConnectorWebhookDelivery).order_by(ConnectorWebhookDelivery.received_at)
        ).all()
    return [(row.provider, row.event_digest, row.notified) for row in rows]


def test_009d_a_verified_delivery_has_one_scoped_effect_per_connection(lab, api):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    k4 = lab.connect("owner_a", w.a, w.a1, account="syn-other")
    assert lab.worker()["sync"] == {"succeeded": 4}
    sender = api.new_client(lab.config)
    response = _deliver(lab, sender, "evt-1")
    assert (response.status_code, response.json()) == (200, {"result": "accepted"})
    # One incremental run for each active connection of the account, in its own scope.
    assert _open_runs(lab, k1, k2, k3, k4) == [1, 1, 1, 0]
    assert _deliveries(lab) == [("synthetic", event_digest("evt-1"), 3)]
    with Session(w.db.migration) as session:
        queued = session.scalars(
            select(ConnectorSyncRun).where(ConnectorSyncRun.status == "queued")
        ).all()
    assert {(run.connection_id, run.kind) for run in queued} == {
        (k1, "incremental"),
        (k2, "incremental"),
        (k3, "incremental"),
    }
    # A repeated delivery, freshly signed, has no further effect.
    response = _deliver(lab, sender, "evt-1")
    assert (response.status_code, response.json()) == (200, {"result": "duplicate"})
    assert _open_runs(lab, k1, k2, k3, k4) == [1, 1, 1, 0]
    assert len(_deliveries(lab)) == 1
    assert lab.worker()["sync"] == {"succeeded": 3}
    # An account no connection holds: the same response and no effect.
    response = _deliver(lab, sender, "evt-2", account="syn-unknown")
    assert (response.status_code, response.json()) == (200, {"result": "accepted"})
    assert _open_runs(lab, k1, k2, k3, k4) == [0, 0, 0, 0]
    # A connection with an open run is not queued twice.
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    assert _deliver(lab, sender, "evt-3").json() == {"result": "accepted"}
    assert _open_runs(lab, k1, k2, k3, k4) == [1, 1, 1, 0]
    assert [item[2] for item in _deliveries(lab)] == [3, 0, 3]
    assert lab.worker()["sync"] == {"succeeded": 3}


def test_009d_refused_deliveries_cause_no_ingestion(lab, api):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    assert lab.worker()["sync"] == {"succeeded": 1}
    sender = api.new_client(lab.config)
    body = _body("evt-x")
    now = int(now_utc().timestamp())
    signed = lab.provider.sign_delivery
    cases = [
        (body, None, 401, "signature_invalid"),
        (body, "garbage", 401, "signature_invalid"),
        (body, f"t={now},v1={sign_webhook('another-secret', now, body)}", 401, "signature_invalid"),
        (_body("evt-y"), signed(body, now), 401, "signature_invalid"),
        (body, signed(body, now - 301), 401, "signature_expired"),
        (b'{"event_id": 1, "account_id": "x"}', None, 400, "invalid_delivery"),
        (b"not json", None, 400, "invalid_delivery"),
        (b'{"event_id": "evt-z"}', None, 400, "invalid_delivery"),
    ]
    for payload, signature, status, error in cases:
        if signature is None and status == 400:
            signature = signed(payload, now)
        response = _post(sender, payload, signature)
        assert (response.status_code, response.json()) == (status, {"error": error}), payload
    oversized = b"{" + b" " * 16384 + b"}"
    response = _post(sender, oversized, signed(oversized, now))
    assert (response.status_code, response.json()) == (413, {"error": "request_too_large"})
    response = sender.post("/connectors/webhooks/other", content=body)
    assert (response.status_code, response.json()) == (404, {"error": "provider_unavailable"})
    assert _deliveries(lab) == [] and _open_runs(lab, k1) == [0]
    # The event ID was not consumed by the refused attempts.
    assert _post(sender, body, signed(body, now)).json() == {"result": "accepted"}
    assert _open_runs(lab, k1) == [1]


def test_009d_deliveries_skip_inactive_connections_and_follow_disconnect(lab, api):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    sender = api.new_client(lab.config)
    _archive(w, w.a2)
    _fail_k(lab, w.b, w.b1, k3, owner="owner_b")
    assert _deliver(lab, sender, "evt-1").json() == {"result": "accepted"}
    assert _open_runs(lab, k1, k2, k3) == [1, 0, 0]
    assert lab.worker()["sync"] == {"succeeded": 1}
    # Disconnecting and disconnected connections receive nothing.
    assert lab.disconnect("owner_a", w.a, w.a1, k1).status_code == 202
    assert _deliver(lab, sender, "evt-2").json() == {"result": "accepted"}
    assert _open_runs(lab, k1, k2, k3) == [0, 0, 0]
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert _deliver(lab, sender, "evt-3").json() == {"result": "accepted"}
    assert _open_runs(lab, k1, k2, k3) == [0, 0, 0]
    assert [item[2] for item in _deliveries(lab)] == [1, 0, 0]
    # A reactivated client receives deliveries again.
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a2, status="active")
    assert _deliver(lab, sender, "evt-4").json() == {"result": "accepted"}
    assert _open_runs(lab, k1, k2, k3) == [0, 1, 0]


def test_009d_concurrent_repeats_have_one_effect(lab):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    outcomes, barrier = [], threading.Barrier(2)

    def submit():
        barrier.wait()
        delivery = WebhookDelivery("evt-race", ACCOUNT)
        outcomes.append(receive_delivery(w.db.runtime, "synthetic", delivery, now_utc()))

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "duplicate"]
    assert _open_runs(lab, k1, k2, k3) == [1, 1, 1]
    assert _deliveries(lab) == [("synthetic", event_digest("evt-race"), 3)]


def test_009d_privileges_and_lifecycle(lab, lifecycle_engine, lifecycle_settings):
    w = lab.w
    lab.connect("owner_a", w.a, w.a1)
    received = now_utc()
    assert (
        receive_delivery(w.db.runtime, "synthetic", WebhookDelivery("evt-1", ACCOUNT), received)
        == "accepted"
    )
    for statement in (
        "DELETE FROM connector_webhook_deliveries",
        "UPDATE connector_webhook_deliveries SET event_digest = event_digest",
        "UPDATE connector_webhook_deliveries SET provider = provider",
        "UPDATE connector_webhook_deliveries SET received_at = received_at",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            with w.db.runtime.begin() as connection:
                connection.execute(text(statement))
    # tracking_lifecycle deletes delivery records 7 days after receipt.
    result = run_lifecycle(
        lifecycle_engine, lifecycle_settings, cutoff=received + timedelta(days=7)
    )
    assert result["deleted"]["connector_webhook_deliveries"] == 0
    later = received + timedelta(days=7, minutes=1)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=later)
    assert result["deleted"]["connector_webhook_deliveries"] == 1
    assert _deliveries(lab) == []
