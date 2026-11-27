"""016-B conversions list and the person-level release corrections (D-089 D11, BV15).

GET /attribution/conversions is a person-level read: identity:read, never a service key,
attribution_stale unless caught up, and sales only with finance:read. The list and the runs
route refuse an answer when an erasure or a worker pass commits while it is being built (O1 of
the 008-B merge review), and the status route reads inside one snapshot (O2). Synthetic
values only.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from attribution_support import FIRST, LINEAR, make_attribution_world
from credit_support import at, list_url, sale_day, set_grant, today, versions
from identity_support import ATTRIBUTION, make_identity_world
from report_support import grant, key_client, service_key
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import attribution as attribution_api
from app.security import now_utc
from app.services import attribution_reads
from app.services import attribution_store as store
from app.services.attribution_scrub import scrub_person

pytestmark = pytest.mark.integration


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def window(day=None, days=3):
    first = today()
    return {"start": first.isoformat(), "end": (first + timedelta(days=days)).isoformat()}


def listing(reader, aw, **params):
    return reader.get(list_url(aw.w), params={**window(), **params})


def world(aw):
    """Two buyers with sales on a future date, an unassociated sale and a trusted lead."""
    day = sale_day()
    buyer = aw.person("buyer@example.test")
    aw.touch(buyer.token, "spring")
    aw.sale("S1", 10_000, when=at(day, 10))
    aw.associate(buyer.assertion, "S1")
    other = aw.person("other@example.test")
    aw.touch(other.token, "autumn")
    aw.sale("S2", 4_000, when=at(day, 11))
    aw.associate(other.assertion, "S2")
    aw.sale("S3", 1_000, when=at(day, 12))
    asker = aw.person("asker@example.test")
    aw.touch(asker.token, "spring")
    lead_event = aw.lead(asker.token)
    aw.settle()
    return buyer, other, asker, lead_event


def test_bv15_stale_while_behind_and_after_withdrawal(aw):
    buyer, _, asker, _ = world(aw)
    owner = aw.idw.owner
    first = listing(owner, aw)
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    assert len(first.json()["items"]) == 4
    aw.touch(buyer.token, "winter")
    stale = listing(owner, aw)
    assert (stale.status_code, stale.json()) == (503, {"error": "attribution_stale"})
    assert stale.headers["Retry-After"] == "1"
    aw.settle()
    assert listing(owner, aw).status_code == 200
    # A withdrawal between two passes: stale until the next pass has applied it.
    aw.consent(asker.token, ATTRIBUTION, "withdrawn")
    assert listing(owner, aw).json() == {"error": "attribution_stale"}
    aw.settle()
    assert listing(owner, aw).status_code == 200


def test_bv15_scrub_pages_filters_finance_and_keys(aw, api):
    w = aw.w
    buyer, other, asker, lead_event = world(aw)
    owner = aw.idw.owner
    body = listing(owner, aw).json()
    assert body["sales"] == "available" and body["model_version"]["version_key"] == LINEAR
    items = body["items"]
    assert [item["kind"] for item in items] == ["sale", "sale", "sale", "lead"]  # newest first
    by_kind = {item["kind"]: item for item in items}
    lead = by_kind["lead"]
    assert (lead["person_id"], lead["lead_event_id"]) == (str(asker.id), str(lead_event))
    assert lead["transaction"] is None and lead["latest_run"]["currency"] is None
    sale = next(item for item in items if item["person_id"] == str(buyer.id))
    assert sale["transaction"] == {"source_account_id": "shop", "sale_operation_id": "S1"}
    assert (sale["latest_run"]["revision"], sale["latest_run"]["verified_net_minor"]) == (1, 10_000)
    assert next(item for item in items if item["person_id"] is None)["kind"] == "sale"
    # Stable pages by an opaque cursor in conversion-time order.
    pages, cursor = [], None
    while True:
        params = {"limit": 1, **({"after": cursor} if cursor else {})}
        page = listing(owner, aw, **params).json()
        pages += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [item["id"] for item in pages] == [item["id"] for item in items]
    assert listing(owner, aw, after="not-a-cursor").json() == {"error": "invalid_cursor"}
    # Filters: kind, status, person and model version; filters are never broadened.
    assert [item["kind"] for item in listing(owner, aw, kind="lead").json()["items"]] == ["lead"]
    mine = listing(owner, aw, person_id=str(buyer.id)).json()["items"]
    assert [item["transaction"]["sale_operation_id"] for item in mine] == ["S1"]
    first_click = versions(owner, w)[FIRST]
    assert (
        listing(owner, aw, model_version=first_click).json()["model_version"]["id"] == first_click
    )
    for params in (
        {"person_id": str(uuid4())},
        {"model_version": str(uuid4())},
        {"model_version": versions(owner, w, client=w.a2)[LINEAR]},
    ):
        assert listing(owner, aw, **params).status_code == 403, params
    response = owner.get(list_url(w), params={**window(), "format": "csv"})
    assert (response.status_code, response.json()) == (422, {"error": "unknown_parameter"})
    # An erasure scrubs: the next pass supersedes the scrubbed conversion, which shows no
    # person and no lead event.
    aw.erase(asker.id)
    aw.settle()
    scrubbed = listing(owner, aw, kind="lead", status="superseded").json()["items"]
    assert len(scrubbed) == 1
    assert (scrubbed[0]["scrubbed"], scrubbed[0]["person_id"], scrubbed[0]["lead_event_id"]) == (
        True,
        None,
        None,
    )
    assert scrubbed[0]["superseded_reason"] == "scrubbed"
    assert str(asker.id) not in listing(owner, aw).text
    # Identity without finance lists leads only; finance alone is not enough.
    analyst = w.signed_in("analyst")
    assert listing(analyst, aw).status_code == 403
    set_grant(aw, can_view_identities=True)
    limited = listing(analyst, aw).json()
    assert limited["sales"] == "permission_unavailable"
    assert {item["kind"] for item in limited["items"]} <= {"lead"}
    assert listing(analyst, aw, kind="sale").json()["items"] == []
    assert "S1" not in listing(analyst, aw).text
    set_grant(aw, can_view_identities=False, can_view_financials=True)
    assert listing(analyst, aw).status_code == 403
    # No service key reaches the list; other clients and agencies see nothing.
    reader = key_client(api, service_key(w, api, [grant(w.a1, financial=True)]))
    assert listing(reader, aw).status_code == 403
    assert listing(aw.idw.ingest, aw).status_code in {401, 403}
    assert w.signed_in("owner_b").get(list_url(w), params=window()).status_code == 403
    assert owner.get(list_url(w, client=w.a2), params=window()).json() == {
        "error": "attribution_stale"
    }


@pytest.mark.parametrize("route", ["list", "runs"])
@pytest.mark.parametrize("change", ["erasure", "worker_pass", "revocation"])
def test_bv15_commit_during_build_refuses_list_and_runs(aw, monkeypatch, route, change):
    w = aw.w
    buyer, _, _, _ = world(aw)
    set_grant(aw, can_view_identities=True, can_view_financials=True)
    reader = w.signed_in("analyst")
    conversion = aw.conversion("S1")
    path = (
        list_url(w)
        if route == "list"
        else f"/agencies/{w.a}/clients/{w.a1}/attribution/conversions/{conversion.id}/runs"
    )
    params = window() if route == "list" else {}
    assert reader.get(path, params=params).status_code == 200
    name = "conversions" if route == "list" else "runs"
    original = getattr(attribution_reads, name)

    def commit():
        if change == "erasure":
            with Session(w.db.runtime) as session, session.begin():
                scrub_person(session, w.a, w.a1, buyer.id, "erased", now_utc())
        elif change == "worker_pass":
            store.process_client(w.db.runtime, w.a, w.a1)
        else:
            with w.db.migration.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE client_grants SET can_view_identities = false "
                        "WHERE membership_id = :m AND client_id = :c"
                    ),
                    {"m": w.analyst, "c": w.a1},
                )

    def building(*args, **kwargs):
        body = original(*args, **kwargs)
        commit()
        return body

    monkeypatch.setattr(attribution_api.attribution_reads, name, building)
    response = reader.get(path, params=params)
    expected = (
        (403, {"error": "access_denied"})
        if change == "revocation"
        else (503, {"error": "attribution_stale"})
    )
    assert (response.status_code, response.json()) == expected
    assert str(buyer.id) not in response.text


def test_bv15_status_reads_one_snapshot(aw, monkeypatch):
    w = aw.w
    world(aw)
    owner = aw.idw.owner
    status = f"/agencies/{w.a}/clients/{w.a1}/attribution/status"
    assert owner.get(status).json()["state"] == "caught_up"
    original = attribution_reads.current_watermark

    def advancing(connection, client_id):
        # A feed record commits between the status read's statements.
        with w.db.migration.begin() as other:
            other.execute(
                text("UPDATE identity_feed_state SET last_seq = last_seq + 1 WHERE client_id = :c"),
                {"c": w.a1},
            )
        return original(connection, client_id)

    monkeypatch.setattr(attribution_reads, "current_watermark", advancing)
    body = owner.get(status).json()
    # Every value comes from the snapshot taken before the commit: one moment, not two.
    assert body["state"] == "caught_up"
    assert body["current"]["identity_seq"] == body["consumer"]["identity_seq"]
    monkeypatch.setattr(attribution_reads, "current_watermark", original)
    after = owner.get(status).json()
    assert after["state"] == "behind"
    assert after["current"]["identity_seq"] == body["current"]["identity_seq"] + 1
