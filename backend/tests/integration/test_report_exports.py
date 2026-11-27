"""016-C retained exports through the real routes on disposable PostgreSQL (D-095, RV01-RV05,
RV09).

Synthetic rows are seeded with report_support; the report clock is fixed at
report_support.NOW, so an export and the direct CSV of the same revision can be compared byte
for byte. No provider is called.
"""

import csv
import io
from datetime import date, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from report_support import (
    NOW,
    ad_account,
    checkpoint,
    connection,
    grant,
    instagram_days,
    key_client,
    midnight,
    run,
    service_key,
    spend_facts,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.models import AuditEvent, ReportExport, ReportExportContent
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import tenancy_transaction

pytestmark = pytest.mark.integration
NOV1, NOV2 = date(2026, 11, 1), date(2026, 11, 2)
SPAN = {"start": "2026-11-01", "end": "2026-11-03"}
FAMILIES = ("social", "spend", "revenue", "attribution", "roas", "funnel")


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.api.reports.now_utc", lambda: NOW)
    monkeypatch.setattr("app.services.report_exports.now_utc", lambda: NOW)


def instagram(w, client=None, agency=None):
    cid = connection(w, client or w.a1, "synthetic_instagram", agency)
    checkpoint(w, cid, "account", midnight(date(2026, 10, 1)), midnight(date(2026, 11, 15)))
    run(w, cid, "account")
    instagram_days(w, cid, [NOV1, NOV2], views=[10, 12], reach=[3, 4])
    return cid


def spend(w, client=None, agency=None):
    cid = connection(w, client or w.a1, "synthetic_meta_ads", agency, day_zone="Africa/Cairo")
    ad_account(w, cid)
    checkpoint(w, cid, "ad_daily", midnight(date(2026, 9, 30)), midnight(date(2026, 11, 15)))
    run(w, cid, "ad_daily")
    spend_facts(
        w,
        cid,
        [
            {
                "ad": "31",
                "adset": "21",
                "campaign": "11",
                "day": NOV1,
                "currency": "EGP",
                "minor": 900,
            }
        ],
    )
    return cid


def bodies(w) -> dict[str, dict]:
    social, ads = instagram(w), spend(w)
    return {
        "social": {"family": "social", "connection_id": str(social), "view": "daily"},
        "spend": {"family": "spend", "connection_id": str(ads), "compare": "previous"},
        "revenue": {"family": "revenue", "compare": "previous"},
        "attribution": {"family": "attribution", "group_by": "recipient"},
        "roas": {"family": "roas", "connection_id": str(ads), "level": "campaign"},
        "funnel": {"family": "funnel"},
    }


def exports_url(w, agency=None, client=None) -> str:
    return f"/agencies/{agency or w.a}/clients/{client or w.a1}/report-exports"


def create(reader, w, body, *, agency=None, client=None, span=SPAN):
    return reader.post(exports_url(w, agency, client), json={**body, **span})


def created(reader, w, body, **options) -> dict:
    response = create(reader, w, body, **options)
    assert response.status_code == 201, response.text
    return response.json()


def direct_csv(reader, w, body, revision) -> bytes:
    query = {key: value for key, value in body.items() if key != "family"}
    query.update(SPAN, format="csv", expected_revision=revision)
    url = f"/agencies/{w.a}/clients/{w.a1}/reports/{body['family']}?{urlencode(query)}"
    response = reader.get(url)
    assert response.status_code == 200, response.text
    return response.content


def download(reader, w, export_id, *, agency=None, client=None):
    return reader.get(f"{exports_url(w, agency, client)}/{export_id}/download")


def parse(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")))


def row(w, export_id) -> ReportExport:
    with Session(w.db.migration) as session:
        item = session.get(ReportExport, UUID(str(export_id)))
        assert item is not None
        session.expunge(item)
        return item


def content(w, export_id) -> ReportExportContent | None:
    with Session(w.db.migration) as session:
        item = session.get(ReportExportContent, UUID(str(export_id)))
        if item is not None:
            session.expunge(item)
        return item


def insert_ready(w, count: int, *, client=None, status="ready", age_hours=0) -> None:
    with w.db.migration.begin() as connection:
        for _ in range(count):
            connection.execute(
                text(
                    "INSERT INTO report_exports (id, agency_id, client_id, family, parameters, "
                    "period_start, period_end, includes_financials, source, "
                    "requested_by_membership_id, status, created_at, stored_at, expires_at, "
                    "row_count, byte_size, report_revision, revoked_at, revoked_reason) "
                    "VALUES (:id, :agency, :client, 'revenue', '{}'::jsonb, '2026-11-01', "
                    "'2026-11-03', true, 'manual', :member, CAST(:status AS text), "
                    "now() - make_interval(hours => CAST(:age AS integer)), "
                    "CASE WHEN CAST(:status AS text) = 'pending' THEN NULL ELSE now() END, "
                    "now() - make_interval(hours => CAST(:age AS integer)) + interval '7 days', "
                    "CASE WHEN CAST(:status AS text) = 'pending' THEN NULL ELSE 1 END, "
                    "CASE WHEN CAST(:status AS text) = 'pending' THEN NULL ELSE 10 END, "
                    "CASE WHEN CAST(:status AS text) = 'pending' THEN NULL "
                    "ELSE repeat('a', 64) END, "
                    "CASE WHEN CAST(:status AS text) = 'revoked' THEN now() END, "
                    "CASE WHEN CAST(:status AS text) = 'revoked' THEN 'manual' END)"
                ),
                {
                    "id": uuid4(),
                    "agency": w.a,
                    "client": client or w.a1,
                    "member": w.owner_a,
                    "status": status,
                    "age": age_hours,
                },
            )


# --- RV01 and RV03: every family, byte for byte equal to the direct CSV ------------------------


@pytest.mark.parametrize("family", FAMILIES)
def test_rv01_rv03_every_family_exports_the_direct_csv(authenticated_world, family):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)[family]
    item = created(owner, w, body)
    assert item["family"] == family and item["status"] == "ready"
    assert item["source"] == "manual" and item["requested_by_membership_id"] == str(w.owner_a)
    assert item["period"] == {"start": "2026-11-01", "end": "2026-11-03", "days": 2}
    assert item["includes_financials"] is (family != "social")
    assert item["download_count"] == 0 and item["row_count"] >= 1
    response = download(owner, w, item["id"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="report-{family}.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) == item["byte_size"]
    assert response.content == direct_csv(owner, w, body, item["report_revision"])
    assert len(parse(response.content)) == item["row_count"]
    stored = row(w, item["id"])
    assert stored.download_count == 1 and stored.last_downloaded_at is not None
    assert stored.parameters["compare"] is (body.get("compare") == "previous")
    with Session(w.db.migration) as session:
        audited = session.scalars(
            select(AuditEvent.action).where(AuditEvent.resource_id == stored.id)
        ).all()
    assert audited == ["report_export.created"]


def test_rv01_parameters_and_bounds(authenticated_world, monkeypatch):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    social = bodies(w)["social"]
    refusals = [
        ({**social, "page": 2}, 422, None),
        ({**social, "metrics": "views"}, 422, None),
        (
            {**social, "view": "content_cohort", "compare": "previous"},
            422,
            "comparison_unsupported",
        ),
        (
            {"family": "attribution", "view": "models", "model_version": str(uuid4())},
            422,
            "model_version_not_applicable",
        ),
        ({"family": "unknown"}, 422, None),
    ]
    for body, status, code in refusals:
        response = create(owner, w, body)
        assert response.status_code == status, (body, response.text)
        if code is not None:
            assert response.json()["error"] == code
    response = create(owner, w, social, span={"start": "2026-11-01", "end": "2026-12-03"})
    assert response.status_code == 422 and response.json()["error"] == "invalid_period"
    # The 016-A input bound refuses the whole export, and the failed build leaves no export.
    monkeypatch.setattr("app.services.reporting.MAX_SOURCE_ROWS", 1)
    response = create(owner, w, social)
    assert response.status_code == 422 and response.json()["error"] == "report_too_large"
    with Session(w.db.migration) as session:
        states = session.scalars(select(ReportExport.status)).all()
    assert states == ["discarded"]
    assert owner.get(exports_url(w)).json()["exports"] == []


def test_rv01_client_viewer_exports_what_it_reads(authenticated_world):
    w = authenticated_world
    viewer = w.signed_in("viewer")
    families = bodies(w)
    item = created(viewer, w, families["social"])
    assert item["requested_by_membership_id"] == str(w.viewer)
    assert download(viewer, w, item["id"]).status_code == 200
    # Spend needs finance:read, and the funnel's sale values are left out without it.
    assert create(viewer, w, families["spend"]).status_code == 403
    funnel = created(viewer, w, families["funnel"])
    assert funnel["includes_financials"] is False
    assert create(viewer, w, families["revenue"], client=w.a2).status_code == 403


def test_rv01_keys_and_foreign_scopes_refused(authenticated_world, api):
    w = authenticated_world
    body = bodies(w)["revenue"]
    for kind in ("read", "ingest"):
        raw = service_key(w, api, [grant(w.a1, financial=kind == "read")], kind=kind)
        client = key_client(api, raw)
        assert create(client, w, body).status_code == 401
        assert client.get(exports_url(w)).status_code == 401
    owner = w.signed_in("owner_a")
    assert create(owner, w, body, agency=w.b, client=w.b1).status_code == 403
    assert create(owner, w, body, client=w.b1).status_code == 403
    other = w.signed_in("owner_b")
    assert create(other, w, body).status_code == 403
    analyst = w.signed_in("analyst")
    assert create(analyst, w, bodies(w)["social"], client=w.a2).status_code == 403
    # A connection of another client answers like the report route, before any row.
    assert create(owner, w, bodies(w)["social"], client=w.a2).status_code == 403
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(ReportExport)) == 0


def test_rv01_fifty_unexpired_exports(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)["revenue"]
    insert_ready(w, 48)
    insert_ready(w, 3, status="revoked")  # revoked exports hold no place
    insert_ready(w, 2, status="pending", age_hours=2)  # neither do stale reservations
    insert_ready(w, 5, client=w.a2)  # nor another client's exports
    created(owner, w, body)
    insert_ready(w, 1, status="pending")  # a live reservation holds a place
    response = create(owner, w, body)
    assert response.status_code == 409 and response.json()["error"] == "export_limit_reached"
    with Session(w.db.migration) as session:
        pending = session.scalar(
            select(func.count())
            .select_from(ReportExport)
            .where(ReportExport.client_id == w.a1, ReportExport.status == "pending")
        )
    assert pending == 3  # the refused reservation rolled back
    with w.db.migration.begin() as connection:
        connection.execute(
            update(ReportExport)
            .where(ReportExport.status == "pending", ReportExport.client_id == w.a1)
            .values(status="discarded", revoked_at=func.now())
        )
    created(owner, w, body)
    assert create(owner, w, body).status_code == 409


def test_rv01_missing_keyring_not_configured(authenticated_world, api):
    w = authenticated_world
    settings = api.config.model_copy(
        update={"token_keyring": SecretStr(""), "token_keyring_active": ""}
    )
    owner = api.new_client(settings)
    api.login(owner, "owner_a@example.test")
    response = create(owner, w, bodies(w)["revenue"])
    assert response.status_code == 503 and response.json()["error"] == "not_configured"
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(ReportExport)) == 0


# --- RV02: encryption ---------------------------------------------------------------------------


def test_rv02_no_plaintext_stored(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)["social"]
    item = created(owner, w, body)
    plain = download(owner, w, item["id"]).content
    sealed = content(w, item["id"])
    assert sealed is not None and sealed.alg == "A256GCM-ENV-v1" and sealed.kek_id
    assert len(sealed.ciphertext) == len(plain) + 16
    for fragment in (b"row_type", b"metadata", item["report_revision"].encode(), b"views"):
        assert fragment not in sealed.ciphertext
    with w.db.migration.connect() as connection:
        found = connection.execute(
            text(
                "SELECT count(*) FROM report_exports e JOIN report_export_contents c "
                "ON c.export_id = e.id WHERE position('row_type' in e.parameters::text) > 0 "
                "OR position(convert_to('row_type', 'UTF8') in c.ciphertext) > 0"
            )
        ).scalar_one()
    assert found == 0


def test_rv02_copied_ciphertext_does_not_open(authenticated_world):
    w = authenticated_world
    owner, other = w.signed_in("owner_a"), w.signed_in("owner_b")
    body = bodies(w)["revenue"]
    first, second = created(owner, w, body), created(owner, w, body)
    foreign = created(other, w, body, agency=w.b, client=w.b1)
    elsewhere = created(owner, w, body, client=w.a2)
    source = content(w, first["id"])
    assert source is not None
    columns = ("kek_id", "wrap_nonce", "wrapped_dek", "nonce", "ciphertext")
    with w.db.migration.begin() as connection:
        for target in (second, foreign, elsewhere):
            connection.execute(
                update(ReportExportContent)
                .where(ReportExportContent.export_id == UUID(target["id"]))
                .values({name: getattr(source, name) for name in columns})
            )
    for reader, target, agency, client in (
        (owner, second, w.a, w.a1),
        (other, foreign, w.b, w.b1),
        (owner, elsewhere, w.a, w.a2),
    ):
        response = download(reader, w, target["id"], agency=agency, client=client)
        assert response.status_code == 500, response.text
        assert response.json() == {"error": "export_unreadable"}
    assert download(owner, w, first["id"]).status_code == 200


# --- RV03: downloads ----------------------------------------------------------------------------


def test_rv03_scope_resolved_again(authenticated_world):
    w = authenticated_world
    analyst, viewer = w.signed_in("analyst"), w.signed_in("viewer")
    body = bodies(w)["social"]
    mine, theirs = created(analyst, w, body), created(viewer, w, body)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.revoke_client(w.a, w.a1, w.analyst)
        service.update_member(w.a, w.viewer, status="disabled")
    assert download(analyst, w, mine["id"]).status_code == 403
    assert analyst.get(exports_url(w)).status_code == 403
    assert download(viewer, w, theirs["id"]).status_code == 403
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, w.analyst)
    assert download(analyst, w, mine["id"]).status_code == 200


