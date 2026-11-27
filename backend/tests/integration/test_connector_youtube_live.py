"""Live YouTube adapter through the connector runtime (specification 011-C, D-060).

The API and the worker build the real YouTubeProvider from settings; its transport is the
in-memory FakeYouTube, which answers with the shapes the 011-B feasibility check recorded. No
case contacts Google. Agency A connects the synthetic channel in client A1. The merge review
corrections (D-061) add a rejected client (R011-14) and a deleted channel (R011-16).
"""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from connector_support import make_lab
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from youtube_api import CHANNEL, CLIENT_ID, CLIENT_SECRET, LABEL, FakeYouTube, _error

import app.connectors.youtube as youtube
from app.config import BACKEND_ROOT
from app.connector_purge import main as purge_main
from app.connector_purge import purge_provider
from app.connectors.synthetic_youtube import ANALYTICS_SCOPE
from app.models import (
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorUsageRecord,
)
from app.services.connectors import build_providers

pytestmark = pytest.mark.integration
PROVIDER = "youtube"
APPROVAL = {"approved": True, "disclosure": "dev-agent-approval-1"}


@pytest.fixture
def live(authenticated_world, api, tmp_path, monkeypatch):
    google = FakeYouTube()
    monkeypatch.setattr(youtube, "http_send", google)
    lab = make_lab(
        authenticated_world,
        api,
        tmp_path,
        connector_youtube_enabled=True,
        youtube_client_id=CLIENT_ID,
        youtube_client_secret=SecretStr(CLIENT_SECRET),
    )
    lab.google = google
    lab.registry = build_providers(lab.config)
    assert "youtube" in lab.registry
    return lab


