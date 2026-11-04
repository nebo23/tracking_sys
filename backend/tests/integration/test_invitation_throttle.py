"""Persistent throttling of invitation acceptance (review amendment T-02)."""

import secrets

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import AgencyMembership, AuditEvent, AuthRateLimit
from app.security import keyed_digest, now_utc

pytestmark = pytest.mark.integration


def signed_in_with(api, settings, name):
    client = api.new_client(settings)
    api.login(client, f"{name}@example.test")
    return client


def issue_invitation(world, api):
    manager = world.signed_in("owner_a")
    response = manager.post(
        f"/agencies/{world.a}/invitations",
        json={
            "email": "second_owner@example.test",
            "role": "analyst",
            "clients": [{"client_id": str(world.a1)}],
        },
    )
    assert response.status_code == 201, response.text
    return [t for _, subject, t in api.mail_tokens() if subject == "Agency invitation"][-1]


def counter(world, settings, scope, subject):
    with Session(world.db.migration) as session:
        return session.scalar(
            select(AuthRateLimit.attempts).where(
                AuthRateLimit.bucket_key == keyed_digest(settings, "rate:" + scope, subject)
            )
        )


def membership_count(world):
    with Session(world.db.migration) as session:
        return session.scalar(
            select(func.count())
            .select_from(AgencyMembership)
            .where(
                AgencyMembership.agency_id == world.a,
                AgencyMembership.user_id == world.users.second_owner,
            )
        )


def accepted_audits(world):
    with Session(world.db.migration) as session:
        return session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.agency_id == world.a, AuditEvent.action == "invitation.accepted")
        )


def test_invitation_acceptance_is_throttled_per_user_and_persists_after_rollback(
    authenticated_world, api
):
    w = authenticated_world
    token = issue_invitation(w, api)
    settings = api.config.model_copy(update={"invitation_attempts_per_minute": 3})
    invitee = signed_in_with(api, settings, "second_owner")
    other = signed_in_with(api, settings, "outsider")

    # Invalid tokens roll back the business transaction but remain counted.
    for _ in range(2):
        response = invitee.post("/invitations/accept", json={"token": secrets.token_urlsafe(32)})
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_or_expired_token"}
    assert counter(w, settings, "invitation-accept", str(w.users.second_owner)) == 2
    assert membership_count(w) == 0

    # The third attempt is still below the limit and succeeds; a replay is then rejected.
    assert invitee.post("/invitations/accept", json={"token": token}).status_code == 200
    replay = invitee.post("/invitations/accept", json={"token": token})
    assert replay.status_code == 429
    assert replay.json() == {"error": "rate_limited"}
    assert 1 <= int(replay.headers["Retry-After"]) <= 61
    assert membership_count(w) == 1 and accepted_audits(w) == 1

    # Another authenticated subject keeps an independent budget.
    response = other.post("/invitations/accept", json={"token": secrets.token_urlsafe(32)})
    assert response.status_code == 400

    # After the window expires, the subject may try again; the replay is still invalid.
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            update(AuthRateLimit)
            .where(
                AuthRateLimit.bucket_key
                == keyed_digest(settings, "rate:invitation-accept", str(w.users.second_owner))
            )
            .values(expires_at=now_utc())
        )
    replay = invitee.post("/invitations/accept", json={"token": token})
    assert replay.status_code == 400
    assert counter(w, settings, "invitation-accept", str(w.users.second_owner)) == 1
    assert membership_count(w) == 1 and accepted_audits(w) == 1


def test_throttled_valid_invitation_has_no_side_effects(authenticated_world, api):
    w = authenticated_world
    token = issue_invitation(w, api)
    settings = api.config.model_copy(update={"invitation_attempts_per_minute": 1})
    invitee = signed_in_with(api, settings, "second_owner")
    assert (
        invitee.post("/invitations/accept", json={"token": secrets.token_urlsafe(32)}).status_code
        == 400
    )
    denied = invitee.post("/invitations/accept", json={"token": token})
    assert denied.status_code == 429 and "Retry-After" in denied.headers
    assert membership_count(w) == 0 and accepted_audits(w) == 0


def test_invitation_peer_limit_precedes_authentication(authenticated_world, api):
    w = authenticated_world
    settings = api.config.model_copy(update={"auth_requests_per_minute": 1})
    anonymous = api.new_client(settings)
    body = {"token": secrets.token_urlsafe(32)}
    assert anonymous.post("/invitations/accept", json=body).status_code == 401
    limited = anonymous.post("/invitations/accept", json=body)
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert counter(w, settings, "invitation-ip", "testclient") == 2
