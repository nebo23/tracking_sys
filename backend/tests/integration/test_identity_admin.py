"""Specification 006 reads, permissions, merges, erasure and holds on disposable PostgreSQL.

Covers P2 of the joint verification matrix (D-075): identity read permissions (JV03), the
profile, timeline and lead inbox, the worked merge and reversal of design section 10.2, person
erasure with exact held sets and their resolution (design section 7.2), the exclusion marker
after settled holds (R006-24, JV07), merge-participant loss (R006-25, JV08) and suppression by
identity tombstones with a neutral boundary. Synthetic values only.
"""

from uuid import UUID, uuid4

import pytest
from identity_support import ALL, ATTRIBUTION, IDENTITY, count, make_identity_world, rows
from sqlalchemy import select

from app.models import (
    ClientGrant,
    CollectedEvent,
    CollectionSubject,
    IdentityAssertion,
    IdentityErasureHold,
    IdentityKey,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
    StoredTombstone,
    SubjectDeletionRequest,
)
from app.security import digest

pytestmark = pytest.mark.integration


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def people(db, client_id):
    return rows(
        db,
        select(IdentitySubject.id)
        .where(IdentitySubject.client_id == client_id)
        .order_by(IdentitySubject.created_at, IdentitySubject.id),
    )


def ok(response, status=201):
    assert response.status_code == status, response.text
    return response.json()


def email(idw, value, method="email_code"):
    return idw.identifier("email", value, method)


def person_of(db, client_id, kind_value_hint=None):
    found = people(db, client_id)
    return found[-1]


def identity_url(idw, suffix, client_id=None):
    return f"{idw.base}/clients/{client_id or idw.w.a1}/identity{suffix}"


def test_identity_reads_need_the_identity_permission(idw, api):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(token, [email(idw, "perm@example.test")]))
    (person,) = people(w.db, w.a1)
    path = identity_url(idw, f"/subjects/{person}")
    owner, admin = idw.owner, w.signed_in("admin")
    analyst, viewer = w.signed_in("analyst"), w.signed_in("viewer")
    assert owner.get(path).status_code == 200
    assert admin.get(path).status_code == 200
    for client in (analyst, viewer):
        assert client.get(path).status_code == 403
    # Grant identity access to the analyst; a legacy update that omits the flag keeps it.
    grant = f"{idw.base}/members/{w.analyst}/clients/{w.a1}"
    assert owner.put(grant, json={"can_view_identities": True}).status_code == 204
    assert analyst.get(path).status_code == 200
    assert owner.put(grant, json={"can_view_financials": True}).status_code == 204
    flags = rows(w.db, select(ClientGrant).where(ClientGrant.membership_id == w.analyst))[0]
    assert (flags.can_view_identities, flags.can_view_financials) == (True, True)
    assert analyst.get(path).status_code == 200
    # Finance alone never grants identity access.
    viewer_grant = f"{idw.base}/members/{w.viewer}/clients/{w.a1}"
    assert owner.put(viewer_grant, json={"can_view_financials": True}).status_code == 204
    assert viewer.get(path).status_code == 403
    # Live revocation blocks the next read.
    assert owner.delete(grant).status_code == 204
    assert analyst.get(path).status_code == 403
    # Service keys: no read key and no ingest key reads identities, and none can be issued.
    read_key = owner.post(
        idw.base + "/service-credentials",
        json={"name": "Reader", "clients": [{"client_id": str(w.a1)}]},
    )
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + read_key.json()["key"]
    assert reader.get(path).status_code == 403
    assert idw.ingest.get(path).status_code in {401, 403}
    refused = owner.post(
        idw.base + "/service-credentials",
        json={
            "name": "Identity reader",
            "clients": [{"client_id": str(w.a1), "can_view_identities": True}],
        },
    )
    assert refused.status_code == 422


def test_invitation_carries_the_identity_flag(idw, api, db):
    w = idw.w
    invited = idw.owner.post(
        idw.base + "/invitations",
        json={
            "email": "newanalyst@example.test",
            "role": "analyst",
            "clients": [{"client_id": str(w.a1), "can_view_identities": True}],
        },
    )
    assert invited.status_code == 201, invited.text
    from app.models import InvitationClientGrant

    stored = rows(db, select(InvitationClientGrant))
    assert [item.can_view_identities for item in stored] == [True]


