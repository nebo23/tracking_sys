"""Instagram-shaped connector runtime on disposable PostgreSQL (specification 010-A, D-053).

Uses the synthetic lab of connector_support with the Instagram-shaped synthetic provider that
the API builds next to the 009 provider. Agency A connects ig-acct-1 in clients A1 (K1) and A2
(K2), and agency B connects it in client B1 (K3); nothing is shared between them. No case
contacts Meta: the provider reproduces documented shapes only.
"""

from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import pytest
from connector_support import archive as _archive
from connector_support import make_lab
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.connectors.synthetic import OBSERVED_AT
from app.connectors.synthetic_instagram import SyntheticInstagramProvider
from app.models import (
    ConnectorCheckpoint,
    ConnectorDeletionRequest,
    ConnectorRecord,
    ConnectorSyncRun,
)
from app.security import now_utc
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
PROVIDER = "synthetic_instagram"
ACCOUNT = "ig-acct-1"
STREAMS = ("account", "media", "stories")
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def ig(authenticated_world, api, tmp_path):
    lab = make_lab(authenticated_world, api, tmp_path)
    state = lab.state.with_name(lab.state.stem + "-instagram" + lab.state.suffix)
    lab.ig = SyntheticInstagramProvider(state)
    lab.registry = {PROVIDER: lab.ig}
    lab.public = api.new_client(lab.config)
    return lab


