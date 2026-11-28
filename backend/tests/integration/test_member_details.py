"""Member details and archived clients for the agency's managers (018-B plan, B1 and B2; D-101)."""

from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import User

pytestmark = pytest.mark.integration


def members_of(client, agency) -> dict[str, dict]:
    response = client.get(f"/agencies/{agency}/members")
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


def client_ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


def test_managers_see_each_member_by_name_with_their_client_grants(authenticated_world):
    w = authenticated_world
    for manager in ("owner_a", "admin"):
        members = members_of(w.signed_in(manager), w.a)
        assert set(members) == {str(w.owner_a), str(w.admin), str(w.analyst), str(w.viewer)}
        analyst = members[str(w.analyst)]
        assert analyst["user_id"] == str(w.users.analyst)
        assert (analyst["display_name"], analyst["email_normalized"]) == (
            "analyst",
            "analyst@example.test",
        )
        assert (analyst["role"], analyst["status"], analyst["account"]) == (
            "analyst",
            "active",
            "active",
        )
        assert analyst["clients"] == [
            {"client_id": str(w.a1), "can_view_financials": False, "can_view_identities": False}
        ]
        assert analyst["joined_at"]
        assert members[str(w.owner_a)]["role"] == "owner"
        assert members[str(w.owner_a)]["clients"] == []
        assert members[str(w.viewer)]["role"] == "client_viewer"


def test_a_grant_change_shows_in_the_list_of_members(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    grant = f"/agencies/{w.a}/members/{w.analyst}/clients/{w.a2}"
    assert owner.put(grant, json={"can_view_financials": True}).status_code == 204
    analyst = members_of(owner, w.a)[str(w.analyst)]
    assert analyst["clients"] == sorted(
        [
            {"client_id": str(w.a1), "can_view_financials": False, "can_view_identities": False},
            {"client_id": str(w.a2), "can_view_financials": True, "can_view_identities": False},
        ],
        key=lambda item: item["client_id"],
    )
    assert owner.delete(grant).status_code == 204
    analyst = members_of(owner, w.a)[str(w.analyst)]
    assert [item["client_id"] for item in analyst["clients"]] == [str(w.a1)]


def test_member_details_are_refused_outside_the_managers_of_the_agency(authenticated_world):
    w = authenticated_world
    for name in ("analyst", "viewer", "outsider", "owner_b"):
        response = w.signed_in(name).get(f"/agencies/{w.a}/members")
        assert (response.status_code, response.json()) == (403, {"error": "access_denied"}), name


def test_member_details_stay_within_their_agency(authenticated_world):
    w = authenticated_world
    # The analyst of agency A is an Admin of agency B: they list B's members, never A's grants.
    members = members_of(w.signed_in("analyst"), w.b)
    assert {item["agency_id"] for item in members.values()} == {str(w.b)}
    grants = {grant["client_id"] for item in members.values() for grant in item["clients"]}
    assert grants == {str(w.b2)}
    assert str(w.analyst) not in members


def test_a_closed_account_is_never_named(api, authenticated_world):
    w = authenticated_world
    viewer = w.signed_in("viewer")
    assert viewer.post("/auth/close-account", json={"password": api.password}).status_code == 204
    member = members_of(w.signed_in("owner_a"), w.a)[str(w.viewer)]
    assert (member["display_name"], member["email_normalized"]) == (None, None)
    assert (member["account"], member["status"]) == ("closed", "disabled")
    assert "closed-" not in str(member) and "Closed account" not in str(member)


def test_an_account_disabled_by_an_administrator_keeps_its_name(authenticated_world):
    w = authenticated_world
    with Session(w.db.migration) as session, session.begin():
        session.execute(update(User).where(User.id == w.users.viewer).values(status="disabled"))
    member = members_of(w.signed_in("owner_a"), w.a)[str(w.viewer)]
    assert (member["display_name"], member["account"]) == ("viewer", "disabled")


def test_the_list_of_members_is_paged(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    first = owner.get(f"/agencies/{w.a}/members?limit=3")
    rest = owner.get(f"/agencies/{w.a}/members?limit=3&offset=3")
    assert (first.status_code, rest.status_code) == (200, 200)
    ids = [item["id"] for item in first.json() + rest.json()]
    assert len(first.json()) == 3 and len(ids) == len(set(ids)) == 4
    assert ids == sorted(ids, key=UUID)


def test_archived_clients_are_listed_for_managers_on_request(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    clients = f"/agencies/{w.a}/clients"
    assert owner.patch(f"{clients}/{w.a2}", json={"status": "archived"}).status_code == 200

    assert client_ids(owner.get(clients)) == [str(w.a1)]
    assert client_ids(owner.get(clients + "?status=active")) == [str(w.a1)]
    for manager in (owner, w.signed_in("admin")):
        archived = manager.get(clients + "?status=archived")
        assert client_ids(archived) == [str(w.a2)]
        assert archived.json()[0]["status"] == "archived"

    # Restoring brings the client back to the active list.
    assert owner.patch(f"{clients}/{w.a2}", json={"status": "active"}).status_code == 200
    assert client_ids(owner.get(clients + "?status=archived")) == []
    assert set(client_ids(owner.get(clients))) == {str(w.a1), str(w.a2)}


def test_archived_clients_are_refused_to_everyone_else(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    archived = owner.patch(f"/agencies/{w.a}/clients/{w.a1}", json={"status": "archived"})
    assert archived.status_code == 200
    for name in ("analyst", "viewer", "outsider", "owner_b"):
        response = w.signed_in(name).get(f"/agencies/{w.a}/clients?status=archived")
        assert (response.status_code, response.json()) == (403, {"error": "access_denied"}), name
    # Another agency's archived clients are not listed through this agency, nor the other way.
    assert owner.get(f"/agencies/{w.b}/clients?status=archived").status_code == 403
    assert client_ids(w.signed_in("owner_b").get(f"/agencies/{w.b}/clients?status=archived")) == []

    # A service key reads its granted active clients only, never the archived list.
    issued = w.signed_in("admin").post(
        f"/agencies/{w.a}/service-credentials",
        json={"name": "Synthetic reader", "clients": [{"client_id": str(w.a2)}]},
    )
    assert issued.status_code == 201, issued.text
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + issued.json()["key"]
    assert client_ids(reader.get(f"/agencies/{w.a}/clients")) == [str(w.a2)]
    refused = reader.get(f"/agencies/{w.a}/clients?status=archived")
    assert (refused.status_code, refused.json()) == (403, {"error": "access_denied"})


def test_an_unknown_client_status_is_refused(authenticated_world):
    w = authenticated_world
    for status in ("deleted", "ARCHIVED", ""):
        response = w.signed_in("owner_a").get(f"/agencies/{w.a}/clients?status={status}")
        assert (response.status_code, response.json()) == (422, {"error": "validation_failed"})