def test_profile_timeline_and_leads_without_values(idw, db):
    w = idw.w
    phone = idw.browser_subject()["subject_token"]
    first = idw.event(phone)
    ok(idw.via_browser(phone, [email(idw, "mona@example.test")]))
    (person,) = people(db, w.a1)
    server = idw.server_subject()
    lead = idw.event(server["subject_token"], event_type="lead_signal", trusted=True)
    ok(idw.via_server(server, ALL, [email(idw, "mona@example.test")]))
    idw.event(
        server["subject_token"],
        event_type="purchase_signal",
        trusted=True,
        payload={"external_ref": "order-9", "amount_minor": 1000, "currency": "EGP"},
    )
    stranger = idw.browser_subject({ATTRIBUTION: "granted"})["subject_token"]
    idw.event(stranger, event_type="lead_signal")
    body = ok(idw.owner.get(identity_url(idw, f"/subjects/{person}")), 200)
    assert body["stage"] == "lead"
    assert body["flags"] == ["purchase_reported"]
    assert body["customer_qualification"] == "not_customer"
    assert body["keys"] == [
        {
            "kind": "email",
            "normalizer": "email:v1",
            "method": "email_code",
            "verified_at": body["keys"][0]["verified_at"],
            "contested": False,
        }
    ]
    assert body["device_subjects"] == 2 and body["touchpoints"] == 3
    assert "mona@example.test" not in str(body)
    timeline = ok(idw.owner.get(identity_url(idw, f"/subjects/{person}/timeline?limit=2")), 200)
    assert [entry["event_id"] for entry in timeline["entries"]][0] == str(first)
    assert timeline["entries"][0]["evidence"]["keys"] == ["email"]
    assert timeline["next_cursor"] is not None
    rest = ok(
        idw.owner.get(
            identity_url(idw, f"/subjects/{person}/timeline?after={timeline['next_cursor']}")
        ),
        200,
    )
    assert len(timeline["entries"]) + len(rest["entries"]) == 3
    assert rest["entries"][-1]["note"] == "Reported purchase; not verified sale evidence."
    leads = ok(idw.owner.get(identity_url(idw, "/leads")), 200)["items"]
    assert {item["identified"] for item in leads} == {True, False}
    assert any(
        item["event_id"] == str(lead) and item["person"]["stage"] == "lead" for item in leads
    )
    only_trusted = ok(idw.owner.get(identity_url(idw, "/leads?trust=trusted_sender")), 200)
    assert [item["event_id"] for item in only_trusted["items"]] == [str(lead)]
    # An identity reader without finance sees neither the purchase claim nor customer status.
    grant = f"{idw.base}/members/{w.analyst}/clients/{w.a1}"
    assert idw.owner.put(grant, json={"can_view_identities": True}).status_code == 204
    analyst = w.signed_in("analyst")
    limited = ok(analyst.get(identity_url(idw, f"/subjects/{person}")), 200)
    assert limited["flags"] == [] and limited["customer_qualification"] == "permission_unavailable"
    assert limited["touchpoints"] == 2
    entries = ok(analyst.get(identity_url(idw, f"/subjects/{person}/timeline")), 200)["entries"]
    assert all(entry["type"] != "purchase_signal" for entry in entries)
    listing = ok(idw.owner.get(identity_url(idw, "/subjects?stage=lead")), 200)
    assert [item["id"] for item in listing["items"]] == [str(person)]


def merge(idw, survivor, merged, versions=(1, 1), operation=None):
    return idw.owner.post(
        identity_url(idw, "/merges"),
        json={
            "operation_id": str(operation or uuid4()),
            "survivor_id": str(survivor),
            "merged_id": str(merged),
            "survivor_version": versions[0],
            "merged_version": versions[1],
            "reason_code": "same_person_confirmed_by_client",
        },
    )


def reverse(idw, merge_id, versions, operation=None):
    return idw.owner.post(
        identity_url(idw, f"/merges/{merge_id}/reversal"),
        json={
            "operation_id": str(operation or uuid4()),
            "survivor_version": versions[0],
            "merged_version": versions[1],
            "reason_code": "data_correction",
        },
    )


