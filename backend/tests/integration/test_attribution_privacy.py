"""008-B privacy, retention and freshness on disposable PostgreSQL (D-079).

Cases AV08, AV09, AV10, AV15, AV17 and AV20 of the 008-B verification matrix, and the
erasure-after-snapshot case of AV11. Withdrawals remove touches from new revisions; erasure,
expiry and the deletion of a person scrub every identifying pointer in the removal transaction
while shares, amounts and provenance stay; a replay never restores a pointer; marked events
never become touches; clients never mix; the lifecycle discards failed staging rows without
touching money; and a person-level read is refused while it could be stale. Synthetic values
only.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from uuid import UUID, uuid4

import pytest
from attribution_support import FIRST, LAST, LINEAR, make_attribution_world
from identity_support import ATTRIBUTION, IDENTITY, make_identity_world, rows
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_review_006_007 import age_identity_evidence

from app.attribution import AttributionInputError
from app.config import BACKEND_ROOT
from app.ledger import OperationKind
from app.models import (
    AttributionConsumerState,
    AttributionConversion,
    IdentitySubject,
    SubjectDeletionRequest,
)
from app.services import attribution_reads as reads
from app.services import attribution_store as store
from app.services.attribution_models import AttributionError
from app.services.lifecycle import run_lifecycle
from app.services.reporting import report_snapshot
from app.services.tenancy import AccessDenied

pytestmark = pytest.mark.integration
ONE = Fraction(1)
HALF = Fraction(1, 2)
TABLES = (
    "attribution_model_versions",
    "attribution_conversions",
    "attribution_runs",
    "attribution_allocations",
    "attribution_credit_changes",
    "attribution_consumer_state",
)
# The columns that must never change once written: money, shares, dates and provenance.
KEPT = {
    "attribution_runs": (
        "revision, status, basis, causes, currency, currency_exponent, verified_net_minor, "
        "window_start, window_end, excluded_reasons, cardinality(excluded_touchpoint_ids)"
    ),
    "attribution_allocations": (
        "ordinal, credited, recipient, basis, position, share_numerator, share_denominator, "
        "amount_minor, evidence_class, source, campaign_ref, content_ref, link_ref"
    ),
    "attribution_credit_changes": (
        "ordinal, conversion_kind, effective_at, recipient, source, campaign_ref, content_ref, "
        "link_ref, delta_share_numerator, delta_share_denominator, delta_minor, currency"
    ),
}


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def dump(aw, client=None) -> str:
    """Every stored attribution row of a client as text, for value scans."""
    parts: list[str] = []
    with aw.w.db.migration.connect() as connection:
        for table in TABLES:
            parts += connection.execute(
                text(f"SELECT row_to_json(t)::text FROM {table} t WHERE client_id = :c"),
                {"c": client or aw.w.a1},
            ).scalars()
    return "\n".join(parts)


def kept(aw, client=None) -> dict:
    with aw.w.db.migration.connect() as connection:
        return {
            table: {
                row[0]: tuple(tuple(v) if isinstance(v, list) else v for v in row[1:])
                for row in connection.execute(
                    text(f"SELECT id, {columns} FROM {table} WHERE client_id = :c"),
                    {"c": client or aw.w.a1},
                )
            }
            for table, columns in KEPT.items()
        }


def assert_kept(before: dict, after: dict) -> None:
    for table, stored in before.items():
        for identifier, values in stored.items():
            assert after[table][identifier] == values, table


def journey(aw, email="buyer@example.test", campaigns=("spring", "autumn")):
    """A person with touches, an associated sale that takes effect in an hour and a lead."""
    buyer = aw.person(email)
    events = [aw.touch(buyer.token, campaign) for campaign in campaigns]
    return buyer, events


def later() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def test_av08_withdrawals_remove_touches_from_new_revisions(aw):
    buyer, (first, second) = journey(aw)
    lead = aw.lead(buyer.token, at=datetime.now(UTC) + timedelta(seconds=30))
    aw.sale("S1", 10_000, when=later())
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    lead_conversion = aw.conversion(event=lead)
    assert aw.credit(aw.latest(lead_conversion.id)[LINEAR]) == {
        "spring": (HALF, None),
        "autumn": (HALF, None),
    }
    # Attribution withdrawal: the next pass removes the touches and the sale loses its owner.
    aw.consent(buyer.token, ATTRIBUTION, "withdrawn")
    totals = aw.settle()
    assert totals["superseded"] == 1 and totals["opened"] == 1
    assert aw.conversion("S1").owner_person_id is None
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"unknown": (ONE, 10_000)}
    revisions = aw.revisions(lead_conversion.id, LINEAR)
    assert [item.revision for item in revisions] == [1, 2]
    assert revisions[1].causes == ("touches_changed",)
    assert aw.credit(revisions[1]) == {"unknown": (ONE, None)}
    assert sorted(revisions[1].excluded) == sorted(
        [(first, "consent_not_granted"), (second, "consent_not_granted")]
    )
    # A withdrawal scrubs nothing: the earlier revision keeps its touches.
    assert [row.touchpoint_id for row in revisions[0].allocations] == [first, second]
    aw.assert_fresh()
    # A new grant restores the touches of the lead; the sale needs a new association.
    aw.consent(buyer.token, ATTRIBUTION, "granted")
    aw.settle()
    assert aw.credit(aw.revisions(lead_conversion.id, LINEAR)[-1]) == {
        "spring": (HALF, None),
        "autumn": (HALF, None),
    }
    assert aw.conversion("S1").owner_person_id is None
    aw.assert_fresh()
    # W1: withdrawing identity_link removes the person, whose conversions are scrubbed.
    before = kept(aw)
    aw.consent(buyer.token, IDENTITY, "withdrawn")
    assert rows(aw.w.db, select(IdentitySubject.id)) == []
    stored = dump(aw)
    assert str(buyer.id) not in stored and str(lead) not in stored
    assert_kept(before, kept(aw))
    totals = aw.settle()
    assert totals["superseded"] == 1 and not totals["opened"]
    closed = [row for row in aw.conversions(every=True) if row.kind == "lead"]
    assert [(row.status, row.superseded_reason) for row in closed] == [("superseded", "scrubbed")]
    assert aw.ledger(LINEAR, conversion_id=lead_conversion.id) == {}
    aw.assert_fresh()


def test_av08_a_surviving_person_keeps_its_history_after_w1(aw):
    buyer = aw.person("two@example.test")
    phone = aw.idw.browser_subject()["subject_token"]
    aw.link(phone, "two@example.test")  # a second device of the same person
    desktop_touch = aw.touch(buyer.token, "spring")
    phone_touch = aw.touch(phone, "autumn")
    lead = aw.lead(buyer.token, at=datetime.now(UTC) + timedelta(seconds=30))
    aw.settle()
    conversion = aw.conversion(event=lead)
    aw.consent(phone, IDENTITY, "withdrawn")
    assert rows(aw.w.db, select(IdentitySubject.id)) == [buyer.id]
    aw.settle()
    revisions = aw.revisions(conversion.id, LINEAR)
    assert [row.touchpoint_id for row in revisions[0].allocations] == [desktop_touch, phone_touch]
    assert [row.touchpoint_id for row in revisions[1].allocations] == [desktop_touch]
    assert aw.conversion(event=lead).id == conversion.id  # the same conversion, a new revision
    aw.assert_fresh()


def test_av08_erasure_and_expiry_scrub_every_pointer(aw, lifecycle_engine, lifecycle_settings):
    w = aw.w
    erased, erased_events = journey(aw, "erased@example.test")
    lead = aw.lead(erased.token, at=datetime.now(UTC) + timedelta(seconds=30))
    aw.sale("S1", 10_000, when=later())
    aw.associate(erased.assertion, "S1")
    expiring, expiring_events = journey(aw, "expiring@example.test", campaigns=("winter",))
    aw.sale("S2", 4_000, when=later())
    aw.associate(expiring.assertion, "S2")
    aw.settle()
    before = kept(aw)
    stored = dump(aw)
    assert str(erased.id) in stored and str(expiring.id) in stored
    # Erasure: the scrub runs in the erasure transaction, before any worker pass.
    result = aw.erase(erased.id)
    request = rows(w.db, select(SubjectDeletionRequest))[0]
    assert request.target_outcomes["attribution"] == "done", result
    stored = dump(aw)
    for pointer in (erased.id, lead, *erased_events):
        assert str(pointer) not in stored
    assert str(expiring.id) in stored  # another person is untouched
    assert_kept(before, kept(aw))
    scrubbed = [row for row in aw.conversions() if row.scrubbed_at is not None]
    assert len(scrubbed) == 2
    for row in scrubbed:
        assert row.owner_person_id is None and row.lead_event_id is None
        assert row.conversion_key == f"scrubbed.{row.id}"
        for key in (FIRST, LAST, LINEAR):
            (values,) = aw.revisions(row.id, key)
            assert all(item.touchpoint_id is None for item in values.allocations)
            assert all(item.occurred_at is None for item in values.allocations)
            assert {item.campaign_ref for item in values.allocations} == {"spring", "autumn"}
    # The next pass supersedes the scrubbed conversions; the sale now credits unknown.
    totals = aw.settle()
    assert totals["superseded"] == 2 and totals["opened"] == 1
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"unknown": (ONE, 10_000)}
    assert sum(minor for _, minor in aw.ledger(LINEAR).values()) == 14_000
    assert_kept(before, kept(aw))
    aw.assert_fresh()
    # Expiry: the lifecycle role scrubs when the person's evidence expires.
    age_identity_evidence(w.db, expiring.id)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed", result
    assert rows(w.db, select(IdentitySubject.id)) == []
    stored = dump(aw)
    for pointer in (expiring.id, *expiring_events):
        assert str(pointer) not in stored
    assert_kept(before, kept(aw))
    aw.settle()
    assert aw.credit(aw.latest(aw.conversion("S2").id)[LINEAR]) == {"unknown": (ONE, 4_000)}
    assert sum(minor for _, minor in aw.ledger(LINEAR).values()) == 14_000
    assert {
        row.superseded_reason for row in aw.conversions(every=True) if row.status == "superseded"
    } == {"scrubbed"}
    aw.assert_fresh()


def test_av08_a_replay_after_erasure_restores_no_pointer(aw):
    buyer, events = journey(aw)
    aw.sale("S1", 10_000, when=later())
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    aw.erase(buyer.id)
    aw.settle()
    pointers = [str(buyer.id), *(str(event) for event in events)]
    # The old association request and assertion are replayed; passes and a rebuild follow.
    response = aw.idw.ingest.post(
        f"{aw.idw.base}/clients/{aw.w.a1}/revenue/identity-associations",
        json={
            "request_id": str(uuid4()),
            "source_account_id": "shop",
            "sale_operation_id": "S1",
            "assertion_id": str(buyer.assertion),
            "expected_revision": None,
        },
    )
    assert response.status_code in {200, 201, 409}
    aw.settle()
    created = aw.idw.owner.post(
        f"/agencies/{aw.w.a}/clients/{aw.w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7},
    )
    assert created.status_code == 201
    assert aw.settle()["rebuilds"] == 1
    for _ in range(2):
        aw.run()
    stored = dump(aw)
    assert not [pointer for pointer in pointers if pointer in stored]
    assert aw.conversion("S1").owner_person_id is None
    aw.assert_fresh()


def test_av11_an_erasure_after_the_snapshot_is_never_restored(aw):
    buyer, events = journey(aw)
    aw.sale("S1", 10_000, when=later())
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    events.append(aw.touch(buyer.token, "winter"))  # pending work naming the person
    outer = aw.run(hook=lambda stage: aw.erase(buyer.id))
    # The worker calculated from a snapshot that still held the person: its swap fails.
    assert outer["outcome"] == "conflict" and not outer.get("revisions")
    stored = dump(aw)
    assert not [item for item in (buyer.id, *events) if str(item) in stored]
    aw.settle()
    stored = dump(aw)
    assert not [item for item in (buyer.id, *events) if str(item) in stored]
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"unknown": (ONE, 10_000)}
    aw.assert_fresh()


def test_av09_marked_events_never_become_touches(aw):
    buyer, (first, second) = journey(aw)
    third = aw.touch(buyer.token, "winter")
    with aw.w.db.runtime.begin() as connection:
        connection.execute(
            text("UPDATE collected_events SET identity_excluded_at = now() WHERE event_id = :e"),
            {"e": second},
        )
    aw.sale("S1", 9_000, when=later())
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    conversion = aw.conversion("S1")
    values = aw.latest(conversion.id)[LINEAR]
    assert [row.touchpoint_id for row in values.allocations] == [first, third]
    assert second not in {touch for touch, _ in values.excluded}
    assert str(second) not in dump(aw)
    # An event marked later leaves the journey at the next verification, without a feed record.
    with aw.w.db.runtime.begin() as connection:
        connection.execute(
            text("UPDATE collected_events SET identity_excluded_at = now() WHERE event_id = :e"),
            {"e": third},
        )
    result = aw.run()
    assert result["outcome"] == "caught_up" and result["revisions"] == 3
    values = aw.latest(conversion.id)[LINEAR]
    assert [row.touchpoint_id for row in values.allocations] == [first]
    assert values.causes == ("touches_changed",)
    aw.assert_fresh()


def test_av10_identical_references_in_two_clients_never_mix(
    aw, lifecycle_engine, lifecycle_settings
):
    w = aw.w
    people, events = {}, {}
    for client in (w.a1, w.a2):
        people[client] = aw.person("same@example.test", client=client)
        events[client] = [
            aw.touch(people[client].token, campaign, client=client)
            for campaign in ("spring", "autumn")
        ]
        aw.sale("S1", 10_000 if client == w.a1 else 6_000, when=later(), client=client)
        aw.associate(people[client].assertion, "S1", client=client)
    result = store.run_pass(w.db.runtime)
    assert result["opened"] == 2 and result["caught_up"] == 4
    assert people[w.a1].id != people[w.a2].id
    for client, net in ((w.a1, 10_000), (w.a2, 6_000)):
        conversion = aw.conversion("S1", client=client)
        assert conversion.owner_person_id == people[client].id
        values = aw.latest(conversion.id, client)[LINEAR]
        assert [row.touchpoint_id for row in values.allocations] == events[client]
        assert aw.ledger(LINEAR, client) == {
            ("spring", "EGP"): (HALF, net // 2),
            ("autumn", "EGP"): (HALF, net // 2),
        }
        other = w.a2 if client == w.a1 else w.a1
        stored = dump(aw, client)
        assert str(people[other].id) not in stored
        assert not [event for event in events[other] if str(event) in stored]
        aw.assert_fresh(client)
    # An erasure, a pass and a lifecycle run in one client leave the other byte-identical.
    untouched = (aw.snapshot(w.a2), aw.state(w.a2).version)
    aw.erase(people[w.a1].id)
    aw.settle()
    assert run_lifecycle(lifecycle_engine, lifecycle_settings)["status"] == "completed"
    assert (aw.snapshot(w.a2), aw.state(w.a2).version) == untouched
    assert aw.conversion("S1", client=w.a2).owner_person_id == people[w.a2].id
    assert aw.conversion("S1").owner_person_id is None


def test_av15_lifecycle_scrubs_and_discards_without_touching_money(
    aw, lifecycle_engine, lifecycle_settings, monkeypatch
):
    w = aw.w
    buyer, _ = journey(aw)
    for operation in ("S1", "S2", "S3"):
        aw.sale(operation, 5_000, when=later())
        aw.associate(buyer.assertion, operation)
    aw.settle()
    published = aw.snapshot()
    money = kept(aw)
    # A rebuild that supersedes two conversions fails at its last chunk.
    aw.detach("S1")
    aw.detach("S2")
    created = aw.idw.owner.post(
        f"/agencies/{w.a}/clients/{w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7},
    )
    assert created.status_code == 201
    monkeypatch.setattr(store, "CHUNK_LIMIT", 1)
    calls = []

    def refuse_last(stage):
        calls.append(stage)
        if len(calls) == 3:
            raise AttributionInputError("revision_mismatch")

    assert aw.run(hook=refuse_last)["outcome"] == "failed"
    state = aw.state()
    assert (state.status, state.failure_code, state.staging_generation) == (
        "failed",
        "revision_mismatch",
        2,
    )
    staged = [row for row in aw.conversions(every=True) if row.superseded_generation == 2]
    assert staged and all(row.status == "active" for row in staged)  # invisible supersessions
    assert aw.run() == {"outcome": "failed"}  # the worker waits for the lifecycle
    # A conversion whose owner no longer exists is scrubbed by the safety net.
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE attribution_conversions SET owner_person_id = :ghost "
                "WHERE client_id = :c AND sale_operation_id = 'S3' AND generation = 1"
            ),
            {"ghost": uuid4(), "c": w.a1},
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed", result
    assert result["deleted"]["attribution_staging"] >= 2
    assert result["deleted"]["attribution_scrubbed"] == 1
    state = aw.state()
    assert (state.status, state.failure_code, state.unit_kind, state.staging_generation) == (
        "ready",
        None,
        None,
        None,
    )
    assert state.generation == 1
    after = aw.snapshot()
    for table in ("attribution_runs", "attribution_allocations", "attribution_credit_changes"):
        # Exactly the published rows remain (the first column is the row ID).
        assert {row[0] for row in after[table]} == {row[0] for row in published[table]}, table
    assert not [row for row in aw.conversions(every=True) if row.superseded_generation]
    assert_kept(money, kept(aw))
    # A second run finds nothing, and the worker then rebuilds from the published state.
    again = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert "attribution_staging" not in again["deleted"]
    assert "attribution_scrubbed" not in again["deleted"]
    monkeypatch.setattr(store, "CHUNK_LIMIT", 200)
    totals = aw.settle()
    assert totals["rebuilds"] == 1 and aw.state().generation == 2
    assert sum(minor for _, minor in aw.ledger(LINEAR).values()) == 15_000
    assert_kept(money, kept(aw))
    aw.assert_fresh()


def read(aw, conversion_id, version=None, *, finance=True, client=None):
    with report_snapshot(aw.w.db.runtime) as session:
        return reads.runs(
            session, aw.w.a, client or aw.w.a1, conversion_id, version, finance=finance
        )


def status(aw, client=None):
    with report_snapshot(aw.w.db.runtime) as session:
        return reads.status(session, aw.w.a, client or aw.w.a1)


def assert_stale(aw, conversion_id):
    with pytest.raises(AttributionError) as caught:
        read(aw, conversion_id)
    assert (caught.value.code, caught.value.status) == ("attribution_stale", 503)


def test_av17_stale_while_behind_then_released(aw):
    w = aw.w
    assert status(aw)["state"] == "rebuilding"
    buyer, _ = journey(aw)
    aw.sale("S1", 10_000, when=later())
    aw.associate(buyer.assertion, "S1")
    with pytest.raises(AccessDenied):
        read(aw, uuid4())
    aw.settle()
    conversion = aw.conversion("S1")
    body = read(aw, conversion.id)
    assert status(aw)["state"] == "caught_up"
    assert [run["revision"] for run in body["runs"]] == [1]
    assert body["model_version"]["version_key"] == LINEAR  # the client's default
    assert body["conversion"]["person_id"] == str(buyer.id)
    # A new touch: the feed is ahead of the checkpoint.
    aw.touch(buyer.token, "winter")
    report = status(aw)
    assert report["state"] == "behind"
    assert report["consumer"]["identity_seq"] < report["current"]["identity_seq"]
    assert_stale(aw, conversion.id)
    aw.settle()
    assert [run["revision"] for run in read(aw, conversion.id)["runs"]] == [1, 2]
    # A refund: the ledger is ahead of the checkpoint.
    aw.sale("R1", 2_000, kind=OperationKind.REFUND, parent="S1")
    report = status(aw)
    assert report["state"] == "behind"
    assert report["consumer"]["receipt_ordinal"] < report["current"]["receipt_ordinal"]
    assert_stale(aw, conversion.id)
    aw.settle()
    body = read(aw, conversion.id)
    assert [run["verified_net_minor"] for run in body["runs"]] == [10_000, 10_000, 8_000]
    report = status(aw)
    assert report["state"] == "caught_up"
    assert report["consumer"]["receipt_ordinal"] == report["current"]["receipt_ordinal"] == 2
    assert report["consumer"]["model_set_current"] is True
    # A consent that lapsed moves no watermark: the read recalculates and refuses.
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE consent_records SET expires_at = now() - interval '1 second' "
                "WHERE client_id = :c AND purpose = 'attribution'"
            ),
            {"c": w.a1},
        )
    assert status(aw)["state"] == "caught_up"
    assert_stale(aw, conversion.id)
    aw.settle()
    # The association no longer qualifies: the conversion is history, its successor unknown.
    body = read(aw, conversion.id)
    assert body["conversion"]["status"] == "superseded"
    assert body["runs"][-1]["status"] == "superseded"
    successor = aw.conversion("S1")
    assert read(aw, successor.id)["conversion"]["person_id"] is None
    # A detach is a pending association change: stale until the pass applies it.
    other, _ = journey(aw, "other@example.test", campaigns=("spring",))
    aw.sale("S2", 3_000, when=later())
    aw.associate(other.assertion, "S2")
    aw.settle()
    owned = aw.conversion("S2")
    assert read(aw, owned.id)["conversion"]["person_id"] == str(other.id)
    aw.detach("S2")
    assert status(aw)["state"] == "behind"
    assert_stale(aw, owned.id)
    aw.settle()
    assert read(aw, owned.id)["conversion"]["superseded_reason"] == "owner_changed"
    # A new model version: rebuilding until its history is published.
    created = aw.idw.owner.post(
        f"/agencies/{w.a}/clients/{w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7},
    )
    assert created.status_code == 201
    assert status(aw)["consumer"]["model_set_current"] is False
    assert_stale(aw, successor.id)
    aw.settle()
    body = read(aw, successor.id, UUID(created.json()["id"]))
    assert [run["revision"] for run in body["runs"]] == [1]
    # Without finance access a sale's amounts and transaction answer permission_unavailable.
    hidden = read(aw, successor.id, finance=False)
    assert hidden["conversion"]["transaction"] == {
        "state": "permission_unavailable",
        "source_account_id": None,
        "sale_operation_id": None,
    }
    run = hidden["runs"][0]
    assert (run["amounts"], run["verified_net_minor"], run["currency"]) == (
        "permission_unavailable",
        None,
        None,
    )
    assert all(item["amount_minor"] is None for item in run["allocations"])
    assert all(item["delta_minor"] is None for item in run["differences"])
    assert run["allocations"][0]["share"] == {"numerator": 1, "denominator": 1}


def test_av20_no_contact_value_token_or_identifier_in_rows_responses_or_logs(aw, caplog):
    w = aw.w
    emails = ("values@example.test", "second@example.test")
    buyer = aw.person(emails[0])
    other = aw.person(emails[1])
    for person in (buyer, other):
        aw.touch(person.token, "spring")
        aw.lead(person.token, at=datetime.now(UTC) + timedelta(seconds=30))
    aw.sale("S1", 10_000, when=later())
    aw.associate(buyer.assertion, "S1")
    caplog.clear()
    environment = {**os.environ}
    completed = subprocess.run(
        [sys.executable, "-m", "app.attribution_worker"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    counts = json.loads(completed.stdout)
    assert counts["clients"] == 4 and counts["opened"] == 3
    assert all(isinstance(value, int) for value in counts.values())
    aw.erase(other.id)
    aw.settle()
    bodies = [json.dumps(status(aw))]
    for row in aw.conversions(every=True):
        bodies.append(json.dumps(read(aw, row.id)))
    secrets = [
        *emails,
        buyer.token,
        other.token,
        aw.idw.ingest.headers["Authorization"].removeprefix("Bearer "),
    ]
    stored = dump(aw)
    for value in secrets:
        assert value not in stored
        assert all(value not in body for body in bodies)
        assert value not in completed.stdout and value not in completed.stderr
        assert value not in caplog.text
    # Rows hold pseudonymous IDs only; the worker output and the logs hold none at all.
    identifiers = [str(buyer.id), str(other.id), str(buyer.assertion)]
    identifiers += [str(row.id) for row in aw.conversions(every=True)]
    for value in identifiers:
        assert value not in completed.stdout and value not in completed.stderr
        assert value not in caplog.text
    assert str(other.id) not in stored and str(buyer.id) in stored
    with Session(w.db.migration) as session:
        columns = {
            column.name
            for model in (AttributionConversion, AttributionConsumerState)
            for column in model.__table__.columns
        }
        assert session.scalar(select(AttributionConversion.id).limit(1)) is not None
    assert not {"email", "subject_token", "token_digest", "identifier", "key_bytes"} & columns
