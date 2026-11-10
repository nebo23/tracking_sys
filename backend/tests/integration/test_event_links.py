"""Specification 005-C event link references and the consent-state read (D-033).

Disposable PostgreSQL only; every case checks stored rows or their absence. Synthetic values.
"""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.collection.contract import fingerprint
from app.models import (
    CollectedEvent,
    CollectionSubject,
    EventDiagnostic,
    ManagedLink,
    StoredConsentRecord,
    StoredTombstone,
)
from app.security import digest, now_utc
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration

ORIGIN = "https://shop.example.test"
STRANGER = "https://attacker.example.test"
NOTICE = "b" * 64
ANALYTICS, ATTRIBUTION = "analytics.first_party", "attribution"


def total(db, model, *conditions) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def stored(db, event_id) -> CollectedEvent | None:
    with Session(db.migration) as session:
        return session.scalar(select(CollectedEvent).where(CollectedEvent.event_id == event_id))


def envelope(token, *, link_id=None, event_id=None, url=None):
    body = {
        "schema_version": 1,
        "event_id": str(event_id or uuid4()),
        "event_type": "page_view",
        "occurred_at": now_utc().isoformat(),
        "subject_token": token,
        "payload": {"url": url or f"{ORIGIN}/offer?utm_source=site"},
    }
    if link_id is not None:
        body["link_id"] = str(link_id)
    return body


