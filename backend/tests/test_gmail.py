"""Gmail send-only transport and owner authorization helper with controlled substitutes."""

import base64
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app import gmail_authorize
from app.services.gmail import SEND_SCOPE, GmailError, GmailSender

PAYLOAD = {"to": "recipient@example.test", "subject": "Verify your email", "body": "Code 012345"}


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class Opener:
    """Records requests and returns queued responses or raises queued errors."""

    def __init__(self, *outcomes):
        self.outcomes, self.requests = list(outcomes), []

    def __call__(self, request, timeout):
        assert timeout <= 15
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Response(outcome)


def http_error(status, reason=""):
    body = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return urllib.error.HTTPError("https://example.test", status, "error", {}, io.BytesIO(body))


@pytest.fixture
def gmail_settings(settings):
    return settings.model_copy(
        update={
            "mail_mode": "gmail",
            "gmail_client_id": "synthetic-sender.apps.googleusercontent.com",
            "gmail_client_secret": SecretStr("synthetic-sender-secret"),
            "gmail_refresh_token": SecretStr("synthetic-refresh-token"),
            "gmail_sender": "sender@example.test",
        }
    )


TOKEN = {"access_token": "synthetic-access", "expires_in": 3600, "scope": SEND_SCOPE}


def test_send_refreshes_once_and_submits_encoded_mime(gmail_settings):
    opener = Opener(TOKEN, {"id": "1"}, {"id": "2"})
    sender = GmailSender(gmail_settings, opener=opener)
    message_id = uuid4()
    sender.send(message_id, PAYLOAD)
    sender.send(uuid4(), PAYLOAD)
    token_request, send_request, _ = opener.requests
    assert token_request.full_url == "https://oauth2.googleapis.com/token"
    assert b"grant_type=refresh_token" in token_request.data
    assert send_request.full_url.endswith("/gmail/v1/users/me/messages/send")
    assert send_request.get_header("Authorization") == "Bearer synthetic-access"
    raw = json.loads(send_request.data)["raw"]
    mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    assert mime["From"] == "sender@example.test" and mime["To"] == PAYLOAD["to"]
    assert mime["Message-ID"] == f"<{message_id}@tracking.invalid>"
    assert mime.get_body().get_content().strip() == "Code 012345"


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (http_error(400, "invalid_grant"), "gmail_authorization_revoked"),
        (http_error(503), "gmail_temporary_failure"),
        (urllib.error.URLError("unreachable"), "gmail_temporary_failure"),
        ({"access_token": "a", "expires_in": 3600, "scope": "openid"}, "gmail_scope_missing"),
    ],
)
def test_refresh_failures_are_sanitized(gmail_settings, outcome, code):
    sender = GmailSender(gmail_settings, opener=Opener(outcome))
    with pytest.raises(GmailError) as error:
        sender.send(uuid4(), PAYLOAD)
    assert error.value.code == code
    assert "synthetic" not in str(error.value)


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (http_error(429), "gmail_rate_limited"),
        (http_error(403, "userRateLimitExceeded"), "gmail_rate_limited"),
        (http_error(403, "forbidden"), "gmail_access_denied"),
        (http_error(400, "invalidArgument"), "gmail_message_rejected"),
        (http_error(500), "gmail_temporary_failure"),
        (TimeoutError(), "gmail_temporary_failure"),
        (http_error(401), "gmail_authorization_failed"),
    ],
)
def test_send_failures_are_sanitized(gmail_settings, outcome, code):
    opener = Opener(TOKEN, outcome, TOKEN, {"id": "3"})
    sender = GmailSender(gmail_settings, opener=opener)
    with pytest.raises(GmailError) as error:
        sender.send(uuid4(), PAYLOAD)
    assert error.value.code == code
    sender.send(uuid4(), PAYLOAD)
    refreshed = sum(r.full_url.endswith("/token") for r in opener.requests)
    assert refreshed == (2 if code == "gmail_authorization_failed" else 1)


def test_helper_requires_a_separate_desktop_client(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "TRACKING_GOOGLE_CLIENT_ID=same.apps.googleusercontent.com\n"
        "TRACKING_GMAIL_CLIENT_ID=same.apps.googleusercontent.com\n"
        "TRACKING_GMAIL_CLIENT_SECRET=synthetic\n",
        encoding="utf-8",
    )
    with pytest.raises(gmail_authorize.AuthorizationFailed):
        gmail_authorize.sender_client(env, None)
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "w", "client_secret": "s"}}))
    with pytest.raises(gmail_authorize.AuthorizationFailed):
        gmail_authorize.sender_client(env, web)
    desktop = tmp_path / "desktop.json"
    desktop.write_text(json.dumps({"installed": {"client_id": "d", "client_secret": "s"}}))
    assert gmail_authorize.sender_client(env, desktop) == ("d", "s")


def test_helper_requests_only_the_send_scope_with_pkce():
    url = gmail_authorize.authorization_url("d", "http://127.0.0.1:5000/", "state", "v" * 64)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["scope"] == [SEND_SCOPE] and query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"] and query["state"] == ["state"]


def test_helper_accepts_only_the_matching_state(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    for state, expected in (("expected", "code-1"), ("forged", None)):
        server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/?code=code-1&state={state}"
        thread = threading.Thread(target=lambda u=url: urllib.request.urlopen(u, timeout=5).read())
        thread.start()
        try:
            if expected is None:
                with pytest.raises(gmail_authorize.AuthorizationFailed):
                    gmail_authorize.wait_for_code(server, "expected")
            else:
                assert gmail_authorize.wait_for_code(server, "expected") == expected
        finally:
            thread.join(5)
            server.server_close()


def test_helper_requires_exactly_the_send_scope_and_stores_privately(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TRACKING_GMAIL_REFRESH_TOKEN=\n", encoding="utf-8")
    broad = {"refresh_token": "r", "scope": SEND_SCOPE + " https://mail.google.com/"}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response(broad))
    with pytest.raises(gmail_authorize.AuthorizationFailed):
        gmail_authorize.exchange("d", "s", "code", "verifier", "http://127.0.0.1:1/")
    exact = {"refresh_token": "synthetic-refresh", "scope": SEND_SCOPE}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response(exact))
    token = gmail_authorize.exchange("d", "s", "code", "verifier", "http://127.0.0.1:1/")
    gmail_authorize.store(env, {"TRACKING_GMAIL_REFRESH_TOKEN": token})
    assert "TRACKING_GMAIL_REFRESH_TOKEN='synthetic-refresh'" in env.read_text(encoding="utf-8")
