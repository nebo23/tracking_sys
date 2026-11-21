"""Connector connection lifecycle on disposable PostgreSQL (specification 009-A, D-048).

Synthetic fixture: agency A connects the same external account in clients A1 (K1) and A2 (K2),
and agency B connects it in client B1 (K3). The synthetic provider keeps its grants in a SQLite
file shared with the worker subprocess, so revocation is observed across processes.
"""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from connector_support import ACCOUNT, WorkerStopped, make_lab
from connector_support import archive as _archive
from connector_support import fail_connection as _fail_k
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.connectors.contracts import ErrorKind, ProviderError, ProviderRecord
from app.connectors.synthetic import SyntheticProvider
from app.models import (
    AuditEvent,
    ConnectorConnection,
    ConnectorOAuthTransaction,
    ConnectorRecord,
    ConnectorSyncRun,
)
from app.security import now_utc
from app.services.access import AccessService, ClientPermission
from app.services.connectors import (
    ConnectorError,
    complete_authorization,
)
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import Role, tenancy_transaction

pytestmark = pytest.mark.integration


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    return make_lab(authenticated_world, api, tmp_path)


def test_connect_status_isolation_and_sync(lab):
    w = lab.w
    url = lab.start("owner_a", w.a, w.a1)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"][0]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/connectors/oauth/callback"]
    result, location = lab.finish("owner_a", url)
    assert result["result"] == "connected"
    assert set(result) == {"result", "connection_id"}
    assert "state=" not in location and "code=" not in location
    k1 = UUID(result["connection_id"])
    k2 = lab.connect("owner_a", w.a, w.a2)
    k3 = lab.connect("owner_b", w.b, w.b1)
    assert len({k1, k2, k3}) == 3
    assert lab.worker()["sync"] == {"succeeded": 3}
    assert [lab.records(k) for k in (k1, k2, k3)] == [3, 3, 3]

    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["account"] == {"external_account_id": ACCOUNT, "label": "Synthetic Brand"}
    assert body["status"] == "active" and body["disconnect"] is None
    assert body["actions"] == {"reconnect": False, "disconnect": True}
    assert body["last_successful_sync_at"] is not None
    assert set(body) == {
        "id",
        "provider",
        "account",
        "status",
        "status_reason",
        "granted_scopes",
        "connected_at",
        "last_successful_sync_at",
        "actions",
        "disconnect",
        "grant_expires_at",
    }
    # Readers with a grant see the connection; another agency and ungranted clients do not.
    assert lab.view("analyst", w.a, w.a1, k1).status_code == 200
    assert lab.view("viewer", w.a, w.a1, k1).status_code == 200
    assert lab.view("analyst", w.a, w.a2, k2).status_code == 403
    assert lab.view("owner_b", w.a, w.a1, k1).status_code == 403
    assert lab.view("owner_a", w.a, w.a2, k1).status_code == 403
    assert lab.view("owner_a", w.b, w.b1, k3).status_code == 403
    listed = lab.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/connections").json()
    assert [item["id"] for item in listed] == [str(k1)]
    # Only Owner/Admin may mutate.
    assert lab.disconnect("analyst", w.a, w.a1, k1).status_code == 403
    assert lab.disconnect("viewer", w.a, w.a1, k1).status_code == 403
    assert lab.disconnect("owner_b", w.a, w.a1, k1).status_code == 403
    assert lab.sync("analyst", w.a, w.a1, k1).status_code == 403
    response = lab.browser("analyst").post(
        f"/agencies/{w.a}/clients/{w.a1}/connections", json={"provider": "synthetic"}
    )
    assert response.status_code == 403
    for k in (k1, k2, k3):
        assert set(lab.tokens(k)) == {"access_token", "refresh_token"}
        assert all(lab.provider.token_usable(t) for t in lab.tokens(k).values())


def test_callback_replay_expiry_binding_and_concurrent_submission(lab):
    w = lab.w
    url = lab.start("owner_a", w.a, w.a1)
    code = lab.provider.approve(url, ACCOUNT)
    state = parse_qs(urlsplit(url).query)["state"][0]
    params = {"code": code, "state": state}
    # Another session, even one holding its own binding cookie, cannot complete it, and its
    # attempt does not consume the owner's state.
    lab.start("admin", w.a, w.a2)
    other = lab.browser("admin")
    response = other.get("/connectors/oauth/callback", params=params, follow_redirects=False)
    assert response.headers["location"].endswith("?error=connection_failed")
    assert lab.complete("admin", url, None) == "connection_failed"
    owner = lab.browser("owner_a")
    first = owner.get("/connectors/oauth/callback", params=params, follow_redirects=False)
    assert "result=connected" in first.headers["location"]
    # The binding cookie is cleared, and a replay of the same callback is refused.
    assert lab.binding("owner_a") is None
    replay = owner.get("/connectors/oauth/callback", params=params, follow_redirects=False)
    assert "error=connection_failed" in replay.headers["location"]

    # Expired transactions are refused before the provider is contacted.
    url = lab.start("owner_a", w.a, w.a2)
    with w.db.migration.begin() as connection:
        connection.execute(
            update(ConnectorOAuthTransaction)
            .where(ConnectorOAuthTransaction.consumed_at.is_(None))
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
    result, _ = lab.finish("owner_a", url)
    assert result == {"error": "connection_failed"}

    # Concurrent submission of one callback: one grant, one connection.
    url = lab.start("owner_a", w.a, w.a2)
    code = lab.provider.approve(url, ACCOUNT)
    state = parse_qs(urlsplit(url).query)["state"][0]
    binding = owner.cookies.get("tracking_connector_oauth", path="/connectors/oauth")
    session_token = owner.cookies.get("tracking_session")
    outcomes, barrier = [], threading.Barrier(4)

    def submit():
        barrier.wait()
        try:
            outcomes.append(
                complete_authorization(
                    w.db.runtime,
                    lab.config,
                    {"synthetic": lab.provider},
                    state,
                    binding,
                    code,
                    session_token,
                ).purpose
            )
        except ConnectorError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=submit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["connect"] + ["connection_failed"] * 3
    with Session(w.db.migration) as session:
        live = session.scalars(
            select(ConnectorConnection).where(ConnectorConnection.status != "disconnected")
        ).all()
    assert sorted(item.client_id for item in live) == sorted([w.a1, w.a2])
    assert lab.provider.calls().count(("exchange", "ok")) == 2


def test_two_codes_for_one_client_account_keep_one_grant(lab):
    w = lab.w
    k2 = lab.connect("owner_a", w.a, w.a2)
    first = lab.start("owner_a", w.a, w.a1)
    first_cookie = lab.binding("owner_a")
    second = lab.start("owner_a", w.a, w.a1)
    k1 = lab.complete("owner_a", second, lab.binding("owner_a"))
    assert isinstance(k1, UUID)
    # The first authorization completes later with its own binding and loses.
    assert lab.complete("owner_a", first, first_cookie) == "account_already_connected"
    grants = lab.provider.grants()
    assert grants == [(ACCOUNT, False), (ACCOUNT, False), (ACCOUNT, True)]
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k1).values())
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k2).values())

    # Concurrent installation of two independent grants for one client and account.
    lab.disconnect("owner_a", w.a, w.a1, k1)
    lab.worker()
    owner = lab.browser("owner_a")
    session_token = owner.cookies.get("tracking_session")
    pending = []
    for _ in range(2):
        url = lab.start("owner_a", w.a, w.a1)
        pending.append((url, lab.binding("owner_a"), lab.provider.approve(url, ACCOUNT)))
    outcomes, barrier = [], threading.Barrier(2)

    def submit(url, binding, code):
        barrier.wait()
        try:
            complete_authorization(
                w.db.runtime,
                lab.config,
                {"synthetic": lab.provider},
                parse_qs(urlsplit(url).query)["state"][0],
                binding,
                code,
                session_token,
            )
            outcomes.append("connected")
        except ConnectorError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=submit, args=item) for item in pending]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["account_already_connected", "connected"]
    assert lab.provider.grants()[-2:] in (
        [(ACCOUNT, False), (ACCOUNT, True)],
        [(ACCOUNT, True), (ACCOUNT, False)],
    )
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k2).values())