def test_rv03_sale_values_need_finance(authenticated_world):
    w = authenticated_world
    owner, analyst = w.signed_in("owner_a"), w.signed_in("analyst")
    families = bodies(w)
    attribution = created(owner, w, families["attribution"])
    ads = created(owner, w, families["spend"])
    lead_only = created(analyst, w, families["attribution"])
    assert attribution["includes_financials"] and not lead_only["includes_financials"]
    listed = {item["id"] for item in analyst.get(exports_url(w)).json()["exports"]}
    assert listed == {lead_only["id"]}
    for item in (attribution, ads):
        assert download(analyst, w, item["id"]).status_code == 403
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, w.analyst, can_view_financials=True)
    for item in (attribution, ads, lead_only):
        assert download(analyst, w, item["id"]).status_code == 200


def test_rv03_revoked_or_expired_export_gone(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)["revenue"]
    revoked, expired = created(owner, w, body), created(owner, w, body)
    assert owner.delete(f"{exports_url(w)}/{revoked['id']}").status_code == 200
    with w.db.migration.begin() as connection:
        connection.execute(
            update(ReportExport)
            .where(ReportExport.id == UUID(expired["id"]))
            .values(
                created_at=func.now() - timedelta(days=8),
                expires_at=func.now() - timedelta(days=1),
            )
        )
    for item in (revoked, expired):
        response = download(owner, w, item["id"])
        assert response.status_code == 410 and response.json() == {"error": "export_gone"}
    states = {item["id"]: item["status"] for item in owner.get(exports_url(w)).json()["exports"]}
    assert states == {revoked["id"]: "revoked", expired["id"]: "expired"}
    assert row(w, expired["id"]).download_count == 0


