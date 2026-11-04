"""Google sign-in and linking against a controlled provider substitute (D-022).

The substitute signs ID tokens with a locally generated RSA key and checks PKCE; automated
tests never contact Google.
"""

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import ExternalIdentity, PasswordCredential, SecurityEvent, User
from app.services.google import GoogleProviderError

pytestmark = pytest.mark.integration
CLIENT_ID = "synthetic-sign-in.apps.googleusercontent.com"
COMPLETE = "http://localhost:8000/docs"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeGoogle:
    """Implements configuration/exchange/signing_key like GoogleOIDC, without network access."""

    def __init__(self):
        self.pending: dict[str, tuple[str, dict, object]] = {}

    def configuration(self):
        return {
            "authorization_endpoint": "https://accounts.google.test/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.google.test/token",
            "jwks_uri": "https://www.google.test/oauth2/v3/certs",
            "issuer": "https://accounts.google.com",
        }

    def expect(self, code, challenge, claims, key=SIGNING_KEY):
        self.pending[code] = (challenge, claims, key)

    def exchange(self, code, verifier):
        if code not in self.pending:
            raise GoogleProviderError("google_sign_in_failed")
        challenge, claims, key = self.pending.pop(code)
        computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        if computed.rstrip(b"=").decode() != challenge:
            raise GoogleProviderError("google_sign_in_failed")
        return {"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})}

    def signing_key(self, id_token):
        return SIGNING_KEY.public_key()


@pytest.fixture
def google(api):
    settings = api.config.model_copy(
        update={
            "google_sign_in_enabled": True,
            "google_client_id": CLIENT_ID,
            "google_client_secret": SecretStr("synthetic-client-secret"),
            "google_complete_url": COMPLETE,
        }
    )
    fake = FakeGoogle()

    def browser():
        client = api.new_client(settings)
        client.app.state.google = fake
        return client

    return browser, fake


def claims(params, **changes):
    now = int(time.time())
    base = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "synthetic-google-subject-1",
        "email": "new.person@gmail.com",
        "email_verified": True,
        "name": "New Person",
        "iat": now,
        "exp": now + 300,
        "nonce": params["nonce"][0],
    }
    return {key: value for key, value in (base | changes).items() if value is not None}


def start(client):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    return response, parse_qs(urlsplit(response.headers["location"]).query)


def finish(client, fake, params, code="code-1", key=SIGNING_KEY, **changes):
    fake.expect(code, params["code_challenge"][0], claims(params, **changes), key)
    response = client.get(
        "/auth/google/callback",
        params={"code": code, "state": params["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response, parse_qs(urlsplit(response.headers["location"]).query)


def count(db, model, *where):
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def test_google_routes_are_hidden_when_disabled(api):
    assert api.client.get("/auth/google/start", follow_redirects=False).status_code == 404
    assert api.client.get("/auth/google/callback", follow_redirects=False).status_code == 404


def test_google_sign_up_session_and_repeat_login(api, db, google):
    browser, fake = google
    client = browser()
    started, params = start(client)
    assert started.headers["location"].startswith("https://accounts.google.test/")
    assert params["scope"] == ["openid email profile"]
    assert params["code_challenge_method"] == ["S256"] and "access_type" not in params
    assert params["client_id"] == [CLIENT_ID]
    binding = started.headers["set-cookie"]
    assert "tracking_oauth=" in binding and "HttpOnly" in binding and "Path=/auth/google" in binding
    response, result = finish(client, fake, params)
    assert response.headers["location"].startswith(COMPLETE + "?")
    assert result == {"result": ["signed_in"]}
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email_normalized"] == "new.person@gmail.com"
    with Session(db.migration) as session:
        user = session.scalar(select(User).where(User.email_normalized == "new.person@gmail.com"))
        assert user.email_verified_at is not None and user.display_name == "New Person"
        assert session.get(PasswordCredential, user.id) is None
    assert client.get("/agencies").json() == []
    # Session parity: mutations still require Origin and the session-bound CSRF token.
    assert client.post("/agencies", json={"name": "Synthetic Agency"}).status_code == 403
    client.headers["X-CSRF-Token"] = me.json()["csrf_token"]
    assert client.post("/agencies", json={"name": "Synthetic Agency"}).status_code == 201
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401
    # A second sign-in maps the same subject to the same user.
    again = browser()
    _, params = start(again)
    _, result = finish(again, fake, params, code="code-2", email="changed@gmail.com")
    assert result == {"result": ["signed_in"]}
    assert again.get("/auth/me").json()["user"]["id"] == str(user.id)
    assert count(db, User) == 1 and count(db, ExternalIdentity) == 1
    assert count(db, SecurityEvent, SecurityEvent.action == "google_registered") == 1
    assert count(db, SecurityEvent, SecurityEvent.action == "google_login_succeeded") == 1


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"aud": "another.apps.googleusercontent.com"}, "google_sign_in_failed"),
        ({"iss": "https://accounts.example.test"}, "google_sign_in_failed"),
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, "google_sign_in_failed"),
        ({"nonce": "not-the-transaction-nonce"}, "google_sign_in_failed"),
        ({"key": OTHER_KEY}, "google_sign_in_failed"),
        ({"email_verified": False}, "google_email_not_verified"),
        ({"email": "person@example.test"}, "google_email_not_verified"),
        ({"sub": None}, "google_sign_in_failed"),
    ],
)
def test_google_rejects_invalid_identity_tokens(api, db, google, changes, expected):
    browser, fake = google
    client = browser()
    _, params = start(client)
    key = changes.pop("key", SIGNING_KEY)
    response, result = finish(client, fake, params, key=key, **changes)
    assert result == {"error": [expected]}
    assert all("tracking_session=" not in item for item in response.headers.get_list("set-cookie"))
    assert client.get("/auth/me").status_code == 401
    assert count(db, User) == 0 and count(db, ExternalIdentity) == 0


