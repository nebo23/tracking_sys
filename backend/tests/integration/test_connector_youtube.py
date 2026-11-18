"""YouTube-shaped connector runtime on disposable PostgreSQL (specification 011-A, D-058, D-060).

Uses the synthetic lab of connector_support with the YouTube-shaped synthetic provider that the
API builds next to the 009 and 010 providers. Agency A connects the synthetic channel in
clients A1 and A2, and agency B connects it in client B1. No case contacts Google: the provider
reproduces the documented shapes and the 011-B evidence only. The worker's clock and the
provider's data clock are set together where data depends on dates; token lifetimes use the
real clock. The merge review corrections (D-061) add the authorization check for archived
clients and suspended agencies (R011-13) and the resumed first day read (R011-15).
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from connector_support import archive, make_lab
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.connectors.synthetic_youtube import (
    ANALYTICS_SCOPE,
    BUCKETS,
    CAPABILITY,
    CLOCK,
    DATA_SCOPE,
    VIDEO_ATTRIBUTES,
    SyntheticYouTubeProvider,
)
from app.models import (
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorUsageRecord,
)
from app.security import now_utc
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
PROVIDER = "synthetic_youtube"
CHANNEL = "UCsyntheticchannel01"
LABEL = "Synthetic Channel"
DISCLOSURE = "dev-agent-approval-1"
APPROVAL = {"approved": True, "disclosure": DISCLOSURE}
STREAMS = ("channel", "channel_daily", "videos", "video_totals")
NOT_RETURNED = {"state": "missing", "value": None, "reason": "not_returned"}
PDT, PST = timedelta(hours=7), timedelta(hours=8)


@pytest.fixture
def yt(authenticated_world, api, tmp_path):
    lab = make_lab(authenticated_world, api, tmp_path)
    state = lab.state.with_name(lab.state.stem + "-youtube" + lab.state.suffix)
    lab.yt = SyntheticYouTubeProvider(state)
    lab.registry = {PROVIDER: lab.yt}
    return lab


def _begin(lab, name, agency, client_id, approval=APPROVAL, connection_id=None):
    browser = lab.browser(name)
    base = f"/agencies/{agency}/clients/{client_id}/connections"
    if connection_id is not None:
        body = None if approval is None else {"agent_approval": approval}
        return browser.post(f"{base}/{connection_id}/reconnect", json=body)
    body = {"provider": PROVIDER}
    if approval is not None:
        body["agent_approval"] = approval
    return browser.post(base, json=body)


def _finish(lab, name, url, account=CHANNEL, **approve):
    code = lab.yt.approve(url, account, LABEL, **approve)
    state = parse_qs(urlsplit(url).query)["state"][0]
    response = lab.browser(name).get(
        "/connectors/oauth/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return {
        key: values[0]
        for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()
    }


def _connect(lab, name, agency, client_id, account=CHANNEL, **approve):
    response = _begin(lab, name, agency, client_id)
    assert response.status_code == 200, response.text
    result = _finish(lab, name, response.json()["authorization_url"], account, **approve)
    assert result["result"] == "connected", result
    return UUID(result["connection_id"])


def _work(lab, now=None, schedule=False, limit=20):
    return lab.worker(now=now, registry=lab.registry, schedule=schedule, limit=limit)


def _sync(lab, name, agency, client_id, connection_id, stream):
    response = lab.sync(name, agency, client_id, connection_id, {"stream": stream})
    assert response.status_code == 202, response.text


def _records(lab, name, agency, client_id, connection_id, stream):
    response = lab.browser(name).get(
        f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/records?"
        + urlencode({"stream": stream})
    )
    assert response.status_code == 200, response.text
    return {item["provider_object_id"]: item for item in response.json()["records"]}


def _coverage(lab, name, agency, client_id, connection_id):
    response = lab.browser(name).get(
        f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/coverage"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _calls(lab, operation):
    return [outcome for name, outcome in lab.yt.calls() if name == operation]


def _usable(lab, *connections):
    return all(
        lab.yt.token_usable(token) for item in connections for token in lab.tokens(item).values()
    )


def _latest(lab, connection_id, stream):
    with Session(lab.w.db.migration) as session:
        return session.scalars(
            select(ConnectorSyncRun)
            .where(
                ConnectorSyncRun.connection_id == connection_id, ConnectorSyncRun.stream == stream
            )
            .order_by(ConnectorSyncRun.created_at.desc(), ConnectorSyncRun.id.desc())
        ).first()


def _checkpoint(lab, connection_id, stream):
    with Session(lab.w.db.migration) as session:
        return session.scalar(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.connection_id == connection_id,
                ConnectorCheckpoint.stream == stream,
            )
        )


def _usage(lab, connection_id):
    with Session(lab.w.db.migration) as session:
        rows = session.execute(
            select(
                ConnectorUsageRecord.bucket,
                ConnectorUsageRecord.period,
                ConnectorUsageRecord.operation,
                func.sum(ConnectorUsageRecord.quantity),
            )
            .where(ConnectorUsageRecord.connection_id == connection_id)
            .group_by(
                ConnectorUsageRecord.bucket,
                ConnectorUsageRecord.period,
                ConnectorUsageRecord.operation,
            )
        ).all()
    return {(row[0], row[1], row[2]): row[3] for row in rows}


def _stored(lab, connection_id, stream):
    with Session(lab.w.db.migration) as session:
        return {
            row.provider_object_id: row
            for row in session.scalars(
                select(ConnectorRecord).where(
                    ConnectorRecord.connection_id == connection_id,
                    ConnectorRecord.stream == stream,
                )
            )
        }


# Make one connection require reconnection: its read is refused and its refresh rejected.
def _lose(lab, name, agency, client_id, connection_id):
    lab.yt.set_behavior("fetch", "unauthorized")
    lab.yt.set_behavior("refresh", "invalid_grant")
    _sync(lab, name, agency, client_id, connection_id, "channel")
    assert _work(lab)["sync"] == {"stopped": 1}
    lab.yt.set_behavior("fetch", "ok")
    lab.yt.set_behavior("refresh", "ok")


def _day_values(day):
    ordinal = day.toordinal()
    if ordinal % 7 == 0:
        return None
    return 0 if ordinal % 5 == 0 else ordinal % 97 + 10


def test_011a_authorization_parameters_and_agent_approval(yt):
    lab, w = yt, yt.w
    # D13: the connect must carry the approval of the current disclosure version.
    for approval in (None, {"approved": True, "disclosure": "dev-agent-approval-0"}):
        refused = _begin(lab, "owner_a", w.a, w.a1, approval)
        assert (refused.status_code, refused.json()) == (422, {"error": "agent_approval_required"})
    assert (
        _begin(lab, "owner_a", w.a, w.a1, {"approved": False, "disclosure": DISCLOSURE}).status_code
        == 422
    )
    # Providers without a disclosure need no approval.
    synthetic = lab.browser("owner_a").post(
        f"/agencies/{w.a}/clients/{w.a2}/connections", json={"provider": "synthetic"}
    )
    assert synthetic.status_code == 200

    # D3, D4: offline access, consent on every connect, PKCE S256 and only the two scopes.
    response = _begin(lab, "owner_a", w.a, w.a1)
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"][0]
    assert set(query["scope"][0].split()) == {DATA_SCOPE, ANALYTICS_SCOPE}
    before = now_utc()
    result = _finish(lab, "owner_a", url)
    k1 = UUID(result["connection_id"])
    row = lab.row(k1)
    assert row.agent_disclosure == DISCLOSURE and before - row.agent_approved_at < timedelta(
        minutes=5
    )
    # F1: the reported 7-day refresh-token lifetime is kept as the grant's expiry.
    assert timedelta(days=7) - timedelta(minutes=5) < row.grant_expires_at - before
    assert row.grant_expires_at - before <= timedelta(days=7, minutes=1)
    secrets = {item.kind: item for item in lab.secrets(k1)}
    assert secrets["refresh_token"].provider_expires_at == row.grant_expires_at
    assert (row.account_label, row.account_label_refreshed_at is not None) == (LABEL, True)
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["grant_expires_at"] is not None
    assert body["account"] == {"external_account_id": CHANNEL, "label": LABEL}


def test_011a_partial_consent_and_unavailable_accounts_are_refused(yt):
    lab, w = yt, yt.w
    other = _connect(lab, "owner_a", w.a, w.a2, account="UCotherchannel")
    # D2: a first consent with one scope cleared is refused and its grant revoked; the other
    # channel's connection is untouched.
    url = _begin(lab, "owner_a", w.a, w.a1).json()["authorization_url"]
    assert _finish(lab, "owner_a", url, scopes=(DATA_SCOPE,)) == {"error": "scopes_missing"}
    assert lab.yt.grants() == [("UCotherchannel", False), (CHANNEL, True)]
    assert _usable(lab, other)
    with Session(w.db.migration) as session:
        assert not session.scalar(
            select(func.count())
            .select_from(ConnectorConnection)
            .where(ConnectorConnection.client_id == w.a1)
        )

    # F1: an account that already granted both scopes is granted both again, whatever is
    # cleared on the screen, so the connection is installed.
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k3 = _connect(lab, "owner_b", w.b, w.b1, scopes=(ANALYTICS_SCOPE,))
    assert set(lab.row(k3).granted_scopes) == {DATA_SCOPE, ANALYTICS_SCOPE}

    # F4: an account without exactly one channel is refused. A grant without a channel is
    # revoked; with several channels the account cannot be told apart from another
    # connection's, so the grant is kept rather than risk revoking working tokens (D5).
    for channels in (0, 2):
        url = _begin(lab, "owner_b", w.b, w.b2).json()["authorization_url"]
        result = _finish(lab, "owner_b", url, f"UCnone{channels}", channels=channels)
        assert result == {"error": "account_unavailable"}
    assert ("UCnone0", True) in lab.yt.grants() and ("UCnone2", False) in lab.yt.grants()
    assert _usable(lab, other, k1, k3)


def test_011a_account_wide_grants_are_revoked_only_by_the_last_connection(yt):
    lab, w = yt, yt.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k2 = _connect(lab, "owner_a", w.a, w.a2)
    k3 = _connect(lab, "owner_b", w.b, w.b1)
    assert _work(lab)["sync"] == {"succeeded": 12}

    # A refused duplicate connect keeps the grant the working connection shares (D5).
    url = _begin(lab, "owner_a", w.a, w.a1).json()["authorization_url"]
    assert _finish(lab, "owner_a", url) == {"error": "account_already_connected"}
    assert _calls(lab, "revoke") == []
    assert _usable(lab, k1, k2, k3)

    # Disconnecting one client's connection keeps the grant the others share.
    assert lab.disconnect("owner_a", w.a, w.a1, k1).status_code == 202
    assert _work(lab)["teardown"] == {"disconnected": 1}
    row = lab.row(k1)
    assert (row.status, row.revocation_status) == ("disconnected", "shared")
    assert (row.account_label_refreshed_at, row.grant_expires_at) == (None, None)
    assert row.agent_disclosure == DISCLOSURE
    assert {item.revocation for item in lab.secrets(k1)} == {"shared"}
    assert _calls(lab, "revoke") == [] and lab.records(k1) == 0
    assert _usable(lab, k2, k3)

    # A reconnect replaces the grant without revoking it, which would revoke the new one.
    _lose(lab, "owner_a", w.a, w.a2, k2)
    assert lab.row(k2).reconnect_required_since is not None
    refused = _begin(lab, "owner_a", w.a, w.a2, approval=None, connection_id=k2)
    assert refused.json() == {"error": "agent_approval_required"}
    url = _begin(lab, "owner_a", w.a, w.a2, connection_id=k2).json()["authorization_url"]
    assert _finish(lab, "owner_a", url)["result"] == "reconnected"
    replaced = [item for item in lab.secrets(k2) if item.version == 1]
    assert {item.revocation for item in replaced} == {"not_required"}
    assert lab.row(k2).reconnect_required_since is None
    assert _calls(lab, "revoke") == []
    assert _usable(lab, k2, k3)

    # K2's disconnect is shared with K3; the last connection revokes the account's grant.
    assert lab.disconnect("owner_a", w.a, w.a2, k2).status_code == 202
    assert _work(lab)["teardown"] == {"disconnected": 1}
    assert lab.row(k2).revocation_status == "shared" and _calls(lab, "revoke") == []
    assert lab.disconnect("owner_b", w.b, w.b1, k3).status_code == 202
    assert _work(lab)["teardown"] == {"disconnected": 1}
    assert lab.row(k3).revocation_status == "done"
    assert _calls(lab, "revoke") == ["ok", "ok"]
    assert all(revoked for account, revoked in lab.yt.grants() if account == CHANNEL)


def test_011a_refresh_ahead_authorization_check_and_grace_purge(yt):
    lab, w = yt, yt.w
    # D4: an access token that expires within 5 minutes is refreshed before any read.
    lab.yt.set_behavior("access_ttl", "200")
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab)["sync"] == {"succeeded": 4}
    assert _calls(lab, "refresh") == ["ok"] * 4
    assert "unauthorized" not in _calls(lab, "fetch")

    # A recently refreshed long-lived token is used as it is.
    lab.yt.set_behavior("access_ttl", str(30 * 86400))
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab)["sync"] == {"succeeded": 1}
    assert len(_calls(lab, "refresh")) == 5
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab)["sync"] == {"succeeded": 1}
    assert len(_calls(lab, "refresh")) == 5

    # D6: seven days without a refresh force one, even for a token that has not expired.
    later = now_utc() + timedelta(days=7, minutes=1)
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab, now=later)["sync"] == {"succeeded": 1}
    assert len(_calls(lab, "refresh")) == 6

    # A refused refresh makes the connection require reconnection, keeping its data.
    lab.yt.set_behavior("refresh", "invalid_grant")
    lost = later + timedelta(days=7, minutes=1)
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab, now=lost)["sync"] == {"stopped": 1}
    row = lab.row(k1)
    assert (row.status, row.status_reason, row.reconnect_required_since) == (
        "reconnect_required",
        "credential_expired",
        lost,
    )
    assert lab.records(k1) > 0
    # After 14 days without a reconnect it is disconnected and purged (authorization_lost).
    early = _work(lab, now=lost + timedelta(days=14) - timedelta(minutes=1), schedule=True)
    assert early["schedule"] == {} and lab.row(k1).status == "reconnect_required"
    due = lost + timedelta(days=14)
    assert _work(lab, now=due, schedule=True)["schedule"] == {"expired": 1}
    row = lab.row(k1)
    assert (row.status, row.status_reason, row.reconnect_required_since) == (
        "disconnecting",
        "authorization_lost",
        None,
    )
    assert _work(lab, now=due)["teardown"] == {"disconnected": 1}
    row = lab.row(k1)
    assert (row.status, row.revocation_status, row.external_account_id) == (
        "disconnected",
        "done",
        None,
    )
    assert lab.records(k1) == 0


def test_011a_quota_buckets_follow_the_pacific_day_and_quota_answers_defer(yt, monkeypatch):
    import app.api.connectors as routes

    lab, w = yt, yt.w
    t0 = datetime(2026, 11, 6, 7, 30, tzinfo=UTC)  # 23:30 on 2026-11-05, Pacific time
    lab.yt.set_behavior("clock", t0.isoformat())
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab, now=t0)["sync"] == {"succeeded": 4}
    # D10: one row per bucket and call, on the Pacific day; a refresh is not metered. Data: 1
    # for the channel, 2 for one page of videos and 1 for the totals. Analytics: 3 windows of at
    # most 31 days for the 90 days read at connect and 1 for the totals.
    pacific = date(2026, 11, 5)
    assert _usage(lab, k1) == {
        ("youtube_data", pacific, "fetch"): 4,
        ("youtube_analytics", pacific, "fetch"): 4,
    }

    # quotaExceeded defers the run to the next Pacific midnight; it is not a retry or failure.
    lab.yt.set_behavior("fetch_script", "quota_exceeded")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab, now=t0)["sync"] == {"deferred": 1}
    reset = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
    run = _latest(lab, k1, "channel_daily")
    assert (run.status, run.error_kind, run.not_before, run.retries) == (
        "queued",
        "budget_exhausted",
        reset,
        0,
    )
    monkeypatch.setattr(routes, "now_utc", lambda: t0)
    stream = next(
        item
        for item in _coverage(lab, "owner_a", w.a, w.a1, k1)["streams"]
        if item["stream"] == "channel_daily"
    )
    assert stream["sync"]["state"] == "budget_stopped"
    assert _work(lab, now=reset - timedelta(seconds=1))["sync"] == {}
    assert _work(lab, now=reset)["sync"] == {"succeeded": 1}
    assert _usage(lab, k1)[("youtube_analytics", date(2026, 11, 6), "fetch")] == 1

    # Separate buckets: an exhausted Analytics allocation stops Analytics reads only.
    data, analytics = BUCKETS
    lab.yt.capability = replace(CAPABILITY, buckets=(data, replace(analytics, connection_daily=1)))
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    _sync(lab, "owner_a", w.a, w.a1, k1, "videos")
    assert _work(lab, now=reset)["sync"] == {"deferred": 1, "succeeded": 1}
    run = _latest(lab, k1, "channel_daily")
    assert (run.error_kind, run.not_before) == (
        "budget_exhausted",
        datetime(2026, 11, 7, 8, 0, tzinfo=UTC),
    )
    # The provider cap counts every connection of the provider: K1's 2 Data units of the day
    # fill a cap of 2, so K2's Data reads wait while its Analytics-only read proceeds.
    k2 = _connect(lab, "owner_a", w.a, w.a2)
    lab.yt.capability = replace(CAPABILITY, buckets=(replace(data, daily_quota=2), analytics))
    lab.yt.set_behavior("fetch_script", "")
    for stream_name in STREAMS:
        _sync(lab, "owner_a", w.a, w.a2, k2, stream_name)
    assert _work(lab, now=reset)["sync"] == {"succeeded": 1, "deferred": 3}
    assert (
        sum(
            quantity
            for (bucket, period, _), quantity in _usage(lab, k2).items()
            if bucket == "youtube_data" and period == date(2026, 11, 6)
        )
        == 0
    )
    # The coverage cost reports each bucket of the connection's own use.
    cost = _coverage(lab, "owner_a", w.a, w.a1, k1)["cost"]
    by_bucket = {item["bucket"]: item for item in cost["buckets"]}
    assert set(by_bucket) == {"youtube_data", "youtube_analytics"}


def test_011a_pacific_days_completeness_and_days_without_rows(yt, monkeypatch):
    import app.api.connectors as routes

    lab, w = yt, yt.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 4}
    # D-060: complete through the end of the last Pacific day that ended at least 72 hours
    # before the read (2026-11-02), 90 days back at connect.
    point = _checkpoint(lab, k1, "channel_daily")
    assert point.complete_through == datetime(2026, 11, 3, tzinfo=UTC) + PST
    assert point.covered_from == datetime(2026, 8, 5, tzinfo=UTC) + PDT
    monkeypatch.setattr(routes, "now_utc", lambda: CLOCK)
    days = _records(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert len(days) == 90 and "day-2026-11-03" not in days
    # Day boundaries come from the zone: 2026-11-01 is 25 hours long.
    assert days["day-2026-10-31"]["observed_at"] == "2026-10-31T07:00:00Z"
    assert days["day-2026-11-01"]["observed_at"] == "2026-11-01T07:00:00Z"
    assert days["day-2026-11-02"]["observed_at"] == "2026-11-02T08:00:00Z"
    stored = _stored(lab, k1, "channel_daily")
    for key, item in days.items():
        day = date.fromisoformat(key.removeprefix("day-"))
        value = _day_values(day)
        if value is None:
            # A day without a row is missing with not_returned, never zero.
            assert all(metric == NOT_RETURNED for metric in item["metrics"].values())
            assert stored[key].metrics == {}
        else:
            assert item["metrics"]["views"] == {"state": "observed", "value": value, "reason": None}
    assert any(_day_values(date.fromisoformat(key[4:])) is None for key in days)
    assert any(_day_values(date.fromisoformat(key[4:])) == 0 for key in days)
    # Days within the 4-day re-read after the latency stay provisional.
    provisional = {key for key, item in days.items() if item["provisional"]}
    assert provisional == {"day-2026-10-30", "day-2026-10-31", "day-2026-11-01", "day-2026-11-02"}

    # The next run re-reads four local days before the watermark, starting at a local midnight
    # across the change, and moves the watermark by the days that became complete.
    later = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)
    lab.yt.set_behavior("clock", later.isoformat())
    lab.yt.set_behavior("revision", "5")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab, now=later)["sync"] == {"succeeded": 1}
    assert (
        _latest(lab, k1, "channel_daily").window_since == datetime(2026, 10, 30, tzinfo=UTC) + PDT
    )
    assert (
        _checkpoint(lab, k1, "channel_daily").complete_through
        == datetime(2026, 11, 5, tzinfo=UTC) + PST
    )
    stored = _stored(lab, k1, "channel_daily")
    for key in ("day-2026-10-29", "day-2026-10-30", "day-2026-11-04"):
        value = _day_values(date.fromisoformat(key[4:]))
        if value:
            revised = key != "day-2026-10-29"
            assert stored[key].metrics["views"] == value + (5 if revised else 0)


def test_011a_videos_attributes_product_types_and_deleted_videos(yt, monkeypatch):
    import app.api.connectors as routes

    lab, w = yt, yt.w
    lab.yt.set_behavior("leak_title", "yes")
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 4}
    monkeypatch.setattr(routes, "now_utc", lambda: CLOCK)

    # D11: the inventory lists private and unlisted uploads with allow-listed attributes only.
    videos = _records(lab, "owner_a", w.a, w.a1, k1, "videos")
    assert set(videos) == {"v0001", "v0002", "v0003", "v0004"}
    assert {item["attributes"]["privacy_status"] for item in videos.values()} == {
        "private",
        "unlisted",
        "public",
    }
    assert all(set(item["attributes"]) == set(VIDEO_ATTRIBUTES) for item in videos.values())
    assert all(item["attributes_refreshed_at"] is not None for item in videos.values())
    assert all("title" not in row.attributes for row in _stored(lab, k1, "videos").values())
    assert videos["v0003"]["metrics"]["likeCount"] == NOT_RETURNED
    assert videos["v0002"]["metrics"]["commentCount"] == NOT_RETURNED
    assert all(item["product_type"] is None for item in videos.values())

    # D8: product types from the lowerCamelCase content types; a video without analytics rows
    # is not_returned; totals of a recent upload are provisional.
    totals = _records(lab, "owner_a", w.a, w.a1, k1, "video_totals")
    assert {key: item["product_type"] for key, item in totals.items()} == {
        "v0001": "VIDEO_ON_DEMAND",
        "v0002": "UNSPECIFIED",
        "v0003": "SHORTS",
        "v0004": "VIDEO_ON_DEMAND",
    }
    assert all(value == NOT_RETURNED for value in totals["v0002"]["metrics"].values())
    assert (totals["v0001"]["provisional"], totals["v0004"]["provisional"]) == (True, False)
    channel = _records(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert [item["metrics"]["subscriberCount"]["value"] for item in channel.values()] == [12300]
    metrics = {
        (item["stream"], item["name"]): item
        for item in _coverage(lab, "owner_a", w.a, w.a1, k1)["metrics"]
    }
    assert metrics[("channel", "subscriberCount")]["unit"] == "rounded_count"
    assert metrics[("channel_daily", "averageViewDuration")]["additive"] is False
    assert metrics[("channel_daily", "views")]["additive"] is True
    assert metrics[("channel_daily", "views")]["definition_changes"] == [
        "2025-04-30",
        "2026-08-27",
        "2026-11-16",
    ]
    # A content type not yet observed maps to UNSPECIFIED.
    lab.yt.set_behavior("content_type", "liveStream")
    _sync(lab, "owner_a", w.a, w.a1, k1, "video_totals")
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 1}
    totals = _records(lab, "owner_a", w.a, w.a1, k1, "video_totals")
    assert {item["product_type"] for item in totals.values()} == {"UNSPECIFIED"}

    # A deleted video is purged from every stream once videos.list confirms it gone; a video
    # missing from the playlist that still exists is kept.
    lab.yt.set_behavior("deleted", "v0004")
    lab.yt.set_behavior("hidden", "v0003")
    _sync(lab, "owner_a", w.a, w.a1, k1, "videos")
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 1}
    assert _calls(lab, "confirm") == ["ok"]
    assert set(_stored(lab, k1, "videos")) == {"v0001", "v0002", "v0003"}
    assert set(_stored(lab, k1, "video_totals")) == {"v0001", "v0002", "v0003"}
    assert _usage(lab, k1)[("youtube_data", date(2026, 11, 6), "confirm")] == 1


def test_011a_lifecycle_clears_attributes_labels_and_keeps_provider_retention(
    yt, lifecycle_engine, lifecycle_settings
):
    lab, w = yt, yt.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 4}
    daily = len(_stored(lab, k1, "channel_daily"))

    # Within 730 days nothing is deleted; a shorter provider period deletes older records.
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=CLOCK)["deleted"][
            "connector_records"
        ]
        == 0
    )
    shorter = lifecycle_settings.model_copy(
        update={"connector_provider_retention_days": {PROVIDER: 30}}
    )
    result = run_lifecycle(lifecycle_engine, shorter, cutoff=CLOCK)
    # Days from 2026-08-05 through 2026-10-07 began before the 30-day limit.
    assert result["deleted"]["connector_records"] == 64
    assert len(_stored(lab, k1, "channel_daily")) == daily - 64

    # D11: attributes and the label not refreshed for 30 days are cleared; statistics stay.
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=CLOCK + timedelta(days=29))
    assert result["deleted"]["connector_record_attributes"] == 0
    after = CLOCK + timedelta(days=31)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=after)
    assert result["deleted"]["connector_record_attributes"] == 4
    assert result["deleted"]["connector_account_labels"] == 1
    videos = _stored(lab, k1, "videos")
    assert all(
        row.attributes == {} and row.attributes_refreshed_at is None for row in videos.values()
    )
    assert all("viewCount" in row.metrics for row in videos.values())
    row = lab.row(k1)
    assert (row.account_label, row.account_label_refreshed_at, row.status) == (None, None, "active")
    # The next channel read refreshes the label.
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab, now=CLOCK)["sync"] == {"succeeded": 1}
    assert lab.row(k1).account_label == LABEL

    # tracking_lifecycle cannot read labels or change statistics.
    for statement in (
        "SELECT account_label FROM connector_connections",
        "UPDATE connector_records SET metrics = metrics",
        "UPDATE connector_connections SET status = status",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            with lifecycle_engine.begin() as connection:
                connection.execute(text(statement))


def test_011a_error_mapping_and_tenant_isolation(yt):
    lab, w = yt, yt.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k3 = _connect(lab, "owner_b", w.b, w.b1)
    assert _work(lab)["sync"] == {"succeeded": 8}

    # 403 insufficientPermissions fails only the stream that needs the scope.
    lab.yt.set_behavior("fetch_script", "forbidden")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab)["sync"] == {"failed": 1}
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel")
    assert _work(lab)["sync"] == {"succeeded": 1}
    assert _latest(lab, k1, "channel_daily").error_kind == "forbidden"
    # 400 is permanent.
    lab.yt.set_behavior("fetch_script", "permanent")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab)["sync"] == {"failed": 1}
    assert _latest(lab, k1, "channel_daily").error_kind == "permanent"
    # 401 authError gets one refresh and the read is repeated.
    refreshes = len(_calls(lab, "refresh"))
    lab.yt.set_behavior("fetch_script", "unauthorized")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab)["sync"] == {"succeeded": 1}
    assert len(_calls(lab, "refresh")) == refreshes + 1
    # A second 401 after the refresh makes the connection require reconnection.
    lab.yt.set_behavior("fetch_script", "unauthorized,unauthorized")
    _sync(lab, "owner_a", w.a, w.a1, k1, "channel_daily")
    assert _work(lab)["sync"] == {"stopped": 1}
    assert (lab.row(k1).status, lab.row(k1).status_reason) == (
        "reconnect_required",
        "provider_revoked",
    )
    assert lab.row(k3).status == "active" and _usable(lab, k3)

    # Agency B sees nothing of agency A's connection, and coverage counts only its own usage.
    assert lab.view("owner_b", w.a, w.a1, k1).status_code == 403
    assert lab.browser("owner_b").get(
        f"/agencies/{w.b}/clients/{w.b1}/connections/{k1}/records"
    ).status_code in (403, 404)
    cost = _coverage(lab, "owner_b", w.b, w.b1, k3)["cost"]
    own = {item["bucket"]: item["consumed"] for item in cost["buckets"]}
    assert own == {"youtube_data": 4, "youtube_analytics": 4}


def test_011a_migration_downgrade_refuses_youtube_state(yt):
    lab, w = yt, yt.w
    _connect(lab, "owner_a", w.a, w.a1)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    def version():
        with w.db.migration.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    head = version()
    with pytest.raises(RuntimeError, match="Refuse to remove populated connector state"):
        command.downgrade(config, "0014_instagram_provider")
    # The refused downgrade leaves every revision in place.
    assert version() == head


# R011-13 (D6): runs are queued and claimed only for an active agency and client, so the
# scheduling step checks the authorization of connections whose client is archived (K1) or
# whose agency is suspended (K3). A revocation in the Google settings, stood in for by a refused
# refresh, then leads to reconnect_required and the 14-day grace purge.
def test_r011_13_authorization_is_checked_for_an_archived_client_and_a_suspended_agency(yt):
    lab, w = yt, yt.w
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    k3 = _connect(lab, "owner_b", w.b, w.b1, account="UCotherchannel")
    assert _work(lab)["sync"] == {"succeeded": 8}
    kept = {item: lab.records(item) for item in (k1, k3)}
    reads, usage = len(_calls(lab, "fetch")), _usage(lab, k1)
    archive(w, w.a1)
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE agencies SET status = 'suspended' WHERE id = :b"), {"b": w.b}
        )
    start = now_utc()

    # Nothing is due within 7 days of the last refresh.
    assert _work(lab, now=start + timedelta(days=6), schedule=True)["schedule"] == {}
    # After 7 days each access token is refreshed without a read, a run or a reservation.
    later = start + timedelta(days=8)
    result = _work(lab, now=later, schedule=True)
    assert (result["schedule"], result["sync"]) == ({"checked": 2}, {})
    assert _calls(lab, "refresh") == ["ok", "ok"] and len(_calls(lab, "fetch")) == reads
    assert _usage(lab, k1) == usage
    for item in (k1, k3):
        versions = [(s.version, s.status) for s in lab.secrets(item) if s.kind == "access_token"]
        assert versions == [(1, "destroyed"), (2, "active")]
        assert lab.row(item).status == "active"
    # A checked authorization is not checked again within the period.
    assert _work(lab, now=later + timedelta(days=6), schedule=True)["schedule"] == {}

    # The next check is refused: both connections require reconnection and keep their data.
    lab.yt.set_behavior("refresh", "invalid_grant")
    lost = later + timedelta(days=7, minutes=1)
    assert _work(lab, now=lost, schedule=True)["schedule"] == {"reconnect_required": 2}
    for item in (k1, k3):
        row = lab.row(item)
        assert (row.status, row.status_reason, row.reconnect_required_since) == (
            "reconnect_required",
            "credential_expired",
            lost,
        )
        assert lab.records(item) == kept[item]
    # 14 days later both are disconnected and purged with reason authorization_lost.
    due = lost + timedelta(days=14)
    assert _work(lab, now=due, schedule=True)["schedule"] == {"expired": 2}
    assert _work(lab, now=due)["teardown"] == {"disconnected": 2}
    for item in (k1, k3):
        row = lab.row(item)
        assert (row.status, row.status_reason, row.revocation_status) == (
            "disconnected",
            "authorization_lost",
            "done",
        )
        assert lab.records(item) == 0


# R011-15 (D9): two Analytics requests a day defer the first channel_daily read (three windows
# of at most 31 days) between pages, whichever stream claims the allocation first. The read
# resumes after the Pacific midnight, when the 72-hour bound has moved by one day, and still
# stores every day from its first one, each exactly once.
def test_r011_15_a_first_day_read_deferred_between_pages_skips_no_day(yt):
    lab, w = yt, yt.w
    t0 = datetime(2026, 11, 6, 7, 30, tzinfo=UTC)  # 23:30 on 2026-11-05, Pacific time
    lab.yt.set_behavior("clock", t0.isoformat())
    data, analytics = BUCKETS
    lab.yt.capability = replace(CAPABILITY, buckets=(data, replace(analytics, connection_daily=2)))
    k1 = _connect(lab, "owner_a", w.a, w.a1)
    _work(lab, now=t0)
    run = _latest(lab, k1, "channel_daily")
    assert (run.status, run.error_kind) == ("queued", "budget_exhausted")
    assert run.pages >= 1 and _checkpoint(lab, k1, "channel_daily").cursor is not None

    t1 = datetime(2026, 11, 6, 8, 30, tzinfo=UTC)  # 00:30 on 2026-11-06, Pacific time
    lab.yt.set_behavior("clock", t1.isoformat())
    lab.yt.capability = CAPABILITY
    _work(lab, now=t1)
    assert _latest(lab, k1, "channel_daily").status == "succeeded"
    days = sorted(
        date.fromisoformat(key.removeprefix("day-")) for key in _stored(lab, k1, "channel_daily")
    )
    # From the first day fixed at connect (90 days before 2026-11-02) through 2026-11-02,
    # which the moved bound made complete.
    assert days == [date(2026, 8, 4) + timedelta(days=index) for index in range(91)]
    point = _checkpoint(lab, k1, "channel_daily")
    assert point.covered_from == datetime(2026, 8, 4, tzinfo=UTC) + PDT
    assert point.complete_through == datetime(2026, 11, 3, tzinfo=UTC) + PST
