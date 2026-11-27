"""Record of agreement to the terms and the Retry-After header (017-A, D-092 D10 and D11).

Cases SV15-SV17 of the entry review's verification matrix, against the controlled Google
provider substitute of test_google.py (no live Google call) and synthetic accounts only. The
fixture import deliberately exposes that substitute to pytest.
"""

# ruff: noqa: F811

from urllib.parse import parse_qs, urlsplit

import pytest
from auth_support import AGREEMENTS
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_google import COMPLETE, finish, google  # noqa: F401

from app.models import OAuthTransaction, SecurityEvent, User, UserAgreement

pytestmark = pytest.mark.integration
EMAIL = "agreeing.person@example.test"
CURRENT = {"terms": "draft-1", "privacy": "draft-1", "published": False}
REQUIRED = {"error": "agreement_required", "agreements": CURRENT}


def _rows(db, *where) -> list[tuple[str, str, str]]:
    with Session(db.migration) as session:
        return sorted(
            (row.document, row.version, row.channel)
            for row in session.scalars(select(UserAgreement).where(*where))
        )


def _count(db, model, *where) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def _register(client, agreements=None, email=EMAIL, password="Synthetic password for tests 123!"):
    body = {"email": email, "display_name": "Agreeing Person", "password": password}
    if agreements is not None:
        body["agreements"] = agreements
    return client.post("/auth/register", json=body)


def _verified(api, email=EMAIL):
    assert _register(api.client, AGREEMENTS, email, api.password).status_code == 202
    code = [v for _, s, v in api.mail_tokens() if s == "Verify your email"][-1]
    verify = {"email": email, "code": code}
    assert api.client.post("/auth/verify-email-code", json=verify).status_code == 204


def _login(client, password, agreements, email=EMAIL):
    body = {"email": email, "password": password}
    if agreements is not None:
        body["agreements"] = agreements
    return client.post("/auth/login", json=body)


def test_sv15_registration_requires_and_records_the_current_versions(api, db):
    assert api.client.get("/auth/agreements").json() == CURRENT
    # Each refusal uses its own address: refused attempts still count for the registration
    # throttle, which runs first.
    refusals = (None, {"terms": "draft-0", "privacy": "draft-1"}, {"terms": "draft-1"})
    for index, agreements in enumerate(refusals):
        response = _register(api.client, agreements, f"refused.{index}@example.test")
        if agreements is not None and "privacy" not in agreements:
            # An incomplete object is malformed input, refused like any other.
            assert response.json() == {"error": "validation_failed"}
            continue
        assert (response.status_code, response.json()) == (422, REQUIRED)
    assert _count(db, User) == 0 and api.mail_tokens() == []
    assert _register(api.client, AGREEMENTS).status_code == 202
    with Session(db.migration) as session:
        user = session.scalar(select(User.id).where(User.email_normalized == EMAIL))
    assert _rows(db, UserAgreement.user_id == user) == [
        ("privacy", "draft-1", "registration"),
        ("terms", "draft-1", "registration"),
    ]
    # A registration of an existing email records nothing and answers the same.
    again = _register(api.client, AGREEMENTS)
    assert again.status_code == 202
    assert _count(db, UserAgreement) == 2
    published = api.config.model_copy(update={"agreement_texts_published": True})
    assert api.new_client(published).get("/auth/agreements").json() == {
        **CURRENT,
        "published": True,
    }


def test_sv16_password_sign_in_records_a_new_version_once(api, db):
    _verified(api)
    assert _login(api.client, api.password, AGREEMENTS).status_code == 200
    assert _count(db, UserAgreement) == 2  # the registration rows already cover draft-1
    changed = api.config.model_copy(update={"terms_version": "2027-01"})
    client = api.new_client(changed)
    stale = _login(client, api.password, AGREEMENTS)
    assert stale.status_code == 422
    assert stale.json() == {
        "error": "agreement_required",
        "agreements": {"terms": "2027-01", "privacy": "draft-1", "published": False},
    }
    assert "set-cookie" not in stale.headers
    for _ in range(2):
        signed_in = _login(client, api.password, {"terms": "2027-01", "privacy": "draft-1"})
        assert signed_in.status_code == 200
    with Session(db.migration) as session:
        user = session.scalar(select(User.id).where(User.email_normalized == EMAIL))
    assert _rows(db, UserAgreement.user_id == user) == [
        ("privacy", "draft-1", "registration"),
        ("terms", "2027-01", "password_sign_in"),
        ("terms", "draft-1", "registration"),
    ]