def _connect(lab, client_id, scopes=None):
    w = lab.w
    browser = lab.browser("owner_a")
    response = browser.post(
        f"/agencies/{w.a}/clients/{client_id}/connections",
        json={"provider": PROVIDER, "agent_approval": APPROVAL},
    )
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    response = browser.get(
        "/connectors/oauth/callback",
        params={"code": lab.google.approve(url, scopes), "state": query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return {
        key: values[0]
        for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }


def _work(lab):
    return lab.worker(registry=lab.registry, limit=20)


def _count(lab, connection_id, stream):
    with Session(lab.w.db.migration) as session:
        return session.scalar(
            select(func.count())
            .select_from(ConnectorRecord)
            .where(ConnectorRecord.connection_id == connection_id, ConnectorRecord.stream == stream)
        )


def _usage(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        rows = session.execute(
            select(ConnectorUsageRecord.bucket, func.sum(ConnectorUsageRecord.quantity))
            .where(ConnectorUsageRecord.connection_id == connection_id)
            .group_by(ConnectorUsageRecord.bucket)
        ).all()
    return dict(rows)


def test_011c_connect_read_every_stream_and_purge(live, capsys):
    lab, w = live, live.w
    result = _connect(lab, w.a1)
    assert result["result"] == "connected", result
    k1 = UUID(result["connection_id"])
    row = lab.row(k1)
    assert (row.external_account_id, row.account_label, row.agent_disclosure) == (
        CHANNEL,
        LABEL,
        "dev-agent-approval-1",
    )
    assert row.grant_expires_at is not None and row.granted_scopes

    # One run per stream reads the channel, 90 days of day reports, the uploads and the
    # lifetime totals, with the page costs reserved in each bucket.
    assert _work(lab)["sync"] == {"succeeded": 4}
    counts = {
        stream: _count(lab, k1, stream)
        for stream in ("channel", "channel_daily", "videos", "video_totals")
    }
    assert counts["channel"] == 1 and counts["videos"] == 4 and counts["video_totals"] == 4
    assert 89 <= counts["channel_daily"] <= 90
    assert _usage(lab, k1) == {"youtube_data": 6, "youtube_analytics": 5}
    with Session(w.db.migration) as session:
        stored = {
            item.provider_object_id: item
            for item in session.scalars(
                select(ConnectorRecord).where(
                    ConnectorRecord.connection_id == k1, ConnectorRecord.stream == "videos"
                )
            )
        }
    assert set(stored["v0001"].attributes) == {
        "published_at",
        "duration",
        "privacy_status",
        "live_state",
    }

    # A quota answer defers the run; a 401 gets one refresh and the read is repeated.
    lab.google.fail_next(_error(403, "quotaExceeded"))
    lab.sync("owner_a", w.a, w.a1, k1, {"stream": "channel_daily"})
    assert _work(lab)["sync"] == {"deferred": 1}
    with Session(w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == k1, ConnectorSyncRun.stream == "channel_daily")
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert (run.status, run.error_kind) == ("queued", "budget_exhausted")
    assert run.not_before.astimezone(UTC).hour in (7, 8)

    # A video confirmed deleted is purged from every stream.
    lab.google.deleted.add("v0004")
    lab.sync("owner_a", w.a, w.a1, k1, {"stream": "videos"})
    assert _work(lab)["sync"] == {"succeeded": 1}
    assert _count(lab, k1, "videos") == 3 and _count(lab, k1, "video_totals") == 3

    # The operator purge disconnects, revokes and purges every YouTube connection at once.
    tokens = lab.tokens(k1)
    assert purge_provider(w.db.runtime, lab.config, lab.registry, PROVIDER) == {
        "stopped": 1,
        "expedited": 0,
        "disconnected": 1,
    }
    row = lab.row(k1)
    assert (row.status, row.status_reason, row.revocation_status) == (
        "disconnected",
        "operator_purged",
        "done",
    )
    assert not any(lab.google.usable(token) for token in tokens.values())
    assert lab.records(k1) == 0
    with pytest.raises(SystemExit):
        purge_main(["--provider", "youtube"])
    assert "--confirm is required" in capsys.readouterr().err


def test_011c_operator_purge_does_not_wait_for_an_unavailable_revocation(live):
    lab, w = live, live.w
    k1 = UUID(_connect(lab, w.a1)["connection_id"])
    assert _work(lab)["sync"] == {"succeeded": 4}
    lab.google.revoke_unavailable = True
    assert purge_provider(w.db.runtime, lab.config, lab.registry, PROVIDER) == {
        "stopped": 1,
        "expedited": 0,
        "disconnected": 1,
    }
    row = lab.row(k1)
    assert (row.status, row.revocation_status, row.purge_status) == (
        "disconnected",
        "failed",
        "done",
    )
    # The deadline is the moment of the purge, so a revocation that cannot be made does not
    # delay the deletion; completion follows within the same command.
    assert timedelta(0) <= row.disconnected_at - row.purge_due_at < timedelta(seconds=30)
    assert lab.records(k1) == 0

    # A teardown already under way waits for its revocation until its own deadline. The purge
    # brings that deadline forward and completes it, also with the adapter removed from the
    # registry (the kill switch).
    k2 = UUID(_connect(lab, w.a1)["connection_id"])
    assert _work(lab)["sync"] == {"succeeded": 4}
    assert lab.disconnect("owner_a", w.a, w.a1, k2).status_code == 202
    assert _work(lab)["teardown"] == {"pending": 1}
    due = lab.row(k2).purge_due_at
    assert purge_provider(w.db.runtime, lab.config, {}, PROVIDER) == {
        "stopped": 0,
        "expedited": 1,
        "disconnected": 1,
    }
    row = lab.row(k2)
    assert (row.status, row.status_reason, row.revocation_status, row.purge_status) == (
        "disconnected",
        "user_requested",
        "failed",
        "done",
    )
    assert row.purge_due_at < due and lab.records(k2) == 0

    # A teardown that a running worker holds is reported as remaining instead of awaited; its
    # deadline is already the time of the purge when the worker completes it.
    k3 = UUID(_connect(lab, w.a1)["connection_id"])
    assert lab.disconnect("owner_a", w.a, w.a1, k3).status_code == 202
    due = lab.row(k3).purge_due_at
    with Session(w.db.migration) as session, session.begin():
        leased = session.get(ConnectorConnection, k3)
        leased.teardown_lease_until = datetime.now(UTC) + timedelta(minutes=2)
    assert purge_provider(w.db.runtime, lab.config, lab.registry, PROVIDER) == {
        "stopped": 0,
        "expedited": 1,
        "remaining": 1,
    }
    assert lab.row(k3).status == "disconnecting" and lab.row(k3).purge_due_at < due
    with Session(w.db.migration) as session, session.begin():
        session.get(ConnectorConnection, k3).teardown_lease_until = None
    assert _work(lab)["teardown"] == {"disconnected": 1}
    assert lab.row(k3).revocation_status == "failed" and lab.records(k3) == 0


def test_011c_partial_consent_is_refused_and_revoked(live):
    lab, w = live, live.w
    result = _connect(lab, w.a1, scopes=(ANALYTICS_SCOPE,))
    assert result == {"error": "scopes_missing"}
    assert lab.google.revoked
    with Session(w.db.migration) as session:
        assert not session.scalar(select(func.count()).select_from(ConnectorRecord))


def test_011c_migration_downgrade_refuses_live_youtube_state(live):
    lab, w = live, live.w
    assert _connect(lab, w.a1)["result"] == "connected"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    def version():
        with w.db.migration.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    head = version()
    # Sign-ins now store agreement records, which 0031 (017-A) refuses to drop first;
    # remove them so that the guard of the revision under test is the one that refuses.
    with w.db.migration.begin() as connection:
        connection.exec_driver_sql("DELETE FROM user_agreements")
    with pytest.raises(RuntimeError, match="Refuse to remove live YouTube connector state"):
        command.downgrade(config, "0015_youtube_runtime")
    # The refused downgrade leaves every revision in place, the 014 revisions included.
    assert version() == head


def _events(captured: str, name: str) -> list[dict]:
    lines = [json.loads(line) for line in captured.splitlines() if line.startswith("{")]
    return [entry for entry in lines if entry.get("event") == name]


def _token_calls(lab) -> int:
    return sum(1 for _, base, _ in lab.google.requests if base == youtube.TOKEN_URL)


# R011-14: a client secret that Google no longer accepts (for example a rotation that .env
# missed) gets 401 invalid_client at the token endpoint. Runs and the scheduled authorization
# check then fail, and the connection stays active with its data; only invalid_grant still
# ends the authorization.
def test_r011_14_a_rejected_client_fails_runs_and_keeps_the_connection_active(live, capsys):
    lab, w = live, live.w
    k1 = UUID(_connect(lab, w.a1)["connection_id"])
    assert _work(lab)["sync"] == {"succeeded": 4}
    records = lab.records(k1)
    rejected = {PROVIDER: youtube.YouTubeProvider(CLIENT_ID, "rotated-client-secret-0000")}
    # Two hours later the access token has expired, so the run refreshes before reading.
    later = datetime.now(UTC) + timedelta(hours=2)
    assert lab.sync("owner_a", w.a, w.a1, k1, {"stream": "channel"}).status_code == 202
    capsys.readouterr()
    assert lab.worker(now=later, registry=rejected, limit=20)["sync"] == {"failed": 1}
    assert len(_events(capsys.readouterr().err, "connector_client_rejected")) == 1
    with Session(w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun)
            .where(ConnectorSyncRun.connection_id == k1, ConnectorSyncRun.stream == "channel")
            .order_by(ConnectorSyncRun.created_at.desc())
        ).first()
    assert (run.status, run.error_kind) == ("failed", "permanent")
    row = lab.row(k1)
    assert (row.status, row.status_reason, row.reconnect_required_since) == ("active", None, None)
    # The scheduled check 8 days later fails the same way and changes nothing either.
    result = lab.worker(now=later + timedelta(days=8), registry=rejected, schedule=True, limit=20)
    assert result["schedule"]["check_failed"] == 1
    assert lab.row(k1).status == "active" and lab.records(k1) == records

    # A revoked grant is still lost authorization: invalid_grant requires reconnection.
    lab.google.revoked.update(grant for _, grant, _ in lab.google.tokens.values())
    assert lab.sync("owner_a", w.a, w.a1, k1, {"stream": "channel"}).status_code == 202
    assert lab.worker(now=later, registry=lab.registry, limit=20)["sync"] == {"stopped": 1}
    row = lab.row(k1)
    assert (row.status, row.status_reason) == ("reconnect_required", "credential_expired")
    assert lab.records(k1) == records


# R011-16: the channel is deleted while the Google account stays, so channels.list returns no
# channel. The run makes its one refresh, reads again, and then requires reconnection; after 14
# days the D6 grace purge removes the records, those of the deleted videos included.
def test_r011_16_a_deleted_channel_requires_reconnection_and_is_purged(live):
    lab, w = live, live.w
    k1 = UUID(_connect(lab, w.a1)["connection_id"])
    assert _work(lab)["sync"] == {"succeeded": 4}
    assert _count(lab, k1, "videos") == 4
    lab.google.channels = 0
    tokens = _token_calls(lab)
    for stream in ("channel", "videos"):
        assert lab.sync("owner_a", w.a, w.a1, k1, {"stream": stream}).status_code == 202
    assert _work(lab)["sync"] == {"stopped": 1}
    assert _token_calls(lab) == tokens + 1
    row = lab.row(k1)
    assert (row.status, row.status_reason) == ("reconnect_required", "provider_revoked")
    due = row.reconnect_required_since + timedelta(days=14)
    assert lab.worker(now=due, registry=lab.registry, schedule=True)["schedule"] == {"expired": 1}
    assert lab.worker(now=due, registry=lab.registry)["teardown"] == {"disconnected": 1}
    row = lab.row(k1)
    assert (row.status, row.status_reason) == ("disconnected", "authorization_lost")
    assert lab.records(k1) == 0