def test_worked_mistaken_merge_and_exact_reversal(idw, db):
    """Design section 10.2 with devices D1, D2, D4, D5 and D6."""
    w = idw.w
    d1 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d1, [email(idw, "ali@example.test")]))
    t1 = idw.event(d1)
    d2 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d2, [idw.identifier("phone", "+20 10 0000 0202", "phone_code")]))
    t3 = idw.event(d2)
    s7, s8 = people(db, w.a1)
    operation = uuid4()
    merged = ok(merge(idw, s7, s8, operation=operation))
    assert merged["survivor"]["version"] == merged["merged"]["version"] == 2
    retry = merge(idw, s7, s8, operation=operation)
    assert retry.status_code == 200 and retry.json() == merged
    assert merge(idw, s7, s8, operation=uuid4()).status_code == 409  # stale versions
    t5 = idw.event(d2)
    d4 = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            d4,
            [
                email(idw, "ali@example.test", "account_verified_email"),
                idw.identifier("phone", "+20 10 0000 0202", "account_verified_phone"),
                idw.identifier("customer_ref", "cust-3001", "account_login"),
            ],
        )
    )
    t7 = idw.event(d4)
    d5 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d5, [idw.identifier("customer_ref", "cust-3001", "account_login")]))
    t8 = idw.event(d5)
    d6 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d6, [email(idw, "ali@example.test")]))
    t9 = idw.event(d6)
    assert set(idw.journey(s7)) == {t1, t3, t5, t7, t8, t9}
    edge = merged["merge_id"]
    dependent = rows(db, select(IdentityLink).where(IdentityLink.merge_id == UUID(edge)))
    assert len(dependent) == 2
    reversed_ = ok(reverse(idw, edge, (2, 2)))
    assert reversed_["survivor"]["version"] == reversed_["merged"]["version"] == 3
    assert len(reversed_["moved_to_review"]["links"]) == 2
    assert len(reversed_["moved_to_review"]["keys"]) == 1
    assert set(idw.journey(s7)) == {t1, t9}
    assert set(idw.journey(s8)) == {t3, t5}
    key = rows(db, select(IdentityKey).where(IdentityKey.kind == "customer_ref"))[0]
    assert (key.status, key.contested_reason, key.subject_id) == ("contested", "unmerged", None)
    assert reverse(idw, edge, (3, 3)).status_code == 409
    review = ok(idw.owner.get(identity_url(idw, "/review")), 200)
    assert {item["reason"] for item in review["ambiguous_segments"]} == {"unmerged"}
    assert review["contested_keys"][0]["reason"] == "unmerged"
    # An assertion of K alone now stays ambiguous (R5).
    d7 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d7, [idw.identifier("customer_ref", "cust-3001", "account_login")]))
    assert rows(
        db,
        select(IdentityAssertion.outcome).order_by(IdentityAssertion.received_at.desc()).limit(1),
    ) == ["ambiguous"]
    edges = rows(db, select(IdentityMerge).order_by(IdentityMerge.created_at))
    assert [(item.kind, item.status) for item in edges] == [
        ("merge", "reversed"),
        ("unmerge", "recorded"),
    ]


def erase(idw, **body):
    return idw.owner.post(identity_url(idw, "/erasures"), json=body)


def resolve(idw, request_id, **body):
    return idw.owner.post(identity_url(idw, f"/erasures/{request_id}/resolution"), json=body)


def test_exclusive_erasure_tombstones_and_suppression(idw, db):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    event_id = idw.event(token)
    ok(idw.via_browser(token, [email(idw, "erase@example.test")]))
    (person,) = people(db, w.a1)
    request = ok(erase(idw, subject_id=str(person), objected=True))
    assert request["status"] == "completed"
    assert request["target_outcomes"]["identity_records"] == "done"
    assert people(db, w.a1) == []
    assert count(db, CollectedEvent, CollectedEvent.event_id == event_id) == 0
    assert count(db, CollectionSubject, CollectionSubject.token_digest == digest(token)) == 0
    types = sorted(rows(db, select(StoredTombstone.match_type)))
    assert types == sorted(
        ["subject_token", "event_id", "identity_key", "assertion_id", "assertion_fp"]
    )
    # The objection suppresses a later assertion of the same email, with a neutral boundary.
    other = idw.browser_subject()["subject_token"]
    response = idw.via_browser(other, [email(idw, "erase@example.test")])
    assert response.status_code == 201 and response.json()["status"] == "accepted"
    assert people(db, w.a1) == []
    suppressed = rows(db, select(IdentityAssertion))[0]
    assert (suppressed.outcome, suppressed.reason) == ("suppressed", "subject_objected")
    links = rows(db, select(IdentityLink))
    assert [link.status for link in links] == ["neutral"]
    subject = rows(
        db, select(CollectionSubject).where(CollectionSubject.token_digest == digest(other))
    )[0]
    assert subject.identity_shared_at is not None


