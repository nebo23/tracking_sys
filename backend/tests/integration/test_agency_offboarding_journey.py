"""The full offboarding journey, concurrency and logs (017-B, D-098; OV17, OV19 and P4).

One end-to-end journey requests the closure, requests and downloads the export, completes the
closure, offboards the agency, settles its teardown at the synthetic provider, purges it with
the lifecycle command and checks what stays. The concurrency cases race the completion with an
export build, two offboarding workers with each other, and the purge with a late teardown and
late writes. Every log line and output is checked for names, figures, tokens and file content.
Synthetic data and the disposable database only.
"""

import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from uuid import UUID, uuid4

import pytest
from attribution_support import make_attribution_world
from connector_support import make_lab
from identity_support import make_identity_world
from offboarding_support import (
    NAMES,
    branding,
    close_agency,
    end_grace_period,
    owner_membership,
    populate_direct,
    request_closure,
    rows_of,
)
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import agency_offboarding as command
from app.config import BACKEND_ROOT
from app.models import Agency, AgencyExport, AgencyExportPart, AgencyPurge, ConnectorConnection
from app.services import agency_exports, agency_lifecycle, agency_offboarding
from app.services.agency_exports import build_pending
from app.services.agency_offboarding import run_offboarding
from app.services.agency_purge import purge_agency
from app.services.connectors import run_teardowns
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
KEPT = {"agency_plan_assignments", "agency_purges"}
FIGURE = 987_654  # a distinctive sale amount in minor units, never printed or logged
# The amount as a number of its own, not as part of a hexadecimal digest or an identifier.
FIGURE_PATTERN = re.compile(r"(?<![0-9a-fA-F])987654(?![0-9a-fA-F])")


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def _get(db, model, key):
    with Session(db.migration) as session:
        return session.get(model, key)


def _leftover(db, agency, clients) -> dict[str, int]:
    return {
        table: count
        for table, count in rows_of(db, agency, clients).items()
        if count and table not in KEPT
    }


def _export_request(w, api, agency=None, owner="owner_a") -> UUID:
    response = w.signed_in(owner).post(
        f"/agencies/{agency or w.a}/closure/export", json={"password": api.password}
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["export"]["id"])


def _wait_for_lock_wait(db, timeout: float = 2.5) -> None:
    deadline = time.monotonic() + timeout
    with db.migration.connect() as connection:
        while time.monotonic() < deadline:
            if connection.execute(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            ).scalar_one():
                return
            time.sleep(0.02)
    raise AssertionError("No transaction waited for a lock.")


class Pause:
    """Stops the first call of a wrapped function until released, from another thread."""

    def __init__(self) -> None:
        self.entered, self.release, self.calls = threading.Event(), threading.Event(), 0

    def wrap(self, function):
        def wrapped(*args, **kwargs):
            result = function(*args, **kwargs)
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                assert self.release.wait(10), "never released"
            return result

        return wrapped


class Run(threading.Thread):
    """A thread that keeps its target's result or exception."""

    def __init__(self, target, *args) -> None:
        super().__init__(daemon=True)
        self.target_function, self.arguments = target, args
        self.result, self.error = None, None

    def run(self) -> None:
        try:
            self.result = self.target_function(*self.arguments)
        except BaseException as error:  # noqa: BLE001 - reported by the test
            self.error = error

    def outcome(self):
        self.join(20)
        assert not self.is_alive(), "the thread did not finish"
        if self.error is not None:
            raise self.error
        return self.result


def _private(w, api, tokens: dict[str, str]) -> tuple[str, ...]:
    return (
        NAMES["a"],
        NAMES["b"],
        "Synthetic Client",
        "Synthetic brand",
        "@example.test",
        api.password,
        "tracking_session=",
        "9876.54",
        "clients/",
        '"event_type"',
        "syn-acct",
        *tokens.values(),
    )


