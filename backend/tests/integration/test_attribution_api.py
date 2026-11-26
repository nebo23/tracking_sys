"""008-B attribution routes and permissions on disposable PostgreSQL (D-079, AV12).

Model administration is Owner/Admin and audited. The runs route needs identity:read, a sale's
amounts and transaction references also need finance:read, and a service key reaches the models
and the status only. Scope is resolved again before a person-level release, so a revocation
during the request releases nothing. Other clients and agencies see nothing, and a stale read
answers the retryable attribution_stale. Synthetic values only.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from attribution_support import LINEAR, make_attribution_world
from identity_support import make_identity_world
from report_support import grant, key_client, service_key
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api import attribution as attribution_api
from app.models import AuditEvent

pytestmark = pytest.mark.integration


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def url(w, suffix, client=None, agency=None) -> str:
    return f"/agencies/{agency or w.a}/clients/{client or w.a1}/attribution{suffix}"


def settled_sale(aw):
    """A caught-up client with one associated sale that has two touches."""
    buyer = aw.person("buyer@example.test")
    for campaign in ("spring", "autumn"):
        aw.touch(buyer.token, campaign)
    aw.sale("S1", 10_000, when=datetime.now(UTC) + timedelta(hours=1))
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    return buyer, aw.conversion("S1")


def set_grant(aw, **flags):
    grant_url = f"{aw.idw.base}/members/{aw.w.analyst}/clients/{aw.w.a1}"
    assert aw.idw.owner.put(grant_url, json=flags).status_code == 204


def test_av12_model_administration_is_owner_admin_and_audited(aw, api):
    w = aw.w
    body = {"operation_id": str(uuid4()), "model": "linear", "window_days": 7}
    for name in ("analyst", "viewer"):
        assert w.signed_in(name).post(url(w, "/models"), json=body).status_code == 403
    # Another agency's owner and an unknown client learn nothing.
    assert w.signed_in("owner_b").post(url(w, "/models"), json=body).status_code == 403
    assert (
        w.signed_in("owner_a").post(url(w, "/models", client=uuid4()), json=body).status_code == 403
    )
    created = w.signed_in("admin").post(url(w, "/models"), json=body)
    assert created.status_code == 201, created.text
    version = created.json()["id"]
    owner = w.signed_in("owner_a")
    for action in ("default", "retire"):
        denied = w.signed_in("analyst").post(
            url(w, f"/models/{version}/{action}"), json={"operation_id": str(uuid4())}
        )
        assert denied.status_code == 403
    assert (
        owner.post(
            url(w, f"/models/{version}/default"), json={"operation_id": str(uuid4())}
        ).status_code
        == 201
    )
    # A version of another client is not found under this client.
    other = owner.get(url(w, "/models", client=w.a2)).json()["versions"][0]["id"]
    foreign = owner.post(url(w, f"/models/{other}/default"), json={"operation_id": str(uuid4())})
    assert foreign.status_code == 403
    with Session(w.db.migration) as session:
        events = session.execute(
            select(AuditEvent.action, AuditEvent.actor_user_id, AuditEvent.client_id)
            .where(AuditEvent.resource_type == "attribution_model")
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        ).all()
    assert sorted(tuple(event) for event in events) == sorted(
        [
            ("attribution.model_created", w.users.admin, w.a1),
            ("attribution.model_default_set", w.users.owner_a, w.a1),
        ]
    )


def test_av12_runs_need_identity_read_and_amounts_need_finance_read(aw):
    w = aw.w
    buyer, conversion = settled_sale(aw)
    route = url(w, f"/conversions/{conversion.id}/runs")
    owner = aw.idw.owner
    full = owner.get(route)
    assert full.status_code == 200, full.text
    assert full.headers["Cache-Control"] == "no-store"
    body = full.json()
    assert body["conversion"]["person_id"] == str(buyer.id)
    assert body["conversion"]["transaction"] == {
        "state": "available",
        "source_account_id": "shop",
        "sale_operation_id": "S1",
    }
    assert body["model_version"]["version_key"] == LINEAR
    (run,) = body["runs"]
    assert (run["amounts"], run["verified_net_minor"], run["currency"]) == (
        "available",
        10_000,
        "EGP",
    )
    assert [item["amount_minor"] for item in run["allocations"]] == [5_000, 5_000]
    assert [item["campaign_ref"] for item in run["allocations"]] == ["spring", "autumn"]
    assert [item["delta_minor"] for item in run["differences"]] == [5_000, 5_000]
    # A named version, and an unknown one.
    versions = {
        item["version_key"]: item["id"] for item in owner.get(url(w, "/models")).json()["versions"]
    }
    first = owner.get(route, params={"model_version": versions["first_click_30d_v1"]}).json()
    assert [item["credited"] for item in first["runs"][0]["allocations"]] == [True, False]
    assert owner.get(route, params={"model_version": str(uuid4())}).status_code == 403
    assert owner.get(url(w, f"/conversions/{uuid4()}/runs")).status_code == 403
    # An analyst with the client grant but without identity access reads nothing.
    analyst = w.signed_in("analyst")
    assert analyst.get(route).status_code == 403
    assert analyst.get(url(w, "/status")).status_code == 200
    # Identity without finance: shares, touches and provenance, and the explicit state for money.
    set_grant(aw, can_view_identities=True)
    limited = analyst.get(route)
    assert limited.status_code == 200, limited.text
    hidden = limited.json()
    assert hidden["conversion"]["transaction"] == {
        "state": "permission_unavailable",
        "source_account_id": None,
        "sale_operation_id": None,
    }
    (run,) = hidden["runs"]
    assert (run["amounts"], run["verified_net_minor"], run["currency"]) == (
        "permission_unavailable",
        None,
        None,
    )
    assert all(item["amount_minor"] is None for item in run["allocations"])
    assert all(item["delta_minor"] is None for item in run["differences"])
    assert [item["share"] for item in run["allocations"]] == [
        {"numerator": 1, "denominator": 2}
    ] * 2
    # Finance without identity is refused; both together see the amounts.
    set_grant(aw, can_view_identities=False, can_view_financials=True)
    assert analyst.get(route).status_code == 403
    set_grant(aw, can_view_identities=True, can_view_financials=True)
    assert analyst.get(route).json()["runs"][0]["verified_net_minor"] == 10_000
    # A viewer without the flag, another agency and another client of the same agency.
    assert w.signed_in("viewer").get(route).status_code == 403
    assert w.signed_in("owner_b").get(route).status_code == 403
    assert owner.get(url(w, f"/conversions/{conversion.id}/runs", client=w.a2)).status_code == 403
    assert (
        w.signed_in("owner_b")
        .get(url(w, f"/conversions/{conversion.id}/runs", client=w.b1, agency=w.b))
        .status_code
        == 403
    )


def test_av12_service_keys_reach_models_and_status_only(aw, api):
    w = aw.w
    _, conversion = settled_sale(aw)
    reader = key_client(api, service_key(w, api, [grant(w.a1, financial=True)]))
    assert reader.get(url(w, "/models")).status_code == 200
    report = reader.get(url(w, "/status"))
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["state"] == "caught_up"
    assert body["consumer"]["generation"] == 1 and body["consumer"]["status"] == "ready"
    assert body["consumer"]["receipt_ordinal"] == body["current"]["receipt_ordinal"] == 1
    assert body["consumer"]["identity_seq"] == body["current"]["identity_seq"]
    assert body["current"]["ledger"] == "available"
    assert reader.get(url(w, f"/conversions/{conversion.id}/runs")).status_code == 403
    # Without the client's grant a read key reaches nothing; an ingest key is not a reader.
    assert reader.get(url(w, "/models", client=w.a2)).status_code == 403
    assert reader.get(url(w, "/status", client=w.a2)).status_code == 403
    ingest = aw.idw.ingest
    assert ingest.get(url(w, "/status")).status_code in {401, 403}
    assert ingest.get(url(w, f"/conversions/{conversion.id}/runs")).status_code in {401, 403}
    # The status of a client that was never processed names no person and is not caught up.
    fresh = aw.idw.owner.get(url(w, "/status", client=w.a2)).json()
    assert fresh["state"] == "rebuilding" and fresh["consumer"]["generation"] == 0


@pytest.mark.parametrize("flag", ["can_view_identities", "can_view_financials"])
def test_av12_a_revocation_during_the_request_releases_nothing(aw, monkeypatch, flag):
    w = aw.w
    _, conversion = settled_sale(aw)
    set_grant(aw, can_view_identities=True, can_view_financials=True)
    analyst = w.signed_in("analyst")
    route = url(w, f"/conversions/{conversion.id}/runs")
    assert analyst.get(route).status_code == 200
    original = attribution_api.attribution_reads.runs

    def revoking(*args, **kwargs):
        body = original(*args, **kwargs)
        with w.db.migration.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE client_grants SET {flag} = false "
                    "WHERE membership_id = :m AND client_id = :c"
                ),
                {"m": w.analyst, "c": w.a1},
            )
        return body

    monkeypatch.setattr(attribution_api.attribution_reads, "runs", revoking)
    response = analyst.get(route)
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})


def test_stale_reads_answer_the_retryable_code(aw):
    w = aw.w
    buyer, conversion = settled_sale(aw)
    route = url(w, f"/conversions/{conversion.id}/runs")
    owner = aw.idw.owner
    aw.touch(buyer.token, "winter")
    stale = owner.get(route)
    assert (stale.status_code, stale.json()) == (503, {"error": "attribution_stale"})
    assert stale.headers["Retry-After"] == "1"
    assert owner.get(url(w, "/status")).json()["state"] == "behind"
    aw.settle()
    released = owner.get(route)
    assert released.status_code == 200
    assert [run["revision"] for run in released.json()["runs"]] == [1, 2]
    assert owner.get(url(w, "/status")).json()["state"] == "caught_up"
