"""Authenticated tenancy, invitation, service credential, and trusted scope boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgencyInvitation,
    AgencyMembership,
    AuditEvent,
    ClientGrant,
    ClientWorkspace,
    InvitationClientGrant,
    MailOutbox,
    ServiceClientGrant,
    ServiceCredential,
    User,
)
from app.security import AuthError, digest, now_utc
from app.services.access import Principal, resolve_scope
from app.services.tenancy import AccessDenied, Role, tenancy_transaction

pytestmark = pytest.mark.integration


def invite(
    api, world, client=None, *, role="analyst", email="second_owner@example.test", clients=None
):
    manager = client or world.signed_in("owner_a")
    response = manager.post(
        f"/agencies/{world.a}/invitations",
        json={
            "email": email,
            "role": role,
            "clients": clients if clients is not None else [{"client_id": str(world.a1)}],
        },
    )
    return response


def invitation_token(api):
    return [t for _, subject, t in api.mail_tokens() if subject == "Agency invitation"][-1]


def issue_key(world, client=None, *, financial=False):
    manager = client or world.signed_in("admin")
    response = manager.post(
        f"/agencies/{world.a}/service-credentials",
        json={
            "name": "Synthetic reader",
            "clients": [
                {"client_id": str(world.a1), "can_view_financials": financial},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authenticated_http_scopes_and_live_membership_revocation(authenticated_world, api):
    w = authenticated_world
    viewer, owner = w.signed_in("viewer"), w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    assert viewer.get(base).status_code == 403
    assert [item["id"] for item in viewer.get(base + "/clients").json()] == [str(w.a1)]
    for path in [
        f"{base}/clients/{w.a2}",
        f"/agencies/{w.b}/clients/{w.b1}",
        base + "/members",
        base + "/audit",
    ]:
        assert viewer.get(path).status_code == 403
    assert viewer.post(base + "/clients", json={"name": "Denied"}).status_code == 403
    assert owner.patch(f"/agencies/{w.b}", json={"name": "Denied"}).status_code == 403
    assert (
        owner.patch(f"{base}/members/{w.owner_a}", json={"status": "disabled"}).status_code == 409
    )
    assert owner.patch(f"{base}/members/{w.viewer}", json={"status": "disabled"}).status_code == 200
    assert viewer.get(base + "/clients").status_code == 403
    # Identity remains valid; only the agency membership is revoked.
    assert viewer.get("/auth/me").status_code == 200


def test_invitation_acceptance_is_scoped_single_use_and_audited(authenticated_world, api):
    w = authenticated_world
    response = invite(api, w, clients=[{"client_id": str(w.a1), "can_view_financials": True}])
    assert response.status_code == 201
    assert "token" not in response.text
    token = invitation_token(api)
    recipient = w.signed_in("second_owner")
    accepted = recipient.post("/invitations/accept", json={"token": token})
    assert accepted.status_code == 200 and accepted.json()["role"] == "analyst"
    assert recipient.get(f"/agencies/{w.a}/clients/{w.a1}").status_code == 200
    assert recipient.get(f"/agencies/{w.a}/clients/{w.a2}").status_code == 403
    assert recipient.post("/invitations/accept", json={"token": token}).status_code == 400
    with Session(w.db.runtime) as session:
        resolve_scope(session, Principal("user", w.users.second_owner), w.a, w.a1, "finance:read")
        invitation = session.get(AgencyInvitation, UUID(response.json()["id"]))
        assert invitation.token_digest == digest(token) and invitation.status == "accepted"
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.resource_id == invitation.id))
        )
        assert {event.action for event in events} == {"invitation.created", "invitation.accepted"}
        assert (
            next(e for e in events if e.action == "invitation.accepted").actor_user_id
            == w.users.second_owner
        )


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_email",
        "expiry",
        "revoked",
        "disabled_inviter",
        "demoted_inviter",
        "archived_client",
        "unverified",
    ],
)
def test_invitation_acceptance_rechecks_live_state(authenticated_world, api, failure):
    w = authenticated_world
    admin = w.signed_in("admin")
    invitation = invite(api, w, admin)
    assert invitation.status_code == 201
    token = invitation_token(api)
    recipient = w.signed_in("outsider" if failure == "wrong_email" else "second_owner")
    with Session(w.db.migration) as session, session.begin():
        if failure == "expiry":
            session.execute(
                update(AgencyInvitation).values(expires_at=now_utc() - timedelta(seconds=1))
            )
        elif failure == "revoked":
            session.execute(update(AgencyInvitation).values(status="revoked"))
        elif failure == "disabled_inviter":
            session.execute(
                update(AgencyMembership)
                .where(AgencyMembership.id == w.admin)
                .values(status="disabled")
            )
        elif failure == "demoted_inviter":
            session.execute(
                update(AgencyMembership)
                .where(AgencyMembership.id == w.admin)
                .values(role="analyst")
            )
        elif failure == "archived_client":
            session.execute(
                update(ClientWorkspace).where(ClientWorkspace.id == w.a1).values(status="archived")
            )
        elif failure == "unverified":
            session.execute(
                update(User).where(User.id == w.users.second_owner).values(email_verified_at=None)
            )
    assert recipient.post("/invitations/accept", json={"token": token}).status_code in {
        400,
        401,
        403,
    }
    with Session(w.db.migration) as session:
        assert (
            session.scalar(
                select(AgencyMembership).where(
                    AgencyMembership.agency_id == w.a,
                    AgencyMembership.user_id == w.users.second_owner,
                )
            )
            is None
        )
        assert session.scalar(select(AgencyInvitation.status)) != "accepted"


def test_invitation_owner_rules_foreign_grants_and_revoke_endpoint(authenticated_world, api):
    w = authenticated_world
    admin, owner = w.signed_in("admin"), w.signed_in("owner_a")
    assert invite(api, w, admin, role="owner").status_code == 403
    assert invite(api, w, admin, clients=[{"client_id": str(w.b1)}]).status_code == 403
    assert invite(api, w, admin, clients=[{"client_id": str(w.a1)}] * 2).status_code == 422
    response = invite(api, w, owner, role="owner")
    assert response.status_code == 201
    path = f"/agencies/{w.a}/invitations/{response.json()['id']}"
    assert admin.delete(path).status_code == 403
    assert owner.delete(path).status_code == 204
    recipient = w.signed_in("second_owner")
    assert (
        recipient.post("/invitations/accept", json={"token": invitation_token(api)}).status_code
        == 400
    )


def test_invitation_does_not_promote_an_existing_membership(authenticated_world, api):
    w = authenticated_world
    assert invite(api, w, email="viewer@example.test").status_code == 409
    assert invite(api, w).status_code == 201
    token = invitation_token(api)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.add_member(w.a, w.users.second_owner, Role.CLIENT_VIEWER)
    recipient = w.signed_in("second_owner")
    assert recipient.post("/invitations/accept", json={"token": token}).status_code == 409
    with Session(w.db.migration) as session:
        assert (
            session.scalar(
                select(AgencyMembership.role).where(
                    AgencyMembership.agency_id == w.a,
                    AgencyMembership.user_id == w.users.second_owner,
                )
            )
            == "client_viewer"
        )


def test_concurrent_invitation_acceptance_creates_one_membership(authenticated_world, api):
    w = authenticated_world
    assert invite(api, w).status_code == 201
    token = invitation_token(api)
    clients = [w.signed_in("second_owner"), w.signed_in("second_owner")]
    barrier = Barrier(2)

    def accept(client):
        barrier.wait(timeout=10)
        return client.post("/invitations/accept", json={"token": token}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(accept, clients)) == [200, 400]
    with Session(w.db.migration) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgencyMembership)
                .where(
                    AgencyMembership.agency_id == w.a,
                    AgencyMembership.user_id == w.users.second_owner,
                )
            )
            == 1
        )


def test_service_key_read_scope_no_writes_no_cookie_ambiguity(authenticated_world, api):
    w = authenticated_world
    issued = issue_key(w)
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + issued["key"]
    base = f"/agencies/{w.a}"
    assert reader.get(f"{base}/clients/{w.a1}").status_code == 200
    assert [item["id"] for item in reader.get(base + "/clients").json()] == [str(w.a1)]
    for path in [
        f"{base}/clients/{w.a2}",
        f"/agencies/{w.b}/clients/{w.b1}",
        f"/agencies/{w.b}/clients",
    ]:
        assert reader.get(path).status_code == 403
    assert reader.get(base + "/members").status_code == 401
    assert reader.post(base + "/clients", json={"name": "Denied"}).status_code == 401
    manager = w.signed_in("admin")
    listing = manager.get(base + "/service-credentials")
    assert listing.status_code == 200 and issued["key"] not in listing.text
    assert "token_digest" not in listing.text
    assert manager.get(f"{base}/clients/{w.a1}", headers=reader.headers).status_code == 401
    with Session(w.db.migration) as session:
        assert session.scalar(select(ServiceCredential.token_digest)) == digest(issued["key"])
    assert (
        manager.delete(f"{base}/service-credentials/{issued['credential']['id']}").status_code
        == 204
    )
    assert reader.get(f"{base}/clients/{w.a1}").status_code == 401


@pytest.mark.parametrize(
    "failure",
    [
        "expiry",
        "revoked",
        "creator_disabled",
        "creator_demoted",
        "user_disabled",
        "client_archived",
    ],
)
def test_service_key_rechecks_liveness(authenticated_world, api, failure):
    w = authenticated_world
    issued = issue_key(w)
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + issued["key"]
    with Session(w.db.migration) as session, session.begin():
        if failure == "expiry":
            session.execute(
                update(ServiceCredential).values(expires_at=now_utc() - timedelta(seconds=1))
            )
        elif failure == "revoked":
            session.execute(update(ServiceCredential).values(status="revoked"))
        elif failure in {"creator_disabled", "creator_demoted"}:
            values = (
                {"status": "disabled"} if failure == "creator_disabled" else {"role": "analyst"}
            )
            session.execute(
                update(AgencyMembership).where(AgencyMembership.id == w.admin).values(**values)
            )
        elif failure == "user_disabled":
            session.execute(update(User).where(User.id == w.users.admin).values(status="disabled"))
        else:
            session.execute(
                update(ClientWorkspace).where(ClientWorkspace.id == w.a1).values(status="archived")
            )
    assert reader.get(f"/agencies/{w.a}/clients/{w.a1}").status_code == (
        403 if failure == "client_archived" else 401
    )


def test_service_key_finance_scope_and_cached_scope_reauthorization(authenticated_world, api):
    w = authenticated_world
    restricted = issue_key(w)
    financial = issue_key(w, financial=True)
    basic_id, finance_id = UUID(restricted["credential"]["id"]), UUID(financial["credential"]["id"])
    with Session(w.db.runtime) as session:
        principal = Principal("service", basic_id)
        scope = resolve_scope(session, principal, w.a, w.a1)
        with pytest.raises(AccessDenied):
            resolve_scope(session, principal, w.a, w.a1, "finance:read")
        full = resolve_scope(session, Principal("service", finance_id), w.a, w.a1, "finance:read")
        own = resolve_scope(session, Principal("user", w.users.owner_a), w.a, w.a1)
        other = resolve_scope(session, Principal("user", w.users.owner_a), w.a, w.a2)
        foreign = resolve_scope(session, Principal("user", w.users.owner_b), w.b, w.b1)
        assert len({item.cache_key("summary") for item in [scope, full, own, other, foreign]}) == 5
        with Session(w.db.migration) as admin, admin.begin():
            admin.execute(
                update(ServiceCredential)
                .where(ServiceCredential.id == basic_id)
                .values(status="revoked")
            )
        with pytest.raises(AuthError):
            resolve_scope(session, principal, w.a, w.a1)
    with Session(w.db.runtime) as session:
        viewer = Principal("user", w.users.viewer)
        resolve_scope(session, viewer, w.a, w.a1)
        with pytest.raises(AccessDenied):
            resolve_scope(session, viewer, w.a, w.a1, "finance:read")
        with Session(w.db.migration) as admin, admin.begin():
            admin.execute(delete(ClientGrant).where(ClientGrant.membership_id == w.viewer))
        with pytest.raises(AccessDenied):
            resolve_scope(session, viewer, w.a, w.a1)


@pytest.mark.parametrize("kind", ["invitation", "service"])
def test_database_rejects_cross_agency_auth_grants(authenticated_world, api, kind):
    w = authenticated_world
    if kind == "invitation":
        response = invite(api, w)
        entity = InvitationClientGrant(
            agency_id=w.a, invitation_id=UUID(response.json()["id"]), client_id=w.b1
        )
    else:
        issued = issue_key(w)
        entity = ServiceClientGrant(
            agency_id=w.a, credential_id=UUID(issued["credential"]["id"]), client_id=w.b1
        )
    with pytest.raises(IntegrityError), Session(w.db.runtime) as session, session.begin():
        session.add(entity)
        session.flush()


def test_invitation_and_outbox_are_atomic_with_audit(authenticated_world, api, monkeypatch):
    from app.services.access import AccessService

    w = authenticated_world

    def fail_audit(*args, **kwargs):
        raise ValueError("Synthetic audit failure")

    monkeypatch.setattr(AccessService, "_audit", fail_audit)
    assert invite(api, w).status_code == 422
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(AgencyInvitation)) == 0
        assert session.scalar(select(func.count()).select_from(MailOutbox)) == 0