# Run python -m app.connector_worker as its own process, sharing only the database and the
# provider file. Both tombstone keyring variables are set explicitly, blank when `tombstones` is
# false, so the result never depends on the developer's environment or .env (R014-02).
def _worker_command(lab, *, tombstones: bool = True) -> subprocess.CompletedProcess:
    tombstone, tombstone_active = "", ""
    if tombstones:
        tombstone = lab.config.tombstone_keyring.get_secret_value()
        tombstone_active = lab.config.tombstone_keyring_active
    environment = {
        **os.environ,
        "TRACKING_TOKEN_KEYRING": lab.config.token_keyring.get_secret_value(),
        "TRACKING_TOKEN_KEYRING_ACTIVE": lab.config.token_keyring_active,
        "TRACKING_TOMBSTONE_KEYRING": tombstone,
        "TRACKING_TOMBSTONE_KEYRING_ACTIVE": tombstone_active,
        "TRACKING_CONNECTOR_SYNTHETIC_STATE": str(lab.state),
    }
    return subprocess.run(
        [sys.executable, "-m", "app.connector_worker"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_disconnect_through_worker_command_isolates_other_clients(lab, capfd):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    k1_tokens, k2_tokens, k3_tokens = (lab.tokens(k) for k in (k1, k2, k3))

    response = lab.disconnect("owner_a", w.a, w.a1, k1)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "disconnecting" and body["actions"]["disconnect"] is False
    assert body["disconnect"]["revocation"] == "pending"
    due = body["disconnect"]["purge_due_at"]
    again = lab.disconnect("owner_a", w.a, w.a1, k1).json()
    assert again["disconnect"]["purge_due_at"] == due
    # A disconnecting connection cannot be synchronized.
    assert lab.sync("owner_a", w.a, w.a1, k1).json() == {"error": "connection_not_active"}

    # The worker runs as its own process, sharing only the database and the provider file.
    completed = _worker_command(lab)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "teardown": {"disconnected": 1},
        "schedule": {},
        "sync": {},
        # 014-B: the worker command also runs a bounded delivery step.
        "delivery": {},
    }

    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["status"] == "disconnected" and body["account"] is None
    assert body["disconnect"]["revocation"] == "done"
    assert body["disconnect"]["secret_destruction"] == "done"
    assert body["disconnect"]["data_purge"] == "done"
    assert body["disconnect"]["deadline_met"] is True
    assert not any(lab.provider.token_usable(t) for t in k1_tokens.values())
    stored = lab.secrets(k1)
    assert {(s.kind, s.status, s.revocation) for s in stored} == {
        ("access_token", "destroyed", "done"),
        ("refresh_token", "destroyed", "done"),
    }
    assert all(
        s.ciphertext is None and s.wrapped_dek is None and s.nonce is None and s.kek_id is None
        for s in stored
    )
    assert lab.records(k1) == 0
    connection = lab.row(k1)
    assert connection.external_account_id is None and connection.account_label is None

    # K2 and K3 keep working at the provider and keep syncing.
    assert all(lab.provider.token_usable(t) for t in [*k2_tokens.values(), *k3_tokens.values()])
    assert lab.provider.fetch_page(k2_tokens["access_token"]).records
    assert lab.provider.fetch_page(k3_tokens["access_token"]).records
    assert lab.sync("owner_a", w.a, w.a2, k2).status_code == 202
    assert lab.sync("owner_b", w.b, w.b1, k3).status_code == 202
    completed = _worker_command(lab)
    assert json.loads(completed.stdout) == {
        "teardown": {},
        "schedule": {},
        "sync": {"succeeded": 2},
        "delivery": {},
    }
    assert lab.records(k2) == 3 and lab.records(k3) == 3

    # No token value reached a response, redirect, log, audit row, or worker output.
    with Session(w.db.migration) as session:
        audit = session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()
    assert [e.action for e in audit if e.resource_type == "connection"] == [
        "connector.connected",
        "connector.connected",
        "connector.connected",
        "connector.disconnect_requested",
    ]
    captured = capfd.readouterr()
    haystack = "".join(
        [
            captured.out,
            captured.err,
            completed.stdout,
            completed.stderr,
            json.dumps([[e.action, str(e.resource_id)] for e in audit]),
            json.dumps(body),
        ]
    )
    for token in [*k1_tokens.values(), *k2_tokens.values(), *k3_tokens.values()]:
        assert token not in haystack


def test_worker_command_without_the_tombstone_keyring_reports_not_configured(lab):
    # R014-02: the documented connector configuration needs the token keyring only. With the
    # synthetic delivery provider registered and a blank tombstone keyring, the command still
    # runs every step, exits 0 and reports the delivery step as not configured.
    w = lab.w
    k1, _, _ = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    assert lab.disconnect("owner_a", w.a, w.a1, k1).status_code == 202
    completed = _worker_command(lab, tombstones=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "teardown": {"disconnected": 1},
        "schedule": {},
        "sync": {},
        "delivery": {"not_configured": 1},
    }
    assert lab.view("owner_a", w.a, w.a1, k1).json()["status"] == "disconnected"


class _Hooked(SyntheticProvider):
    def __init__(self, path, **hooks):
        super().__init__(path)
        self.hooks = hooks

    def fetch_page(self, access_token, **window):
        page = super().fetch_page(access_token, **window)
        if "fetch" in self.hooks:
            self.hooks.pop("fetch")()
        return page

    def refresh(self, refresh_token):
        grant = super().refresh(refresh_token)
        if "refresh" in self.hooks:
            self.hooks.pop("refresh")()
        return grant

    def revoke(self, token, kind):
        outcome = super().revoke(token, kind)
        if "revoke" in self.hooks:
            self.hooks.pop("revoke")()
        return outcome


def test_disconnect_during_fetch_discards_results_and_archive_stops_writes(lab):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    # Disconnect commits while K1's page is in flight: the write sees the new generation.
    hooked = _Hooked(lab.state, fetch=lambda: lab.disconnect("owner_a", w.a, w.a1, k1))
    counts = lab.worker(registry={"synthetic": hooked})
    assert counts["sync"] == {"discarded": 1, "succeeded": 2}
    assert lab.records(k1) == 0 and lab.records(k2) == 3
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert lab.records(k1) == 0

    # The other order: K2's page commits, then K2 disconnects, and the purge removes it.
    assert lab.records(k2) == 3
    lab.disconnect("owner_a", w.a, w.a2, k2)
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert lab.records(k2) == 0
    assert lab.records(k3) == 3

    # Archive after enqueue: the claim cancels the run; archive during a fetch: no write.
    k1b = lab.connect("owner_a", w.a, w.a1)
    _archive(w, w.a1)
    assert lab.worker()["sync"] == {"canceled": 1}
    with Session(w.db.migration) as session:
        run = session.scalars(
            select(ConnectorSyncRun).where(ConnectorSyncRun.connection_id == k1b)
        ).one()
    assert (run.status, run.error_kind) == ("canceled", "client_inactive")
    assert lab.records(k1b) == 0
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_client(w.a, w.a1, status="active")
    assert lab.sync("owner_a", w.a, w.a1, k1b).status_code == 202
    hooked = _Hooked(lab.state, fetch=lambda: _archive(w, w.a1))
    assert lab.sync("owner_b", w.b, w.b1, k3).status_code == 202
    counts = lab.worker(registry={"synthetic": hooked})
    assert counts["sync"] == {"discarded": 1, "succeeded": 1}
    assert lab.records(k1b) == 0 and lab.records(k3) == 3
    assert [s.version for s in lab.secrets(k1b) if s.kind == "access_token"] == [1]

    # A teardown requested before a suspension still finishes after it.
    lab.disconnect("owner_a", w.a, w.a1, k1b)
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE agencies SET status = 'suspended' WHERE id = :a"), {"a": w.a}
        )
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert lab.row(k1b).status == "disconnected"
    assert lab.provider.token_usable(lab.tokens(k3)["access_token"])