def test_erasure_without_objection_admits_new_consent_after_deletion(idw, db):
    w = idw.w
    token = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(token, [email(idw, "again@example.test")]))
    (person,) = people(db, w.a1)
    ok(erase(idw, subject_id=str(person)))
    fresh = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(fresh, [email(idw, "again@example.test")]))
    (new_person,) = people(db, w.a1)
    assert new_person != person


def shared_tablet(idw, db):
    """Sara then an ambiguous Omar/Ali interval on one tablet (design section 7.2 example)."""
    w = idw.w
    for value in ("omar@example.test", "ali@example.test"):
        device = idw.browser_subject()["subject_token"]
        ok(idw.via_browser(device, [email(idw, value)]))
    omar, ali = people(db, w.a1)
    tablet = idw.browser_subject()["subject_token"]
    before = idw.event(tablet)
    ok(idw.via_browser(tablet, [email(idw, "sara@example.test")]))
    sara = people(db, w.a1)[-1]
    hers = idw.event(tablet)
    ok(
        idw.via_browser(
            tablet,
            [
                email(idw, "omar@example.test", "account_verified_email"),
                idw.identifier("phone", "+20 10 0000 0909", "phone_code"),
            ],
        )
    )
    # The phone joins Omar (R2); now a conflicting pair opens an ambiguous segment.
    ok(
        idw.via_browser(
            tablet,
            [
                email(idw, "ali@example.test", "account_verified_email"),
                idw.identifier("phone", "+20 10 0000 0909", "account_verified_phone"),
            ],
        )
    )
    ambiguous = idw.event(tablet)
    return tablet, sara, omar, ali, before, hers, ambiguous


def test_shared_device_erasure_holds_exact_set_and_resolutions(idw, db):
    tablet, sara, omar, ali, before, hers, ambiguous = shared_tablet(idw, db)
    first = ok(erase(idw, subject_id=str(sara)))
    assert first["status"] == "on_hold"
    assert first["target_outcomes"]["unresolved_events"] == "pending"
    assert count(db, CollectedEvent, CollectedEvent.event_id == hers) == 0
    held = rows(db, select(IdentityErasureHold).where(IdentityErasureHold.state == "held"))
    event_ids = rows(
        db,
        select(CollectedEvent.event_id).where(
            CollectedEvent.id.in_([item.collected_event_id for item in held])
        ),
    )
    assert before in event_ids and ambiguous not in event_ids  # excluded for Sara
    marked = rows(
        db, select(CollectedEvent.identity_excluded_at).where(CollectedEvent.event_id == before)
    )
    assert marked[0] is not None
    # A second request for Omar holds the ambiguous-interval event too (he is a candidate).
    second = ok(erase(idw, subject_id=str(omar)))
    assert second["status"] == "on_hold"
    second_holds = rows(
        db,
        select(CollectedEvent.event_id)
        .join(IdentityErasureHold, IdentityErasureHold.collected_event_id == CollectedEvent.id)
        .where(IdentityErasureHold.deletion_request_id == UUID(second["id"])),
    )
    assert ambiguous in second_holds and before in second_holds
    # Retain for the first request completes it and leaves the second on hold.
    retained = ok(resolve(idw, first["id"], unresolved_events="retain"), 200)
    assert retained["status"] == "completed"
    assert retained["target_outcomes"]["unresolved_events"] == "done"
    assert count(db, CollectedEvent, CollectedEvent.event_id == before) == 1
    assert rows(
        db,
        select(SubjectDeletionRequest.status).where(
            SubjectDeletionRequest.id == UUID(second["id"])
        ),
    ) == ["on_hold"]
    erased = ok(resolve(idw, second["id"], unresolved_events="erase"), 200)
    assert erased["status"] == "completed"
    assert count(db, CollectedEvent, CollectedEvent.event_id.in_([before, ambiguous])) == 0
    assert resolve(idw, second["id"], unresolved_events="erase").status_code == 409
    states = sorted(rows(db, select(IdentityErasureHold.state)))
    assert "retained" in states and "erased" in states and "held" not in states
    assert ali in people(db, idw.w.a1)


