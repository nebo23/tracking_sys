"""016-C schedules, the report worker and report_ready emails on disposable PostgreSQL
(D-095 D8-D10, RV10, RV12-RV16, RV19).

The worker clock is fixed at report_support.NOW (2026-11-20 12:00 UTC); a daily 06:00 UTC
schedule therefore reports 2026-11-19. Emails are written as local .eml files only.
"""

# ruff: noqa: F811

import logging
import threading
from datetime import UTC, date, datetime, timedelta
from email import policy
from email.parser import BytesParser
from uuid import UUID

import pytest
from pydantic import SecretStr
from report_support import (
    NOW,
    checkpoint,
    connection,
    grant,
    instagram_days,
    key_client,
    midnight,
    run,
    service_key,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_report_exports import (  # noqa: F401
    bodies,
    created,
    download,
    exports_url,
    fixed_clock,
    instagram,
    parse,
)

from app.models import Agency, MailOutbox, ReportExport, ReportSchedule
from app.reporting.common import ReportError
from app.services import report_exports
from app.services.mail import process_mail
from app.services.report_schedules import run_pass
from app.services.tenancy import Role, tenancy_transaction

pytestmark = pytest.mark.integration
SLOT_DAY = date(2026, 11, 20)


def schedules_url(w, agency=None, client=None) -> str:
    return f"/agencies/{agency or w.a}/clients/{client or w.a1}/report-schedules"


def schedule_body(report, **extra) -> dict:
    return {
        "name": "Synthetic daily report",
        "report": report,
        "cadence": "daily",
        "hour": 6,
        "time_zone": "UTC",
        **extra,
    }


def scheduled(reader, w, body, **options) -> dict:
    response = reader.post(schedules_url(w, **options), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def due(w, *schedule_ids, at=NOW - timedelta(hours=1)) -> None:
    with w.db.migration.begin() as connection:
        connection.execute(
            update(ReportSchedule)
            .where(ReportSchedule.id.in_([UUID(str(item)) for item in schedule_ids]))
            .values(next_run_at=at)
        )


def schedule_row(w, schedule_id) -> ReportSchedule:
    with Session(w.db.migration) as session:
        item = session.get(ReportSchedule, UUID(str(schedule_id)))
        assert item is not None
        session.expunge(item)
        return item


def schedule_exports(w, schedule_id) -> list[ReportExport]:
    with Session(w.db.migration) as session:
        items = list(
            session.scalars(
                select(ReportExport)
                .where(ReportExport.schedule_id == UUID(str(schedule_id)))
                .order_by(ReportExport.created_at)
            )
        )
        for item in items:
            session.expunge(item)
        return items


# An Instagram connection whose account stream is complete through the scheduled period.
def recent_instagram(w, views, reach):
    cid = connection(w, w.a1, "synthetic_instagram")
    checkpoint(w, cid, "account", midnight(date(2026, 10, 1)), midnight(SLOT_DAY))
    run(w, cid, "account")
    instagram_days(w, cid, [SLOT_DAY - timedelta(days=1)], views=[views], reach=[reach])
    return cid


def update_agency(agency_id, status):
    return update(Agency).where(Agency.id == agency_id).values(status=status)


def worker(w, api, settings=None, limit=25):
    return run_pass(w.db.runtime, settings or api.config, {}, limit=limit, clock=lambda: NOW)


def outbox(w) -> list[MailOutbox]:
    with Session(w.db.migration) as session:
        items = list(
            session.scalars(
                select(MailOutbox)
                .where(MailOutbox.purpose == "report_ready")
                .order_by(MailOutbox.created_at)
            )
        )
        for item in items:
            session.expunge(item)
        return items


# --- RV10: schedule rules -----------------------------------------------------------------------


def test_rv10_schedule_validation(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    families = bodies(w)
    social = families["social"]
    refusals = [
        (schedule_body(social, cadence="weekly"), 422, "invalid_schedule"),
        (schedule_body(social, weekday=3), 422, "invalid_schedule"),
        (schedule_body(social, hour=24), 422, None),
        (schedule_body(social, time_zone="Mars/Olympus_Mons"), 422, "invalid_time_zone"),
        (schedule_body(social, name="Line\nbreak"), 422, None),
        (schedule_body(social, name="x" * 101), 422, None),
        (schedule_body(social, sale_values=True), 422, "invalid_schedule"),
        (schedule_body({**social, "page": 1}), 422, None),
        (
            schedule_body({**social, "view": "content_cohort", "compare": "previous"}),
            422,
            "comparison_unsupported",
        ),
        (
            schedule_body({**families["spend"], "connection_id": social["connection_id"]}),
            422,
            "not_a_spend_connection",
        ),
        (schedule_body(social, recipients=[str(w.viewer)] * 21), 422, None),
    ]
    for body, status, code in refusals:
        response = owner.post(schedules_url(w), json=body)
        assert response.status_code == status, (body, response.text)
        if code is not None:
            assert response.json()["error"] == code
    # A connection of another client is refused like the report route refuses it.
    foreign = instagram(w, client=w.a2)
    response = owner.post(
        schedules_url(w), json=schedule_body({**social, "connection_id": str(foreign)})
    )
    assert response.status_code == 403
    item = scheduled(
        owner,
        w,
        schedule_body(
            {**social, "metrics": ["views"]},
            cadence="weekly",
            weekday=1,
            hour=7,
            time_zone="Africa/Cairo",
        ),
    )
    assert item["report"] == {
        "family": "social",
        "connection_id": social["connection_id"],
        "view": "daily",
        "metrics": ["views"],
        "compare": False,
    }
    assert (item["cadence"], item["weekday"], item["hour"]) == ("weekly", 1, 7)
    assert item["status"] == "active" and item["owner_membership_id"] == str(w.owner_a)
    assert item["recipients"] == [] and item["receiving"] is False
    first = datetime.fromisoformat(item["next_run_at"])
    assert first > datetime.now(UTC) and first.astimezone(UTC).hour == 5
    assert first.isoweekday() == 1
    # A stopped connection is refused when a schedule is created for it.
    owner.post(f"/agencies/{w.a}/clients/{w.a1}/connections/{social['connection_id']}/disconnect")
    response = owner.post(schedules_url(w), json=schedule_body(social))
    assert response.status_code == 409 and response.json()["error"] == "source_unavailable"


def test_rv10_managers_only(authenticated_world, api):
    w = authenticated_world
    body = schedule_body(bodies(w)["revenue"])
    for name in ("analyst", "viewer", "owner_b"):
        assert w.signed_in(name).post(schedules_url(w), json=body).status_code == 403
    raw = service_key(w, api, [grant(w.a1, financial=True)])
    assert key_client(api, raw).post(schedules_url(w), json=body).status_code == 401
    item = scheduled(w.signed_in("admin"), w, body)
    assert item["owner_membership_id"] == str(w.admin)
    analyst = w.signed_in("analyst")
    url = f"{schedules_url(w)}/{item['id']}"
    assert analyst.patch(url, json={"name": "Renamed"}).status_code == 403
    assert analyst.delete(url).status_code == 403
    assert analyst.get(url).status_code == 403
    owner = w.signed_in("owner_a")
    assert owner.delete(url).status_code == 204
    assert owner.get(url).status_code == 403


def test_rv10_ten_active_schedules(authenticated_world):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = schedule_body(bodies(w)["revenue"])
    items = [scheduled(owner, w, body) for _ in range(10)]
    response = owner.post(schedules_url(w), json=body)
    assert response.status_code == 409 and response.json()["error"] == "schedule_limit_reached"
    assert scheduled(owner, w, body, client=w.a2)["status"] == "active"
    paused = owner.patch(f"{schedules_url(w)}/{items[0]['id']}", json={"status": "paused"})
    assert paused.status_code == 200 and paused.json()["pause_reason"] == "manual"
    assert paused.json()["next_run_at"] is None
    scheduled(owner, w, body)
    response = owner.patch(f"{schedules_url(w)}/{items[0]['id']}", json={"status": "active"})
    assert response.status_code == 409 and response.json()["error"] == "schedule_limit_reached"


def test_rv10_recipients(authenticated_world):
    w = authenticated_world
    owner, viewer = w.signed_in("owner_a"), w.signed_in("viewer")
    families = bodies(w)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        disabled = service.add_member(w.a, w.users.second_owner, Role.ANALYST)
        service.grant_client(w.a, w.a1, disabled.id)
        service.update_member(w.a, disabled.id, status="disabled")
    refused = [
        (families["spend"], [w.viewer]),  # no finance:read
        (families["social"], [w.other_member]),  # another agency's member
        (families["social"], [w.viewer, w.viewer]),
        (families["social"], [disabled.id]),
        (families["attribution"], [w.analyst], {"client": w.a2}),  # cannot read that client
    ]
    for item in refused:
        report, recipients, *options = item
        response = owner.post(
            schedules_url(w, **(options[0] if options else {})),
            json=schedule_body(report, recipients=[str(value) for value in recipients]),
        )
        assert response.status_code == 422 and response.json()["error"] == "invalid_recipient"
    response = owner.post(
        schedules_url(w),
        json=schedule_body(families["attribution"], sale_values=True, recipients=[str(w.analyst)]),
    )
    assert response.status_code == 422 and response.json()["error"] == "invalid_recipient"
    received = scheduled(
        owner,
        w,
        schedule_body(families["social"], recipients=[str(w.viewer), str(w.analyst)]),
    )
    hidden = scheduled(owner, w, schedule_body(families["social"], recipients=[str(w.analyst)]))
    assert sorted(received["recipients"]) == sorted([str(w.viewer), str(w.analyst)])
    listed = viewer.get(schedules_url(w)).json()["schedules"]
    assert [item["id"] for item in listed] == [received["id"]]
    assert listed[0]["receiving"] is True and listed[0]["recipients"] is None
    assert viewer.get(f"{schedules_url(w)}/{hidden['id']}").status_code == 403
    leave = f"{schedules_url(w)}/{received['id']}/recipients/me"
    assert viewer.delete(leave).status_code == 204
    assert viewer.get(f"{schedules_url(w)}/{received['id']}").status_code == 403
    assert viewer.delete(leave).status_code == 403
    remaining = owner.get(f"{schedules_url(w)}/{received['id']}").json()["recipients"]
    assert remaining == [str(w.analyst)]


# --- RV12: the worker ---------------------------------------------------------------------------


def test_rv12_due_schedule_runs_once_under_two_workers(authenticated_world, api, monkeypatch):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = schedule_body(bodies(w)["revenue"])
    items = [scheduled(owner, w, body)["id"] for _ in range(3)]
    due(w, *items)
    barrier = threading.Barrier(2, timeout=20)
    entered: set[int] = set()

    def hook(export_id):
        thread = threading.get_ident()
        if thread not in entered:
            entered.add(thread)
            barrier.wait()  # both workers are building at the same time

    monkeypatch.setattr("app.services.report_exports.before_build", hook)
    results: list[dict] = []
    threads = [threading.Thread(target=lambda: results.append(worker(w, api))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert len(results) == 2 and len(entered) == 2
    assert sum(result["built"] for result in results) == 3
    assert sum(result["due"] for result in results) == 3
    for item in items:
        assert len(schedule_exports(w, item)) == 1
        assert schedule_row(w, item).next_run_at > NOW
    assert worker(w, api)["due"] == 0


def test_rv12_next_slot_and_missed_slot(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    item = scheduled(owner, w, schedule_body(bodies(w)["revenue"]))
    # Three slots were missed; one run reports the latest period and none is repeated.
    due(w, item["id"], at=NOW - timedelta(days=3))
    assert worker(w, api) == {
        "due": 1,
        "built": 1,
        "notified": 0,
        "skipped": 0,
        "failed": 0,
        "paused": 0,
    }
    (export,) = schedule_exports(w, item["id"])
    assert (export.period_start, export.period_end) == (SLOT_DAY - timedelta(days=1), SLOT_DAY)
    assert (export.source, export.requested_by_membership_id) == ("schedule", w.owner_a)
    stored = schedule_row(w, item["id"])
    assert stored.next_run_at == datetime(2026, 11, 21, 6, tzinfo=UTC)
    assert (stored.last_outcome, stored.last_run_at) == ("built", NOW)
    assert worker(w, api)["due"] == 0


def test_rv12_pass_is_bounded(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    body = schedule_body(bodies(w)["revenue"])
    items = [scheduled(owner, w, body)["id"] for _ in range(3)]
    due(w, *items)
    assert worker(w, api, limit=2)["built"] == 2
    assert worker(w, api, limit=2)["built"] == 1
    with pytest.raises(ValueError):
        worker(w, api, limit=101)


# --- RV13 and RV14: permissions at run time and the email ----------------------------------------


def test_rv13_owner_without_access_pauses(authenticated_world, api):
    w = authenticated_world
    admin, owner = w.signed_in("admin"), w.signed_in("owner_a")
    item = scheduled(admin, w, schedule_body(bodies(w)["revenue"]))
    # The former Admin can still read the report, but only an Owner or Admin runs a schedule.
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_member(w.a, w.admin, role=Role.ANALYST)
        service.grant_client(w.a, w.a1, w.admin, can_view_financials=True)
    due(w, item["id"])
    assert worker(w, api)["paused"] == 1
    stored = schedule_row(w, item["id"])
    assert (stored.status, stored.pause_reason, stored.next_run_at) == (
        "paused",
        "owner_access_lost",
        None,
    )
    assert schedule_exports(w, item["id"]) == []
    resumed = owner.patch(f"{schedules_url(w)}/{item['id']}", json={"status": "active"})
    assert resumed.status_code == 200
    assert resumed.json()["owner_membership_id"] == str(w.owner_a)
    due(w, item["id"])
    assert worker(w, api)["built"] == 1
    (export,) = schedule_exports(w, item["id"])
    assert export.requested_by_membership_id == w.owner_a


def test_rv13_recipients_without_access_skipped(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    families = bodies(w)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, w.analyst, can_view_financials=True)
    sales = scheduled(
        owner,
        w,
        schedule_body(
            families["attribution"],
            sale_values=True,
            recipients=[str(w.admin), str(w.analyst)],
        ),
    )
    social = scheduled(
        owner, w, schedule_body(families["social"], recipients=[str(w.viewer), str(w.analyst)])
    )
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.grant_client(w.a, w.a1, w.analyst, can_view_financials=False)
        service.revoke_client(w.a, w.a1, w.viewer)
    due(w, sales["id"], social["id"])
    result = worker(w, api)
    assert (result["built"], result["notified"], result["skipped"]) == (2, 2, 2)
    assert schedule_row(w, sales["id"]).last_notified == 1
    assert schedule_row(w, social["id"]).last_skipped == 1
    (financial,) = schedule_exports(w, sales["id"])
    assert financial.includes_financials
    # Sale values reach only readers with finance:read, in the list as in the email.
    analyst = w.signed_in("analyst")
    listed = {item["id"] for item in analyst.get(exports_url(w)).json()["exports"]}
    assert str(financial.id) not in listed
    (lead_free,) = schedule_exports(w, social["id"])
    assert str(lead_free.id) in listed


def test_rv14_report_ready_email(authenticated_world, api):
    w = authenticated_world
    owner, viewer = w.signed_in("owner_a"), w.signed_in("viewer")
    cid = recent_instagram(w, 987654, 876543)
    report = {"family": "social", "connection_id": str(cid), "view": "daily"}
    item = scheduled(
        owner,
        w,
        schedule_body(report, name="Synthetic daily social", recipients=[str(w.viewer)]),
    )
    due(w, item["id"])
    assert worker(w, api)["notified"] == 1
    (export,) = schedule_exports(w, item["id"])
    (message,) = outbox(w)
    assert message.expires_at == export.expires_at and message.delivered_at is None
    # The recipient sees the export in the application and can download it.
    listed = [entry["id"] for entry in viewer.get(exports_url(w)).json()["exports"]]
    assert listed == [str(export.id)]
    data = download(viewer, w, export.id).content
    assert b"987654" in data
    delivered = process_mail(w.db.runtime, api.config)
    assert delivered["delivered"] == 1
    files = list(api.config.mail_directory.glob("*.eml"))
    assert [path.name for path in files] == [f"{message.id}.eml"]
    parsed = BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())
    assert str(parsed["To"]) == "viewer@example.test"
    assert str(parsed["Subject"]) == "Report ready: Synthetic daily social"
    body = parsed.get_body().get_content().replace(chr(13) + chr(10), chr(10))
    assert body.startswith("Synthetic Agency A\n\n")
    assert "Report: Social\n" in body and "Period: 2026-11-19 to 2026-11-19\n" in body
    link = f"{api.config.frontend_origin}/agencies/{w.a}/clients/{w.a1}/reports/exports/{export.id}"
    assert link in body
    for forbidden in ("987654", "876543", "Synthetic Client A1", "token", "tsk_", "#"):
        assert forbidden not in body


# --- RV15 and RV16: stop states and failures -----------------------------------------------------


def test_rv15_stop_states_get_no_run(authenticated_world, api):
    w = authenticated_world
    owner, other = w.signed_in("owner_a"), w.signed_in("owner_b")
    archived = scheduled(owner, w, schedule_body(bodies(w)["revenue"]), client=w.a2)
    foreign = scheduled(other, w, schedule_body(bodies(w)["revenue"]), agency=w.b, client=w.b1)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a2, status="archived")
    due(w, archived["id"], foreign["id"])
    for status in ("suspended", "closing", "closed"):
        with w.db.migration.begin() as connection:
            connection.execute(update_agency(w.b, status))
        assert worker(w, api)["due"] == 0
    with w.db.migration.begin() as connection:
        connection.execute(update_agency(w.b, "active"))
    assert worker(w, api)["built"] == 1
    assert len(schedule_exports(w, foreign["id"])) == 1
    assert schedule_exports(w, archived["id"]) == []
    assert schedule_row(w, archived["id"]).status == "active"


def test_rv16_failures(authenticated_world, api, monkeypatch):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    families = bodies(w)
    original = report_exports._build
    calls = {"count": 0}

    def changing(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise ReportError("report_changed", 409)
        return original(*args, **kwargs)

    retried = scheduled(owner, w, schedule_body(families["revenue"]))
    due(w, retried["id"])
    monkeypatch.setattr("app.services.report_exports._build", changing)
    assert worker(w, api)["built"] == 1 and calls["count"] == 3
    monkeypatch.setattr("app.services.report_exports._build", original)
    assert schedule_row(w, retried["id"]).last_outcome == "built"
    # A report too large, a source not ready and a missing keyring are closed codes.
    social = scheduled(owner, w, schedule_body(families["social"]))
    instagram_days(
        w,
        UUID(families["social"]["connection_id"]),
        [SLOT_DAY - timedelta(days=1)],
        views=[5],
        reach=[4],
    )
    unknown_zone = connection(w, w.a1, "synthetic_meta_ads")
    roas = scheduled(
        owner,
        w,
        schedule_body({"family": "roas", "connection_id": str(unknown_zone)}),
    )
    monkeypatch.setattr("app.services.reporting.MAX_SOURCE_ROWS", 0)
    due(w, social["id"], roas["id"])
    assert worker(w, api)["failed"] == 2
    assert schedule_row(w, social["id"]).last_error_code == "report_too_large"
    assert schedule_row(w, roas["id"]).last_error_code == "source_not_ready"
    no_keys = api.config.model_copy(
        update={"token_keyring": SecretStr(""), "token_keyring_active": ""}
    )
    due(w, social["id"])
    assert worker(w, api, settings=no_keys)["failed"] == 1
    stored = schedule_row(w, social["id"])
    assert (stored.last_error_code, stored.consecutive_failures) == ("not_configured", 2)
    due(w, social["id"])
    result = worker(w, api)
    assert (result["failed"], result["paused"]) == (1, 1)
    stored = schedule_row(w, social["id"])
    assert (stored.status, stored.pause_reason, stored.consecutive_failures) == (
        "paused",
        "repeated_failures",
        3,
    )
    with Session(w.db.migration) as session:
        discarded = session.scalar(
            select(func.count()).select_from(ReportExport).where(ReportExport.status == "discarded")
        )
    # The two report_changed attempts and three failed builds; a missing keyring refuses the
    # build before any reservation.
    assert discarded == 2 + 3
    assert schedule_row(w, roas["id"]).consecutive_failures == 1


# --- RV19: no data in logs or output; isolation of schedules -------------------------------------


def test_rv19_no_data_in_logs_or_output(authenticated_world, api, caplog):
    w = authenticated_world
    owner, viewer = w.signed_in("owner_a"), w.signed_in("viewer")
    cid = recent_instagram(w, 918273, 827364)
    report = {"family": "social", "connection_id": str(cid), "view": "daily"}
    caplog.set_level(logging.DEBUG)
    export = created(owner, w, report, span={"start": "2026-11-19", "end": "2026-11-20"})
    data = download(owner, w, export["id"]).content
    assert b"918273" in data and parse(data)
    item = scheduled(
        owner, w, schedule_body(report, name="Synthetic private name", recipients=[str(w.viewer)])
    )
    due(w, item["id"])
    result = worker(w, api)
    assert set(result) == {"due", "built", "notified", "skipped", "failed", "paused"}
    assert all(isinstance(value, int) for value in result.values())
    process_mail(w.db.runtime, api.config)
    logged = "\n".join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    for forbidden in (
        "918273",
        "827364",
        "Synthetic Client A1",
        "Synthetic Agency A",
        "Synthetic private name",
        "viewer@example.test",
        export["report_revision"],
        "row_type",
    ):
        assert forbidden not in logged, forbidden
    # Another agency sees none of these schedules.
    other = w.signed_in("owner_b")
    assert other.get(schedules_url(w)).status_code == 403
    assert other.get(f"{schedules_url(w)}/{item['id']}").status_code == 403
    assert other.delete(f"{schedules_url(w)}/{item['id']}/recipients/me").status_code == 403
    assert viewer.get(f"{schedules_url(w)}/{item['id']}").status_code == 200