@pytest.fixture
def ev(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    key = owner.post(
        base + "/service-credentials",
        json={
            "name": "Ingest",
            "kind": "ingest",
            "clients": [{"client_id": str(w.a1)}, {"client_id": str(w.a2)}],
        },
    )
    assert key.status_code == 201, key.text
    ingest = api.new_client()
    ingest.headers["Authorization"] = "Bearer " + key.json()["key"]
    source = owner.post(
        f"{base}/clients/{w.a1}/ingestion-sources",
        json={
            "kind": "browser",
            "name": "Shop",
            "allowed_origins": [ORIGIN],
            "notice_sha256": NOTICE,
        },
    )
    assert source.status_code == 201, source.text
    public_key = source.json()["source"]["public_key"]

    def link(client_id, slug):
        path = f"{base}/clients/{client_id}"
        origin = owner.post(f"{path}/link-destination-origins", json={"origin": ORIGIN})
        assert origin.status_code in {201, 409}, origin.text
        created = owner.post(
            f"{path}/managed-links", json={"slug": slug, "destination": f"{ORIGIN}/offer"}
        )
        assert created.status_code == 201, created.text
        return UUID(created.json()["id"])

    own = link(w.a1, "own-link")
    second = owner.post(
        f"{base}/clients/{w.a1}/managed-links",
        json={"slug": "own-second", "destination": f"{ORIGIN}/second"},
    )
    assert second.status_code == 201, second.text
    second = second.json()["id"]
    foreign = link(w.a2, "foreign-link")
    public = api.new_client()
    public.headers["Origin"] = ORIGIN

    def subject(choices=None):
        body = {"choices": choices or {ANALYTICS: "granted"}, "notice_sha256": NOTICE}
        response = ingest.post(f"{base}/clients/{w.a1}/consent", json=body)
        assert response.status_code == 200, response.text
        return response.json()["subject_token"]

    def send(body):
        return ingest.post(f"{base}/clients/{w.a1}/events", json=body)

    def collect(route, body, client=public, content_type="application/json"):
        return client.post(
            f"/collect/v1/{public_key}/{route}",
            content=json.dumps(body),
            headers={"Content-Type": content_type},
        )

    return SimpleNamespace(
        w=w,
        api=api,
        db=w.db,
        owner=owner,
        base=base,
        own=own,
        second=UUID(second),
        foreign=foreign,
        public=public,
        public_key=public_key,
        subject=subject,
        send=send,
        collect=collect,
    )


def counter(ev, channel, outcome, reason) -> int:
    with Session(ev.db.migration) as session:
        return (
            session.scalar(
                select(EventDiagnostic.count).where(
                    EventDiagnostic.channel == channel,
                    EventDiagnostic.outcome == outcome,
                    EventDiagnostic.reason == reason,
                )
            )
            or 0
        )


def test_old_clients_keep_deduplicating_and_link_references_are_content(ev):
    token = ev.subject()
    old = envelope(token)
    assert ev.send(old).status_code == 201
    assert ev.send(old).json() == {"status": "duplicate", "revision": 1}
    row = stored(ev.db, UUID(old["event_id"]))
    assert row.link_id is None
    assert row.fingerprint == fingerprint(
        "page_view", row.occurred_at, row.subject_id, row.payload, False
    )
    claimed = ev.send({**old, "link_id": str(ev.own)})
    assert (claimed.status_code, claimed.json()) == (409, {"error": "event_conflict"})
    assert stored(ev.db, UUID(old["event_id"])).link_id is None
    linked = envelope(token, link_id=ev.own)
    assert ev.send(linked).status_code == 201
    assert ev.send(linked).json() == {"status": "duplicate", "revision": 1}
    assert ev.send({**linked, "link_id": str(ev.second)}).status_code == 409
    without = {key: value for key, value in linked.items() if key != "link_id"}
    assert ev.send(without).status_code == 409
    row = stored(ev.db, UUID(linked["event_id"]))
    assert (row.link_id, row.conflict_count) == (ev.own, 2)
    for reference in (ev.foreign, uuid4()):
        rejected = ev.send(envelope(token, link_id=reference))
        assert (rejected.status_code, rejected.json()) == (422, {"error": "unknown_link"})
    assert counter(ev, "server", "rejected", "unknown_link") == 2
    assert total(ev.db, CollectedEvent, CollectedEvent.link_id == ev.foreign) == 0
    disabled = ev.owner.patch(
        f"{ev.base}/clients/{ev.w.a1}/managed-links/{ev.own}", json={"status": "disabled"}
    )
    assert disabled.status_code == 200
    historical = envelope(token, link_id=ev.own)
    assert ev.send(historical).status_code == 201
    assert stored(ev.db, UUID(historical["event_id"])).link_id == ev.own


def test_public_link_claims_are_limited_trust_and_upgraded_by_trusted_copies(ev):
    token = ev.subject({ANALYTICS: "granted", ATTRIBUTION: "granted"})
    public_copy = envelope(token, link_id=ev.own)
    response = ev.collect("events", public_copy)
    assert (response.status_code, response.json()) == (202, {"status": "received"})
    row = stored(ev.db, UUID(public_copy["event_id"]))
    assert (row.channel, row.trust_rank, row.link_id) == ("browser", 1, ev.own)
    foreign = ev.collect("events", envelope(token, link_id=ev.foreign))
    assert (foreign.status_code, foreign.json()) == (202, {"status": "received"})
    assert counter(ev, "browser", "rejected", "unknown_link") == 1
    trusted = ev.send({**public_copy, "link_id": str(ev.second)})
    assert trusted.json() == {"status": "upgraded", "revision": 2}
    row = stored(ev.db, UUID(public_copy["event_id"]))
    assert (row.channel, row.trust_rank, row.link_id) == ("server", 2, ev.second)
    assert ev.collect("events", public_copy).status_code == 202
    row = stored(ev.db, UUID(public_copy["event_id"]))
    assert (row.link_id, row.revision, row.conflict_count) == (ev.second, 2, 1)
    assert total(ev.db, CollectedEvent) == 1


def test_erasure_and_lifecycle_remove_link_references_but_keep_configuration(
    ev, lifecycle_engine, lifecycle_settings, capfd
):
    token = ev.subject()
    body = envelope(token, link_id=ev.own)
    assert ev.collect("events", body).status_code == 202
    assert stored(ev.db, UUID(body["event_id"])).link_id == ev.own
    erased = ev.collect("erasure", {"subject_token": token})
    assert erased.status_code == 202
    assert stored(ev.db, UUID(body["event_id"])) is None
    assert total(ev.db, StoredTombstone) == 2
    assert total(ev.db, ManagedLink) == 3
    assert ev.collect("events", body).status_code == 202
    assert stored(ev.db, UUID(body["event_id"])) is None
    replay = ev.send(body)
    assert replay.json() == {"error": "subject_deleted"}
    again = ev.subject()
    aged = envelope(again, link_id=ev.second)
    assert ev.send(aged).status_code == 201
    cutoff = now_utc()
    with Session(ev.db.migration) as session, session.begin():
        session.execute(
            update(CollectedEvent)
            .where(CollectedEvent.event_id == UUID(aged["event_id"]))
            .values(expires_at=cutoff - timedelta(seconds=1))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
    assert result["status"] == "completed" and result["deleted"]["collected_events"] == 1
    assert total(ev.db, CollectedEvent, CollectedEvent.link_id.is_not(None)) == 0
    assert total(ev.db, ManagedLink) == 3
    visit = ev.api.new_client().get("/r/own-second", follow_redirects=False)
    assert visit.status_code == 302
    output = "".join(capfd.readouterr())
    for secret in (token, again, visit.headers["location"], "ts_link"):
        assert secret not in output


def state_snapshot(ev, token):
    with Session(ev.db.migration) as session:
        subject = session.scalar(
            select(CollectionSubject).where(CollectionSubject.token_digest == digest(token))
        )
        records = session.execute(
            select(StoredConsentRecord.id, StoredConsentRecord.expires_at).order_by(
                StoredConsentRecord.id
            )
        ).all()
        subjects = session.scalar(select(func.count()).select_from(CollectionSubject))
        counters = session.execute(
            select(EventDiagnostic.reason, EventDiagnostic.count).order_by(EventDiagnostic.reason)
        ).all()
    return subject.last_activity_at, records, subjects, counters


def test_consent_state_reads_current_consent_without_mutating_anything(ev):
    granted = ev.collect("consent", {"choices": {ANALYTICS: "granted"}})
    assert granted.status_code == 200
    token = granted.json()["subject_token"]
    before = state_snapshot(ev, token)
    for content_type in ("application/json", "text/plain;charset=UTF-8", "application/json"):
        read = ev.collect("consent-state", {"subject_token": token}, content_type=content_type)
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["status"] == "active"
        assert body["states"][ANALYTICS] == "granted"
        assert body["states"][ATTRIBUTION] == "unknown"
        assert set(body["expires_at"]) == {ANALYTICS}
        assert read.headers["access-control-allow-origin"] == ORIGIN
        assert read.headers["access-control-expose-headers"] == "Retry-After"
        assert "access-control-allow-credentials" not in read.headers
        assert read.headers["cache-control"] == "no-store"
        assert "subject_token" not in body
    assert state_snapshot(ev, token) == before
    unknown = ev.collect("consent-state", {"subject_token": "sbj_" + "Z" * 43}).json()
    assert unknown["status"] == "unknown" and set(unknown["states"].values()) == {"unknown"}
    assert unknown["expires_at"] == {}
    withdrawn = ev.collect("consent", {"choices": {ANALYTICS: "withdrawn"}, "subject_token": token})
    assert withdrawn.status_code == 200
    assert (
        ev.collect("consent-state", {"subject_token": token}).json()["states"][ANALYTICS]
        == "withdrawn"
    )
    regrant = ev.collect("consent", {"choices": {ANALYTICS: "granted"}, "subject_token": token})
    assert regrant.status_code == 200
    with Session(ev.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.state == "granted")
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
    expired = ev.collect("consent-state", {"subject_token": token}).json()
    assert expired["states"][ANALYTICS] == "expired" and expired["expires_at"] == {}
    assert ev.collect("erasure", {"subject_token": token}).status_code == 202
    erased = ev.collect("consent-state", {"subject_token": token}).json()
    assert {key: erased[key] for key in ("status", "states", "expires_at")} == {
        key: unknown[key] for key in ("status", "states", "expires_at")
    }
    assert total(ev.db, CollectionSubject) == 0


def test_consent_state_enforces_origin_body_and_its_own_rate_limit(ev):
    token = ev.collect("consent", {"choices": {ANALYTICS: "granted"}}).json()["subject_token"]
    path = f"/collect/v1/{ev.public_key}/consent-state"
    # The persistent limiter counts per source and peer, so measure it before other reads.
    limited = ev.api.config.model_copy(update={"consent_state_per_minute": 2})
    client = ev.api.new_client(limited)
    client.headers["Origin"] = ORIGIN
    statuses = [
        ev.collect("consent-state", {"subject_token": token}, client=client) for _ in range(3)
    ]
    assert [item.status_code for item in statuses] == [200, 200, 429]
    assert int(statuses[2].headers["retry-after"]) >= 1
    assert statuses[2].headers["access-control-allow-origin"] == ORIGIN
    assert statuses[2].headers["access-control-expose-headers"] == "Retry-After"
    preflight = ev.public.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == ORIGIN
    stranger = ev.api.new_client()
    stranger.headers["Origin"] = STRANGER
    denied = ev.collect("consent-state", {"subject_token": token}, client=stranger)
    assert denied.status_code == 403
    assert "access-control-allow-origin" not in denied.headers
    assert "access-control-expose-headers" not in denied.headers
    assert ev.public.get(path).status_code == 405
    assert ev.public.post(path + f"?subject_token={token}", json={}).status_code == 422
    assert ev.collect("consent-state", {"subject_token": token, "extra": 1}).status_code == 422
    events_still = ev.collect("events", envelope(token), client=client)
    assert events_still.status_code == 202  # separate bucket from event intake
    ev.owner.patch(
        f"{ev.base}/clients/{ev.w.a1}/ingestion-sources/"
        f"{ev.owner.get(f'{ev.base}/clients/{ev.w.a1}/ingestion-sources').json()[0]['id']}",
        json={"status": "disabled"},
    )
    assert ev.collect("consent-state", {"subject_token": token}).status_code == 404
    platform = ev.api.new_client().get("/health/live")
    assert "access-control-expose-headers" not in platform.headers