# --- RV04 and RV05: visibility and manual revocation ---------------------------------------------


def test_rv04_visibility(authenticated_world):
    w = authenticated_world
    owner, admin, analyst, viewer, outsider = (
        w.signed_in(name) for name in ("owner_a", "admin", "analyst", "viewer", "owner_b")
    )
    body = bodies(w)["social"]
    mine = {
        name: created(reader, w, body)["id"]
        for name, reader in (("owner", owner), ("analyst", analyst), ("viewer", viewer))
    }
    created(owner, w, bodies(w)["revenue"], client=w.a2)
    for reader in (owner, admin, analyst):
        listed = {item["id"] for item in reader.get(exports_url(w)).json()["exports"]}
        assert listed == set(mine.values())
    listed = [item["id"] for item in viewer.get(exports_url(w)).json()["exports"]]
    assert listed == [mine["viewer"]]
    assert viewer.get(f"{exports_url(w)}/{mine['owner']}").status_code == 403
    assert download(viewer, w, mine["analyst"]).status_code == 403
    assert outsider.get(exports_url(w)).status_code == 403
    assert outsider.get(f"{exports_url(w)}/{mine['owner']}").status_code == 403
    assert download(outsider, w, mine["owner"]).status_code == 403
    # Newest first, paginated.
    page = owner.get(f"{exports_url(w)}?limit=2&offset=0").json()
    assert [item["id"] for item in page["exports"]] == [mine["viewer"], mine["analyst"]]
    rest = owner.get(f"{exports_url(w)}?limit=2&offset=2").json()["exports"]
    assert [item["id"] for item in rest] == [mine["owner"]]


