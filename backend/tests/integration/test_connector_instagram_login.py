"""Live Instagram Login adapter through the connector runtime (specification 010-C, D-055).

The API and the worker build the real InstagramProvider from settings; its transport is the
in-memory FakeGraph, which answers with the shapes the 010-B feasibility check recorded. No
case contacts Meta. Agency A connects the synthetic professional account in clients A1 (K1)
and A2 (K2); agency B's client B1 stays unconnected.
"""

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import pytest
from connector_support import make_lab
from instagram_graph import (
    APP_ID,
    APP_SCOPED_ID,
    APP_SECRET,
    PERMISSIONS,
    PRODUCT_METRICS,
    USERNAME,
    FakeGraph,
    graph_error,
)
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.connectors.instagram as instagram
from app.connectors.instagram import SCOPES
from app.models import ConnectorCheckpoint, ConnectorRecord, ConnectorSyncRun
from app.security import now_utc
from app.services.connectors import build_providers

pytestmark = pytest.mark.integration
PROVIDER = "instagram"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def live(authenticated_world, api, tmp_path, monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(instagram, "http_send", graph)
    lab = make_lab(
        authenticated_world,
        api,
        tmp_path,
        connector_instagram_enabled=True,
        instagram_app_id=APP_ID,
        instagram_app_secret=SecretStr(APP_SECRET),
    )
    lab.graph = graph
    lab.registry = build_providers(lab.config)
    assert set(lab.registry) == {
        "synthetic",
        "synthetic_instagram",
        "instagram",
        "synthetic_youtube",
    }
    lab.public = api.new_client(lab.config)
    return lab


def _connect(lab, name, agency, client_id):
    browser = lab.browser(name)
    response = browser.post(
        f"/agencies/{agency}/clients/{client_id}/connections", json={"provider": PROVIDER}
    )
    assert response.status_code == 200, response.text
    parts = urlsplit(response.json()["authorization_url"])
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://www.instagram.com/oauth/authorize"
    )
    assert (query["client_id"], query["scope"]) == (APP_ID, ",".join(SCOPES))
    assert query["redirect_uri"] == lab.config.connector_redirect_uri
    assert "code_challenge" not in query and APP_SECRET not in parts.query
    # The browser never sends the "#_" fragment Instagram appends to the redirect.
    code = lab.graph.issue_code().removesuffix("#_")
    response = browser.get(
        "/connectors/oauth/callback",
        params={"code": code, "state": query["state"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    result = {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}
    assert result["result"] == "connected", result
    assert code not in location and query["state"] not in location
    return UUID(result["connection_id"])


def _work(lab, now=None):
    return lab.worker(now=now, registry=lab.registry)


def _records(lab, agency, client_id, connection_id, stream):
    response = lab.browser("owner_a").get(
        f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/records?"
        + urlencode({"stream": stream})
    )
    assert response.status_code == 200, response.text
    return response.json()["records"]


def _count(lab, model, connection_id):
    with Session(lab.w.db.migration) as session:
        return session.scalar(
            select(func.count()).select_from(model).where(model.connection_id == connection_id)
        )


def _events(captured: str, name: str) -> list[dict]:
    lines = [json.loads(line) for line in captured.splitlines() if line.startswith("{")]
    return [entry for entry in lines if entry.get("event") == name]


def _queued(lab, connection_id, stream):
    with Session(lab.w.db.migration) as session:
        return session.scalars(
            select(ConnectorSyncRun).where(
                ConnectorSyncRun.connection_id == connection_id,
                ConnectorSyncRun.stream == stream,
                ConnectorSyncRun.status == "queued",
            )
        ).one()


def test_010c_connects_reads_every_stream_and_flags_extra_permissions(live, capsys):
    lab, w = live, live.w
    feed = lab.graph.post("FEED", timedelta(hours=3))
    reel = lab.graph.post("REELS", timedelta(days=1), "VIDEO")
    story = lab.graph.post("STORY", timedelta(hours=2))
    capsys.readouterr()
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    # Instagram granted every permission configured on the app; the grant is kept, recorded,
    # and flagged without logging the permissions themselves.
    events = _events(capsys.readouterr().err, "connector_extra_scopes")
    assert len(events) == 1 and set(events[0]) == {"timestamp", "level", "event"}
    view = lab.view("owner_a", w.a, w.a1, k1).json()
    assert view["provider"] == PROVIDER and view["status"] == "active"
    assert view["account"] == {"external_account_id": APP_SCOPED_ID, "label": USERNAME}
    assert view["granted_scopes"] == sorted(PERMISSIONS)
    token = lab.tokens(k1)["access_token"]
    assert token in lab.graph.tokens and set(lab.tokens(k1)) == {"access_token"}

    assert _work(lab)["sync"] == {"succeeded": 3}
    account = _records(lab, w.a, w.a1, k1, "account")
    assert len(account) == 7 and {item["product_type"] for item in account} == {None}
    assert account[0]["metrics"]["reach"]["state"] == "observed"
    assert account[0]["metrics"]["follows_and_unfollows"] == {
        "state": "missing",
        "value": None,
        "reason": "below_threshold",
    }
    media = {item["product_type"]: item for item in _records(lab, w.a, w.a1, k1, "media")}
    assert set(media) == {"FEED", "REELS"}
    assert media["FEED"]["provider_object_id"] == feed.id
    assert media["REELS"]["provider_object_id"] == reel.id
    for product, item in media.items():
        observed = {name for name, value in item["metrics"].items() if value["state"] == "observed"}
        assert observed == PRODUCT_METRICS[product]
    assert media["FEED"]["metrics"]["ig_reels_avg_watch_time"]["state"] == "unsupported"
    assert media["REELS"]["metrics"]["profile_visits"]["state"] == "unsupported"
    stories = _records(lab, w.a, w.a1, k1, "stories")
    assert [item["provider_object_id"] for item in stories] == [story.id]
    observed = {
        name for name, value in stories[0]["metrics"].items() if value["state"] == "observed"
    }
    assert observed == PRODUCT_METRICS["STORY"]
    coverage = lab.browser("owner_a").get(
        f"/agencies/{w.a}/clients/{w.a1}/connections/{k1}/coverage"
    )
    body = coverage.json()
    assert body["source"]["adapter_version"] == "instagram-login-v27.0"
    assert body["source"]["account_kind"] == "business"
    assert [(item["stream"], item["state"]) for item in body["streams"]] == [
        ("account", "complete"),
        ("media", "complete"),
        ("stories", "complete"),
    ]
    assert _count(lab, ConnectorCheckpoint, k1) == 3
    # Nothing in the API answers carries a token.
    for text in (json.dumps(view), json.dumps(body), json.dumps(account)):
        assert token not in text and APP_SECRET not in text


def test_010c_throttling_self_refresh_and_a_revoked_token(live):
    lab, w = live, live.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab)["sync"] == {"succeeded": 3}
    sync = lab.sync("owner_a", w.a, w.a1, k1, {"stream": "account"})
    assert sync.status_code == 202, sync.text

    # A Graph throttling answer defers the run by the adapter's wait.
    lab.graph.fail_next("insights", graph_error(4))
    start = now_utc()
    assert _work(lab, now=start)["sync"] == {"deferred": 1}
    run = _queued(lab, k1, "account")
    assert (run.error_kind, run.not_before - start) == ("rate_limited", timedelta(seconds=900))
    # So does an app usage of 90% or more, before Meta throttles.
    lab.graph.usage = 95
    assert _work(lab, now=start + timedelta(seconds=901))["sync"] == {"deferred": 1}
    lab.graph.usage = 20
    assert _work(lab, now=start + timedelta(seconds=1802))["sync"] == {"succeeded": 1}

    # Within 7 days of expiry and at least 24 hours old, the token refreshes itself.
    first = lab.tokens(k1)["access_token"]
    expiry = next(row for row in lab.secrets(k1) if row.status != "destroyed").provider_expires_at
    assert timedelta(days=59) < expiry - start <= timedelta(days=60)
    lab.graph.age(first, 25)
    lab.sync("owner_a", w.a, w.a1, k1, {"stream": "account"})
    assert _work(lab, now=expiry - timedelta(days=6))["sync"] == {"succeeded": 1}
    renewed = lab.tokens(k1)["access_token"]
    assert renewed != first and renewed in lab.graph.tokens
    assert [(row.kind, row.version, row.status, row.revocation) for row in lab.secrets(k1)] == [
        ("access_token", 1, "destroyed", "not_required"),
        ("access_token", 2, "active", None),
    ]

    # A token Meta no longer accepts, whose refresh also fails, requires reconnection.
    records = _count(lab, ConnectorRecord, k1)
    lab.graph.expire(renewed)
    lab.sync("owner_a", w.a, w.a1, k1, {"stream": "media"})
    assert _work(lab)["sync"] == {"stopped": 1}
    row = lab.row(k1)
    assert (row.status, row.status_reason) == ("reconnect_required", "credential_expired")
    assert _count(lab, ConnectorRecord, k1) == records


def test_010c_signed_requests_name_the_app_scoped_account(live):
    lab, w = live, live.w
    lab.graph.post("FEED", timedelta(hours=3))
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k2 = _connect(lab, "owner_a", w.a, w.a2)
    assert _work(lab)["sync"] == {"succeeded": 6}
    path = f"/connectors/{PROVIDER}/data-deletion"
    foreign = lab.graph.sign(APP_SCOPED_ID, now_utc(), "f" * 32)
    response = lab.public.post(path, content=urlencode({"signed_request": foreign}), headers=FORM)
    assert response.status_code == 401 and response.json()["error"] == "signature_invalid"
    assert {lab.row(k).status for k in (k1, k2)} == {"active"}
    # Meta may deliver a request hours after it signed it.
    signed = lab.graph.sign(APP_SCOPED_ID, now_utc() - timedelta(hours=2))
    response = lab.public.post(path, content=urlencode({"signed_request": signed}), headers=FORM)
    assert response.status_code == 200, response.text
    code = response.json()["confirmation_code"]
    assert response.json()["url"] == f"http://127.0.0.1:8000{path}/{code}"
    for connection in (k1, k2):
        row = lab.row(connection)
        assert (row.status, row.status_reason) == ("disconnecting", "deletion_requested")
    assert _work(lab)["teardown"] == {"disconnected": 2}
    for connection in (k1, k2):
        view = lab.view("owner_a", w.a, w.a1 if connection == k1 else w.a2, connection).json()
        assert view["status"] == "disconnected"
        assert view["disconnect"]["revocation"] == "unsupported"
        assert _count(lab, ConnectorRecord, connection) == 0
        assert all(row.status == "destroyed" for row in lab.secrets(connection))
    status = lab.public.get(f"{path}/{code}").json()
    assert status["status"] == "completed"
    # The professional account ID is not the account reference: it matches no connection.
    response = lab.public.post(
        f"/connectors/{PROVIDER}/deauthorize",
        content=urlencode({"signed_request": lab.graph.sign("17841400000000001", now_utc())}),
        headers=FORM,
    )
    assert response.status_code == 200 and response.json() == {"result": "accepted"}
