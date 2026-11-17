"""Offline checks of the owner-run YouTube feasibility tool (specification 011-B, D-058).

A fake transport stands in for Google; nothing here contacts the network except one test of
the loopback receiver on 127.0.0.1. The main property is that no token, code, secret, channel
or video ID, or metric value reaches the console or the evidence files.
"""

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from dotenv import dotenv_values

import app.youtube_feasibility as tool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
TODAY = NOW.astimezone(tool.PACIFIC).date()
CLIENT_ID = "123456789012-abcdef.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-client-secret"
CODE, ACCESS, RENEWED = "4/0CodeSecretValue", "ya29.AccessSecret", "ya29.RenewedSecret"
REFRESH, REFRESH_B = "1//RefreshSecretA", "1//RefreshSecretB"
CHANNEL_ID, UPLOADS = "UCchannelIdentifier0001", "UUchannelIdentifier0001"
VIDEO_IDS = ("Vid0000001a", "Vid0000002b", "Vid0000003c")
VIEWS, SUBSCRIBERS, MINUTES = 7319753, 6626021, 5180417
SECRETS = (
    CLIENT_SECRET,
    CODE,
    ACCESS,
    RENEWED,
    REFRESH,
    REFRESH_B,
    CHANNEL_ID,
    UPLOADS,
    *VIDEO_IDS,
    str(VIEWS),
    str(SUBSCRIBERS),
    str(MINUTES),
)
REDIRECT = "http://127.0.0.1:8000/connectors/oauth/callback"


def _config():
    return tool.AppConfig(CLIENT_ID, CLIENT_SECRET, REDIRECT)


def _reply(status, body, headers=None):
    return tool.Reply(status, body, headers or {})


def _api_error(code, reason, message="", status="FAILED"):
    return {
        "error": {
            "code": code,
            "status": status,
            "message": message,
            "errors": [{"reason": reason, "domain": "youtube"}],
        }
    }