def test_refresh_install_is_fenced_and_terminal_failure_requires_reconnect(lab):
    w = lab.w
    lab.provider.set_behavior("access_ttl", "0")
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    lab.provider.set_behavior("access_ttl", "3600")
    # An expired access token is refreshed and the new version installed.
    assert lab.worker()["sync"] == {"succeeded": 2}
    versions = [(s.kind, s.version, s.status, s.revocation) for s in lab.secrets(k1)]
    assert versions == [
        ("access_token", 1, "destroyed", "not_required"),
        ("access_token", 2, "active", None),
        ("refresh_token", 1, "active", None),
    ]

    # A refresh racing a disconnect: the new token is not installed and is revoked.
    lab.provider.set_behavior("access_ttl", "0")
    k3 = lab.connect("owner_b", w.b, w.b1)
    lab.provider.set_behavior("access_ttl", "3600")
    hooked = _Hooked(lab.state, refresh=lambda: lab.disconnect("owner_b", w.b, w.b1, k3))
    calls = len(lab.provider.calls())
    assert lab.worker(registry={"synthetic": hooked})["sync"] == {"stopped": 1}
    assert [s.version for s in lab.secrets(k3) if s.kind == "access_token"] == [1]
    assert lab.provider.calls()[calls:] == [("refresh", "ok"), ("revoke", "ok")]
    assert lab.worker()["teardown"] == {"disconnected": 1}

    # Terminal credential failure: only K1 needs reconnection, K2 keeps syncing.
    lab.provider.set_behavior("fetch", "unauthorized")
    lab.provider.set_behavior("refresh", "invalid_grant")
    assert lab.sync("owner_a", w.a, w.a1, k1).status_code == 202
    assert lab.worker()["sync"] == {"stopped": 1}
    lab.provider.set_behavior("fetch", "ok")
    lab.provider.set_behavior("refresh", "ok")
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert (body["status"], body["status_reason"]) == ("reconnect_required", "credential_expired")
    assert body["actions"] == {"reconnect": True, "disconnect": True}
    assert lab.records(k1) == 3
    assert {s.status for s in lab.secrets(k1) if s.status != "destroyed"} == {"revoked"}
    assert lab.sync("owner_a", w.a, w.a1, k1).json() == {"error": "connection_not_active"}
    assert lab.sync("owner_a", w.a, w.a2, k2).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 1}


