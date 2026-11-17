"""Offline checks of the owner-run Instagram feasibility tool (specification 010-B, D-053).

A fake transport stands in for Meta; nothing here contacts the network. The main property is
that no token, code, secret, account or media ID, username, or metric value reaches the
console or the evidence files.
"""

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from dotenv import dotenv_values

import app.instagram_feasibility as tool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
SHORT, LONG, RENEWED = "IGshort-SECRET-1", "IGlong-SECRET-2", "IGrenewed-SECRET-3"
USER_ID, MEDIA_IDS = "17841400000000001", ("18000000000000011", "18000000000000022")
STORY_ID, USERNAME, CODE = "18000000000000033", "private.owner.name", "AQCodeSecret"
APP_SECRET = "app-secret-value"
SECRETS = (SHORT, LONG, RENEWED, USER_ID, *MEDIA_IDS, STORY_ID, USERNAME, CODE, APP_SECRET)
REDIRECT = "https://localhost/instagram-feasibility/callback"


def _config():
    return tool.AppConfig("1234567890", APP_SECRET, REDIRECT)


def _reply(status, body, headers=None):
    return tool.Reply(status, body, headers or {})


class FakeMeta:
    """Answers the documented requests with identifying values that must never leak."""

    def __init__(self, *, product_type_field=True, throttle=False):
        self.requests = []
        self.product_type_field, self.throttle = product_type_field, throttle

    def __call__(self, method, url, form):
        self.requests.append((method, url, dict(form or {})))
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if method == "POST":
            assert form["code"] == CODE and form["client_secret"] == APP_SECRET
            return _reply(
                200,
                {
                    "data": [
                        {
                            "access_token": SHORT,
                            "user_id": USER_ID,
                            "permissions": "instagram_business_basic,"
                            "instagram_business_manage_insights",
                        }
                    ]
                },
            )
        if parts.path == "/access_token":
            assert query["access_token"] == SHORT
            return _reply(
                200, {"access_token": LONG, "token_type": "bearer", "expires_in": 5183944}
            )
        if parts.path == "/refresh_access_token":
            return _reply(
                200, {"access_token": RENEWED, "token_type": "bearer", "expires_in": 5184000}
            )
        if self.throttle:
            return _reply(400, {"error": {"code": 4, "message": "Application request limit"}})
        path = parts.path.removeprefix(f"/{tool.GRAPH_VERSION}/")
        usage = {
            "X-Business-Use-Case-Usage": json.dumps(
                {USER_ID: [{"type": "instagram", "call_count": 7, "total_time": 3}]}
            )
        }
        if path == "me":
            return _reply(
                200,
                {
                    "user_id": USER_ID,
                    "username": USERNAME,
                    "account_type": "BUSINESS",
                    "media_count": 2,
                    "followers_count": 42,
                },
                usage,
            )
        if path == f"{USER_ID}/media":
            if "media_product_type" in query["fields"] and not self.product_type_field:
                return _reply(
                    400,
                    {"error": {"code": 100, "message": f"Tried accessing {USER_ID} field"}},
                )
            return _reply(
                200,
                {
                    "data": [
                        {
                            "id": MEDIA_IDS[0],
                            "media_type": "IMAGE",
                            "timestamp": "2026-11-10T09:00:00+0000",
                            **({"media_product_type": "FEED"} if self.product_type_field else {}),
                        },
                        {
                            "id": MEDIA_IDS[1],
                            "media_type": "VIDEO",
                            "timestamp": "2026-10-01T09:00:00+0000",
                            **({"media_product_type": "REELS"} if self.product_type_field else {}),
                        },
                    ],
                    "paging": {"cursors": {"after": "abc"}},
                },
            )
        if path == f"{USER_ID}/stories":
            return _reply(200, {"data": [{"id": STORY_ID, "media_type": "IMAGE"}]})
        if path.endswith("/insights"):
            metric = query["metric"]
            if metric == "impressions":
                return _reply(400, {"error": {"code": 100, "message": "metric deprecated"}})
            if metric == "follows_and_unfollows":
                return _reply(200, {"data": []})
            if "metric_type" in query:
                return _reply(200, {"data": [{"name": metric, "total_value": {"value": 987654}}]})
            return _reply(
                200, {"data": [{"name": metric, "period": "lifetime", "values": [{"value": 4321}]}]}
            )
        return _reply(404, {"error": {"code": 803, "message": "unknown path"}})