def test_hosted_domain_claim_allows_workspace_sign_up(api, db, google):
    browser, fake = google
    client = browser()
    _, params = start(client)
    _, result = finish(
        client, fake, params, email="person@workspace.example.test", hd="workspace.example.test"
    )
    assert result == {"result": ["signed_in"]}
    assert count(db, User, User.email_normalized == "person@workspace.example.test") == 1


def test_google_state_is_single_use_and_bound_to_the_browser(api, db, google):
    browser, fake = google
    client = browser()
    _, params = start(client)
    _, first = finish(client, fake, params)
    assert first == {"result": ["signed_in"]}
    _, replay = finish(client, fake, params, code="code-replay")
    assert replay == {"error": ["google_sign_in_failed"]}
    other = browser()
    _, params = start(client)
    _, foreign = finish(other, fake, params, code="code-foreign")
    assert foreign == {"error": ["google_sign_in_failed"]}
    cancelled = client.get(
        "/auth/google/callback",
        params={"error": "access_denied", "state": params["state"][0]},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(cancelled.headers["location"]).query) == {
        "error": ["google_sign_in_cancelled"]
    }
    assert count(db, User) == 1


def test_existing_email_requires_explicit_link_then_signs_in(api, db, google):
    browser, fake = google
    email = "linked.person@gmail.com"
    body = {"email": email, "display_name": "Linked Person", "password": api.password}
    assert api.client.post("/auth/register", json=body).status_code == 202
    code = [v for _, s, v in api.mail_tokens() if s == "Verify your email"][-1]
    verify = {"email": email, "code": code}
    assert api.client.post("/auth/verify-email-code", json=verify).status_code == 204
    client = browser()
    _, params = start(client)
    _, result = finish(client, fake, params, email=email, sub="subject-linked")
    assert result == {"error": ["google_link_required"]}
    assert count(db, ExternalIdentity) == 0
    # Link from an authenticated session (Origin and CSRF required by BrowserDep).
    api.login(client, email)
    assert client.post("/auth/google/link", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    linked = client.post("/auth/google/link")
    assert linked.status_code == 200
    params = parse_qs(urlsplit(linked.json()["authorization_url"]).query)
    _, result = finish(client, fake, params, code="code-link", email=email, sub="subject-linked")
    assert result == {"result": ["linked"]}
    assert count(db, SecurityEvent, SecurityEvent.action == "google_identity_linked") == 1
    fresh = browser()
    _, params = start(fresh)
    _, result = finish(fresh, fake, params, code="code-after", email=email, sub="subject-linked")
    assert result == {"result": ["signed_in"]}
    assert fresh.get("/auth/me").json()["user"]["email_normalized"] == email


def test_linked_subject_cannot_move_and_disabled_users_are_denied(api, db, google):
    browser, fake = google
    first = browser()
    _, params = start(first)
    _, result = finish(first, fake, params, sub="subject-owned")
    assert result == {"result": ["signed_in"]}
    email = "second.person@gmail.com"
    body = {"email": email, "display_name": "Second Person", "password": api.password}
    assert api.client.post("/auth/register", json=body).status_code == 202
    code = [v for _, s, v in api.mail_tokens() if s == "Verify your email"][-1]
    verify = {"email": email, "code": code}
    assert api.client.post("/auth/verify-email-code", json=verify).status_code == 204
    second = browser()
    api.login(second, email)
    params = parse_qs(urlsplit(second.post("/auth/google/link").json()["authorization_url"]).query)
    _, result = finish(second, fake, params, code="code-steal", sub="subject-owned")
    assert result == {"error": ["google_identity_in_use"]}
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(User)
            .where(User.email_normalized == "new.person@gmail.com")
            .values(status="disabled")
        )
    again = browser()
    _, params = start(again)
    _, result = finish(again, fake, params, code="code-disabled", sub="subject-owned")
    assert result == {"error": ["google_sign_in_failed"]}
    assert again.get("/auth/me").status_code == 401