def test_reconnect_binding_mismatch_and_race_with_disconnect(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    assert lab.worker()["sync"] == {"succeeded": 2}
    lab.provider.set_behavior("fetch", "unauthorized")
    lab.provider.set_behavior("refresh", "invalid_grant")
    lab.sync("owner_a", w.a, w.a1, k1)
    assert lab.worker()["sync"] == {"stopped": 1}
    lab.provider.set_behavior("fetch", "ok")
    lab.provider.set_behavior("refresh", "ok")
    assert lab.row(k1).status == "reconnect_required"
    assert lab.row(k2).status == "active"
    generation = lab.row(k1).generation

    # A different external account cannot replace K1's account.
    grants = len(lab.provider.grants())
    result, _ = lab.finish("owner_a", lab.start("owner_a", w.a, w.a1, k1), account="syn-other")
    assert result == {"error": "account_mismatch"}
    assert lab.provider.grants()[grants:] == [("syn-other", True)]

    # A successful reconnect installs new versions and revokes the replaced grant.
    old = lab.tokens(k1)
    result, _ = lab.finish("owner_a", lab.start("owner_a", w.a, w.a1, k1))
    assert result["result"] == "reconnected" and result["connection_id"] == str(k1)
    connection = lab.row(k1)
    assert connection.status == "active" and connection.generation == generation + 1
    assert [(s.kind, s.version, s.status) for s in lab.secrets(k1)] == [
        ("access_token", 1, "destroyed"),
        ("access_token", 2, "active"),
        ("refresh_token", 1, "destroyed"),
        ("refresh_token", 2, "active"),
    ]
    assert not any(lab.provider.token_usable(t) for t in old.values())
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k1).values())
    assert lab.tokens(k2) and all(lab.provider.token_usable(t) for t in lab.tokens(k2).values())

    # A stale reconnect started at an earlier generation is refused even when the connection
    # requires reconnection again: only the generation tells the two authorizations apart.
    def fail_k1():
        lab.provider.set_behavior("fetch", "unauthorized")
        lab.provider.set_behavior("refresh", "invalid_grant")
        lab.sync("owner_a", w.a, w.a1, k1)
        assert lab.worker()["sync"] == {"stopped": 1}
        lab.provider.set_behavior("fetch", "ok")
        lab.provider.set_behavior("refresh", "ok")

    fail_k1()
    stale = lab.start("owner_a", w.a, w.a1, k1)
    stale_cookie = lab.binding("owner_a")
    result, _ = lab.finish("owner_a", lab.start("owner_a", w.a, w.a1, k1))
    assert result["result"] == "reconnected"
    fail_k1()
    current = lab.tokens(k1)
    grants = len(lab.provider.grants())
    assert lab.complete("owner_a", stale, stale_cookie) == "connection_changed"
    assert lab.provider.grants()[grants:] == [(ACCOUNT, True)]
    assert lab.row(k1).status == "reconnect_required" and lab.tokens(k1) == current

    # A pending reconnect loses to a disconnect: its new grant is revoked, nothing installed.
    lab.provider.set_behavior("fetch", "unauthorized")
    lab.provider.set_behavior("refresh", "invalid_grant")
    lab.sync("owner_a", w.a, w.a1, k1)
    lab.worker()
    lab.provider.set_behavior("fetch", "ok")
    lab.provider.set_behavior("refresh", "ok")
    url = lab.start("owner_a", w.a, w.a1, k1)
    lab.disconnect("owner_a", w.a, w.a1, k1)
    grants = len(lab.provider.grants())
    result, _ = lab.finish("owner_a", url)
    assert result == {"error": "connection_changed"}
    assert lab.provider.grants()[grants:] == [(ACCOUNT, True)]
    assert lab.worker()["teardown"] == {"disconnected": 1}
    assert lab.row(k1).status == "disconnected"
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k2).values())


def test_late_callback_after_role_loss_is_denied(lab):
    w = lab.w
    url = lab.start("admin", w.a, w.a1)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.update_member(w.a, w.admin, role=Role.ANALYST)
    result, _ = lab.finish("admin", url)
    assert result == {"error": "connection_denied"}
    assert lab.provider.grants() == [(ACCOUNT, True)]
    with Session(w.db.migration) as session:
        assert session.scalars(select(ConnectorConnection)).all() == []


def test_teardown_outcomes_with_controlled_clock(lab):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    lab.worker()
    k1_tokens = lab.tokens(k1)
    start = now_utc()

    # Transient failure, then success after the lease expires.
    lab.provider.set_behavior("revoke", "retryable")
    lab.disconnect("owner_a", w.a, w.a1, k1)
    assert lab.worker(now=start + timedelta(minutes=1))["teardown"] == {"pending": 1}
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["status"] == "disconnecting" and body["disconnect"]["revocation"] == "pending"
    assert all(s.ciphertext is not None for s in lab.secrets(k1))
    lab.provider.set_behavior("revoke", "ok")
    assert lab.worker(now=start + timedelta(minutes=4))["teardown"] == {"disconnected": 1}
    assert lab.view("owner_a", w.a, w.a1, k1).json()["disconnect"]["revocation"] == "done"
    assert not any(lab.provider.token_usable(t) for t in k1_tokens.values())

    # Unsupported revocation is reported, never counted as done.
    k2_tokens = lab.tokens(k2)
    lab.provider.set_behavior("revoke", "unsupported")
    lab.disconnect("owner_a", w.a, w.a2, k2)
    assert lab.worker()["teardown"] == {"disconnected": 1}
    body = lab.view("owner_a", w.a, w.a2, k2).json()
    assert body["disconnect"]["revocation"] == "unsupported"
    assert {s.revocation for s in lab.secrets(k2)} == {"unsupported"}
    assert all(lab.provider.token_usable(t) for t in k2_tokens.values())
    assert lab.records(k2) == 0

    # Failure through the deadline: finished at the deadline with revocation failed.
    k3_tokens = lab.tokens(k3)
    lab.provider.set_behavior("revoke", "retryable")
    lab.disconnect("owner_b", w.b, w.b1, k3)
    due = lab.row(k3).purge_due_at
    assert due - lab.row(k3).disconnect_requested_at == timedelta(hours=72)
    assert lab.worker(now=due - timedelta(seconds=1))["teardown"] == {"pending": 1}
    assert lab.records(k3) == 3
    assert lab.worker(now=due)["teardown"] == {"disconnected": 1}
    body = lab.view("owner_b", w.b, w.b1, k3).json()
    assert body["disconnect"]["revocation"] == "failed"
    assert body["disconnect"]["deadline_met"] is True and body["account"] is None
    assert lab.records(k3) == 0
    assert all(s.ciphertext is None and s.revocation == "failed" for s in lab.secrets(k3))
    assert all(lab.provider.token_usable(t) for t in k3_tokens.values())