def test_authorization_url_requests_read_only_scopes_and_pkce_only_on_request():
    query = parse_qs(urlsplit(tool.authorization_url(_config(), "state-1")).query)
    assert query["scope"] == ["instagram_business_basic,instagram_business_manage_insights"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == [REDIRECT]
    assert "code_challenge" not in query
    verifier, challenge = tool.pkce_pair()
    probed = parse_qs(urlsplit(tool.authorization_url(_config(), "s", challenge)).query)
    assert probed["code_challenge"] == [challenge] and probed["code_challenge_method"] == ["S256"]
    assert verifier != challenge


def test_redirect_parsing_strips_the_suffix_and_checks_state_and_origin():
    pasted = f"{REDIRECT}?code={CODE}&state=s1#_"
    assert tool.code_from_redirect(pasted, "s1", REDIRECT) == CODE
    for bad, state in (
        (f"{REDIRECT}?code={CODE}&state=other", "s1"),
        (f"https://evil.example/cb?code={CODE}&state=s1", "s1"),
        (f"{REDIRECT}?error=access_denied&error_reason=user_denied&state=s1", "s1"),
        (f"{REDIRECT}?state=s1", "s1"),
    ):
        with pytest.raises(tool.FeasibilityFailed):
            tool.code_from_redirect(bad, state, REDIRECT)


def test_app_configuration_is_required_and_bounded():
    good = {tool.APP_ID: "123", tool.APP_SECRET: "x", tool.REDIRECT: REDIRECT}
    assert tool.app_config(good).app_id == "123"
    assert APP_SECRET not in repr(tool.AppConfig("1", APP_SECRET, REDIRECT))
    for change in (
        {tool.APP_ID: "abc"},
        {tool.APP_SECRET: ""},
        {tool.REDIRECT: "http://example.com/cb"},
        {tool.REDIRECT: f"{REDIRECT}#x"},
    ):
        with pytest.raises(tool.FeasibilityFailed):
            tool.app_config(good | change)
    assert tool.app_config(good | {tool.REDIRECT: "http://localhost:8765/cb"})


def test_probe_records_availability_without_identifying_values():
    meta = FakeMeta()
    evidence = tool.probe_account(meta, LONG, NOW)
    text = json.dumps(evidence)
    for secret in (*SECRETS, "987654", "4321"):
        assert secret not in text
    assert evidence["account"] == {
        "account_type": "BUSINESS",
        "followers_bucket": "under_100",
        "media_count_type": "int",
    }
    assert evidence["account_insights"]["reach"] == {"outcome": "ok", "value_type": "int"}
    assert evidence["account_insights"]["follows_and_unfollows"] == {"outcome": "empty"}
    assert evidence["account_insights"]["impressions"]["outcome"] == "error"
    assert evidence["media"]["counts"] == {"IMAGE/FEED": 1, "VIDEO/REELS": 1}
    assert evidence["media"]["age_days_range"] == [10, 50]
    assert set(evidence["media_insights_by_type"]) == {"IMAGE/FEED", "VIDEO/REELS"}
    assert evidence["stories"] == {"outcome": "ok", "live_stories": 1}
    assert evidence["rate_limit"] == {
        "x-business-use-case-usage": {
            "<id-0>": [{"type": "instagram", "call_count": 7, "total_time": 3}]
        }
    }
    # Every Graph read carried the token only as the access_token parameter, never a write.
    assert {method for method, _, _ in meta.requests} == {"GET"}


def test_a_refused_product_type_field_is_recorded_and_the_read_continues():
    evidence = tool.probe_account(FakeMeta(product_type_field=False), LONG, NOW)
    field = evidence["media"]["media_product_type_field"]
    assert field["refused"]["code"] == 100 and "<n>" in field["refused"]["message"]
    assert evidence["media"]["counts"] == {"IMAGE/-": 1, "VIDEO/-": 1}
    assert USER_ID not in json.dumps(evidence)


def test_throttling_and_the_call_budget_stop_the_probe():
    throttled = tool.probe_account(FakeMeta(throttle=True), LONG, NOW)
    assert throttled["calls"] == 1 or throttled.get("stopped") == "no_user_id"
    limited = tool.probe_account(FakeMeta(), LONG, NOW, max_calls=5)
    assert limited["calls"] == 5
    assert "not_requested" in json.dumps(limited)


def test_exchange_keeps_only_the_shape_permissions_and_lifetime():
    token, record = tool.exchange_code(FakeMeta(), _config(), CODE, None)
    assert token == LONG
    assert record == {
        "code_exchange_status": 200,
        "code_exchange_shape": "data_array",
        "granted_permissions": [
            "instagram_business_basic",
            "instagram_business_manage_insights",
        ],
        "user_id_returned": True,
        "long_lived_status": 200,
        "token_type": "bearer",
        "expires_in": 5183944,
    }


def test_owner_commands_store_and_forget_the_token_without_printing(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(
        f"TRACKING_INSTAGRAM_APP_ID=1234567890\nTRACKING_INSTAGRAM_APP_SECRET={APP_SECRET}\n"
        f"TRACKING_INSTAGRAM_REDIRECT_URI={REDIRECT}\nOTHER=kept\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    monkeypatch.setattr(
        tool.getpass, "getpass", lambda prompt: f"{REDIRECT}?code={CODE}&state=fixed-24#_"
    )
    meta = FakeMeta()
    base = ["--env-file", str(env)]
    assert tool.main([*base, "authorize", "--no-browser"], transport=meta) == 0
    values = dotenv_values(env)
    assert values[tool.TOKEN] == LONG and values["OTHER"] == "kept"
    assert tool.main([*base, "refresh"], transport=meta) == 0
    assert dotenv_values(env)[tool.TOKEN] == RENEWED
    assert tool.main([*base, "check-access"], transport=meta) == 0
    output = capsys.readouterr()
    for secret in SECRETS:
        assert secret not in output.out and secret not in output.err
    files = sorted((tmp_path / "local-data" / "instagram-feasibility").glob("*.json"))
    assert {path.name.split("-")[0] for path in files} == {"authorize", "probe", "refresh", "check"}
    for path in files:
        content = path.read_text(encoding="utf-8")
        for secret in (*SECRETS, "987654", "4321"):
            assert secret not in content
    assert tool.main([*base, "forget"], transport=meta) == 0
    values = dotenv_values(env)
    assert tool.TOKEN not in values and tool.ISSUED not in values and values["OTHER"] == "kept"
    assert tool.main([*base, "probe"], transport=meta) == 1


def test_a_wrong_pkce_verifier_is_recorded_as_a_probe_result(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        f"TRACKING_INSTAGRAM_APP_ID=1234567890\nTRACKING_INSTAGRAM_APP_SECRET={APP_SECRET}\n"
        f"TRACKING_INSTAGRAM_REDIRECT_URI={REDIRECT}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tool.secrets, "token_urlsafe", lambda size=32: f"fixed-{size}")
    monkeypatch.setattr(
        tool.getpass, "getpass", lambda prompt: f"{REDIRECT}?code={CODE}&state=fixed-24"
    )

    def refusing(method, url, form):
        if method == "POST":
            assert form["code_verifier"]
            return _reply(400, {"error": {"code": 36008, "type": "OAuthException"}})
        raise AssertionError("no other request expected")

    argv = ["--env-file", str(env), "authorize", "--no-browser", "--pkce-wrong-verifier"]
    assert tool.main(argv, transport=refusing) == 0
    (record_path,) = (tmp_path / "local-data" / "instagram-feasibility").glob("authorize-*.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["pkce"] == "wrong_verifier"
    assert record["code_exchange_error"]["code"] == 36008
    assert tool.TOKEN not in dotenv_values(env)