def test_rv05_manual_revocation(authenticated_world):
    w = authenticated_world
    owner, admin, analyst, viewer = (
        w.signed_in(name) for name in ("owner_a", "admin", "analyst", "viewer")
    )
    body = bodies(w)["social"]
    by_viewer, by_owner = created(viewer, w, body), created(owner, w, body)
    assert analyst.delete(f"{exports_url(w)}/{by_viewer['id']}").status_code == 403
    assert viewer.delete(f"{exports_url(w)}/{by_owner['id']}").status_code == 403
    assert content(w, by_viewer["id"]) is not None
    response = viewer.delete(f"{exports_url(w)}/{by_viewer['id']}")
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert response.json()["revoked_reason"] == "manual"
    response = admin.delete(f"{exports_url(w)}/{by_owner['id']}")
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    for item in (by_viewer, by_owner):
        assert content(w, item["id"]) is None
        assert row(w, item["id"]).revoked_at is not None
    # Revoking again changes nothing and audits nothing.
    assert owner.delete(f"{exports_url(w)}/{by_owner['id']}").status_code == 200
    with Session(w.db.migration) as session:
        audited = sorted(
            (str(item.resource_id), str(item.actor_user_id))
            for item in session.scalars(
                select(AuditEvent).where(AuditEvent.action == "report_export.revoked")
            )
        )
    assert audited == sorted(
        [(by_viewer["id"], str(w.users.viewer)), (by_owner["id"], str(w.users.admin))]
    )