def test_teardown_resumes_after_crash_and_records_late_completion(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k1_tokens = lab.tokens(k1)
    lab.disconnect("owner_a", w.a, w.a1, k1)

    def crash():
        raise WorkerStopped

    start = now_utc()
    hooked = _Hooked(lab.state, revoke=crash)
    with pytest.raises(WorkerStopped):
        lab.worker(now=start, registry={"synthetic": hooked})
    assert not lab.provider.token_usable(k1_tokens["refresh_token"])
    assert {s.revocation for s in lab.secrets(k1)} == {None}
    # Within the lease another pass leaves it alone; after it, the teardown resumes.
    assert lab.worker(now=start + timedelta(minutes=1))["teardown"] == {}
    late = lab.row(k1).purge_due_at + timedelta(hours=5)
    assert lab.worker(now=late)["teardown"] == {"disconnected": 1}
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["disconnect"]["revocation"] == "done"
    assert body["disconnect"]["deadline_met"] is False
    assert lab.row(k1).disconnected_at == late


def test_runtime_privileges_scoped_references_and_lifecycle(
    lab, lifecycle_engine, lifecycle_settings
):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    lab.worker()
    # The 0009 downgrade refuses populated connector state.
    with pytest.raises(RuntimeError, match="populated connector state"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0008_links_tracker")
    assert lab.row(k1).status == "active"
    denied = [
        "DELETE FROM connector_token_secrets",
        "DELETE FROM connector_connections",
        "DELETE FROM connector_sync_runs",
        "DELETE FROM connector_oauth_transactions",
        "UPDATE connector_connections SET provider = 'synthetic'",
        "UPDATE connector_connections SET client_id = client_id",
        "UPDATE connector_token_secrets SET connection_id = connection_id",
        "UPDATE connector_token_secrets SET kind = kind",
        "UPDATE connector_records SET provider_object_id = provider_object_id",
        "UPDATE connector_oauth_transactions SET state_digest = state_digest",
        "UPDATE connector_sync_runs SET connection_generation = 1",
    ]
    for statement in denied:
        with pytest.raises(DBAPIError, match="permission denied"):
            with w.db.runtime.begin() as connection:
                connection.execute(text(statement))
    # Composite keys refuse a reference to another client's connection.
    with pytest.raises(IntegrityError):
        with Session(w.db.runtime) as session, session.begin():
            session.add(
                ConnectorRecord(
                    agency_id=w.a,
                    client_id=w.a2,
                    connection_id=k1,
                    connection_generation=1,
                    provider_object_id="cross-client",
                    observed_at=now_utc(),
                    metrics={},
                )
            )
    with pytest.raises(IntegrityError):
        with Session(w.db.runtime) as session, session.begin():
            session.add(
                ConnectorOAuthTransaction(
                    agency_id=w.b,
                    client_id=w.b1,
                    connection_id=k1,
                    expected_generation=1,
                    initiator_membership_id=w.owner_a,
                    provider="synthetic",
                    purpose="reconnect",
                    state_digest="a" * 64,
                    binding_digest="b" * 64,
                    expires_at=now_utc(),
                )
            )
    # Destroyed material is enforced by the schema, not only by code.
    with pytest.raises(IntegrityError):
        with w.db.runtime.begin() as connection:
            connection.execute(
                text(
                    "UPDATE connector_token_secrets SET ciphertext = NULL WHERE connection_id = :k"
                ),
                {"k": k2},
            )
    # A complete disconnect as tracking_app is permitted by the grants.
    lab.disconnect("owner_a", w.a, w.a1, k1)
    assert lab.worker()["teardown"] == {"disconnected": 1}

    # tracking_lifecycle deletes connector transactions one day after consumption or expiry.
    with Session(w.db.migration) as session:
        count = len(session.scalars(select(ConnectorOAuthTransaction)).all())
    assert count == 2
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=now_utc())
    assert result["deleted"]["connector_oauth_transactions"] == 0
    later = now_utc() + timedelta(days=1, minutes=11)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=later)
    assert result["deleted"]["connector_oauth_transactions"] == 2


def test_disconnect_and_status_fail_closed_without_configuration(lab, api):
    w = lab.w
    client = api.new_client(api.config)
    api.login(client, "owner_a@example.test")
    response = client.post(
        f"/agencies/{w.a}/clients/{w.a1}/connections", json={"provider": "synthetic"}
    )
    assert response.status_code == 404 and response.json() == {"error": "provider_unavailable"}
    with pytest.raises(ProviderError):
        lab.provider.fetch_page("syn_at_unknown")


# --- Pre-publication review regressions (pre-pr-review-2026-11-15.md, R009-01 to R009-07) ---


class _Scripted(SyntheticProvider):
    """Synthetic provider with per-token revocation failures and one-shot hooks."""

    def __init__(self, path, *, fail_revoke=(), on_fetch=None, fetch_error=None, on_refresh=None):
        super().__init__(path)
        self.fail_revoke = set(fail_revoke)
        self.on_fetch, self.fetch_error, self.on_refresh = on_fetch, fetch_error, on_refresh

    def revoke(self, token, kind):
        if token in self.fail_revoke:
            raise ProviderError(ErrorKind.RETRYABLE, "unavailable")
        return super().revoke(token, kind)

    def fetch_page(self, access_token, **window):
        page = super().fetch_page(access_token, **window)
        if self.on_fetch is not None:
            hook, self.on_fetch = self.on_fetch, None
            hook()
            if self.fetch_error is not None:
                raise self.fetch_error
            # Distinguishable stale page data.
            return replace(
                page,
                records=tuple(
                    ProviderRecord(r.provider_object_id, r.observed_at, {"stale": 1})
                    for r in page.records
                ),
            )
        return page

    def refresh(self, refresh_token):
        grant = super().refresh(refresh_token)
        if self.on_refresh is not None:
            hook, self.on_refresh = self.on_refresh, None
            hook()
        return grant


def _disposal_events(captured: str) -> list[dict]:
    events = []
    for line in captured.splitlines():
        if line.startswith("{"):
            entry = json.loads(line)
            if entry.get("event") == "connector_grant_disposal_failed":
                events.append(entry)
    return events


