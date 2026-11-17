"""Synthetic connector test lab shared by the connector integration tests (specification 009).

Synthetic fixture: agency A connects the same external account in clients A1 (K1) and A2 (K2),
and agency B connects it in client B1 (K3). The synthetic provider keeps its grants in a SQLite
file shared with the worker subprocess, so revocation is observed across processes. Only
synthetic identities and tokens are used, against the guarded disposable database.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.synthetic import SyntheticProvider
from app.models import ConnectorConnection, ConnectorRecord, ConnectorTokenSecret
from app.privacy.token_secrets import SealedSecret, SecretContext, open_secret
from app.services.connectors import ConnectorError, complete_authorization, process_connectors
from app.services.tenancy import tenancy_transaction

ACCOUNT = "syn-acct-777"


# Build the lab for one test from the authenticated synthetic world and API client factory.
def make_lab(authenticated_world, api, tmp_path):
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

    def finish(name, url, account=ACCOUNT, label="Synthetic Brand", client=None, kind="business"):
        code = provider.approve(url, account, label, kind)
        state_value = parse_qs(urlsplit(url).query)["state"][0]
        response = (client or browser(name)).get(
            "/connectors/oauth/callback",
            params={"code": code, "state": state_value},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}, location

    def connect(name, agency, client_id, account=ACCOUNT, kind="business"):
        result, _ = finish(name, start(name, agency, client_id), account, kind=kind)
        assert result["result"] == "connected", result
        return UUID(result["connection_id"])

    # One worker pass; the scheduling step runs only when a test asks for it.
    def worker(now=None, registry=None, limit=10, schedule=False, settings=None):
        return process_connectors(
            w.db.runtime,
            settings or config,
            registry or {"synthetic": provider},
            now=now,
            limit=limit,
            schedule=schedule,
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

    def sync(name, agency, client_id, connection_id, body=None):
        return browser(name).post(
            f"/agencies/{agency}/clients/{client_id}/connections/{connection_id}/sync", json=body
        )

    def binding(name):
        return browser(name).cookies.get("tracking_connector_oauth", path="/connectors/oauth")

    def complete(name, url, cookie, account=ACCOUNT, registry=None):
        code = provider.approve(url, account)
        try:
            outcome = complete_authorization(
                w.db.runtime,
                config,
                registry or {"synthetic": provider},
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


# Archive a client of the synthetic world (agency A by default).
def archive(w, client_id, agency=None, actor=None):
    with tenancy_transaction(w.db.runtime, actor or w.users.owner_a) as service:
        service.update_client(agency or w.a, client_id, status="archived")


# Simulates the worker process stopping (not a provider failure, so nothing catches it).
class WorkerStopped(BaseException):
    pass


# Make one connection require reconnection: its read is refused and its refresh rejected.
def fail_connection(lab, agency, client_id, connection_id, owner="owner_a"):
    lab.provider.set_behavior("fetch", "unauthorized")
    lab.provider.set_behavior("refresh", "invalid_grant")
    lab.sync(owner, agency, client_id, connection_id)
    assert lab.worker()["sync"] == {"stopped": 1}
    lab.provider.set_behavior("fetch", "ok")
    lab.provider.set_behavior("refresh", "ok")