# --- RV09: expiry -------------------------------------------------------------------------------


def test_rv09_lifecycle_deletes_expired_exports(
    authenticated_world, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = bodies(w)["revenue"]
    items = [created(owner, w, body)["id"] for _ in range(4)]
    kept = created(owner, w, body)["id"]
    owner.delete(f"{exports_url(w)}/{items[3]}")
    with w.db.migration.begin() as connection:
        connection.execute(
            update(ReportExport)
            .where(ReportExport.id.in_([UUID(item) for item in items]))
            .values(
                created_at=func.now() - timedelta(days=8),
                expires_at=func.now() - timedelta(days=1),
            )
        )
    insert_ready(w, 1, status="pending", age_hours=2)
    insert_ready(w, 1, status="pending")  # a live reservation stays
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO report_exports (id, agency_id, client_id, family, parameters, "
                "period_start, period_end, includes_financials, source, "
                "requested_by_membership_id, status, expires_at, revoked_at) VALUES (:id, "
                ":agency, :client, 'revenue', '{}'::jsonb, '2026-11-01', '2026-11-03', true, "
                "'manual', :member, 'discarded', now() + interval '1 day', now())"
            ),
            {"id": uuid4(), "agency": w.a, "client": w.a1, "member": w.owner_a},
        )
    settings = lifecycle_settings.model_copy(update={"lifecycle_batch_size": 2})
    result = run_lifecycle(lifecycle_engine, settings)
    assert result["status"] == "completed", result
    assert result["deleted"]["report_exports"] == 6
    assert result["deleted"]["report_export_contents"] == 3
    with Session(w.db.migration) as session:
        remaining = session.execute(select(ReportExport.id, ReportExport.status)).all()
        contents = session.scalars(select(ReportExportContent.export_id)).all()
    assert sorted(status for _, status in remaining) == ["pending", "ready"]
    assert UUID(kept) in {identifier for identifier, _ in remaining}
    assert contents == [UUID(kept)]
    again = run_lifecycle(lifecycle_engine, settings)
    assert "report_exports" not in again["deleted"] and again["status"] == "completed"
    assert download(owner, w, kept).status_code == 200