def test_r009_01_reconnect_keeps_the_previous_grant_revocation_obligation(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k2 = lab.connect("owner_a", w.a, w.a2)
    lab.worker()
    _fail_k(lab, w.a, w.a1, k1)
    old = lab.tokens(k1)
    k2_tokens = lab.tokens(k2)
    # The provider temporarily cannot revoke the previous grant: the reconnect does not
    # replace it, the new grant is disposed, and the old versions stay outstanding.
    failing = _Scripted(lab.state, fail_revoke=old.values())
    url = lab.start("owner_a", w.a, w.a1, k1)
    grants = len(lab.provider.grants())
    outcome = lab.complete("owner_a", url, lab.binding("owner_a"), registry={"synthetic": failing})
    assert outcome == "provider_unavailable"
    assert lab.provider.grants()[grants:] == [(ACCOUNT, True)]
    assert lab.row(k1).status == "reconnect_required"
    assert lab.tokens(k1) == old and lab.provider.token_usable(old["refresh_token"])
    # A later disconnect includes those versions: the result is done only once they are
    # revoked at the provider, and the other client's grant is untouched.
    lab.disconnect("owner_a", w.a, w.a1, k1)
    assert lab.worker(registry={"synthetic": failing})["teardown"] == {"pending": 1}
    assert lab.worker(now=now_utc() + timedelta(minutes=3))["teardown"] == {"disconnected": 1}
    assert lab.view("owner_a", w.a, w.a1, k1).json()["disconnect"]["revocation"] == "done"
    assert not any(lab.provider.token_usable(t) for t in old.values())
    assert all(lab.provider.token_usable(t) for t in k2_tokens.values())

    # An unsupported revocation of a replaced grant is kept in the connection-level result.
    _fail_k(lab, w.a, w.a2, k2)
    previous = lab.tokens(k2)
    lab.provider.set_behavior("revoke", "unsupported")
    result, _ = lab.finish("owner_a", lab.start("owner_a", w.a, w.a2, k2))
    assert result["result"] == "reconnected"
    lab.provider.set_behavior("revoke", "ok")
    lab.disconnect("owner_a", w.a, w.a2, k2)
    assert lab.worker()["teardown"] == {"disconnected": 1}
    body = lab.view("owner_a", w.a, w.a2, k2).json()
    assert body["disconnect"]["revocation"] == "unsupported"
    assert lab.provider.token_usable(previous["refresh_token"])


def test_r009_02_superseded_sync_attempt_cannot_overwrite_its_replacement(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    start = now_utc()
    replacement = start + timedelta(minutes=6)

    # The first attempt's lease expires while its page is in flight; a replacement claims the
    # run and completes it before the first attempt returns with different data.
    stale = _Scripted(lab.state, on_fetch=lambda: lab.worker(now=replacement))
    assert lab.worker(now=start, registry={"synthetic": stale})["sync"] == {"superseded": 1}
    connection = lab.row(k1)
    assert connection.last_successful_sync_at == replacement
    with Session(w.db.migration) as session:
        rows = session.scalars(
            select(ConnectorRecord).where(ConnectorRecord.connection_id == k1)
        ).all()
        run = session.scalars(
            select(ConnectorSyncRun).where(ConnectorSyncRun.connection_id == k1)
        ).one()
    assert {r.fetched_at for r in rows} == {replacement}
    assert all("stale" not in r.metrics for r in rows)
    assert (run.status, run.attempt, run.finished_at) == ("succeeded", 2, replacement)

    # An error result of the superseded attempt changes neither the connection nor tokens.
    lab.sync("owner_a", w.a, w.a1, k1)
    lab.provider.set_behavior("refresh", "invalid_grant")
    later = replacement + timedelta(minutes=1)
    stale = _Scripted(
        lab.state,
        on_fetch=lambda: lab.worker(now=later + timedelta(minutes=6)),
        fetch_error=ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token"),
    )
    lab.worker(now=later, registry={"synthetic": stale})
    lab.provider.set_behavior("refresh", "ok")
    connection = lab.row(k1)
    assert connection.status == "active"
    assert connection.last_successful_sync_at == later + timedelta(minutes=6)
    assert [s.version for s in lab.secrets(k1) if s.kind == "access_token"] == [1]

    # A stale attempt that already refreshed and then gets 401 cannot require reconnection.
    lab.provider.set_behavior("access_ttl", "0")
    k2 = lab.connect("owner_a", w.a, w.a2)
    lab.provider.set_behavior("access_ttl", "3600")
    third = later + timedelta(minutes=20)
    stale = _Scripted(
        lab.state,
        on_fetch=lambda: lab.worker(now=third + timedelta(minutes=6)),
        fetch_error=ProviderError(ErrorKind.UNAUTHORIZED, "invalid_token"),
    )
    assert lab.worker(now=third, registry={"synthetic": stale})["sync"] == {"superseded": 1}
    connection = lab.row(k2)
    assert connection.status == "active"
    assert connection.last_successful_sync_at == third + timedelta(minutes=6)


def test_r009_03_stale_refresh_never_revokes_the_winning_grant(lab):
    w = lab.w
    lab.provider.set_behavior("access_ttl", "0")
    k1 = lab.connect("owner_a", w.a, w.a1)
    lab.provider.set_behavior("access_ttl", "3600")
    start = now_utc()
    # The first attempt's refresh call is in flight when its lease expires; the replacement
    # refreshes, installs its token and succeeds before the first attempt returns.
    stale = _Scripted(lab.state, on_refresh=lambda: lab.worker(now=start + timedelta(minutes=6)))
    lab.worker(now=start, registry={"synthetic": stale})
    winner = lab.tokens(k1)
    assert [s.version for s in lab.secrets(k1) if s.kind == "access_token"] == [1, 2]
    assert all(lab.provider.token_usable(t) for t in winner.values())
    assert len(lab.provider.fetch_page(winner["access_token"]).records) == 3
    assert lab.row(k1).status == "active"


def test_r009_04_deadline_is_judged_at_completion_time(lab, monkeypatch):
    import app.services.connectors as service

    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    lab.disconnect("owner_a", w.a, w.a1, k1)
    due = lab.row(k1).purge_due_at
    clock = [due - timedelta(seconds=1)]

    class Slow(SyntheticProvider):
        def revoke(self, token, kind):
            clock[0] = due + timedelta(seconds=1)
            return super().revoke(token, kind)

    monkeypatch.setattr(service, "now_utc", lambda: clock[0])
    assert lab.worker(registry={"synthetic": Slow(lab.state)})["teardown"] == {"disconnected": 1}
    monkeypatch.undo()
    connection = lab.row(k1)
    assert connection.disconnected_at == due + timedelta(seconds=1)
    assert connection.purge_due_at == due
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["disconnect"]["deadline_met"] is False


def test_r009_05_actions_reflect_the_requesting_principal(lab, api):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    base = f"/agencies/{w.a}/clients/{w.a1}/connections"
    with Session(w.db.runtime, expire_on_commit=False) as session, session.begin():
        _, raw = AccessService(session, w.users.owner_a, lab.config).issue_service_key(
            w.a, "Synthetic reader", [ClientPermission(w.a1)]
        )
    reader = api.new_client(lab.config)
    reader.headers["Authorization"] = f"Bearer {raw}"
    expected = {
        "owner_a": {"reconnect": False, "disconnect": True},
        "admin": {"reconnect": False, "disconnect": True},
        "analyst": {"reconnect": False, "disconnect": False},
        "viewer": {"reconnect": False, "disconnect": False},
    }
    for name, actions in expected.items():
        client = lab.browser(name)
        assert client.get(f"{base}/{k1}").json()["actions"] == actions, name
        assert [item["actions"] for item in client.get(base).json()] == [actions], name
    readonly = {"reconnect": False, "disconnect": False}
    assert reader.get(f"{base}/{k1}").json()["actions"] == readonly
    assert [item["actions"] for item in reader.get(base).json()] == [readonly]
    _fail_k(lab, w.a, w.a1, k1)
    assert lab.view("admin", w.a, w.a1, k1).json()["actions"] == {
        "reconnect": True,
        "disconnect": True,
    }
    assert lab.view("analyst", w.a, w.a1, k1).json()["actions"] == readonly


def test_r009_06_unresolved_grant_disposal_is_reported(lab, capfd):
    w = lab.w
    for client_id, behavior, outcome in (
        (w.a1, "unsupported", "unsupported"),
        (w.a2, "retryable", "failed"),
    ):
        first = lab.start("owner_a", w.a, client_id)
        first_cookie = lab.binding("owner_a")
        second = lab.start("owner_a", w.a, client_id)
        winner = lab.complete("owner_a", second, lab.binding("owner_a"))
        assert isinstance(winner, UUID)
        capfd.readouterr()
        lab.provider.set_behavior("revoke", behavior)
        assert lab.complete("owner_a", first, first_cookie) == "account_already_connected"
        lab.provider.set_behavior("revoke", "ok")
        events = _disposal_events(capfd.readouterr().err)
        assert [event.get("outcome") for event in events] == [outcome], client_id
        # The discarded grant is still live at the provider; the winning grant is unaffected.
        assert lab.provider.grants()[-1] == (ACCOUNT, False)
        assert all(lab.provider.token_usable(t) for t in lab.tokens(winner).values())


def test_r009_07_a_retrying_teardown_does_not_starve_other_tenants(lab):
    w = lab.w
    k1 = lab.connect("owner_a", w.a, w.a1)
    k3 = lab.connect("owner_b", w.b, w.b1)
    k1_tokens = lab.tokens(k1)
    lab.disconnect("owner_a", w.a, w.a1, k1)
    lab.disconnect("owner_b", w.b, w.b1, k3)
    failing = _Scripted(lab.state, fail_revoke=k1_tokens.values())
    start = now_utc()
    for index in range(4):
        lab.worker(
            now=start + timedelta(minutes=5 * index), registry={"synthetic": failing}, limit=1
        )
    assert lab.row(k3).status == "disconnected"
    assert lab.view("owner_b", w.b, w.b1, k3).json()["disconnect"]["revocation"] == "done"
    assert lab.row(k1).status == "disconnecting"
    # The earlier request still completes at its own deadline, reporting the failure.
    due = lab.row(k1).purge_due_at
    assert lab.worker(now=due, registry={"synthetic": failing}, limit=1)["teardown"] == {
        "disconnected": 1
    }
    assert lab.view("owner_a", w.a, w.a1, k1).json()["disconnect"]["revocation"] == "failed"
    assert lab.records(k1) == 0


# --- Correction review regressions (corrections-review-2026-11-15.md, R009-08 to R009-10) ---


def _lock_waits(db) -> int:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted")).scalar()


# Wait for a condition another thread establishes; correctness never depends on the delay.
def _wait_until(predicate, message, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.02)


# The same Owner initiating both reconnects, as reviewed, and two different managers, whose
# sessions share no user row lock, so only the connection lock orders the two callbacks.
@pytest.mark.parametrize("initiators", [("owner_a", "owner_a"), ("owner_a", "admin")])
def test_r009_08_concurrent_reconnects_keep_the_winning_grant_usable(lab, monkeypatch, initiators):
    import app.services.connectors as service

    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    _fail_k(lab, w.a, w.a1, k1)
    previous = lab.tokens(k1)
    others = {k: lab.tokens(k) for k in (k2, k3)}
    # Two reconnects for the same connection generation.
    names = dict(zip(("delayed", "other"), initiators, strict=True))
    delayed_url = lab.start(names["delayed"], w.a, w.a1, k1)
    delayed_cookie = lab.binding(names["delayed"])
    other_url = lab.start(names["other"], w.a, w.a1, k1)
    other_cookie = lab.binding(names["other"])

    # The delayed callback stops after it has checked the connection generation and before it
    # reads the versions of the previous grant; the other callback then runs.
    paused, release = threading.Event(), threading.Event()
    live_secrets = service._live_secrets

    def gated(session, connection_id):
        if threading.current_thread().name == "delayed" and not paused.is_set():
            paused.set()
            assert release.wait(60)
        return live_secrets(session, connection_id)

    monkeypatch.setattr(service, "_live_secrets", gated)
    outcomes = {}

    def callback(name, url, cookie):
        outcomes[name] = lab.complete(names[name], url, cookie)

    delayed = threading.Thread(
        target=callback, args=("delayed", delayed_url, delayed_cookie), name="delayed"
    )
    other = threading.Thread(target=callback, args=("other", other_url, other_cookie), name="other")
    delayed.start()
    assert paused.wait(60)
    other.start()
    # The other callback either completes or waits for the delayed callback's consistent view.
    _wait_until(
        lambda: not other.is_alive() or _lock_waits(w.db) > 0,
        "The second callback neither completed nor waited.",
    )
    release.set()
    delayed.join(60)
    other.join(60)
    monkeypatch.undo()
    assert not delayed.is_alive() and not other.is_alive()

    # Exactly one callback installs its grant; the superseded one disposed of its own grant.
    assert sorted(outcomes.values(), key=str) == sorted([k1, "connection_changed"], key=str)
    delayed_grant, other_grant = lab.provider.grants()[-2:]
    assert delayed_grant == (ACCOUNT, outcomes["delayed"] == "connection_changed")
    assert other_grant == (ACCOUNT, outcomes["other"] == "connection_changed")
    body = lab.view("owner_a", w.a, w.a1, k1).json()
    assert body["status"] == "active" and body["actions"]["reconnect"] is False
    installed = lab.tokens(k1)
    assert set(installed) == {"access_token", "refresh_token"}
    assert all(lab.provider.token_usable(t) for t in installed.values())
    assert len(lab.provider.fetch_page(installed["access_token"]).records) == 3
    assert lab.worker()["sync"] == {"succeeded": 1}
    assert not any(lab.provider.token_usable(t) for t in previous.values())
    # The client sharing the account and the client in another agency are unaffected.
    for k, tokens in others.items():
        assert lab.tokens(k) == tokens
        assert all(lab.provider.token_usable(t) for t in tokens.values())
    assert lab.sync("owner_a", w.a, w.a2, k2).status_code == 202
    assert lab.sync("owner_b", w.b, w.b1, k3).status_code == 202
    assert lab.worker()["sync"] == {"succeeded": 2}


def test_r009_09_a_rejected_reconnect_keeps_the_original_grant(lab, api, capfd):
    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    _fail_k(lab, w.a, w.a1, k1)
    original = lab.tokens(k1)
    recorded = [(s.id, s.kind, s.version, s.status, s.revocation) for s in lab.secrets(k1)]
    others = {k: lab.tokens(k) for k in (k2, k3)}
    generation = lab.row(k1).generation

    def rejected(outcome, account=ACCOUNT, attempt=None):
        grants = len(lab.provider.grants())
        capfd.readouterr()
        result = (
            attempt()
            if attempt
            else lab.finish("owner_a", lab.start("owner_a", w.a, w.a1, k1), account)[0]
        )
        assert result == {"error": outcome}
        # The rejected grant is disposed at the provider without a disposal failure.
        assert lab.provider.grants()[grants:] == [(account, True)]
        assert _disposal_events(capfd.readouterr().err) == []
        # The original grant still works and its recorded outcome is unchanged.
        connection = lab.row(k1)
        assert (connection.status, connection.generation) == ("reconnect_required", generation)
        assert [
            (s.id, s.kind, s.version, s.status, s.revocation) for s in lab.secrets(k1)
        ] == recorded
        assert lab.tokens(k1) == original
        assert all(lab.provider.token_usable(t) for t in original.values())
        assert len(lab.provider.fetch_page(original["access_token"]).records) == 3

    # A different external account.
    rejected("account_mismatch", account="syn-other")

    # Loss of authority: the initiating Admin becomes an Analyst before the callback.
    url = lab.start("admin", w.a, w.a1, k1)
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as tenancy:
        tenancy.update_member(w.a, w.admin, role=Role.ANALYST)
    rejected("connection_denied", attempt=lambda: lab.finish("admin", url)[0])

    # An ineligible client: archived between initiation and callback.
    url = lab.start("owner_a", w.a, w.a1, k1)
    _archive(w, w.a1)
    rejected("connection_denied", attempt=lambda: lab.finish("owner_a", url)[0])
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as tenancy:
        tenancy.update_client(w.a, w.a1, status="active")

    # A session that ended before the callback.
    browser = api.new_client(lab.config)
    api.login(browser, "owner_a@example.test")
    response = browser.post(f"/agencies/{w.a}/clients/{w.a1}/connections/{k1}/reconnect")
    url = response.json()["authorization_url"]
    cookie = browser.cookies.get("tracking_connector_oauth", path="/connectors/oauth")
    session_token = browser.cookies.get("tracking_session")
    assert browser.post("/auth/logout").status_code == 204

    def ended_session():
        code = lab.provider.approve(url, ACCOUNT)
        try:
            complete_authorization(
                w.db.runtime,
                lab.config,
                {"synthetic": lab.provider},
                parse_qs(urlsplit(url).query)["state"][0],
                cookie,
                code,
                session_token,
            )
        except ConnectorError as error:
            return {"error": error.code}
        return {"result": "unexpected"}

    rejected("connection_denied", attempt=ended_session)

    # A valid reconnect still succeeds and only then revokes the original grant.
    result, _ = lab.finish("owner_a", lab.start("owner_a", w.a, w.a1, k1))
    assert result["result"] == "reconnected"
    assert not any(lab.provider.token_usable(t) for t in original.values())
    assert all(lab.provider.token_usable(t) for t in lab.tokens(k1).values())
    for k, tokens in others.items():
        assert lab.tokens(k) == tokens
        assert all(lab.provider.token_usable(t) for t in tokens.values())


def test_r009_10_completion_is_timed_after_the_purge(lab, monkeypatch):
    import app.services.connectors as service

    w = lab.w
    k1, k2, k3 = lab.fixtures()
    assert lab.worker()["sync"] == {"succeeded": 3}
    clock = [now_utc()]

    class SlowRevoke(SyntheticProvider):
        def revoke(self, token, kind):
            clock[0] = due + timedelta(seconds=1)
            return super().revoke(token, kind)

    def advance_on_purge(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE FROM CONNECTOR_RECORDS"):
            clock[0] = due + timedelta(seconds=1)

    def teardown(connection_id, agency, client_id, owner, registry=None):
        nonlocal due
        assert lab.disconnect(owner, agency, client_id, connection_id).status_code == 202
        due = lab.row(connection_id).purge_due_at
        clock[0] = due - timedelta(seconds=1)
        monkeypatch.setattr(service, "now_utc", lambda: clock[0])
        try:
            counts = lab.worker(registry=registry)
        finally:
            monkeypatch.undo()
        assert counts["teardown"] == {"disconnected": 1}
        assert lab.records(connection_id) == 0
        assert all(s.status == "destroyed" for s in lab.secrets(connection_id))
        connection = lab.row(connection_id)
        assert connection.purge_due_at == due
        body = lab.view(owner, agency, client_id, connection_id).json()
        return connection.disconnected_at, body["disconnect"]

    due = None
    # On time: purge and completion both before the deadline.
    completed, outcome = teardown(k1, w.a, w.a1, "owner_a")
    assert completed == due - timedelta(seconds=1)
    assert outcome["deadline_met"] is True and outcome["revocation"] == "done"

    # Late provider revocation: the deadline passes while the provider is called.
    completed, outcome = teardown(
        k2, w.a, w.a2, "owner_a", registry={"synthetic": SlowRevoke(lab.state)}
    )
    assert completed == due + timedelta(seconds=1)
    assert outcome["deadline_met"] is False and outcome["revocation"] == "done"

    # Late database cleanup: the deadline passes while provider records are deleted.
    event.listen(w.db.runtime, "after_cursor_execute", advance_on_purge)
    try:
        completed, outcome = teardown(k3, w.b, w.b1, "owner_b")
    finally:
        event.remove(w.db.runtime, "after_cursor_execute", advance_on_purge)
    assert completed == due + timedelta(seconds=1)
    assert outcome["deadline_met"] is False and outcome["revocation"] == "done"
    assert outcome["completed_at"] is not None
