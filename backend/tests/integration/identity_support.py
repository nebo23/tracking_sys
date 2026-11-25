"""Synthetic identity fixtures for specification 006 integration tests (D-075).

Builds one agency with clients A1 and A2, a client-granted ingest key, a browser source per
client and helpers for browser- and server-issued collection subjects, handoffs, assertions and
events. Every value is synthetic (example.test addresses, fictional digit patterns).
"""

import json
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectedEvent
from app.security import now_utc
from app.services import identity

ORIGIN = "https://shop.example.test"
NOTICE = "b" * 64
ANALYTICS, ATTRIBUTION, IDENTITY = "analytics.first_party", "attribution", "identity_link"
ALL = {ANALYTICS: "granted", ATTRIBUTION: "granted", IDENTITY: "granted"}


def receipt_for(response: dict, choices: dict, purpose: str = IDENTITY) -> str:
    """The receipt ID of one purpose: receipts follow the sorted purpose order."""
    return response["receipts"][sorted(choices).index(purpose)]


def challenge() -> str:
    return secrets.token_urlsafe(24)


def count(db, model, *conditions) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def rows(db, query):
    with Session(db.migration, expire_on_commit=False) as session:
        return list(session.scalars(query))


def make_identity_world(authenticated_world, api) -> SimpleNamespace:
    w = authenticated_world
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    issued = owner.post(
        base + "/service-credentials",
        json={
            "name": "Synthetic identity ingest",
            "kind": "ingest",
            "clients": [{"client_id": str(w.a1)}, {"client_id": str(w.a2)}],
        },
    )
    assert issued.status_code == 201, issued.text
    ingest = api.new_client()
    ingest.headers["Authorization"] = "Bearer " + issued.json()["key"]
    credential_id = UUID(issued.json()["credential"]["id"])
    keys = {}
    for client_id in (w.a1, w.a2):
        source = owner.post(
            f"{base}/clients/{client_id}/ingestion-sources",
            json={
                "kind": "browser",
                "name": "Shop",
                "allowed_origins": [ORIGIN],
                "notice_sha256": NOTICE,
            },
        )
        assert source.status_code == 201, source.text
        keys[client_id] = source.json()["source"]["public_key"]
    public = api.new_client()
    public.headers["Origin"] = ORIGIN

    def public_post(path, body, client_id=w.a1):
        return public.post(
            f"/collect/v1/{keys[client_id]}/{path}",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )

    def browser_subject(choices=None, client_id=w.a1, token=None):
        choices = choices or ALL
        body = {"choices": choices}
        if token:
            body["subject_token"] = token
        response = public_post("consent", body, client_id)
        assert response.status_code == 200, response.text
        return response.json()

    def server_subject(choices=None, client_id=w.a1, token=None):
        choices = choices or ALL
        body = {"choices": choices, "notice_sha256": NOTICE}
        if token:
            body["subject_token"] = token
        response = ingest.post(f"{base}/clients/{client_id}/consent", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def handoff(token, value=None, client_id=w.a1):
        response = public_post(
            "identity-handoff",
            {"subject_token": token, "challenge": value or challenge()},
            client_id,
        )
        return response

    def issued_handoff(token, client_id=w.a1):
        value = challenge()
        response = handoff(token, value, client_id)
        assert response.status_code == 201, response.text
        return response.json()["code"], value

    def identifier(kind, value, method, verified_at=None):
        return {
            "kind": kind,
            "value": value,
            "method": method,
            "verified_at": (verified_at or now_utc() - timedelta(seconds=5)).isoformat(),
        }

    def assertion(identifiers, *, proof, assertion_id=None, client_id=w.a1, sender=ingest):
        body = {"assertion_id": str(assertion_id or uuid4()), "identifiers": identifiers, **proof}
        return sender.post(f"{base}/clients/{client_id}/identity-assertions", json=body)

    def via_browser(token, identifiers, client_id=w.a1, **extra):
        code, value = issued_handoff(token, client_id)
        return assertion(
            identifiers, proof={"handoff": code, "challenge": value}, client_id=client_id, **extra
        )

    def via_server(subject, choices, identifiers, client_id=w.a1, **extra):
        proof = {
            "subject_token": subject["subject_token"],
            "identity_consent_receipt_id": receipt_for(subject, choices),
        }
        return assertion(identifiers, proof=proof, client_id=client_id, **extra)

    def event(
        token,
        *,
        event_type="page_view",
        occurred_at=None,
        client_id=w.a1,
        trusted=False,
        payload=None,
        event_id=None,
    ):
        body = {
            "schema_version": 1,
            "event_id": str(event_id or uuid4()),
            "event_type": event_type,
            "occurred_at": (occurred_at or now_utc()).isoformat(),
            "subject_token": token,
            "payload": payload
            or (
                {"url": "https://shop.example.test/offer"}
                if event_type == "page_view"
                else {"action": "consultation_request"}
                if event_type == "lead_signal"
                else {}
            ),
        }
        if trusted:
            response = ingest.post(f"{base}/clients/{client_id}/events", json=body)
            assert response.status_code in {200, 201}, response.text
        else:
            response = public_post("events", body, client_id)
            assert response.status_code == 202, response.text
        return UUID(body["event_id"])

    def journey(person_id, client_id=w.a1):
        with Session(w.db.runtime) as session, session.begin():
            now = session.scalar(select(func.clock_timestamp()))
            return [
                item.event_id
                for item, _ in identity.journey_events(session, client_id, person_id, now)
            ]

    def event_row(event_id) -> CollectedEvent:
        return rows(w.db, select(CollectedEvent).where(CollectedEvent.event_id == event_id))[0]

    return SimpleNamespace(
        w=w,
        owner=owner,
        base=base,
        ingest=ingest,
        credential_id=credential_id,
        public=public,
        keys=keys,
        browser_subject=browser_subject,
        server_subject=server_subject,
        handoff=handoff,
        issued_handoff=issued_handoff,
        identifier=identifier,
        assertion=assertion,
        via_browser=via_browser,
        via_server=via_server,
        event=event,
        journey=journey,
        event_row=event_row,
        public_post=public_post,
    )


def iso(moment: datetime) -> str:
    return moment.isoformat()
