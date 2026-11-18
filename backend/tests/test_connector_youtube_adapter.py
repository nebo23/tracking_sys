"""Live YouTube adapter against the in-memory Google API (specification 011-C, D-060).

Offline: every answer comes from tests/youtube_api.py, built from the 011-B evidence. Covers:
- the capability, the authorization parameters, the exchange with its refusals, refresh and
  revocation;
- each stream's records and windows, and the confirmation of deleted videos;
- the error mapping;
- the settings and the rule-gated registration.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr, ValidationError
from youtube_api import (
    CHANNEL,
    CLIENT_ID,
    CLIENT_SECRET,
    LABEL,
    UPLOADS,
    FakeYouTube,
    _error,
)

import app.services.connectors as connectors
from app.config import Settings
from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.synthetic_youtube import ANALYTICS, ANALYTICS_SCOPE, DATA, DATA_SCOPE
from app.connectors.youtube import CAPABILITY, METRIC_NAMES, Reply, YouTubeProvider
from app.privacy.providers import RuleStatus
from app.services.connectors import build_providers, pkce_challenge

NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)  # 12:00 PST
REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"
VERIFIER = "v" * 64
PST = timedelta(hours=8)


def _provider(api: FakeYouTube) -> YouTubeProvider:
    return YouTubeProvider(CLIENT_ID, CLIENT_SECRET, transport=api, clock=lambda: NOW)


def _grant(api: FakeYouTube, provider: YouTubeProvider, scopes=None):
    url = provider.authorization_url(
        state="s" * 43,
        code_challenge=pkce_challenge(VERIFIER),
        redirect_uri=REDIRECT,
        scopes=CAPABILITY.scopes,
    )
    return provider.exchange(
        code=api.approve(url, scopes), code_verifier=VERIFIER, redirect_uri=REDIRECT
    )


def test_capability_requests_read_only_scopes_with_pkce_and_offline_access():
    assert CAPABILITY.provider == "youtube" and CAPABILITY.version == "youtube-data-v3-analytics-v2"
    assert CAPABILITY.scopes == (DATA_SCOPE, ANALYTICS_SCOPE)
    assert (CAPABILITY.pkce, CAPABILITY.revocation_scope, CAPABILITY.require_all_scopes) == (
        "S256",
        "account",
        True,
    )
    assert CAPABILITY.bucket_costs("fetch", "videos") == {DATA: 3}
    assert CAPABILITY.bucket_costs("fetch", "video_totals") == {DATA: 2, ANALYTICS: 1}
    assert CAPABILITY.bucket_costs("confirm", "videos") == {DATA: 1}
    url = _provider(FakeYouTube()).authorization_url(
        state="state", code_challenge="challenge", redirect_uri=REDIRECT, scopes=CAPABILITY.scopes
    )
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query == {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": f"{DATA_SCOPE} {ANALYTICS_SCOPE}",
        "access_type": "offline",
        "prompt": "consent",
        "state": "state",
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }
    assert repr(_provider(FakeYouTube())) == "YouTubeProvider()"


def test_exchange_reads_the_channel_and_keeps_the_grant_expiry():
    api = FakeYouTube()
    provider = _provider(api)
    grant = _grant(api, provider)
    assert (grant.external_account_id, grant.account_label, grant.account_kind) == (
        CHANNEL,
        LABEL,
        "channel",
    )
    assert grant.scopes == tuple(sorted((DATA_SCOPE, ANALYTICS_SCOPE)))
    assert grant.access_expires_at == NOW + timedelta(seconds=3599)
    assert grant.refresh_expires_at == NOW + timedelta(seconds=604799)
    assert grant.refusal is None and repr(grant).count("synthetic-") == 0
    # The channel lookup asks only for the ID and the title.
    channel = next(query for _, base, query in api.requests if base.endswith("/channels"))
    assert channel == {"part": "id,snippet", "mine": "true", "fields": "items(id,snippet/title)"}
    # A wrong verifier is refused: the Web client enforces PKCE (F2).
    url = provider.authorization_url(
        state="s",
        code_challenge=pkce_challenge(VERIFIER),
        redirect_uri=REDIRECT,
        scopes=CAPABILITY.scopes,
    )
    with pytest.raises(ProviderError) as refused:
        provider.exchange(code=api.approve(url), code_verifier="w" * 64, redirect_uri=REDIRECT)
    assert (refused.value.kind, refused.value.provider_code) == (
        ErrorKind.PERMANENT,
        "invalid_grant",
    )


def test_exchange_refusals_name_their_reason():
    for channels, refusal in ((0, "no_channel"), (2, "several_channels")):
        api = FakeYouTube(channels=channels)
        grant = _grant(api, _provider(api))
        assert (grant.refusal, grant.external_account_id) == (refusal, "")
    # Without the Data API scope the channel is not read; the runtime refuses the scope (D2).
    api = FakeYouTube()
    grant = _grant(api, _provider(api), scopes=(ANALYTICS_SCOPE,))
    assert (grant.refusal, grant.external_account_id, grant.scopes) == (
        None,
        "",
        (ANALYTICS_SCOPE,),
    )
    assert not any(base.endswith("/channels") for _, base, _ in api.requests)
    # A failed lookup leaves the account unknown.
    api = FakeYouTube()
    api.fail_next(_error(500, "backendError"))
    assert _grant(api, _provider(api)).refusal == "channel_unavailable"


def test_refresh_keeps_the_refresh_token_and_revocation_ends_every_grant():
    api = FakeYouTube()
    provider = _provider(api)
    grant = _grant(api, provider)
    refreshed = provider.refresh(grant.refresh_token)
    assert refreshed.refresh_token == grant.refresh_token
    assert refreshed.access_token != grant.access_token
    assert refreshed.refresh_expires_at == NOW + timedelta(seconds=604799 - 120)
    assert provider.revoke(grant.refresh_token, "refresh_token") == "done"
    assert not api.usable(grant.access_token) and not api.usable(refreshed.access_token)
    # An already revoked token is reported as done; the refresh is then refused.
    assert provider.revoke(grant.access_token, "access_token") == "done"
    with pytest.raises(ProviderError) as refused:
        provider.refresh(grant.refresh_token)
    assert (refused.value.kind, refused.value.provider_code) == (
        ErrorKind.UNAUTHORIZED,
        "invalid_grant",
    )
    failing = YouTubeProvider(
        CLIENT_ID, CLIENT_SECRET, transport=lambda *args: Reply(503, {}), clock=lambda: NOW
    )
    with pytest.raises(ProviderError) as unavailable:
        failing.revoke("token", "access_token")
    assert unavailable.value.kind is ErrorKind.RETRYABLE


def test_channel_snapshot_and_day_reports():
    api = FakeYouTube()
    provider = _provider(api)
    access = _grant(api, provider).access_token
    page = provider.fetch_page(access, stream="channel")
    (record,) = page.records
    assert (record.provider_object_id, record.observed_at) == (
        "snapshot-2026-11-18",
        datetime(2026, 11, 18, tzinfo=UTC) + PST,
    )
    assert dict(record.metrics) == {"subscriberCount": 12300, "viewCount": 1234, "videoCount": 2}
    assert page.account_label == LABEL and page.next_cursor is None
    api.hidden_subscribers = True
    (hidden,) = provider.fetch_page(access, stream="channel").records
    assert "subscriberCount" not in hidden.metrics
    assert hidden.unavailable == {"subscriberCount": "not_returned"}

    # 90 days at connect, complete through 2026-11-14 (72 hours before 12:00 PST on 11-18),
    # read in windows of at most 31 days.
    pages, cursor = [], None
    while True:
        page = provider.fetch_page(access, stream="channel_daily", cursor=cursor)
        pages.append(page)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert [len(item.records) for item in pages] == [31, 31, 28]
    assert pages[-1].complete_through == datetime(2026, 11, 15, tzinfo=UTC) + PST
    assert pages[0].covered_from == datetime(2026, 8, 17, tzinfo=UTC) + timedelta(hours=7)
    reports = [query for _, base, query in api.requests if "youtubeanalytics" in base]
    assert (reports[0]["startDate"], reports[-1]["endDate"]) == ("2026-08-17", "2026-11-14")
    assert reports[0]["metrics"] == ",".join(METRIC_NAMES) and reports[0]["dimensions"] == "day"
    days = {record.provider_object_id: record for item in pages for record in item.records}
    missing = [key for key in days if date.fromisoformat(key[4:]).toordinal() % 7 == 0]
    assert missing
    for key in missing:
        assert dict(days[key].metrics) == {}
        assert set(days[key].unavailable.values()) == {"not_returned"}
        assert set(days[key].unavailable) == set(METRIC_NAMES)
    assert days["day-2026-11-01"].observed_at == datetime(2026, 11, 1, 7, tzinfo=UTC)
    # An incremental window starts at the Pacific day of `since`.
    later = provider.fetch_page(
        access, stream="channel_daily", since=datetime(2026, 11, 11, 8, tzinfo=UTC)
    )
    assert [item.provider_object_id for item in later.records] == [
        "day-2026-11-11",
        "day-2026-11-12",
        "day-2026-11-13",
        "day-2026-11-14",
    ]


def test_inventory_attributes_totals_and_deleted_videos():
    api = FakeYouTube(videos=60)
    provider = _provider(api)
    access = _grant(api, provider).access_token
    first = provider.fetch_page(access, stream="videos")
    assert len(first.records) == 50 and first.next_cursor is not None
    assert parse_qs(first.next_cursor) == {"uploads": [UPLOADS], "page": ["50"]}
    second = provider.fetch_page(access, stream="videos", cursor=first.next_cursor)
    assert len(second.records) == 10 and second.next_cursor is None
    # The uploads playlist is resolved once, on the first page.
    uploads = [
        query
        for _, base, query in api.requests
        if query.get("part") == "contentDetails" and base.endswith("/channels")
    ]
    assert len(uploads) == 1
    videos = {record.provider_object_id: record for record in first.records}
    assert videos["v0001"].attributes == {
        "published_at": "2026-11-13T10:00:00Z",
        "duration": "PT1M",
        "privacy_status": "private",
        "live_state": "none",
    }
    assert {record.attributes["privacy_status"] for record in videos.values()} == {
        "private",
        "unlisted",
        "public",
    }
    assert videos["v0003"].unavailable == {"likeCount": "not_returned"}
    assert videos["v0002"].unavailable == {"commentCount": "not_returned"}
    assert dict(videos["v0004"].metrics) == {"viewCount": 400, "likeCount": 40, "commentCount": 4}

    totals = provider.fetch_page(access, stream="video_totals")
    by_id = {record.provider_object_id: record for record in totals.records}
    assert len(by_id) == 50 and totals.complete_through == datetime(2026, 11, 15, tzinfo=UTC) + PST
    assert (
        by_id["v0001"].product_type,
        by_id["v0003"].product_type,
        by_id["v0005"].product_type,
    ) == (
        "VIDEO_ON_DEMAND",
        "SHORTS",
        "UNSPECIFIED",
    )
    assert by_id["v0002"].product_type is None and dict(by_id["v0002"].metrics) == {}
    assert set(by_id["v0002"].unavailable) == set(METRIC_NAMES)
    assert by_id["v0001"].observed_at == datetime(2026, 11, 14, tzinfo=UTC) + PST
    assert by_id["v0001"].provisional_until == datetime(2026, 11, 13, tzinfo=UTC) + PST + timedelta(
        hours=193
    )
    report = [
        query
        for _, base, query in api.requests
        if query.get("dimensions") == "video,creatorContentType"
    ][-1]
    assert (report["startDate"], report["endDate"]) == ("2005-02-14", "2026-11-14")
    assert report["filters"].startswith("video==v0001,v0002")

    api.deleted.add("v0004")
    assert provider.confirm_deleted(access, stream="videos", object_ids=("v0003", "v0004")) == (
        "v0004",
    )
    with pytest.raises(ProviderError):
        provider.confirm_deleted(
            access, stream="videos", object_ids=tuple(f"x{i}" for i in range(51))
        )


@pytest.mark.parametrize(
    ("reply", "stream", "kind", "code", "bucket"),
    [
        (_error(401, "authError"), "channel", ErrorKind.UNAUTHORIZED, "auth_error", None),
        (
            _error(403, "quotaExceeded"),
            "channel",
            ErrorKind.BUDGET_EXHAUSTED,
            "quota_exceeded",
            DATA,
        ),
        (
            _error(403, "quotaExceeded"),
            "channel_daily",
            ErrorKind.BUDGET_EXHAUSTED,
            "quota_exceeded",
            ANALYTICS,
        ),
        (
            _error(403, "insufficientPermissions"),
            "channel",
            ErrorKind.FORBIDDEN,
            "insufficient_permissions",
            None,
        ),
        (_error(403, "rateLimitExceeded"), "channel", ErrorKind.RATE_LIMITED, "rate_limited", None),
        (_error(500, "backendError"), "channel_daily", ErrorKind.RETRYABLE, "backend_error", None),
        (_error(400, "invalidFilters"), "videos", ErrorKind.PERMANENT, "bad_request", None),
    ],
)
def test_errors_map_to_runtime_kinds(reply, stream, kind, code, bucket):
    api = FakeYouTube()
    provider = _provider(api)
    access = _grant(api, provider).access_token
    api.fail_next(reply)
    with pytest.raises(ProviderError) as raised:
        provider.fetch_page(access, stream=stream)
    assert (raised.value.kind, raised.value.provider_code, raised.value.bucket) == (
        kind,
        code,
        bucket,
    )


def test_rate_limits_carry_retry_after_and_invalid_tokens_are_unauthorized():
    api = FakeYouTube()
    provider = _provider(api)
    access = _grant(api, provider).access_token
    api.fail_next(Reply(429, {}, {"retry-after": "30"}))
    with pytest.raises(ProviderError) as limited:
        provider.fetch_page(access, stream="channel")
    assert (limited.value.kind, limited.value.retry_after) == (ErrorKind.RATE_LIMITED, 30)
    with pytest.raises(ProviderError) as unauthorized:
        provider.fetch_page("not-a-token", stream="channel")
    assert unauthorized.value.kind is ErrorKind.UNAUTHORIZED


def test_settings_and_rule_gated_registration(settings, monkeypatch):
    assert "youtube" not in build_providers(settings)
    enabled = settings.model_copy(
        update={
            "connector_youtube_enabled": True,
            "youtube_client_id": CLIENT_ID,
            "youtube_client_secret": SecretStr(CLIENT_SECRET),
        }
    )
    registry = build_providers(enabled, date(2026, 11, 18))
    assert set(registry) == {"youtube"} and repr(registry) == "{'youtube': YouTubeProvider()}"
    # A rule past its review date, or a stale rule, keeps the adapter out of the registry.
    assert build_providers(enabled, date(2027, 11, 19)) == {}
    original = connectors.rule
    monkeypatch.setattr(
        connectors,
        "rule",
        lambda name: (
            replace(original(name), status=RuleStatus.STALE)
            if name == "youtube.other_data"
            else original(name)
        ),
    )
    assert build_providers(enabled, date(2026, 11, 18)) == {}
    base = {"database_password": "synthetic", "_env_file": None, "connector_youtube_enabled": True}
    for values in (
        {"youtube_client_id": "", "youtube_client_secret": CLIENT_SECRET},
        {"youtube_client_id": "123-abc.example.com", "youtube_client_secret": CLIENT_SECRET},
        {"youtube_client_id": CLIENT_ID, "youtube_client_secret": ""},
        {"youtube_client_id": CLIENT_ID, "youtube_client_secret": " padded secret "},
        {
            "youtube_client_id": CLIENT_ID,
            "youtube_client_secret": CLIENT_SECRET,
            "gmail_client_id": CLIENT_ID,
        },
    ):
        with pytest.raises(ValidationError) as invalid:
            Settings(**base, **values)
        assert CLIENT_SECRET not in str(invalid.value)
    disabled = Settings(database_password="synthetic", _env_file=None)
    assert disabled.connector_youtube_enabled is False
