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
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.connectors.contracts import ProviderError
from app.connectors.synthetic import SyntheticProvider
from app.models import (
    AuditEvent,
    ConnectorConnection,
    ConnectorOAuthTransaction,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorTokenSecret,
)
from app.privacy.token_secrets import SealedSecret, SecretContext, open_secret
from app.security import now_utc
from app.services.connectors import (
    ConnectorError,
    complete_authorization,
    process_connectors,
)
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import Role, tenancy_transaction

pytestmark = pytest.mark.integration
ACCOUNT = "syn-acct-777"


@pytest.fixture
def lab(authenticated_world, api, tmp_path):
    w = authenticated_world
    state = tmp_path / "synthetic-provider.sqlite3"
    config = api.config.model_copy(update={"connector_synthetic_state": state})
    provider = SyntheticProvider(state)
    clients = {}

    def browser(name):
        if name not in clients:
            client = api.new_client(config)
            api.login(client, f"{name}@example.test")
            clients[name] = client
        return clients[name]

    def start(name, agency, client_id, connection_id=None):
        client = browser(name)
        base = f"/agencies/{agency}/clients/{client_id}/connections"
        if connection_id is None:
            response = client.post(base, json={"provider": "synthetic"})
        else:
            response = client.post(f"{base}/{connection_id}/reconnect")
        assert response.status_code == 200, response.text
        return response.json()["authorization_url"]

    def finish(name, url, account=ACCOUNT, label="Synthetic Brand", client=None):
        code = provider.approve(url, account, label)
        state_value = parse_qs(urlsplit(url).query)["state"][0]
        response = (client or browser(name)).get(
            "/connectors/oauth/callback",
            params={"code": code, "state": state_value},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}, location

    def connect(name, agency, client_id, account=ACCOUNT):
        result, _ = finish(name, start(name, agency, client_id), account)
        assert result["result"] == "connected", result
        return UUID(result["connection_id"])

    def worker(now=None, registry=None):
        return process_connectors(
            w.db.runtime, config, registry or {"synthetic": provider}, now=now
        )

    def row(connection_id):
        with Session(w.db.migration) as session:
            return session.get(ConnectorConnection, connection_id)

    def secrets(connection_id):
        with Session(w.db.migration) as session:
            return list(
                session.scalars(
                    select(ConnectorTokenSecret)
                    .where(ConnectorTokenSecret.connection_id == connection_id)
                    .order_by(ConnectorTokenSecret.kind, ConnectorTokenSecret.version)
                )
            )

    def tokens(connection_id):
        keyring = config.token_keys()
        opened = {}
        for item in secrets(connection_id):
            if item.status == "destroyed":
                continue
            context = SecretContext(
                item.agency_id, item.client_id, item.connection_id, item.id, item.kind, item.version
            )
            sealed = SealedSecret(
                item.kek_id, item.wrap_nonce, item.wrapped_dek, item.nonce, item.ciphertext
            )
            opened[item.kind] = open_secret(keyring, sealed, context)
        return opened

    def records(connection_id):
        with Session(w.db.migration) as session:
            return session.scalar(
                select(func.count())
                .select_from(ConnectorRecord)
                .where(ConnectorRecord.connection_id == connection_id)
            )

    def view(name, agency, client_id, connection_id):
        return browser(name).get(
            f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}"
        )

    def disconnect(name, agency, client_id, connection_id):
        return browser(name).post(
            f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/disconnect"
        )

    def sync(name, agency, client_id, connection_id):
        return browser(name).post(
            f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/sync"
        )

    def binding(name):
        return browser(name).cookies.get("tracking_connector_oauth", path="/connectors/oauth")

    def complete(name, url, cookie, account=ACCOUNT):
        code = provider.approve(url, account)
        try:
            outcome = complete_authorization(
                w.db.runtime,
                config,
                {"synthetic": provider},
                parse_qs(urlsplit(url).query)["state"][0],
                cookie,
                code,
                browser(name).cookies.get("tracking_session"),
            )
        except ConnectorError as error:
            return error.code
        return outcome.connection_id

    def fixtures():
        k1 = connect("owner_a", w.a, w.a1)
        k2 = connect("owner_a", w.a, w.a2)
        k3 = connect("owner_b", w.b, w.b1)
        return k1, k2, k3

    return SimpleNamespace(
        w=w,
        config=config,
        provider=provider,
        browser=browser,
        start=start,
        finish=finish,
        connect=connect,
        worker=worker,
        row=row,
        secrets=secrets,
        tokens=tokens,
        records=records,
        view=view,
        disconnect=disconnect,
        sync=sync,
        fixtures=fixtures,
        state=state,
        binding=binding,
        complete=complete,
    )


def _archive(w, client_id, agency=None, actor=None):
    with tenancy_transaction(w.db.runtime, actor or w.users.owner_a) as service:
        service.update_client(agency or w.a, client_id, status="archived")


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
    keyring = lab.config.token_keyring.get_secret_value()
    environment = {
        **os.environ,
        "TRACKING_TOKEN_KEYRING": keyring,
        "TRACKING_TOKEN_KEYRING_ACTIVE": lab.config.token_keyring_active,
        "TRACKING_CONNECTOR_SYNTHETIC_STATE": str(lab.state),
    }
    completed = subprocess.run(
        [sys.executable, "-m", "app.connector_worker"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"teardown": {"disconnected": 1}, "sync": {}}

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
    assert lab.provider.fetch_page(k2_tokens["access_token"])
    assert lab.provider.fetch_page(k3_tokens["access_token"])
    assert lab.sync("owner_a", w.a, w.a2, k2).status_code == 202
    assert lab.sync("owner_b", w.b, w.b1, k3).status_code == 202
    completed = subprocess.run(
        [sys.executable, "-m", "app.connector_worker"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert json.loads(completed.stdout) == {"teardown": {}, "sync": {"succeeded": 2}}
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


# Simulates the worker process stopping (not a provider failure, so nothing catches it).
class WorkerStopped(BaseException):
    pass


class _Hooked(SyntheticProvider):
    def __init__(self, path, **hooks):
        super().__init__(path)
        self.hooks = hooks

    def fetch_page(self, access_token):
        records = super().fetch_page(access_token)
        if "fetch" in self.hooks:
            self.hooks.pop("fetch")()
        return records

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
