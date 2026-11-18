"""Offline checks of the owner-run YouTube feasibility tool (specification 011-B, D-058).

A fake transport stands in for Google; nothing here contacts the network except one test of
the loopback receiver on 127.0.0.1. The main property is that no token, code, secret, channel
or video ID, or metric value reaches the console or the evidence files.
"""

import json
import socket
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
MANY_IDS = tuple(f"Many{number:07d}" for number in range(80))
VIEWS, SUBSCRIBERS, MINUTES = 7319753, 6626021, 5180417
SECRETS = (
    *MANY_IDS,
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
    """Answers the documented requests with identifying values that must never leak.

    uploads switches to a channel of that many public uploads (paged by 50); ID lists are
    answered after removing repeated IDs, and more than 50 distinct IDs are refused.
    strict_video_sort refuses video reports without sort and maxResults. revocation_delay
    lets the other consent stop working only once the fake clock has advanced that far.
    fail_at_get makes the n-th GET request get no answer.
    """

    def __init__(
        self,
        *,
        data_scope=True,
        reject_combined=False,
        quota=False,
        views=VIEWS,
        uploads=None,
        strict_video_sort=False,
        revocation_delay=None,
        fail_at_get=None,
    ):
        self.requests = []
        self.data_scope, self.reject_combined, self.quota = data_scope, reject_combined, quota
        self.views, self.uploads, self.strict_video_sort = views, uploads, strict_video_sort
        self.revocation_delay, self.fail_at_get = revocation_delay, fail_at_get
        self.revoked: set[str] = set()
        self.clock, self.gets, self.b_revoked_at = 0.0, 0, None

    def __call__(self, method, url, form, headers):
        self.requests.append((method, url, dict(form or {}), dict(headers or {})))
        if method == "GET":
            self.gets += 1
            if self.gets == self.fail_at_get:
                raise tool.FeasibilityFailed("A Google endpoint did not answer.")
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if url == tool.TOKEN_URL:
            return self._token(form)
        if url == tool.REVOKE_URL:
            # Google revokes every token of the account in the project (entry review G-1);
            # with a delay, the other consent stops working only later.
            self.revoked.add(REFRESH)
            if self.revocation_delay is None:
                self.revoked.add(REFRESH_B)
            else:
                self.b_revoked_at = self.clock + self.revocation_delay
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
        late = self.b_revoked_at is not None and self.clock >= self.b_revoked_at
        if form["refresh_token"] in self.revoked or (form["refresh_token"] == REFRESH_B and late):
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
                                "videoCount": str(self.uploads) if self.uploads else "1",
                            },
                            "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}},
                            "status": {"privacyStatus": "public"},
                        }
                    ]
                },
            )
        if resource == "playlistItems":
            assert query["playlistId"] == UPLOADS
            if self.uploads:
                start = int(query.get("pageToken", "0"))
                page = MANY_IDS[: self.uploads][start : start + 50]
                body = {
                    "items": [
                        {
                            "contentDetails": {"videoId": video},
                            "status": {"privacyStatus": "public"},
                        }
                        for video in page
                    ]
                }
                if start + 50 < self.uploads:
                    body["nextPageToken"] = str(start + 50)
                return _reply(200, body)
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
        if resource == "videos:batchGetStats" or query.get("part") == "id":
            # Repeated IDs are merged, and more than 50 distinct IDs are refused.
            distinct = list(dict.fromkeys(query["id"].split(",")))
            if len(distinct) > 50:
                return _reply(
                    400,
                    _api_error(400, "invalidFilters", f"Too many IDs, such as {distinct[0]}."),
                )
            items = [
                {"id": video, "statistics": {"viewCount": str(self.views)}} for video in distinct
            ]
            if resource == "videos":
                return _reply(200, {"items": [{"id": item["id"]} for item in items]})
            return _reply(
                200,
                {
                    "items": items,
                    "summary": {"requestedVideoCount": len(distinct), "failedVideoIds": []},
                },
            )
        if resource == "videos":
            assert "title" not in query["fields"]
            if self.uploads:
                return _reply(
                    200,
                    {
                        "items": [
                            {
                                "id": video,
                                "snippet": {"publishedAt": "2026-11-01T09:00:00Z"},
                                "contentDetails": {"duration": "PT1M"},
                                "status": {"privacyStatus": "public"},
                                "statistics": {"viewCount": "7", "commentCount": "0"},
                            }
                            for video in query["id"].split(",")
                        ]
                    },
                )
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
        return _reply(404, _api_error(404, "notFound"))

    def _analytics(self, query):
        assert query["ids"] == "channel==MINE"
        dimensions = query.get("dimensions")
        metrics = query["metrics"].split(",")
        sorted_report = "sort" in query and "maxResults" in query
        if dimensions in {"video", "video,creatorContentType"} and self.strict_video_sort:
            if not sorted_report:
                return _reply(400, _api_error(400, "badRequest", "The query is not supported."))
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
            # As observed live on 2026-11-17: both dates must be the first day of a month.
            if not (query["startDate"].endswith("-01") and query["endDate"].endswith("-01")):
                return _reply(
                    400,
                    _api_error(400, "badRequest", "Date range does not align to dimension."),
                )
            return _reply(
                200,
                {
                    "columnHeaders": [{"name": "month"}, {"name": "views"}],
                    "rows": [["2024-01", 0], ["2025-03", MINUTES], ["2026-10", VIEWS]],
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
    # One of the three uploads is missing from the answer, so no comparison is made.
    assert videos["public_items_equal_video_count"] is None
    assert videos["public_items_comparison_skipped"] == "videos_missing_from_answer"
    assert videos["age_days_range"] == [10, 50]
    # Only three distinct uploads exist: 51 IDs are accepted after merging, inconclusively.
    for name in ("videos_id_limit", "batch_get_stats_id_limit"):
        assert evidence[name]["51"] == {
            "ids_sent": 51,
            "distinct_ids": 3,
            "outcome": "ok",
            "returned": 3,
            "conclusive": False,
        }
    assert evidence["batch_get_stats"]["summary_keys"] == ["failedVideoIds", "requestedVideoCount"]
    day = evidence["day_report"]
    assert day["requested_days"] == 31 and day["last_day_offset"] == 3
    assert day["missing_days_within_range"] == 1 and day["zero_view_days"] == 1
    assert [header["name"] for header in day["column_headers"]] == ["day", *tool.CATALOG]
    assert day["value_types"]["views"] == ["int"]
    assert "changed_since_previous_probe" not in day
    history = evidence["history_windows"]
    assert set(history) == {str(days) for days in tool.HISTORY_DAYS}
    assert all(item["outcome"] == "rows" for item in history.values())
    assert all(0 < item["days_with_views"] < item["rows"] for item in history.values())
    months = evidence["months_since_documented_start"]
    assert months["outcome"] == "rows" and months["months_with_views"] == 2
    assert months["earliest_month_offset"] == 34
    assert months["earliest_month_with_views_offset"] == 20
    assert months["earliest_month_with_views_days"]["outcome"] == "rows"
    assert evidence["start_before_youtube"]["outcome"] == "rows"
    density = evidence["day_density"]
    assert density["recent_views_only"]["requested_days"] == 31
    assert density["old_full_catalog"]["requested_days"] == tool.HISTORY_WINDOW
    assert density["old_full_catalog"]["columns"] == ["day", *tool.CATALOG]
    reports = evidence["video_reports"]
    assert reports["video_filter_catalog"]["rows"] == 1
    assert reports["video_filter_unsorted"]["outcome"] == "rows"
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
    assert record["conclusion"] == "final" and record["wait_seconds"] == tool.REVOCATION_WAIT
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


# Regressions of the review of bb3263e (specs/011-youtube/review-corrections-prompt.md).


def test_r011_01_video_reports_send_sort_and_max_results():
    google = FakeGoogle(strict_video_sort=True)
    reports = tool.probe_channel(google, ACCESS, NOW, digest_key=b"k")["video_reports"]
    assert reports["video_filter_catalog"]["outcome"] == "rows"
    assert reports["video_and_content_type"]["outcome"] == "rows"
    assert "video_filter_two_metrics" not in reports
    # The unsorted variant records that this answer needs sort and maxResults.
    assert reports["video_filter_unsorted"]["status"] == 400


def test_r011_02_id_limits_use_distinct_ids_and_say_whether_they_are_conclusive():
    google = FakeGoogle(uploads=60)
    evidence = tool.probe_channel(google, ACCESS, NOW, digest_key=b"k")
    _clean(json.dumps(evidence))
    for name in ("videos_id_limit", "batch_get_stats_id_limit"):
        assert evidence[name]["50"] == {
            "ids_sent": 50,
            "distinct_ids": 50,
            "outcome": "ok",
            "returned": 50,
            "conclusive": True,
        }
        refused = evidence[name]["51"]
        assert refused["ids_sent"] == 51 and refused["distinct_ids"] == 51
        assert refused["outcome"] == "error" and refused["reasons"] == ["invalidFilters"]
        assert refused["conclusive"] is True and "<id>" in refused["message"]
    # batchGetStats is sent with its required part parameter.
    stats_calls = [url for _, url, _, _ in google.requests if "videos:batchGetStats" in url]
    assert stats_calls and all("part=" in url for url in stats_calls)
    assert any("part=statistics" in url for url in stats_calls)


def test_r011_03_a_surviving_slot_b_is_provisional_until_checked_again(tmp_path, capsys):
    a, b = tool.SLOTS["a"], tool.SLOTS["b"]
    env = _env(tmp_path, f"{a[0]}={REFRESH}\n{b[0]}={REFRESH_B}\n")
    google = FakeGoogle(revocation_delay=600)
    argv = ["--env-file", str(env), "revoke-test", "--confirm"]
    assert tool.main(argv, google, sleep=lambda seconds: None) == 0
    folder = tmp_path / "local-data" / "youtube-feasibility"
    (path,) = folder.glob("revoke-test-*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["wait_seconds"] == tool.REVOCATION_WAIT
    assert record["b_survives_revocation_of_a"] is True
    assert record["conclusion"] == "provisional"
    output = capsys.readouterr().out
    assert "provisional" in output and "check-access --slot b" in output
    assert dotenv_values(env)[b[0]] == REFRESH_B
    google.clock += 1800
    later = ["--env-file", str(env), "check-access", "--slot", "b"]
    assert tool.main(later, google) == 0
    (check,) = folder.glob("check-access-*.json")
    assert json.loads(check.read_text(encoding="utf-8"))["error"] == "invalid_grant"


@pytest.mark.parametrize("command", ["probe", "authorize"])
def test_r011_04_a_probe_without_an_answer_still_writes_what_it_read(
    tmp_path, monkeypatch, command
):
    a = tool.SLOTS["a"]
    env = _env(tmp_path, f"{a[0]}={REFRESH}\n" if command == "probe" else "")
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    receiver = StubReceiver(f"/connectors/oauth/callback?state=fixed-24&code={CODE}")
    argv = ["--env-file", str(env), command] + (["--no-browser"] if command == "authorize" else [])
    assert tool.main(argv, FakeGoogle(fail_at_get=12), receiver) == 0
    (path,) = (tmp_path / "local-data" / "youtube-feasibility").glob("probe-*.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["stopped"] == "no_answer"
    assert sum(evidence["calls"].values()) == 12
    assert evidence["channel"]["outcome"] == "ok"
    outcomes = json.dumps(evidence)
    assert outcomes.count('"no_answer"') == 2  # the call without an answer, and stopped
    assert "not_requested" in outcomes


def test_r011_05_public_items_are_compared_only_when_the_inventory_fits_one_batch():
    many = tool.probe_channel(FakeGoogle(uploads=60), ACCESS, NOW, digest_key=b"k")["videos"]
    assert many["public_items_equal_video_count"] is None
    assert many["public_items_comparison_skipped"] == "inventory_not_read_in_one_batch"
    few = tool.probe_channel(FakeGoogle(uploads=20), ACCESS, NOW, digest_key=b"k")["videos"]
    assert few["public_items_equal_video_count"] is True
    assert "public_items_comparison_skipped" not in few


def test_r011_06_max_calls_is_accepted_after_the_command(tmp_path, monkeypatch):
    a = tool.SLOTS["a"]
    env = _env(tmp_path, f"{a[0]}={REFRESH}\n")
    google = FakeGoogle()
    base = ["--env-file", str(env)]
    folder = tmp_path / "local-data" / "youtube-feasibility"

    def calls_of_latest_probe():
        latest = sorted(folder.glob("probe-*.json"))[-1]
        return sum(json.loads(latest.read_text(encoding="utf-8"))["calls"].values())

    assert tool.main([*base, "probe", "--max-calls", "3"], google) == 0
    assert calls_of_latest_probe() == 3
    assert tool.main([*base, "--max-calls", "5", "probe"], google) == 0
    assert calls_of_latest_probe() == 5
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    receiver = StubReceiver(f"/connectors/oauth/callback?state=fixed-24&code={CODE}")
    argv = [*base, "authorize", "--no-browser", "--max-calls", "2"]
    assert tool.main(argv, google, receiver) == 0
    assert calls_of_latest_probe() == 2


def test_r011_09_the_receiver_refuses_a_port_that_is_in_use():
    first = tool.CallbackReceiver("127.0.0.1", 0, "/cb")
    try:
        with pytest.raises(tool.FeasibilityFailed):
            tool.CallbackReceiver("127.0.0.1", first.port, "/cb")
    finally:
        first.server.server_close()


def test_r011_09_the_receiver_does_not_reuse_addresses_on_windows(monkeypatch):
    monkeypatch.setattr(tool.sys, "platform", "win32")
    receiver = tool.CallbackReceiver("127.0.0.1", 0, "/cb")
    try:
        sock = receiver.server.socket
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) != 0
    finally:
        receiver.server.server_close()