def test_journey_export_completion_offboarding_teardown_purge(
    lab, api, lifecycle_engine, lifecycle_settings, tmp_path, capfd
):
    w = lab.w
    aw = make_attribution_world(make_identity_world(w, api))
    alice = aw.person("alice@example.test")
    aw.touch(alice.token, "spring")
    aw.lead(alice.token)
    aw.sale("op-3001", FIGURE)
    aw.associate(alice.assertion, "op-3001")
    aw.settle()
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    member = owner_membership(w.db, w.a)
    populate_direct(w.db, w.a, w.a1, member, connection_id=k1)
    branding(w.db, w.a, member)
    lab.connect("owner_b", w.b, w.b1, account="syn-acct-b1")
    assert set(lab.worker()["sync"]) == {"succeeded"}
    tokens = lab.tokens(k1)
    assert tokens
    b_before = rows_of(w.db, w.b, [w.b1, w.b2])
    outputs = []
    # 1. The Owner requests the closure, then the export, which the worker builds.
    request_closure(w, api, w.a)
    export_id = _export_request(w, api)
    outputs.append(build_pending(w.db.runtime, api.config))
    assert outputs[-1]["built"] == 1
    # 2. The Owner downloads it: one ZIP, byte for byte the stored one.
    owner = w.signed_in("owner_a")
    downloaded = owner.get(f"/agencies/{w.a}/closure/export/download")
    assert downloaded.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(downloaded.content))
    assert archive.testzip() is None
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["total_rows"] == _get(w.db, AgencyExport, export_id).row_count > 0
    outputs.append(owner.get(f"/agencies/{w.a}/closure/export").json())
    # 3. The grace period ends and the lifecycle runner completes the closure.
    end_grace_period(w.db, w.a)
    outputs.append(run_lifecycle(lifecycle_engine, lifecycle_settings))
    assert outputs[-1]["deleted"]["agency_closures_completed"] == 1
    # 4. The offboarding pass disconnects, revokes and disables (D6).
    outputs.append(run_offboarding(w.db.runtime, lab.config))
    assert outputs[-1]["connections_disconnected"] == 1
    outputs.append(command.status(w.db.runtime, w.a))
    assert outputs[-1]["offboarding"]["state"] == "waiting"
    # 5. The connector worker settles the teardown: the provider receives the revocation.
    outputs.append(lab.worker())
    assert outputs[-1]["teardown"] == {"disconnected": 1}
    assert lab.provider.grants() == [("syn-acct-a1", True), ("syn-acct-b1", False)]
    assert all(not lab.provider.token_usable(token) for token in tokens.values())
    # 6. The lifecycle command purges the agency (as its own process, as tracking_lifecycle).
    environment = {
        **os.environ,
        "TRACKING_MAIL_DIRECTORY": str(tmp_path / "lifecycle-mail"),
        "PYTHONIOENCODING": "utf-8",
    }
    purged = subprocess.run(
        [sys.executable, "-m", "app.lifecycle"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert purged.returncode == 0, purged.stderr
    result = json.loads(purged.stdout.strip().splitlines()[-1])
    assert result["deleted"]["agencies_purged"] == 1, result
    shown = subprocess.run(
        [sys.executable, "-m", "app.agency_offboarding", "status", "--agency", str(w.a)],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert shown.returncode == 0, shown.stderr
    status = json.loads(shown.stdout.strip().splitlines()[-1])
    # 7. What stays: the agency row with a pseudonym, its plan history and the purge record.
    assert _leftover(w.db, w.a, [w.a1, w.a2]) == {}
    agency = _get(w.db, Agency, w.a)
    assert (agency.status, agency.name) == ("closed", f"Closed agency {w.a}")
    record = _get(w.db, AgencyPurge, w.a)
    assert record.state == "purged"
    assert record.export_summary["status"] == "ready"
    assert record.export_summary["download_count"] == 1
    assert sum(record.deleted_counts.values()) == result["deleted"]["agency_rows_purged"]
    assert status["offboarding"]["deleted_rows"] == result["deleted"]["agency_rows_purged"]
    assert rows_of(w.db, w.b, [w.b1, w.b2]) == b_before
    # OV19: no name, figure, token or file content in any log line or output.
    captured = capfd.readouterr()
    printed = json.dumps(outputs) + purged.stdout + purged.stderr + shown.stdout + shown.stderr
    for private in _private(w, api, tokens):
        assert private not in printed, private
        assert private not in captured.out + captured.err, private
    for value in (printed, captured.out + captured.err):
        assert not FIGURE_PATTERN.search(value)


def test_ov17_completion_against_an_export_build(
    authenticated_world, api, lifecycle_engine, lifecycle_settings, monkeypatch
):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    populate_direct(
        w.db,
        w.b,
        w.b1,
        owner_membership(w.db, w.b),
        phone="2010002",
        hostname="go.agency-b.example.test",
    )
    # The store holds agency A's lock: the completion batch cannot take it and stays
    # incomplete; the export becomes ready while A is still closing.
    request_closure(w, api, w.a)
    first = _export_request(w, api)
    pause = Pause()
    monkeypatch.setattr(agency_exports, "seal_bytes", pause.wrap(agency_exports.seal_bytes))
    builder = Run(build_pending, w.db.runtime, api.config)
    builder.start()
    assert pause.entered.wait(20)
    end_grace_period(w.db, w.a)
    blocked = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert "agency_closures" in blocked["incomplete"]
    assert _get(w.db, Agency, w.a).status == "closing"
    pause.release.set()
    assert builder.outcome()["built"] == 1
    monkeypatch.undo()
    ready = _get(w.db, AgencyExport, first)
    completed = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert completed["deleted"]["agency_closures_completed"] == 1
    with Session(w.db.migration) as session:
        closure_end = session.scalar(text("SELECT completed_at FROM agency_closures"))
    assert ready.status == "ready" and ready.ready_at < closure_end
    # The completion holds agency B's lock: the store waits for it, then discards the export.
    request_closure(w, api, w.b, owner="owner_b")
    second = _export_request(w, api, agency=w.b, owner="owner_b")
    end_grace_period(w.db, w.b)
    hold = Pause()
    monkeypatch.setattr(
        agency_lifecycle, "complete_closures", hold.wrap(agency_lifecycle.complete_closures)
    )
    completion = Run(run_lifecycle, lifecycle_engine, lifecycle_settings)
    completion.start()
    assert hold.entered.wait(20)
    builder = Run(build_pending, w.db.runtime, api.config)
    builder.start()
    _wait_for_lock_wait(w.db)
    hold.release.set()
    assert completion.outcome()["deleted"]["agency_closures_completed"] == 1
    assert builder.outcome()["discarded"] == 1
    failed = _get(w.db, AgencyExport, second)
    assert (failed.status, failed.error_code) == ("failed", "closure_completed")
    with Session(w.db.migration) as session:
        assert (
            session.scalars(
                select(AgencyExportPart).where(AgencyExportPart.export_id == second)
            ).all()
            == []
        )


def test_ov17_two_offboarding_workers(lab, api, lifecycle_engine, lifecycle_settings, monkeypatch):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    k2 = lab.connect("owner_a", w.a, w.a2, account="syn-acct-a2")
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a), connection_id=k1)
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    generations = {k: _get(w.db, ConnectorConnection, k).generation for k in (k1, k2)}
    pause = Pause()
    monkeypatch.setattr(
        agency_offboarding, "start_disconnect", pause.wrap(agency_offboarding.start_disconnect)
    )
    first = Run(run_offboarding, w.db.runtime, lab.config)
    first.start()
    assert pause.entered.wait(20)
    # The second worker finds the agency locked by the first and passes it by.
    second = run_offboarding(w.db.runtime, lab.config)
    assert (second["offboarded"], second["skipped"], second["connections_disconnected"]) == (
        0,
        1,
        0,
    )
    pause.release.set()
    result = first.outcome()
    assert (result["offboarded"], result["connections_disconnected"]) == (1, 2)
    for k in (k1, k2):
        row = _get(w.db, ConnectorConnection, k)
        assert (row.status, row.generation) == ("disconnecting", generations[k] + 1)
    assert _get(w.db, AgencyPurge, w.a).state == "waiting"
    third = run_offboarding(w.db.runtime, lab.config)
    assert (third["offboarded"], third["skipped"]) == (0, 0)


def test_ov17_purge_against_a_late_worker(lab, api, lifecycle_engine, lifecycle_settings):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1, account="syn-acct-a1")
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a), connection_id=k1)
    close_agency(w, api, lifecycle_engine, lifecycle_settings, w.a)
    run_offboarding(w.db.runtime, lab.config)
    # A late teardown: the worker has claimed the connection and is still revoking when the
    # deadline passes and the purge runs.
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE connector_connections SET purge_due_at = now() - interval '1 second'")
        )
    pause = Pause()

    class SlowProvider:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.capability = inner.capability
            self.revoke = pause.wrap(inner.revoke)

    teardown = Run(
        run_teardowns, w.db.runtime, lab.config, {"synthetic": SlowProvider(lab.provider)}
    )
    teardown.start()
    assert pause.entered.wait(20)
    with lifecycle_engine.connect() as connection:
        rows, outcome = purge_agency(connection, w.a, 25, 2)
    assert outcome == "partial" and rows == 50
    # Late writes between and during the purge's calls: a diagnostic of a late intake.
    late = (
        "INSERT INTO event_diagnostics (id, agency_id, client_id, day, channel, outcome, reason, "
        "count) VALUES (:id, :a, :c, current_date, 'server', 'rejected', 'late_writer', 1)"
    )
    with w.db.runtime.begin() as connection:
        connection.execute(text(late), {"id": uuid4(), "a": w.a, "c": w.a1})
    writer = w.db.runtime.connect()
    try:
        writer.begin()
        writer.execute(
            text(late.replace("late_writer", "late_open")), {"id": uuid4(), "a": w.a, "c": w.a2}
        )
        with lifecycle_engine.connect() as connection:
            _, blocked = purge_agency(connection, w.a, 10_000, None)
        assert blocked in {"partial", "failed"}
        writer.commit()
    finally:
        writer.close()
    pause.release.set()
    # The late teardown finds nothing left to finish and fails nothing.
    assert teardown.outcome() in ({"skipped": 1}, {"disconnected": 1})
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"]["agencies_purged"] == 1
    assert _leftover(w.db, w.a, [w.a1, w.a2]) == {}


