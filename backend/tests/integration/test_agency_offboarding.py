"""Offboarding and purge of closed agencies (017-B, D-098 D6 to D8 and D11).

Cases OV07, OV08, OV09 (the purge of a populated agency), OV10, OV11 and OV13 to OV16 of the
entry review's verification matrix, on synthetic data in the disposable database only. The
revocations reach the synthetic provider only. OV09's table list and OV12 are in
test_agency_offboarding_migration.py. Fixture imports deliberately expose the conversion
delivery fixture to pytest.
"""

# ruff: noqa: F811

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from uuid import uuid4

import pytest
from attribution_support import make_attribution_world
from connector_support import make_lab
from credit_support import ad_objects, campaign, content, managed_link, visit
from identity_support import make_identity_world
from offboarding_support import (
    NAMES,
    agency_export,
    branding,
    close_agency,
    insert,
    owner_membership,
    populate_direct,
    rows_of,
    status_of,
)
from report_support import ad_account, spend_facts
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_conversion_delivery import _deliver, _enqueue, _rows, _sale, _setup, capi  # noqa: F401

from app import agency_offboarding as command
from app.config import BACKEND_ROOT
from app.ledger import calculate
from app.models import (
    Agency,
    AgencyClosure,
    AgencyExport,
    AgencyInvitation,
    AgencyPlanAssignment,
    AgencyPurge,
    ConnectorSyncRun,
    ConversionDestination,
    IngestionSource,
    IntegrationSource,
    PaymentSource,
    ReportExport,
    ReportExportContent,
    ReportSchedule,
    ServiceCredential,
    User,
    WhatsappNumber,
)
from app.security import now_utc
from app.services import attribution_store, report_schedules
from app.services.agency_offboarding import EFFECTS, run_offboarding
from app.services.agency_purge import purge_agency
from app.services.delivery import candidates_from_ledger
from app.services.lifecycle import run_lifecycle
from app.services.whatsapp import WhatsappError, verify_claim

pytestmark = pytest.mark.integration
KEPT = {"agency_plan_assignments", "agency_purges"}
# Tables reached through a parent key, and the two self-referencing tables (design section 1.2).
PATHS = {
    "agency_export_parts",
    "report_export_contents",
    "attribution_allocations",
    "identity_links",
    "booking_events",
    "integration_deliveries",
    "integration_source_secrets",
    "payment_source_secrets",
    "conversion_acknowledgements",
    "ad_spend_facts",
    "ad_objects",
    "ad_accounts",
    "connector_records",
    "connector_usage_records",
    "connector_checkpoints",
    "connector_token_secrets",
    "consent_records",
    "ingestion_source_secrets",
    "identity_merges",
    "identity_subjects",
}


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _get(db, model, key):
    with Session(db.migration) as session:
        return session.get(model, key)


def _all(db, query):
    with Session(db.migration) as session:
        return list(session.scalars(query))


def _value(db, statement, **values):
    with db.migration.connect() as connection:
        return connection.execute(text(statement), values).scalar_one()


def _leftover(db, agency, clients) -> dict[str, int]:
    return {
        table: count
        for table, count in rows_of(db, agency, clients).items()
        if count and table not in KEPT
    }


def _purge(lifecycle_engine, lifecycle_settings, **options) -> dict:
    return run_lifecycle(lifecycle_engine, lifecycle_settings, **options)


def _read_key(w, client) -> None:
    response = w.signed_in("owner_a").post(
        f"/agencies/{w.a}/service-credentials",
        json={
            "name": "Synthetic read key",
            "kind": "read",
            "clients": [{"client_id": str(client)}],
        },
    )
    assert response.status_code == 201, response.text