class FakeGoogle:
    """Answers the documented requests with identifying values that must never leak."""

    def __init__(self, *, data_scope=True, reject_combined=False, quota=False, views=VIEWS):
        self.requests = []
        self.data_scope, self.reject_combined, self.quota = data_scope, reject_combined, quota
        self.views = views
        self.revoked: set[str] = set()

    def __call__(self, method, url, form, headers):
        self.requests.append((method, url, dict(form or {}), dict(headers or {})))
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if url == tool.TOKEN_URL:
            return self._token(form)
        if url == tool.REVOKE_URL:
            # Google revokes every token of the account in the project (entry review G-1).
            self.revoked |= {REFRESH, REFRESH_B}
            return _reply(200, {})
        bearer = (headers or {}).get("Authorization", "")
        if bearer == "Bearer invalid-feasibility-token":
            return _reply(
                401,
                _api_error(401, "authError", "Request had invalid credentials.", "UNAUTHENTICATED"),
            )
        assert bearer in {f"Bearer {ACCESS}", f"Bearer {RENEWED}"}
        if self.quota:
            return _reply(403, _api_error(403, "quotaExceeded", "The request exceeded quota."))
        if parts.netloc == "www.googleapis.com":
            return self._data(parts.path.removeprefix("/youtube/v3/"), query)
        return self._analytics(query)

    def _token(self, form):
        scope = " ".join(tool.SCOPE_SETS["all" if self.data_scope else "analytics-only"])
        if form["grant_type"] == "authorization_code":
            assert form["code"] == CODE and form["client_secret"] == CLIENT_SECRET
            return _reply(
                200,
                {
                    "access_token": ACCESS,
                    "expires_in": 3599,
                    "refresh_token": REFRESH,
                    "scope": scope,
                    "token_type": "Bearer",
                },
            )
        if form["refresh_token"] in self.revoked:
            return _reply(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "Token has been expired or revoked.",
                },
            )
        return _reply(
            200,
            {"access_token": RENEWED, "expires_in": 3599, "scope": scope, "token_type": "Bearer"},
        )

    def _data(self, resource, query):
        if not self.data_scope:
            return _reply(
                403,
                _api_error(403, "insufficientPermissions", "Request had insufficient scopes."),
            )
        if resource == "channels":
            return _reply(
                200,
                {
                    "items": [
                        {
                            "id": CHANNEL_ID,
                            "statistics": {
                                "viewCount": str(self.views),
                                "subscriberCount": str(SUBSCRIBERS),
                                "hiddenSubscriberCount": False,
                                "videoCount": "1",
                            },
                            "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        if resource == "playlistItems":
            assert query["playlistId"] == UPLOADS
            statuses = ("public", "unlisted", "private")
            return _reply(
                200,
                {
                    "items": [
                        {"contentDetails": {"videoId": video}, "status": {"privacyStatus": status}}
                        for video, status in zip(VIDEO_IDS, statuses, strict=True)
                    ]
                },
            )
        if resource == "videos" and query["part"] == "id":
            return _reply(
                400,
                _api_error(400, "badRequest", f"Too many IDs, starting with {VIDEO_IDS[0]}."),
            )
        if resource == "videos":
            assert "title" not in query["fields"]
            return _reply(
                200,
                {
                    "items": [
                        {
                            "id": VIDEO_IDS[0],
                            "snippet": {
                                "publishedAt": "2026-11-10T09:00:00Z",
                                "liveBroadcastContent": "none",
                            },
                            "contentDetails": {"duration": "PT4M13S"},
                            "status": {"privacyStatus": "public"},
                            "statistics": {
                                "viewCount": str(self.views),
                                "likeCount": "12",
                                "commentCount": "3",
                            },
                        },
                        {
                            "id": VIDEO_IDS[1],
                            "snippet": {"publishedAt": "2026-10-01T09:00:00Z"},
                            "contentDetails": {"duration": "PT59S"},
                            "status": {"privacyStatus": "unlisted"},
                            "statistics": {"viewCount": "5"},
                        },
                    ]
                },
            )
        if resource == "videos:batchGetStats":
            return _reply(
                200,
                {
                    "items": [{"id": VIDEO_IDS[0], "statistics": {"viewCount": str(self.views)}}],
                    "summary": {"requestedVideoCount": 3, "failedVideoIds": [VIDEO_IDS[2]]},
                },
            )
        return _reply(404, _api_error(404, "notFound"))

    def _analytics(self, query):
        assert query["ids"] == "channel==MINE"
        dimensions = query.get("dimensions")
        metrics = query["metrics"].split(",")
        if dimensions == "day":
            if len(metrics) > 1 and self.reject_combined:
                return _reply(
                    400,
                    _api_error(400, "badRequest", "Unknown identifier (dislikes) given."),
                )
            start = date.fromisoformat(query["startDate"])
            end = date.fromisoformat(query["endDate"]) - timedelta(days=3)
            rows = []
            day = start
            while day <= end:
                if day != end - timedelta(days=5):
                    values = [0 if day == end - timedelta(days=6) else self.views] * len(metrics)
                    rows.append([day.isoformat(), *values])
                day += timedelta(days=1)
            headers = [{"name": "day", "columnType": "DIMENSION", "dataType": "STRING"}] + [
                {"name": name, "columnType": "METRIC", "dataType": "INTEGER"} for name in metrics
            ]
            body = {"columnHeaders": headers}
            if rows:
                body["rows"] = rows
            return _reply(200, body)
        if dimensions == "month":
            return _reply(
                200,
                {
                    "columnHeaders": [{"name": "month"}, {"name": "views"}],
                    "rows": [["2025-03", MINUTES], ["2026-10", VIEWS]],
                },
            )
        if dimensions is None:
            return _reply(200, {"columnHeaders": [{"name": "views"}], "rows": [[VIEWS]]})
        if dimensions == "video,creatorContentType":
            return _reply(
                200,
                {
                    "columnHeaders": [
                        {"name": "video"},
                        {"name": "creatorContentType"},
                        {"name": "views"},
                    ],
                    "rows": [[VIDEO_IDS[0], "SHORTS", VIEWS], [VIDEO_IDS[1], "VIDEO_ON_DEMAND", 4]],
                },
            )
        if dimensions == "video":
            names = [{"name": "video"}] + [{"name": name} for name in metrics]
            return _reply(
                200,
                {"columnHeaders": names, "rows": [[VIDEO_IDS[0], *[MINUTES] * len(metrics)]]},
            )
        if dimensions == "creatorContentType":
            return _reply(
                200,
                {
                    "columnHeaders": [{"name": "creatorContentType"}, {"name": "views"}],
                    "rows": [["SHORTS", VIEWS], ["VIDEO_ON_DEMAND", MINUTES]],
                },
            )
        return _reply(400, _api_error(400, "badRequest", "The query is not supported."))


def _clean(text):
    for secret in SECRETS:
        assert secret not in text, secret


def _without_digests(evidence):
    copy = json.loads(json.dumps(evidence))
    (copy.get("day_report") or {}).pop("digests", None)
    return json.dumps(copy)


def test_authorization_url_asks_read_only_offline_consent_and_pkce_only_on_request():
    scopes = tool.SCOPE_SETS["all"]
    query = parse_qs(urlsplit(tool.authorization_url(_config(), scopes, "state-1")).query)
    assert query["scope"] == [
        "https://www.googleapis.com/auth/youtube.readonly "
        "https://www.googleapis.com/auth/yt-analytics.readonly"
    ]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == [REDIRECT]
    assert "code_challenge" not in query and "include_granted_scopes" not in query
    verifier, challenge = tool.pkce_pair()
    probed = parse_qs(urlsplit(tool.authorization_url(_config(), scopes, "s", challenge)).query)
    assert probed["code_challenge"] == [challenge] and probed["code_challenge_method"] == ["S256"]
    assert verifier != challenge
    narrow = parse_qs(
        urlsplit(tool.authorization_url(_config(), tool.SCOPE_SETS["analytics-only"], "s")).query
    )
    assert narrow["scope"] == ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def test_configuration_requires_a_web_client_and_a_loopback_redirect():
    good = {tool.CLIENT_ID: CLIENT_ID, tool.CLIENT_SECRET: CLIENT_SECRET}
    config = tool.app_config(good)
    assert config.redirect_uri == tool.DEFAULT_REDIRECT
    assert CLIENT_SECRET not in repr(config)
    for change in (
        {tool.CLIENT_ID: "not-a-client"},
        {tool.CLIENT_SECRET: ""},
        {tool.REDIRECT: "https://example.com/callback"},
        {tool.REDIRECT: "http://127.0.0.1/callback"},
        {tool.REDIRECT: "http://127.0.0.1:8000/"},
        {tool.REDIRECT: "http://127.0.0.1:8000/cb#x"},
        {tool.REDIRECT: "http://127.0.0.1:99999/cb"},
    ):
        with pytest.raises(tool.FeasibilityFailed):
            tool.app_config(good | change)
    assert tool.app_config(good | {tool.REDIRECT: "http://localhost:8765/cb"})


def test_callback_parsing_checks_the_state_and_reports_refusals():
    assert tool.code_from_callback(f"/cb?state=s1&code={CODE}&scope=x", "s1") == (CODE, None)
    assert tool.code_from_callback("/cb?error=access_denied&state=s1", "s1") == (
        None,
        "access_denied",
    )
    assert tool.code_from_callback("/cb?error=<script>&state=s1", "s1") == (None, "other")
    for target in (f"/cb?state=other&code={CODE}", "/cb?state=s1", f"/cb?code={CODE}"):
        with pytest.raises(tool.FeasibilityFailed):
            tool.code_from_callback(target, "s1")


def test_the_loopback_receiver_keeps_only_its_path_and_logs_nothing(capsys):
    receiver = tool.CallbackReceiver("127.0.0.1", 0, "/connectors/oauth/callback")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{receiver.port}"
    answers = []

    def browser():
        try:
            opener.open(f"{base}/favicon.ico", timeout=5)
        except urllib.error.HTTPError as error:
            answers.append(error.code)
        with opener.open(f"{base}/connectors/oauth/callback?code={CODE}&state=s1", timeout=5) as r:
            answers.append(r.read().decode())

    thread = threading.Thread(target=browser)
    thread.start()
    received = receiver.wait(10)
    thread.join(10)
    assert received == f"/connectors/oauth/callback?code={CODE}&state=s1"
    assert answers[0] == 404 and "received the answer" in answers[1]
    output = capsys.readouterr()
    assert CODE not in output.out and CODE not in output.err


def test_probe_records_availability_without_identifying_values():
    google = FakeGoogle()
    evidence = tool.probe_channel(google, ACCESS, NOW, digest_key=b"k" * 32)
    _clean(json.dumps(evidence))
    assert evidence["channel"] == {
        "outcome": "ok",
        "items": 1,
        "statistics": {
            "viewCount": "string",
            "subscriberCount": "string",
            "hiddenSubscriberCount": "bool",
            "videoCount": "string",
        },
        "hidden_subscriber_count": False,
        "uploads_playlist": True,
        "privacy_status": "public",
    }
    assert evidence["uploads"]["privacy_status"] == {"private": 1, "public": 1, "unlisted": 1}
    videos = evidence["videos"]
    assert videos["requested"] == 3 and videos["returned"] == 2
    assert videos["statistics_present"]["likeCount"] == 1
    assert videos["statistics_present"]["dislikeCount"] == 0
    assert videos["title_returned"] is False and videos["iso_durations"] == 2
    assert videos["public_items_equal_video_count"] is True
    assert videos["age_days_range"] == [10, 50]
    assert evidence["videos_51_ids"]["reasons"] == ["badRequest"]
    assert "<id>" in evidence["videos_51_ids"]["message"]
    assert evidence["batch_get_stats"]["summary_keys"] == ["failedVideoIds", "requestedVideoCount"]
    day = evidence["day_report"]
    assert day["requested_days"] == 31 and day["last_day_offset"] == 3
    assert day["missing_days_within_range"] == 1 and day["zero_view_days"] == 1
    assert [header["name"] for header in day["column_headers"]] == ["day", *tool.CATALOG]
    assert day["value_types"]["views"] == ["int"]
    assert "changed_since_previous_probe" not in day
    history = evidence["history_one_day_at_depth"]
    assert set(history) == {str(days) for days in tool.HISTORY_DAYS}
    assert evidence["months_since_documented_start"]["earliest_month_offset"] == 20
    reports = evidence["video_reports"]
    assert reports["video_filter_catalog"]["rows"] == 1
    assert reports["video_and_content_type"]["values_of_creatorContentType"] == [
        "SHORTS",
        "VIDEO_ON_DEMAND",
    ]
    assert evidence["invalid_token"]["data"]["status"] == 401
    assert evidence["invalid_token"]["analytics"]["reasons"] == ["authError"]
    assert evidence["calls"]["invalid_token"] == 2 and evidence["stopped"] is None
    # Only GET reads with a bearer header; the token never travels in a URL.
    assert {method for method, *_ in google.requests} == {"GET"}
    assert all(ACCESS not in url for _, url, _, _ in google.requests)


def test_a_refused_combined_day_report_is_retried_one_metric_at_a_time():
    evidence = tool.probe_channel(FakeGoogle(reject_combined=True), ACCESS, NOW, digest_key=b"k")
    day = evidence["day_report"]
    assert day["combined"]["reasons"] == ["badRequest"]
    assert set(day["per_metric"]) == set(tool.CATALOG)
    assert all(item["outcome"] == "rows" for item in day["per_metric"].values())
    _clean(json.dumps(evidence))


def test_analytics_only_consent_shows_what_needs_the_data_scope():
    evidence = tool.probe_channel(FakeGoogle(data_scope=False), ACCESS, NOW, digest_key=b"k")
    assert evidence["channel"]["reasons"] == ["insufficientPermissions"]
    assert "uploads" not in evidence and "videos" not in evidence
    assert evidence["day_report"]["outcome"] == "rows"
    assert evidence["video_reports"]["video_filter_catalog"] == {"outcome": "no_videos"}


def test_quota_answers_and_the_call_budget_stop_the_probe():
    stopped = tool.probe_channel(FakeGoogle(quota=True), ACCESS, NOW, digest_key=b"k")
    assert stopped["stopped"] == "quota_or_rate_limit"
    assert stopped["calls"]["data"] == 1 and stopped["calls"]["analytics"] == 0
    assert stopped["channel"]["reasons"] == ["quotaExceeded"]
    limited = tool.probe_channel(FakeGoogle(), ACCESS, NOW, max_calls=4, digest_key=b"k")
    assert sum(limited["calls"].values()) == 4
    assert "not_requested" in json.dumps(limited)


def test_exchange_and_refresh_keep_only_scopes_and_lifetimes():
    tokens, record = tool.exchange_code(FakeGoogle(), _config(), CODE, None)
    assert tokens == {"access_token": ACCESS, "refresh_token": REFRESH}
    assert record == {
        "code_exchange_status": 200,
        "fields": ["access_token", "expires_in", "refresh_token", "scope", "token_type"],
        "granted_scopes": sorted(tool.SCOPE_SETS["all"]),
        "token_type": "Bearer",
        "expires_in": 3599,
        "refresh_token_returned": True,
        "refresh_token_expires_in": None,
    }
    google = FakeGoogle()
    access, renewed = tool.refresh_access(google, _config(), REFRESH)
    assert access == RENEWED and renewed["refresh_token_returned"] is False
    google.revoked.add(REFRESH)
    access, refused = tool.refresh_access(google, _config(), REFRESH)
    assert access is None and refused["error"] == "invalid_grant" and refused["status"] == 400


def _env(tmp_path, extra=""):
    env = tmp_path / ".env"
    env.write_text(
        f"TRACKING_YOUTUBE_CLIENT_ID={CLIENT_ID}\nTRACKING_YOUTUBE_CLIENT_SECRET={CLIENT_SECRET}\n"
        f"OTHER=kept\n{extra}",
        encoding="utf-8",
    )
    return env


class StubReceiver:
    def __init__(self, target):
        self.target, self.configs = target, []

    def __call__(self, config):
        self.configs.append(config)
        return self

    def wait(self, timeout):
        return self.target


def test_owner_commands_store_and_forget_tokens_without_printing(tmp_path, monkeypatch, capsys):
    env = _env(tmp_path)
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    receiver = StubReceiver(f"/connectors/oauth/callback?state=fixed-24&code={CODE}")
    google = FakeGoogle()
    base = ["--env-file", str(env)]
    assert tool.main([*base, "authorize", "--no-browser"], google, receiver) == 0
    assert receiver.configs[0].redirect_uri == tool.DEFAULT_REDIRECT
    values = dotenv_values(env)
    assert values[tool.SLOTS["a"][0]] == REFRESH and values["OTHER"] == "kept"
    assert tool.main([*base, "probe"], google) == 0
    assert tool.main([*base, "refresh"], google) == 0
    assert tool.main([*base, "check-access"], google) == 0
    output = capsys.readouterr()
    _clean(output.out)
    _clean(output.err)
    folder = tmp_path / "local-data" / "youtube-feasibility"
    files = sorted(folder.glob("*.json"))
    assert {path.name.split("-")[0] for path in files} == {"authorize", "probe", "refresh", "check"}
    for path in files:
        _clean(_without_digests(json.loads(path.read_text(encoding="utf-8"))))
    assert (folder / "digest-key").is_file()
    assert tool.main([*base, "forget"], google) == 0
    values = dotenv_values(env)
    assert all(name not in values for names in tool.SLOTS.values() for name in names)
    assert values["OTHER"] == "kept"
    assert tool.main([*base, "probe"], google) == 1


def test_a_refused_consent_is_recorded_and_nothing_is_stored(tmp_path):
    env = _env(tmp_path)
    receiver = StubReceiver("/connectors/oauth/callback?error=access_denied")
    argv = ["--env-file", str(env), "authorize", "--no-browser"]
    assert tool.main(argv, FakeGoogle(), receiver) == 1
    (path,) = (tmp_path / "local-data" / "youtube-feasibility").glob("authorize-*.json")
    assert json.loads(path.read_text(encoding="utf-8"))["consent"] == "access_denied"
    assert tool.SLOTS["a"][0] not in dotenv_values(env)


def test_a_wrong_pkce_verifier_is_recorded_and_nothing_is_stored(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    receiver = StubReceiver(f"/connectors/oauth/callback?state=fixed-24&code={CODE}")

    def refusing(method, url, form, headers):
        assert method == "POST" and url == tool.TOKEN_URL and form["code_verifier"]
        return _reply(
            400, {"error": "invalid_grant", "error_description": "Invalid code verifier."}
        )

    argv = ["--env-file", str(env), "authorize", "--no-browser", "--pkce-wrong-verifier"]
    assert tool.main(argv, refusing, receiver) == 0
    (path,) = (tmp_path / "local-data" / "youtube-feasibility").glob("authorize-*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["pkce"] == "wrong_verifier"
    assert record["code_exchange_error"]["error"] == "invalid_grant"
    assert tool.SLOTS["a"][0] not in dotenv_values(env)


def test_revoke_test_needs_confirmation_and_records_the_other_consent(tmp_path, capsys):
    a, b = tool.SLOTS["a"], tool.SLOTS["b"]
    env = _env(tmp_path, f"{a[0]}={REFRESH}\n{b[0]}={REFRESH_B}\n")
    google = FakeGoogle()
    waits = []
    base = ["--env-file", str(env), "revoke-test"]
    assert tool.main(base, google, sleep=waits.append) == 1
    assert not waits and not google.requests
    assert tool.main([*base, "--confirm"], google, sleep=waits.append) == 0
    assert waits == [tool.REVOCATION_WAIT]
    (path,) = (tmp_path / "local-data" / "youtube-feasibility").glob("revoke-test-*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["b_before"]["status"] == 200 and record["revoke_a"] == {"status": 200}
    assert record["b_survives_revocation_of_a"] is False
    assert record["b_after"]["error"] == "invalid_grant"
    values = dotenv_values(env)
    assert a[0] not in values and b[0] not in values
    _clean(capsys.readouterr().out)
    _clean(json.dumps(record))


def test_a_later_probe_reports_which_days_changed_through_digests(tmp_path):
    folder = tmp_path / "evidence"
    key = tool.digest_key(folder)
    assert tool.digest_key(folder) == key
    first = tool.probe_channel(FakeGoogle(), ACCESS, NOW, digest_key=key)
    tool.write_evidence(folder, "probe", first)
    previous = tool.latest_digests(folder)
    assert previous == first["day_report"]["digests"]
    second = tool.probe_channel(
        FakeGoogle(views=VIEWS + 1), ACCESS, NOW, digest_key=key, previous=previous
    )
    changed = second["day_report"]["changed_since_previous_probe"]
    assert changed["compared_days"] == first["day_report"]["rows"]
    # Every day with views changed; the zero-view day did not.
    assert len(changed["changed_day_offsets"]) == changed["compared_days"] - 1
    assert key.hex() not in json.dumps(second)


def test_redaction_removes_known_and_identifier_like_words():
    known = {CHANNEL_ID}
    text = (
        f"Channel {CHANNEL_ID} in project 123456789012 exceeded the insufficientPermissions "
        "check at youtube.googleapis.com for a non-public video."
    )
    redacted = tool.redact(text, known)
    assert CHANNEL_ID not in redacted and "123456789012" not in redacted
    assert "youtube.googleapis.com" in redacted and "exceeded the" in redacted
    assert tool.redact(None) is None and len(tool.redact("x" * 500)) == 200