def test_retained_event_never_returns_to_a_journey(idw, db):
    """R006-24 / JV07: a retained, marked event stays out after upgrades and new assertions."""
    w = idw.w
    tablet = idw.browser_subject()["subject_token"]
    early = idw.event(tablet)
    ok(idw.via_browser(tablet, [email(idw, "first@example.test")]))
    ok(idw.via_browser(tablet, [email(idw, "second@example.test")]))
    first, second = people(db, w.a1)
    request = ok(erase(idw, subject_id=str(first)))
    assert request["status"] == "on_hold"
    ok(resolve(idw, request["id"], unresolved_events="retain"), 200)
    assert count(db, IdentityErasureHold, IdentityErasureHold.state == "held") == 0
    row = idw.event_row(early)
    assert row.identity_excluded_at is not None
    # A higher-trust copy of the same event upgrades its content but keeps the marker.
    idw.event(tablet, trusted=True, event_id=early)
    after = idw.event_row(early)
    assert after.identity_excluded_at == row.identity_excluded_at
    assert after.first_received_at == row.first_received_at
    ok(idw.via_browser(tablet, [email(idw, "second@example.test")]))
    assert early not in idw.journey(second)


def test_merge_participant_loss_closes_the_edge_first(idw, db):
    """R006-25 / JV08: withdrawal of the merged member's last independent evidence."""
    w = idw.w
    d1 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d1, [email(idw, "keep@example.test")]))
    d2 = idw.browser_subject()["subject_token"]
    ok(idw.via_browser(d2, [idw.identifier("phone", "+20 10 0000 0303", "phone_code")]))
    survivor, lost = people(db, w.a1)
    edge = ok(merge(idw, survivor, lost))
    d3 = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            d3,
            [
                email(idw, "keep@example.test", "account_verified_email"),
                idw.identifier("phone", "+20 10 0000 0303", "account_verified_phone"),
            ],
        )
    )
    spanning = idw.event(d3)
    kept = idw.event(d1)
    # The merged member's only independent evidence is on d2; withdrawing it loses the member.
    idw.browser_subject({IDENTITY: "withdrawn"}, token=d2)
    remaining = people(db, w.a1)
    assert remaining == [survivor]
    row = rows(db, select(IdentityMerge).where(IdentityMerge.id == UUID(edge["merge_id"])))[0]
    assert (row.status, row.closed_reason) == ("closed", "participant_withdrew")
    link = rows(
        db,
        select(IdentityLink).where(
            IdentityLink.collection_subject_id == idw.event_row(spanning).subject_id
        ),
    )[0]
    assert link.status == "ambiguous" and link.candidate_ids == [survivor]
    assert spanning not in idw.journey(survivor) and kept in idw.journey(survivor)
    person = rows(db, select(IdentitySubject).where(IdentitySubject.id == survivor))[0]
    assert person.version == 3 and person.status == "active"


def test_paused_erasure_for_an_active_merge_and_contested_identifier(idw, db):
    w = idw.w
    for value in ("p1@example.test", "p2@example.test"):
        device = idw.browser_subject()["subject_token"]
        ok(idw.via_browser(device, [email(idw, value)]))
    a, b = people(db, w.a1)
    edge = ok(merge(idw, a, b))
    paused = ok(erase(idw, subject_id=str(b)))
    assert paused["status"] == "paused_for_clarification"
    assert resolve(idw, paused["id"], subject_id=str(b)).status_code == 409
    ok(reverse(idw, edge["merge_id"], (2, 2)))
    done = ok(resolve(idw, paused["id"], subject_id=str(b)), 200)
    assert done["status"] == "completed"
    assert people(db, w.a1) == [a]
    # A contested identifier pauses before anything is deleted.
    device = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            device,
            [
                idw.identifier("customer_ref", "cust-x", "account_login"),
                email(idw, "p1@example.test", "account_verified_email"),
            ],
        )
    )
    other = idw.browser_subject()["subject_token"]
    ok(
        idw.via_browser(
            other,
            [
                idw.identifier("customer_ref", "cust-y", "account_login"),
                email(idw, "p1@example.test", "account_verified_email"),
            ],
        )
    )
    shared = rows(
        db,
        select(IdentityKey).where(IdentityKey.kind == "email", IdentityKey.status == "contested"),
    )
    assert len(shared) == 1
    before = count(db, IdentitySubject, IdentitySubject.client_id == w.a1)
    held = ok(erase(idw, identifier={"kind": "email", "value": "p1@example.test"}))
    assert held["status"] == "paused_for_clarification"
    assert count(db, IdentitySubject, IdentitySubject.client_id == w.a1) == before