def _connect(lab, name, agency, client_id, account=ACCOUNT, kind="business"):
    browser = lab.browser(name)
    base = f"/agencies/{agency}/clients/{client_id}/connections"
    response = browser.post(base, json={"provider": PROVIDER})
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    assert "code_challenge" not in query and "code_challenge_method" not in query
    code = lab.ig.approve(url, account, "Synthetic Studio", kind)
    response = browser.get(
        "/connectors/oauth/callback",
        params={"code": code, "state": query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    result = {
        key: values[0]
        for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }
    assert result["result"] == "connected", result
    return UUID(result["connection_id"])


def _work(lab, now=None, schedule=False):
    return lab.worker(now=now, registry=lab.registry, schedule=schedule)


def _records(lab, name, agency, client_id, connection_id, stream=None):
    query = "" if stream is None else "?" + urlencode({"stream": stream})
    response = lab.browser(name).get(
        f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/records{query}"
    )
    assert response.status_code == 200, response.text
    return response.json()["records"]


def _coverage(lab, name, agency, client_id, connection_id):
    response = lab.browser(name).get(
        f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/coverage"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _count(lab, model, connection_id, **filters):
    with Session(lab.w.db.migration) as session:
        query = select(func.count()).select_from(model).where(model.connection_id == connection_id)
        for name, value in filters.items():
            query = query.where(getattr(model, name) == value)
        return session.scalar(query)


def _signed(lab, path, account=ACCOUNT, issued=None, secret=None):
    signed = lab.ig.sign_request(account, issued or now_utc(), secret=secret)
    return lab.public.post(path, content=urlencode({"signed_request": signed}), headers=FORM)


def _fixtures(lab):
    w = lab.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k2 = _connect(lab, "owner_a", w.a, w.a2, kind="creator")
    k3 = _connect(lab, "owner_b", w.b, w.b1)
    return k1, k2, k3


def test_010a_streams_product_types_and_isolation(ig):
    lab, w = ig, ig.w
    k1, k2, k3 = _fixtures(lab)
    # Each connection queues one run per stream; the worker reads every stream independently.
    for connection in (k1, k2, k3):
        assert {
            stream: _count(lab, ConnectorSyncRun, connection, stream=stream) for stream in STREAMS
        } == dict.fromkeys(STREAMS, 1)
    assert _work(lab)["sync"] == {"succeeded": 9}
    for connection in (k1, k2, k3):
        assert _count(lab, ConnectorRecord, connection, stream="account") == 3
        assert _count(lab, ConnectorRecord, connection, stream="media") == 3
        assert _count(lab, ConnectorRecord, connection, stream="stories") == 2
        assert _count(lab, ConnectorCheckpoint, connection) == 3

    # Account insights are the default stream; media carry their product type.
    account = _records(lab, "owner_a", w.a, w.a1, k1)
    assert {item["stream"] for item in account} == {"account"}
    assert all(item["product_type"] is None for item in account)
    assert account[0]["metrics"]["reach"]["state"] == "observed"
    media = _records(lab, "owner_a", w.a, w.a1, k1, "media")
    by_type = {item["product_type"]: item for item in media}
    assert set(by_type) == {"FEED", "REELS"}
    feed, reels = by_type["FEED"]["metrics"], by_type["REELS"]["metrics"]
    assert feed["profile_visits"]["state"] == "observed"
    assert feed["ig_reels_avg_watch_time"] == {
        "state": "unsupported",
        "value": None,
        "reason": None,
    }
    assert reels["ig_reels_avg_watch_time"]["state"] == "observed"
    assert reels["profile_visits"]["state"] == "unsupported"
    stories = _records(lab, "owner_a", w.a, w.a1, k1, "stories")
    assert {item["product_type"] for item in stories} == {"STORY"}
    # The D-054 story catalog, as the 010-B evidence showed it.
    assert set(stories[0]["metrics"]) == {
        "reach",
        "views",
        "replies",
        "navigation",
        "shares",
        "follows",
        "profile_visits",
        "total_interactions",
    }
    assert lab.browser("owner_a").get(
        f"/agencies/{w.a}/clients/{w.a1}/connections/{k1}/records?stream=unknown"
    ).status_code in {404, 422}

    # Coverage reports each stream with its own run, and metrics by stream and product type.
    body = _coverage(lab, "owner_a", w.a, w.a1, k1)
    assert [(s["stream"], s["state"], s["sync"]["state"]) for s in body["streams"]] == [
        ("account", "complete", "idle"),
        ("media", "complete", "idle"),
        ("stories", "complete", "idle"),
    ]
    metrics = {(m["stream"], m["name"]): m for m in body["metrics"]}
    assert metrics[("media", "reels_skip_rate")]["product_types"] == ["REELS"]
    assert metrics[("account", "reach")]["availability"] == "available"

    # A sync request names a stream; an unknown stream is refused.
    owner = lab.browser("owner_a")
    sync = f"/agencies/{w.a}/clients/{w.a1}/connections/{k1}/sync"
    response = owner.post(sync, json={"stream": "media"})
    assert response.status_code == 202 and response.json()["stream"] == "media"
    assert owner.post(sync, json={"stream": "objects"}).status_code == 422
    assert owner.post(sync).json()["stream"] == "account"

    # Tenants share no record: another agency's owner and an analyst without a grant are refused.
    for name, agency, client_id in (("owner_b", w.a, w.a1), ("analyst", w.a, w.a2)):
        response = lab.browser(name).get(
            f"/agencies/{agency}/clients/{client_id}/connections/{k1}/records"
        )
        assert response.status_code in {403, 404}
    assert _records(lab, "owner_b", w.b, w.b1, k3, "media")
    assert _records(lab, "owner_a", w.a, w.a2, k2, "media")


def test_010a_absent_values_carry_reasons_and_recent_values_are_provisional(ig, monkeypatch):
    import app.api.connectors as routes

    lab, w = ig, ig.w
    lab.ig.set_behavior("followers", "50")
    lab.ig.set_behavior("story_viewers", "3")
    lab.ig.set_behavior("omit_metric", "saved")
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab)["sync"] == {"succeeded": 3}
    account = _records(lab, "owner_a", w.a, w.a1, k1)[0]["metrics"]
    assert account["follows_and_unfollows"] == {
        "state": "missing",
        "value": None,
        "reason": "below_threshold",
    }
    for item in _records(lab, "owner_a", w.a, w.a1, k1, "stories"):
        assert {value["reason"] for value in item["metrics"].values()} == {"below_threshold"}
        assert all(value["value"] is None for value in item["metrics"].values())
    for item in _records(lab, "owner_a", w.a, w.a1, k1, "media"):
        assert item["metrics"]["saved"] == {
            "state": "missing",
            "value": None,
            "reason": "not_returned",
        }
    with Session(w.db.migration) as session:
        stored = session.scalars(
            select(ConnectorRecord.metrics).where(
                ConnectorRecord.connection_id == k1, ConnectorRecord.stream == "media"
            )
        ).all()
    assert all("saved" not in metrics for metrics in stored)

    # Values observed within the provider's 48-hour delay are provisional.
    monkeypatch.setattr(routes, "now_utc", lambda: OBSERVED_AT + timedelta(hours=20))
    flags = {
        item["observed_at"][:10]: item["provisional"]
        for item in _records(lab, "owner_a", w.a, w.a1, k1)
    }
    assert flags == {"2026-10-30": False, "2026-10-31": True, "2026-11-01": True}


def test_010a_self_refresh_before_expiry_and_failed_refresh(ig):
    lab, w = ig, ig.w
    k1, k2, _ = _fixtures(lab)
    start = now_utc()
    assert _work(lab, now=start)["sync"] == {"succeeded": 9}
    kinds = {row.kind for row in lab.secrets(k1)}
    assert kinds == {"access_token"}
    first = lab.tokens(k1)["access_token"]
    expiry = next(row for row in lab.secrets(k1) if row.status != "destroyed").provider_expires_at
    assert timedelta(days=59) < expiry - start <= timedelta(days=60)

    # Not yet within 7 days of expiry: no refresh.
    lab.sync("owner_a", w.a, w.a1, k1)
    assert _work(lab, now=expiry - timedelta(days=8))["sync"] == {"succeeded": 1}
    assert lab.tokens(k1)["access_token"] == first
    # Within 7 days and at least 24 hours old: the token refreshes itself before the read.
    lab.sync("owner_a", w.a, w.a1, k1)
    due = expiry - timedelta(days=6)
    assert _work(lab, now=due)["sync"] == {"succeeded": 1}
    renewed = lab.tokens(k1)["access_token"]
    assert renewed != first and lab.ig.token_usable(renewed)
    versions = lab.secrets(k1)
    assert [(row.kind, row.version, row.status) for row in versions] == [
        ("access_token", 1, "destroyed"),
        ("access_token", 2, "active"),
    ]
    assert versions[0].revocation == "not_required"
    assert ("refresh", "ok") in lab.ig.calls()
    # A fresh token is not refreshed again within 24 hours.
    calls = len(lab.ig.calls())
    lab.sync("owner_a", w.a, w.a1, k1)
    assert _work(lab, now=due + timedelta(hours=1))["sync"] == {"succeeded": 1}
    assert "refresh" not in {operation for operation, _ in lab.ig.calls()[calls:]}

    # A refused refresh leaves the connection requiring reconnection, with its data kept.
    lab.ig.set_behavior("refresh", "invalid_grant")
    lab.sync("owner_a", w.a, w.a2, k2)
    expiry2 = next(r for r in lab.secrets(k2) if r.status != "destroyed").provider_expires_at
    assert _work(lab, now=expiry2 - timedelta(days=2))["sync"] == {"stopped": 1}
    row = lab.row(k2)
    assert (row.status, row.status_reason) == ("reconnect_required", "credential_expired")
    assert _count(lab, ConnectorRecord, k2) == 8
    assert lab.row(k1).status == "active"


def test_010a_disconnect_reports_unsupported_revocation_and_purges_every_stream(ig):
    lab, w = ig, ig.w
    k1, k2, k3 = _fixtures(lab)
    assert _work(lab)["sync"] == {"succeeded": 9}
    response = lab.disconnect("owner_a", w.a, w.a1, k1)
    assert response.status_code == 202
    assert _work(lab)["teardown"] == {"disconnected": 1}
    view = lab.view("owner_a", w.a, w.a1, k1).json()
    assert view["status"] == "disconnected"
    assert view["disconnect"]["revocation"] == "unsupported"
    assert view["disconnect"]["deadline_met"] is True
    assert _count(lab, ConnectorRecord, k1) == 0 and _count(lab, ConnectorCheckpoint, k1) == 0
    assert all(row.status == "destroyed" for row in lab.secrets(k1))
    for connection in (k2, k3):
        assert _count(lab, ConnectorRecord, connection) == 8
        assert lab.row(connection).status == "active"


def test_010a_signed_requests_are_verified_before_any_effect(ig):
    lab = ig
    k1, k2, k3 = _fixtures(lab)
    path = f"/connectors/{PROVIDER}/deauthorize"
    refused = [
        (_signed(lab, path, secret="foreign-secret"), 401, "signature_invalid"),
        (_signed(lab, path, issued=now_utc() - timedelta(hours=2)), 401, "signature_expired"),
        (
            lab.public.post(path, content="signed_request=abc.def", headers=FORM),
            401,
            "signature_invalid",
        ),
        (lab.public.post(path, content="other=1", headers=FORM), 400, "invalid_delivery"),
        (lab.public.post(path, content=b"\xff\xfe", headers=FORM), 400, "invalid_delivery"),
    ]
    for response, status, code in refused:
        assert response.status_code == status, response.text
        assert response.json()["error"] == code
    # The 009 synthetic provider declares no signed requests.
    assert _signed(lab, "/connectors/synthetic/deauthorize").status_code == 404
    assert {lab.row(k).status for k in (k1, k2, k3)} == {"active"}


def test_010a_deauthorize_stops_every_connection_of_the_account(ig):
    lab, w = ig, ig.w
    k1, k2, k3 = _fixtures(lab)
    other = _connect(lab, "owner_a", w.a, w.a1, account="ig-acct-2")
    _archive(w, w.a2)
    # Twelve runs exceed one pass of ten: K2's runs are canceled because its client is archived.
    passes = [_work(lab)["sync"], _work(lab)["sync"]]
    assert sum(result.get("succeeded", 0) for result in passes) == 9
    assert sum(result.get("canceled", 0) for result in passes) == 3
    response = _signed(lab, f"/connectors/{PROVIDER}/deauthorize")
    assert response.status_code == 200 and response.json() == {"result": "accepted"}
    # Every connection of the account stops, archived client included; others do not.
    for connection in (k1, k2, k3):
        row = lab.row(connection)
        assert (row.status, row.status_reason) == ("disconnecting", "deauthorized")
    assert lab.row(other).status == "active"
    assert _work(lab)["teardown"] == {"disconnected": 3}
    for connection in (k1, k2, k3):
        assert lab.row(connection).status == "disconnected"
        assert _count(lab, ConnectorRecord, connection) == 0
    assert _count(lab, ConnectorRecord, other) == 8
    # An unknown account gets the same answer and no effect.
    response = _signed(lab, f"/connectors/{PROVIDER}/deauthorize", account="ig-unknown")
    assert response.status_code == 200 and response.json() == {"result": "accepted"}


def test_010a_data_deletion_returns_a_status_that_completes_after_the_purge(ig):
    lab, w = ig, ig.w
    k1, k2, k3 = _fixtures(lab)
    assert _work(lab)["sync"] == {"succeeded": 9}
    response = _signed(lab, f"/connectors/{PROVIDER}/data-deletion")
    assert response.status_code == 200, response.text
    receipt = response.json()
    code = receipt["confirmation_code"]
    assert receipt["url"] == (f"http://127.0.0.1:8000/connectors/{PROVIDER}/data-deletion/{code}")
    status_path = f"/connectors/{PROVIDER}/data-deletion/{code}"
    status = lab.public.get(status_path).json()
    assert (status["status"], status["completed_at"]) == ("pending", None)
    for connection in (k1, k2, k3):
        row = lab.row(connection)
        assert (row.status, row.status_reason) == ("disconnecting", "deletion_requested")
        assert row.deletion_request_id is not None
    # The first teardown pass handles one connection; the request completes with the last.
    assert _work(lab, now=None)["teardown"] == {"disconnected": 3}
    status = lab.public.get(status_path).json()
    assert status["status"] == "completed" and status["completed_at"] is not None
    with Session(w.db.migration) as session:
        request = session.scalars(select(ConnectorDeletionRequest)).one()
    assert request.connections == 3
    # No account or tenant is stored with the request.
    columns = set(ConnectorDeletionRequest.__table__.columns.keys())
    assert columns == {
        "id",
        "provider",
        "confirmation_code",
        "received_at",
        "connections",
        "completed_at",
    }
    # A request for an account with no connection completes at once; unknown codes are 404.
    response = _signed(lab, f"/connectors/{PROVIDER}/data-deletion", account="ig-unknown")
    empty = lab.public.get(
        f"/connectors/{PROVIDER}/data-deletion/{response.json()['confirmation_code']}"
    ).json()
    assert empty["status"] == "completed"
    unknown = lab.public.get(f"/connectors/{PROVIDER}/data-deletion/{'x' * 32}")
    assert unknown.status_code == 404


def test_010a_stream_intervals_privileges_and_two_year_retention(
    ig, lifecycle_engine, lifecycle_settings
):
    lab, w = ig, ig.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    t0 = now_utc()
    assert _work(lab, now=t0)["sync"] == {"succeeded": 3}
    # Stories are due every 2 hours, the other streams daily.
    later = t0 + timedelta(hours=3)
    result = _work(lab, now=later, schedule=True)
    assert result["schedule"] == {"queued": 1}
    with Session(w.db.migration) as session:
        newest = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == k1)
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert newest.stream == "stories"
    result = _work(lab, now=t0 + timedelta(hours=25), schedule=True)
    assert result["schedule"] == {"queued": 3}

    denied = (
        "UPDATE connector_deletion_requests SET confirmation_code = confirmation_code",
        "UPDATE connector_deletion_requests SET provider = provider",
        "DELETE FROM connector_deletion_requests",
        "UPDATE connector_records SET connection_id = connection_id",
    )
    for statement in denied:
        with pytest.raises(DBAPIError, match="permission denied"):
            with w.db.runtime.begin() as connection:
                connection.execute(text(statement))

    # tracking_lifecycle deletes records observed more than 730 days before the cutoff.
    total = _count(lab, ConnectorRecord, k1)
    cutoff = OBSERVED_AT + timedelta(days=730)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
    # Everything observed before the anchor day goes: two account days and two media.
    assert result["deleted"]["connector_records"] == total - 4
    assert _count(lab, ConnectorRecord, k1) == 4