def test_sv16_outdated_versions_are_refused_before_the_credential_check(api, db):
    _verified(api)
    failures = _count(db, SecurityEvent, SecurityEvent.action == "login_failed")
    answers = [
        _login(api.client, api.password, None),
        _login(api.client, "Wrong password for tests 1", {"terms": "old", "privacy": "draft-1"}),
        _login(api.client, api.password, None, email="nobody.here@example.test"),
    ]
    assert [(item.status_code, item.json()) for item in answers] == [(422, REQUIRED)] * 3
    # Nothing about the account was checked or recorded.
    assert _count(db, SecurityEvent, SecurityEvent.action == "login_failed") == failures
    assert _count(db, SecurityEvent, SecurityEvent.action == "login_succeeded") == 0
    wrong = _login(api.client, "Wrong password for tests 1", AGREEMENTS)
    assert (wrong.status_code, wrong.json()) == (401, {"error": "invalid_credentials"})


def _start(client, **params):
    response = client.get("/auth/google/start", params=params, follow_redirects=False)
    assert response.status_code == 303
    return response, parse_qs(urlsplit(response.headers["location"]).query)


def test_sv16_google_sign_in_carries_the_versions_in_its_transaction(api, db, google):
    browser, fake = google
    client = browser()
    for params in ({}, {"terms": "draft-1"}, {"terms": "draft-0", "privacy": "draft-1"}):
        response, query = _start(client, **params)
        assert response.headers["location"].startswith(COMPLETE)
        assert query == {"error": ["agreement_required"]}
    assert _count(db, OAuthTransaction) == 0
    _, params = _start(client, **AGREEMENTS)
    with Session(db.migration) as session:
        stored = session.scalar(select(OAuthTransaction))
        assert (stored.terms_version, stored.privacy_version) == ("draft-1", "draft-1")
    _, result = finish(client, fake, params)
    assert result == {"result": ["signed_in"]}
    assert _rows(db) == [
        ("privacy", "draft-1", "google_sign_in"),
        ("terms", "draft-1", "google_sign_in"),
    ]
    # A second sign-in with the same versions records nothing new.
    again = browser()
    _, params = _start(again, **AGREEMENTS)
    _, result = finish(again, fake, params, code="code-2")
    assert result == {"result": ["signed_in"]} and _count(db, UserAgreement) == 2
    # Versions that change between the start and the callback are refused before the code
    # exchange; the transaction is consumed and no session is issued.
    late = browser()
    _, params = _start(late, **AGREEMENTS)
    late.app.state.settings = late.app.state.settings.model_copy(
        update={"privacy_version": "2027-01"}
    )
    fake.expect("code-3", params["code_challenge"][0], {})
    response = late.get(
        "/auth/google/callback",
        params={"code": "code-3", "state": params["state"][0]},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "error": ["agreement_required"]
    }
    assert "code-3" in fake.pending  # never exchanged
    assert "tracking_session" not in response.headers.get("set-cookie", "")
    with Session(db.migration) as session:
        open_transactions = session.scalar(
            select(func.count())
            .select_from(OAuthTransaction)
            .where(OAuthTransaction.consumed_at.is_(None))
        )
    assert open_transactions == 0 and _count(db, UserAgreement) == 2


def test_sv17_retry_after_is_readable_from_the_application_origin(api):
    limited = api.config.model_copy(update={"login_attempts_per_minute": 1})
    client = api.new_client(limited)
    body = {"email": EMAIL, "password": "Synthetic wrong password 1", "agreements": AGREEMENTS}
    assert client.post("/auth/login", json=body).status_code == 401
    throttled = client.post("/auth/login", json=body)
    assert throttled.status_code == 429 and int(throttled.headers["retry-after"]) > 0
    assert throttled.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert throttled.headers["access-control-allow-credentials"] == "true"
    assert throttled.headers["access-control-expose-headers"] == "Retry-After"
    # Ordinary platform responses expose the same single header and nothing else.
    ordinary = client.get("/auth/agreements")
    assert ordinary.headers["access-control-expose-headers"] == "Retry-After"
    # Another origin receives no CORS grant (no Access-Control-Allow-Origin), so its browser can
    # read neither the body nor any header; Starlette's static exposure list is inert there.
    foreign = api.new_client(limited)
    foreign.headers["Origin"] = "https://foreign.example.test"
    answer = foreign.get("/auth/agreements")
    assert "access-control-allow-origin" not in answer.headers