def test_ov07_offboarding_disconnects_revokes_and_disables_once(
    lab, api, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    k2 = lab.connect("owner_a", w.a, w.a2, account="syn-acct-a2")
    kb = lab.connect("owner_b", w.b, w.b1, account="syn-acct-b1")
    member = owner_membership(w.db, w.a)
    ids = populate_direct(w.db, w.a, w.a1, member, connection_id=k1)
    _read_key(w, w.a1)
    pending = agency_export(w.db, w.a, member, ready=False)
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    # The closure itself never revoked anything (017-A D8): connections are still live.
    assert {lab.row(k).status for k in (k1, k2)} == {"active"}
    first = run_offboarding(w.db.runtime, lab.config)
    assert first == {
        "offboarded": 1,
        "skipped": 0,
        "failed": 0,
        "connections_disconnected": 2,
        "service_keys_revoked": 1,
        "invitations_revoked": 1,
        "report_exports_revoked": 1,
        "agency_exports_failed": 1,
        "sources_disabled": 3,
        "destinations_disabled": 1,
        "whatsapp_numbers_disabled": 2,
    }
    for connection_id in (k1, k2):
        row = lab.row(connection_id)
        assert (row.status, row.status_reason) == ("disconnecting", "agency_closed")
        assert row.purge_due_at - row.disconnect_requested_at == timedelta(hours=72)
    assert lab.row(kb).status == "active"
    assert {item.status for item in _all(w.db, select(ServiceCredential))} == {"revoked"}
    assert _get(w.db, AgencyInvitation, ids.invitation).status == "revoked"
    report = _get(w.db, ReportExport, ids.report_export)
    assert (report.status, report.revoked_reason) == ("revoked", "agency_closed")
    assert _get(w.db, ReportExportContent, ids.report_export) is None
    failed = _get(w.db, AgencyExport, pending)
    assert (failed.status, failed.error_code) == ("failed", "closure_completed")
    for model, key in (
        (PaymentSource, ids.payment),
        (IntegrationSource, ids.integration),
        (IngestionSource, ids.webhook),
    ):
        assert _get(w.db, model, key).status == "disabled"
    assert _get(w.db, ConversionDestination, ids.destination).enabled is False
    assert _get(w.db, WhatsappNumber, ids.number).status == "disabled"
    assert _get(w.db, WhatsappNumber, ids.pending_number).status == "revoked"
    record = _get(w.db, AgencyPurge, w.a)
    closure = _all(w.db, select(AgencyClosure).where(AgencyClosure.agency_id == w.a))[0]
    assert record.state == "waiting" and record.offboarding_completed_at is not None
    assert (record.closure_requested_at, record.closes_at, record.closure_completed_at) == (
        closure.requested_at,
        closure.closes_at,
        closure.completed_at,
    )
    assert record.export_summary["status"] == "failed"
    assert record.export_summary["error_code"] == "closure_completed"
    # A second pass finds nothing to do.
    second = run_offboarding(w.db.runtime, lab.config)
    assert second == {"offboarded": 0, "skipped": 0, "failed": 0, **dict.fromkeys(EFFECTS, 0)}
    assert _get(w.db, AgencyPurge, w.a).state == "waiting"


def test_ov08_teardown_revokes_at_the_provider_and_the_purge_waits(
    lab, api, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    kb = lab.connect("owner_b", w.b, w.b1, account="syn-acct-b1")
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    assert run_offboarding(w.db.runtime, lab.config)["connections_disconnected"] == 1
    # While the provider fails, the teardown stays pending and the purge waits.
    lab.provider.set_behavior("revoke", "retryable")
    assert lab.worker()["teardown"] == {"pending": 1}
    waited = _purge(lifecycle_engine, lifecycle_settings)
    assert (
        "agencies_purged" not in waited["deleted"] and "agency_purges" not in waited["incomplete"]
    )
    assert _get(w.db, AgencyPurge, w.a).state == "waiting"
    assert _value(w.db, "SELECT count(*) FROM client_workspaces WHERE agency_id = :a", a=w.a) == 2
    # The synthetic provider receives the revocation; the teardown settles; the purge follows.
    lab.provider.set_behavior("revoke", "ok")
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert lab.provider.grants() == [("syn-acct-a1", True), ("syn-acct-b1", False)]
    assert lab.row(k1).status == "disconnected" and lab.row(k1).revocation_status == "done"
    purged = _purge(lifecycle_engine, lifecycle_settings)
    assert purged["deleted"]["agencies_purged"] == 1
    assert lab.row(k1) is None and lab.row(kb).status == "active"


def test_ov08_a_teardown_past_its_deadline_no_longer_holds_the_purge(
    lab, api, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}
    ad_account(w, k1)
    ad_objects(w, k1, [("120001", "120002", "120003")])
    spend_facts(w, k1, [{"ad": "120001", "day": date.today(), "currency": "EGP", "minor": 500}])
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    run_offboarding(w.db.runtime, lab.config)
    lab.provider.set_behavior("revoke", "retryable")
    assert lab.worker()["teardown"] == {"pending": 1}
    assert _purge(lifecycle_engine, lifecycle_settings)["deleted"].get("agencies_purged") is None
    before = rows_of(w.db, w.a, [w.a1, w.a2])
    assert all(
        before[t] for t in ("connector_records", "ad_spend_facts", "connector_token_secrets")
    )
    # The deadline passes without a worker: the purge deletes the connection, its sealed tokens
    # and its provider rows itself; the grant was never revoked (D7, the provider expires it).
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE connector_connections SET purge_due_at = now() - interval '1 second'")
        )
    result = _purge(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["agencies_purged"] == 1
    assert _leftover(w.db, w.a, [w.a1, w.a2]) == {}
    record = _get(w.db, AgencyPurge, w.a)
    for table in ("connector_records", "ad_spend_facts", "ad_objects", "ad_accounts"):
        assert record.deleted_counts[table] == before[table]
    assert lab.provider.grants() == [("syn-acct-a1", False)]


def _populate(w, api, lab) -> None:
    aw = make_attribution_world(make_identity_world(w, api))
    owner = aw.idw.owner
    alice = aw.person("alice@example.test")
    bob = aw.person("bob@example.test")
    carol = aw.person("carol@example.test")
    link_id = managed_link(
        owner,
        w,
        "spring-offer",
        campaign_id=campaign(owner, w, "spring"),
        content_id=content(owner, w, "reel-1"),
    )
    visit(aw, alice.token, link_id)
    aw.touch(alice.token, "spring")
    aw.lead(alice.token)
    aw.sale("op-1001")
    aw.associate(alice.assertion, "op-1001")
    edge = aw.merge(alice.id, bob.id)
    aw.unmerge(edge)
    aw.merge(alice.id, bob.id)
    aw.erase(carol.id)
    aw.settle()
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}
    ad_account(w, k1)
    ad_objects(w, k1, [("120001", "120002", "120003")])
    spend_facts(w, k1, [{"ad": "120001", "day": date.today(), "currency": "EGP", "minor": 500}])
    member = owner_membership(w.db, w.a)
    populate_direct(w.db, w.a, w.a1, member, connection_id=k1)
    branding(w.db, w.a, member)
    agency_export(w.db, w.a, member)


def _populate_b(w, lab) -> None:
    kb = lab.connect("owner_b", w.b, w.b1, account="syn-acct-b1")
    # Its first synchronization runs now, so later worker passes leave its rows as they are.
    assert set(lab.worker()["sync"]) == {"succeeded"}
    member = owner_membership(w.db, w.b)
    populate_direct(
        w.db,
        w.b,
        w.b1,
        member,
        connection_id=kb,
        phone="2010002",
        hostname="go.agency-b.example.test",
    )
    branding(w.db, w.b, member)
    agency_export(w.db, w.b, member)


def test_ov09_purge_leaves_no_row_of_the_agency(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    _populate(w, api, lab)
    _populate_b(w, lab)
    before = rows_of(w.db, w.a, [w.a1, w.a2])
    populated = {table for table, count in before.items() if count}
    assert PATHS <= populated, sorted(PATHS - populated)
    assert len(populated - KEPT) >= 75, sorted(set(before) - populated)
    b_before = rows_of(w.db, w.b, [w.b1, w.b2])
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    assert run_offboarding(w.db.runtime, lab.config)["offboarded"] == 1
    assert lab.worker()["teardown"] == {"disconnected": 1}
    result = _purge(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["agencies_purged"] == 1
    assert "agency_purges" not in result["incomplete"]
    # No row of the agency or of one of its clients remains anywhere, apart from the record.
    assert _leftover(w.db, w.a, [w.a1, w.a2]) == {}
    record = _get(w.db, AgencyPurge, w.a)
    assert sum(record.deleted_counts.values()) == result["deleted"]["agency_rows_purged"]
    assert set(record.deleted_counts) <= populated | {"agency_closures"}
    # OV11: the other agency, which shares the analyst, keeps every row.
    assert rows_of(w.db, w.b, [w.b1, w.b2]) == b_before


def test_ov10_what_stays_after_the_purge(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    member = owner_membership(w.db, w.a)
    populate_direct(w.db, w.a, w.a1, member)
    export_id = agency_export(w.db, w.a, member)
    exported = _get(w.db, AgencyExport, export_id)
    plans = _value(w.db, "SELECT count(*) FROM agency_plan_assignments WHERE agency_id = :a", a=w.a)
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    closure = _all(w.db, select(AgencyClosure).where(AgencyClosure.agency_id == w.a))[0]
    run_offboarding(w.db.runtime, lab.config)
    result = _purge(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["agencies_purged"] == 1
    agency = _get(w.db, Agency, w.a)
    assert (agency.status, agency.name) == ("closed", f"Closed agency {w.a}")
    assert agency.purged_at is not None
    assert (
        len(_all(w.db, select(AgencyPlanAssignment).where(AgencyPlanAssignment.agency_id == w.a)))
        == plans
    )
    record = _get(w.db, AgencyPurge, w.a)
    assert record.state == "purged" and record.purge_completed_at is not None
    assert (record.closure_requested_at, record.closes_at, record.closure_completed_at) == (
        closure.requested_at,
        closure.closes_at,
        closure.completed_at,
    )
    summary = record.export_summary
    assert summary["status"] == "ready" and summary["manifest_sha256"] == exported.manifest_sha256
    assert (summary["part_count"], summary["byte_size"]) == (1, 40)
    assert record.deleted_counts["client_workspaces"] == 2
    assert record.deleted_counts["agency_memberships"] == 4
    assert record.offboarding_started_at <= record.teardown_settled_at <= record.purge_completed_at
    stored = json.dumps([summary, record.deleted_counts])
    for secret in (NAMES["a"], "Synthetic Client", "example.test", str(w.a1), str(w.a2)):
        assert secret not in stored
    # Users stay as platform accounts and can still sign in; the agency is gone from them.
    assert len(_all(w.db, select(User))) == 7
    client = api.new_client()
    api.login(client, "admin@example.test")
    assert client.get("/agencies").json() == []
    owner_b = w.signed_in("owner_b")
    assert [item["agency_id"] for item in owner_b.get("/agencies").json()] == [str(w.b)]


def test_ov11_other_agencies_keep_every_row(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    ka = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    member = owner_membership(w.db, w.a)
    populate_direct(w.db, w.a, w.a1, member, connection_id=ka)
    _populate_b(w, lab)
    b_before = rows_of(w.db, w.b, [w.b1, w.b2])
    assert sum(b_before.values()) > 40
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    run_offboarding(w.db.runtime, lab.config)
    lab.worker()
    assert _purge(lifecycle_engine, lifecycle_settings)["deleted"]["agencies_purged"] == 1
    assert rows_of(w.db, w.b, [w.b1, w.b2]) == b_before
    assert lab.provider.grants() == [("syn-acct-a1", True), ("syn-acct-b1", False)]
    # The analyst, a member of both agencies, keeps the B membership and reads B's clients.
    analyst = w.signed_in("analyst")
    assert [item["agency_id"] for item in analyst.get("/agencies").json()] == [str(w.b)]
    assert analyst.get(f"/agencies/{w.b}/clients").status_code == 200
    assert status_of(w.db, w.b) == "active"


def test_ov13_purge_is_bounded_and_resumable(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    member = owner_membership(w.db, w.a)
    populate_direct(w.db, w.a, w.a1, member)
    agency_export(w.db, w.a, member)
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    run_offboarding(w.db.runtime, lab.config)
    total = (
        sum(rows_of(w.db, w.a, [w.a1, w.a2]).values())
        - _value(w.db, "SELECT count(*) FROM agency_plan_assignments WHERE agency_id = :a", a=w.a)
        - 1
    )  # the purge record stays
    small = lifecycle_settings.model_copy(update={"lifecycle_batch_size": 7})
    # One bounded batch per run: seven rows, then the run stops and reports itself incomplete.
    first = _purge(lifecycle_engine, small, max_batches=1)
    assert first["deleted"]["agency_rows_purged"] == 7
    assert "agencies_purged" not in first["deleted"] and "agency_purges" in first["incomplete"]
    assert _get(w.db, AgencyPurge, w.a).state == "purging"
    # An interruption: a held row lock makes a batch time out; it rolls back alone.
    with w.db.migration.connect() as holder:
        holder.execute(
            text("SELECT id FROM payment_sources WHERE agency_id = :a FOR UPDATE"), {"a": w.a}
        )
        stopped = _purge(lifecycle_engine, small)
        holder.rollback()
    assert "agency_purges" in stopped["incomplete"]
    after_stop = sum(_get(w.db, AgencyPurge, w.a).deleted_counts.values())
    assert after_stop == 7 + stopped["deleted"].get("agency_rows_purged", 0) < total
    # The next run resumes from the first table; every call stays within its budget.
    calls = []
    with lifecycle_engine.connect() as connection:
        rows, outcome = purge_agency(connection, w.a, 7, None, on_batch=calls.append)
    assert outcome == "purged" and after_stop + rows == total
    assert all(sum(call["deleted"].values()) <= 7 for call in calls)
    assert [call["state"] for call in calls][-1] == "purged"
    assert _leftover(w.db, w.a, [w.a1, w.a2]) == {}
    assert sum(_get(w.db, AgencyPurge, w.a).deleted_counts.values()) == total


def test_ov14_whatsapp_number_and_custom_domain_are_released(
    lab, api, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    hostname = "go.agency-a.example.test"
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a), hostname=hostname)
    claim = uuid4()
    insert(
        w.db,
        [
            (
                "INSERT INTO whatsapp_numbers (id, agency_id, client_id, phone_number_id, name, "
                "created_by_membership_id) VALUES (:id, :agency, :client, '2010001', "
                "'Synthetic claim', :member)",
                {"id": claim, "agency": w.b, "client": w.b1, "member": owner_membership(w.db, w.b)},
            )
        ],
    )
    owner_b = w.signed_in("owner_b")
    domains = f"/agencies/{w.b}/clients/{w.b1}/link-domains"
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    run_offboarding(w.db.runtime, lab.config)
    # Disabled, the closed agency's number and hostname stay reserved until the purge.
    with pytest.raises(WhatsappError) as refused, Session(w.db.runtime) as session:
        with session.begin():
            verify_claim(session, claim)
    assert refused.value.code == "number_already_bound"
    assert owner_b.post(domains, json={"hostname": hostname}).status_code == 409
    assert _purge(lifecycle_engine, lifecycle_settings)["deleted"]["agencies_purged"] == 1
    with Session(w.db.runtime) as session, session.begin():
        assert verify_claim(session, claim).status == "active"
    created = owner_b.post(domains, json={"hostname": hostname})
    assert created.status_code == 201, created.text


def test_ov15_workers_skip_closed_and_purged_agencies(
    lab, api, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    k3 = lab.connect("owner_b", w.b, w.b1, account="syn-acct-b1")
    t0 = now_utc()
    assert lab.worker(now=t0)["sync"] == {"succeeded": 2}
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE report_schedules SET next_run_at = now() - interval '1 minute'")
        )
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    # The run queued before the closure is cancelled, as for a closing agency (017-A).
    assert lab.worker(now=t0 + timedelta(minutes=1))["sync"] == {"canceled": 1}
    for stage in ("closed", "offboarded", "purged"):
        if stage == "offboarded":
            run_offboarding(w.db.runtime, lab.config)
        if stage == "purged":
            lab.worker(now=t0 + timedelta(minutes=2), schedule=False)
            assert _purge(lifecycle_engine, lifecycle_settings)["deleted"]["agencies_purged"] == 1
        later = t0 + timedelta(hours=25 * (1 + ["closed", "offboarded", "purged"].index(stage)))
        result = lab.worker(now=later, schedule=True)
        # Only agency B's connection is scheduled and synchronized.
        assert result["schedule"] == {"queued": 1} and result["sync"] == {"succeeded": 1}
        assert attribution_store.run_pass(w.db.runtime)["clients"] == 2
        assert report_schedules.run_pass(w.db.runtime, lab.config, {})["due"] == 0
    assert run_offboarding(w.db.runtime, lab.config)["offboarded"] == 0
    runs = _all(w.db, select(ConnectorSyncRun.status).where(ConnectorSyncRun.connection_id == k3))
    assert runs.count("succeeded") == 4
    assert _all(w.db, select(ReportSchedule)) == []


def test_ov15_delivery_worker_skips_a_closed_agency(
    capi, api, lifecycle_engine, lifecycle_settings
):
    capi.api_new_client = lambda: api.new_client(capi.config)
    _, _, token = _setup(capi)
    records, journeys = _sale(capi, token)
    assert _enqueue(capi, candidates_from_ledger(calculate(records), journeys)) == {"queued": 1}
    close_agency(capi.w, api, lifecycle_engine, lifecycle_settings, capi.w.a)
    assert _deliver(capi) == {}
    assert [row.status for row in _rows(capi)] == ["queued"]
    records, journeys = _sale(capi, token, "sale-2")
    assert _enqueue(capi, candidates_from_ledger(calculate(records), journeys)) == {
        "client_inactive": 1
    }


def test_ov16_operator_command_status_and_run(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a), connection_id=k1)
    registry = {"synthetic": lab.provider}
    budget = lifecycle_settings.lifecycle_batch_size
    with pytest.raises(command.Refused) as active:
        command.run(w.db.runtime, lifecycle_engine, lab.config, budget, registry, w.a)
    assert (active.value.code, active.value.detail) == ("agency_not_closed", {"status": "active"})
    with pytest.raises(command.Refused) as unknown:
        command.status(w.db.runtime, uuid4())
    assert unknown.value.code == "agency_not_found"
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    before = command.status(w.db.runtime, w.a)
    assert (before["status"], before["offboarding"], before["purged_at"]) == ("closed", None, None)
    assert before["connections"] == {
        "live": 1,
        "disconnecting": 0,
        "past_deadline": 0,
        "disconnected": 0,
    }
    assert before["closure"]["completed_at"] is not None
    result = command.run(w.db.runtime, lifecycle_engine, lab.config, budget, registry, w.a)
    assert result["offboarding"]["state"] == "completed"
    assert result["offboarding"]["connections_disconnected"] == 1
    assert result["teardown"] == {"disconnected": 1}
    assert result["purge"]["outcome"] == "purged" and result["purge"]["state"] == "purged"
    assert result["purge"]["deleted_rows"] > 0
    after = command.status(w.db.runtime, w.a)
    assert after["offboarding"]["state"] == "purged" and after["purged_at"] is not None
    assert after["offboarding"]["deleted_rows"] == result["purge"]["deleted_rows"]
    assert after["connections"] == dict.fromkeys(
        ("live", "disconnecting", "past_deadline", "disconnected"), 0
    )
    assert after["closure"]["completed_at"] == before["closure"]["completed_at"]
    again = command.run(w.db.runtime, lifecycle_engine, lab.config, budget, registry, w.a)
    assert again["offboarding"] == {"state": "already_completed"} and again["teardown"] == {}
    assert again["purge"] == {"outcome": "purged", "state": "purged", "deleted_rows": 0}
    output = json.dumps([before, result, after, again])
    for secret in (NAMES["a"], "Synthetic Client", "example.test", "syn-acct", "Synthetic"):
        assert secret not in output
    # The command runs as its own process; run without --confirm exits with 2 before connecting.
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    shown = subprocess.run(
        [sys.executable, "-m", "app.agency_offboarding", "status", "--agency", str(w.a)],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout.strip().splitlines()[-1])["offboarding"]["state"] == "purged"
    refused = subprocess.run(
        [sys.executable, "-m", "app.agency_offboarding", "run", "--agency", str(w.a)],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert refused.returncode == 2 and "--confirm is required" in refused.stderr