def test_ov19_failures_log_codes_only(lab, api, lifecycle_engine, lifecycle_settings, capfd):
    w = lab.w
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    request_closure(w, api, w.a)
    export_id = _export_request(w, api)

    def broken(*args, **kwargs):
        raise OSError("synthetic disk failure with clients/ and Synthetic Client A1")

    original = agency_exports.write_zip
    agency_exports.write_zip = broken
    try:
        assert build_pending(w.db.runtime, api.config)["failed"] == 1
    finally:
        agency_exports.write_zip = original
    failed = _get(w.db, AgencyExport, export_id)
    assert (failed.status, failed.error_code) == ("failed", "build_failed")
    # A damaged part ends the stream and logs only the event name.
    _export_request(w, api)
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_export_parts SET ciphertext = "
                "set_byte(ciphertext, 0, (get_byte(ciphertext, 0) + 1) % 256)"
            )
        )
    owner = w.signed_in("owner_a")
    try:
        response = owner.get(f"/agencies/{w.a}/closure/export/download")
    except Exception:  # noqa: BLE001 - the transport may refuse a body shorter than declared
        pass
    else:
        assert len(response.content) < int(response.headers["content-length"])
    # An offboarding transaction that fails is logged by name and retried by the next pass.
    end_grace_period(w.db, w.a)
    run_lifecycle(lifecycle_engine, lifecycle_settings)

    def refuse(*args, **kwargs):
        raise OperationalError("synthetic", {}, Exception("Synthetic Agency A"))

    agency_offboarding.offboard_agency, original_offboard = (
        refuse,
        agency_offboarding.offboard_agency,
    )
    try:
        assert run_offboarding(w.db.runtime, lab.config)["failed"] == 1
    finally:
        agency_offboarding.offboard_agency = original_offboard
    assert run_offboarding(w.db.runtime, lab.config)["offboarded"] == 1
    captured = capfd.readouterr()
    lines = [line for line in (captured.out + captured.err).splitlines() if line.startswith("{")]
    events = {json.loads(line).get("event") for line in lines}
    assert {
        "agency_export_failed",
        "agency_export_unreadable",
        "agency_offboarding_failed",
    } <= events
    for private in _private(w, api, {}) + ("synthetic disk failure",):
        assert private not in captured.out + captured.err, private
