"""Specification 004 event collection on disposable PostgreSQL (D-027).

Every case asserts stored rows (or their absence), not only HTTP status codes. Synthetic
values only; no provider is contacted.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.collection.contract import Envelope, sign_webhook
from app.config import BACKEND_ROOT
from app.database import expected_revision
from app.models import (
    AuditEvent,
    ClientWorkspace,
    CollectedEvent,
    CollectionSubject,
    EventDiagnostic,
    IngestionSourceSecret,
    StoredConsentRecord,
    StoredTombstone,
    SubjectDeletionRequest,
)
from app.privacy.consent import ConsentSource, ConsentState, Purpose
from app.privacy.deletion import RequesterKind
from app.security import digest, now_utc
from app.services import collection as collection_service
from app.services.collection import (
    LOCK_NAMESPACE,
    Channel,
    admit,
    consent_view,
    erase_subject,
    record_consent,
)
from app.services.lifecycle import delete_client_batch, run_lifecycle, targets

pytestmark = pytest.mark.integration

ORIGIN = "https://shop.example.test"
NOTICE = "a" * 64
CARD = "4111 1111 1111 1111"
ANALYTICS, ATTRIBUTION = "analytics.first_party", "attribution"


def lock_key(client_id: UUID) -> int:
    return int.from_bytes(client_id.bytes[:4], "big", signed=True)


def select_rows(db, query):
    with Session(db.migration) as session:
        return list(session.scalars(query))


def count_rows(db, model, *conditions) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


def envelope(token, *, event_type="page_view", payload=None, event_id=None, **extra):
    return {
        "schema_version": 1,
        "event_id": str(event_id or uuid4()),
        "event_type": event_type,
        "occurred_at": (extra.pop("occurred_at", None) or now_utc()).isoformat(),
        "subject_token": token,
        "payload": payload or {"url": "https://shop.example.test/offer?utm_source=demo"},
        **extra,
    }


@pytest.fixture
def c(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    base = f"/agencies/{w.a}"
    issued = owner.post(
        base + "/service-credentials",
        json={
            "name": "Synthetic ingest",
            "kind": "ingest",
            "clients": [{"client_id": str(w.a1)}, {"client_id": str(w.a2)}],
        },
    )
    assert issued.status_code == 201, issued.text
    assert issued.json()["credential"]["kind"] == "ingest"
    ingest = api.new_client()
    ingest.headers["Authorization"] = "Bearer " + issued.json()["key"]
    browser = owner.post(
        f"{base}/clients/{w.a1}/ingestion-sources",
        json={
            "kind": "browser",
            "name": "Shop",
            "allowed_origins": [ORIGIN],
            "notice_sha256": NOTICE,
        },
    )
    assert browser.status_code == 201, browser.text
    hook = owner.post(
        f"{base}/clients/{w.a1}/ingestion-sources", json={"kind": "webhook", "name": "Hook"}
    )
    assert hook.status_code == 201, hook.text
    public = api.new_client()
    public.headers["Origin"] = ORIGIN

    def consent(choices, *, token=None, client_id=w.a1, sender=ingest):
        body = {"choices": choices, "notice_sha256": NOTICE}
        if token:
            body["subject_token"] = token
        response = sender.post(f"{base}/clients/{client_id}/consent", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def subject(choices=None, client_id=w.a1):
        return consent(
            choices or {ANALYTICS: "granted", ATTRIBUTION: "granted"}, client_id=client_id
        )["subject_token"]

    def send(body, *, client_id=w.a1, sender=ingest):
        return sender.post(f"{base}/clients/{client_id}/events", json=body)

    def collect(body, *, client=public, content_type="application/json"):
        return client.post(
            f"/collect/v1/{browser.json()['source']['public_key']}/events",
            content=json.dumps(body),
            headers={"Content-Type": content_type},
        )

    def webhook(body, *, secret=None, stamp=None, raw=None):
        raw = raw if raw is not None else json.dumps(body).encode()
        stamp = stamp if stamp is not None else int(time.time())
        signature = sign_webhook(secret or hook.json()["signing_secret"], stamp, raw)
        return api.new_client().post(
            f"/webhooks/v1/{hook.json()['source']['id']}/events",
            content=raw,
            headers={"X-Tracking-Signature": f"t={stamp},v1={signature}"},
        )

    return SimpleNamespace(
        w=w,
        api=api,
        db=w.db,
        owner=owner,
        base=base,
        ingest=ingest,
        credential_id=UUID(issued.json()["credential"]["id"]),
        public=public,
        public_key=browser.json()["source"]["public_key"],
        browser_id=UUID(browser.json()["source"]["id"]),
        hook_id=UUID(hook.json()["source"]["id"]),
        secret=hook.json()["signing_secret"],
        consent=consent,
        subject=subject,
        send=send,
        collect=collect,
        webhook=webhook,
    )


def events(c, client_id=None):
    return select_rows(
        c.db,
        select(CollectedEvent)
        .where(CollectedEvent.client_id == (client_id or c.w.a1))
        .order_by(CollectedEvent.first_received_at),
    )


def counters(c, client_id=None) -> dict[tuple[str, str, str], int]:
    rows = select_rows(
        c.db, select(EventDiagnostic).where(EventDiagnostic.client_id == (client_id or c.w.a1))
    )
    return {(row.channel, row.outcome, row.reason): row.count for row in rows}


def test_ingest_and_read_keys_never_substitute(c):
    w, api = c.w, c.api
    assert c.ingest.get(f"{c.base}/clients/{w.a1}").status_code == 401
    assert c.ingest.get(f"{c.base}/clients").status_code == 401
    reader_key = c.owner.post(
        c.base + "/service-credentials",
        json={"name": "Reader", "clients": [{"client_id": str(w.a1)}]},
    ).json()
    assert reader_key["credential"]["kind"] == "read"
    reader = api.new_client()
    reader.headers["Authorization"] = "Bearer " + reader_key["key"]
    token = c.subject()
    assert c.send(envelope(token), sender=reader).status_code == 401
    assert reader.get(f"{c.base}/clients/{w.a1}").status_code == 200
    denied = c.owner.post(
        c.base + "/service-credentials",
        json={
            "name": "Financial ingest",
            "kind": "ingest",
            "clients": [{"client_id": str(w.a1), "can_view_financials": True}],
        },
    )
    assert denied.status_code == 422
    assert c.send(envelope(token), client_id=w.b1).status_code == 403
    foreign = c.ingest.post(f"/agencies/{w.b}/clients/{w.b1}/events", json=envelope(token))
    assert foreign.status_code == 403
    both = api.new_client()
    both.headers["Authorization"] = c.ingest.headers["Authorization"]
    both.cookies.set("tracking_session", "synthetic")
    assert c.send(envelope(token), sender=both).status_code == 401
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(ClientWorkspace).where(ClientWorkspace.id == w.a1).values(status="archived")
        )
    assert c.send(envelope(token)).status_code == 403
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(ClientWorkspace).where(ClientWorkspace.id == w.a1).values(status="active")
        )
    revoked = c.owner.delete(f"{c.base}/service-credentials/{c.credential_id}")
    assert revoked.status_code == 204
    assert c.send(envelope(token)).status_code == 401
    assert events(c) == []


def test_trusted_intake_deduplicates_and_counts_conflicts(c):
    token = c.subject()
    body = envelope(token)
    first = c.send(body)
    assert (first.status_code, first.json()) == (201, {"status": "accepted", "revision": 1})
    again = c.send(body)
    assert (again.status_code, again.json()) == (200, {"status": "duplicate", "revision": 1})
    changed = dict(body, payload={"url": "https://shop.example.test/other"})
    assert c.send(changed).json() == {"error": "event_conflict"}
    [row] = events(c)
    assert row.payload == {"url": "https://shop.example.test/offer?utm_source=demo"}
    assert (row.channel, row.trust_rank, row.revision, row.conflict_count) == ("server", 2, 1, 1)
    assert row.credential_id == c.credential_id and row.source_id is None
    assert row.expires_at - row.first_received_at == timedelta(days=395)
    assert row.traffic_label == "unclassified"
    assert counters(c)[("server", "accepted", "new")] == 1
    assert counters(c)[("server", "duplicate", "identical")] == 1
    assert counters(c)[("server", "conflict", "changed_content")] == 1


def test_bounds_reject_oversized_batched_and_mistimed_events_without_side_effects(c):
    token = c.subject()
    oversized = envelope(token, payload={"url": "https://shop.example.test/" + "a" * 17000})
    assert c.send(oversized).status_code == 413
    assert c.collect(oversized).status_code == 413
    batch = c.ingest.post(f"{c.base}/clients/{c.w.a1}/events", json=[envelope(token)])
    assert batch.status_code == 422
    future = envelope(token, occurred_at=now_utc() + timedelta(minutes=6))
    assert c.send(future).json() == {"error": "occurred_at_out_of_range"}
    late_time = now_utc() - timedelta(days=6, hours=23)
    late = envelope(token, occurred_at=late_time)
    assert c.send(late).status_code == 201
    [row] = events(c)
    assert row.occurred_at == late_time
    assert row.first_received_at - row.occurred_at > timedelta(days=6)
    assert counters(c)[("server", "rejected", "occurred_at_out_of_range")] == 1


def test_consent_gates_storage_and_withdrawal_suppresses_retries(c):
    token = c.subject({ATTRIBUTION: "granted"})
    page = envelope(token)
    assert c.send(page).json() == {"error": "consent_unknown"}
    lead = envelope(token, event_type="lead_signal", payload={"action": "book_call"})
    assert c.send(lead).status_code == 201
    c.consent({ANALYTICS: "granted"}, token=token)
    assert c.send(page).status_code == 201
    c.consent({ANALYTICS: "withdrawn"}, token=token)
    assert c.send(page).json() == {"error": "consent_withdrawn"}
    assert c.send(envelope(token)).json() == {"error": "consent_withdrawn"}
    c.consent({ANALYTICS: "denied"}, token=token)
    assert c.send(envelope(token)).json() == {"error": "consent_denied"}
    assert len(events(c)) == 2
    [stored] = [row for row in events(c) if row.event_type == "lead_signal"]
    [grant] = select_rows(
        c.db,
        select(StoredConsentRecord).where(
            StoredConsentRecord.purpose == ATTRIBUTION, StoredConsentRecord.state == "granted"
        ),
    )
    assert stored.consent_basis == [grant.id]
    assert grant.expires_at - grant.received_at == timedelta(days=365)
    assert grant.source == "api" and grant.notice_sha256 == NOTICE
    assert counters(c)[("server", "suppressed", "consent_withdrawn")] == 2
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.id == grant.id)
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
    lead2 = envelope(token, event_type="lead_signal", payload={"action": "book_call"})
    assert c.send(lead2).json() == {"error": "consent_expired"}


def test_subjects_exist_only_after_a_grant_and_stay_in_their_client(c):
    nothing = c.consent({ANALYTICS: "denied", ATTRIBUTION: "denied"})
    assert nothing["subject_token"] is None and nothing["receipts"] == []
    assert count_rows(c.db, CollectionSubject) == 0
    assert count_rows(c.db, StoredConsentRecord) == 0
    granted = c.consent({ANALYTICS: "granted"})
    assert granted["states"][ANALYTICS] == "granted" and granted["states"][ATTRIBUTION] == "unknown"
    token, w = granted["subject_token"], c.w
    [subject] = select_rows(c.db, select(CollectionSubject))
    assert token not in json.dumps([subject.token_digest, str(subject.id)])
    event_id = uuid4()
    assert c.send(envelope(token, event_id=event_id), client_id=w.a2).json() == {
        "error": "unknown_subject"
    }
    other = c.subject(client_id=w.a2)
    assert c.send(envelope(token, event_id=event_id)).status_code == 201
    assert c.send(envelope(other, event_id=event_id), client_id=w.a2).status_code == 201
    assert len(events(c)) == 1 and len(events(c, w.a2)) == 1
    assert c.ingest.post(
        f"{c.base}/clients/{w.a1}/consent",
        json={"choices": {ANALYTICS: "granted"}, "subject_token": other, "notice_sha256": NOTICE},
    ).json() == {"error": "unknown_subject"}
    missing_notice = c.ingest.post(
        f"{c.base}/clients/{w.a1}/consent", json={"choices": {ANALYTICS: "granted"}}
    )
    assert missing_notice.status_code == 422


def test_click_identifiers_need_attribution_and_forms_keep_only_mapped_classes(c, capfd):
    url = "https://shop.example.test/p?utm_source=ads&gclid=G-1&q=private#frag"
    analytics_only = c.subject({ANALYTICS: "granted"})
    assert c.send(envelope(analytics_only, payload={"url": url})).status_code == 201
    both = c.subject()
    assert c.send(envelope(both, payload={"url": url})).status_code == 201
    stored = {row.subject_id: row.payload["url"] for row in events(c)}
    assert sorted(stored.values()) == [
        "https://shop.example.test/p?utm_source=ads",
        "https://shop.example.test/p?utm_source=ads&gclid=G-1",
    ]
    assert counters(c)[("server", "minimized", "click_identifier")] == 1
    form = c.owner.put(
        f"{c.base}/clients/{c.w.a1}/collection-forms/lead",
        json={
            "fields": [
                {"name": "plan", "data_class": "form.option", "options": ["basic", "pro"]},
                {"name": "promo", "data_class": "form.code"},
                {"name": "card_number", "data_class": "form.code"},
                {"name": "pass", "data_class": "form.code", "input_type": "password"},
            ]
        },
    )
    assert form.status_code == 200 and form.json()["version"] == 1
    submitted = {
        "plan": "pro",
        "promo": CARD.replace(" ", ""),
        "card_number": "SAVE10",
        "pass": "Synthetic secret value 1",
        "cc-csc": "123",
        "message": f"my card is {CARD}",
    }
    body = envelope(
        both,
        event_type="form_submit",
        payload={"url": "https://shop.example.test/f", "form_key": "lead", "fields": submitted},
    )
    assert c.send(body).status_code == 201
    [row] = [item for item in events(c) if item.event_type == "form_submit"]
    assert row.payload["fields"] == {"plan": "pro"}
    with c.db.migration.connect() as connection:
        dump = " ".join(
            connection.execute(
                text(f"SELECT coalesce(string_agg(t::text, ' '), '') FROM {table} t")
            ).scalar_one()
            for table in ("collected_events", "event_diagnostics", "consent_records")
        )
    for secret in ("4111111111111111", CARD, "SAVE10", "Synthetic secret value 1", "my card"):
        assert secret not in dump
    output = capfd.readouterr()
    assert "4111" not in output.out + output.err and "Synthetic secret" not in output.err
    unknown = envelope(
        both,
        event_type="form_submit",
        payload={"url": "https://shop.example.test/f", "form_key": "missing", "fields": {}},
    )
    assert c.send(unknown).json() == {"error": "unknown_form"}
    path = envelope(both, payload={"url": "https://shop.example.test/u/someone@example.test"})
    assert c.send(path).json() == {"error": "url_identifier"}


def test_public_intake_is_limited_trust_and_indistinguishable(c):
    token = c.subject()
    body = envelope(token)
    received = {"status": "received"}
    first = c.collect(body, content_type="text/plain;charset=UTF-8")
    assert (first.status_code, first.json()) == (202, received)
    for variant in [
        body,
        dict(body, payload={"url": "https://shop.example.test/changed"}),
        envelope("sbj_" + "B" * 43),
        dict(envelope(token), internal=True),
    ]:
        response = c.collect(variant)
        assert (response.status_code, response.json()) == (202, received)
    [row] = events(c)
    assert (row.channel, row.trust_rank, row.source_id) == ("browser", 1, c.browser_id)
    assert row.conflict_count == 1
    assert counters(c)[("browser", "rejected", "internal_flag_untrusted")] == 1
    assert counters(c)[("browser", "rejected", "unknown_subject")] == 1
    wrong_origin = c.api.new_client()
    wrong_origin.headers["Origin"] = "https://attacker.example.test"
    assert c.collect(body, client=wrong_origin).status_code == 403
    no_origin = c.api.new_client()
    no_origin.headers.pop("Origin", None)
    assert c.collect(body, client=no_origin).status_code == 403
    unknown = c.public.post(f"/collect/v1/pk_{'x' * 43}/events", json=body)
    assert unknown.status_code == 404
    bot = c.api.new_client()
    bot.headers.update({"Origin": ORIGIN, "User-Agent": "Googlebot/2.1"})
    assert c.collect(envelope(token), client=bot).status_code == 202
    assert sorted(row.traffic_label for row in events(c)) == ["bot_suspected", "unclassified"]
    disabled = c.owner.patch(
        f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.browser_id}", json={"status": "disabled"}
    )
    assert disabled.status_code == 200
    assert c.collect(envelope(token)).status_code == 404
    assert len(events(c)) == 2


def test_public_consent_uses_the_registered_notice_and_issues_a_token(c):
    path = f"/collect/v1/{c.public_key}/consent"
    response = c.public.post(
        path,
        content=json.dumps({"choices": {ANALYTICS: "granted"}}),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["subject_token"]
    assert token.startswith("sbj_")
    [record] = select_rows(c.db, select(StoredConsentRecord))
    assert (record.source, record.notice_sha256) == ("tracker_banner", NOTICE)
    attested = c.public.post(
        path, json={"choices": {ANALYTICS: "granted"}, "notice_sha256": "b" * 64}
    )
    assert attested.status_code == 422
    assert c.collect(envelope(token)).status_code == 202
    assert len(events(c)) == 1


def test_trusted_copy_upgrades_public_but_public_never_overwrites(c):
    token, other = c.subject(), c.subject()
    event_id = uuid4()
    browser_copy = envelope(token, event_id=event_id)
    assert c.collect(browser_copy).status_code == 202
    server_copy = dict(browser_copy, payload={"url": "https://shop.example.test/verified"})
    upgraded = c.send(server_copy)
    assert (upgraded.status_code, upgraded.json()) == (200, {"status": "upgraded", "revision": 2})
    [row] = events(c)
    assert (row.channel, row.trust_rank, row.revision) == ("server", 2, 2)
    assert row.payload == {"url": "https://shop.example.test/verified"}
    assert row.first_received_at < row.last_received_at
    assert c.collect(browser_copy).status_code == 202
    [row] = events(c)
    assert (row.revision, row.conflict_count) == (2, 1)
    assert row.payload == {"url": "https://shop.example.test/verified"}
    mismatch = envelope(other, event_id=event_id)
    assert c.send(mismatch).json() == {"error": "event_conflict"}
    assert counters(c)[("server", "conflict", "identity_mismatch")] == 1
    second = uuid4()
    assert c.send(envelope(token, event_id=second)).status_code == 201
    hook = c.webhook(
        envelope(token, event_id=second, payload={"url": "https://shop.example.test/w"})
    )
    assert hook.json() == {"error": "event_conflict"}


def test_webhook_signature_precedes_parsing_and_rotation_overlaps(c):
    token = c.subject()
    body = envelope(token)
    accepted = c.webhook(body)
    assert accepted.status_code == 201, accepted.text
    [row] = events(c)
    assert (row.channel, row.source_id, row.trust_rank) == ("webhook", c.hook_id, 2)
    raw = b'{"not": "valid json'
    assert c.webhook(None, raw=raw, secret="whsec_wrong").json() == {"error": "signature_invalid"}
    stale = c.webhook(envelope(token), stamp=int(time.time()) - 301)
    assert stale.json() == {"error": "signature_expired"}
    signed = json.dumps(envelope(token)).encode()
    stamp = int(time.time())
    tampered = c.api.new_client().post(
        f"/webhooks/v1/{c.hook_id}/events",
        content=signed + b" ",
        headers={"X-Tracking-Signature": f"t={stamp},v1={sign_webhook(c.secret, stamp, signed)}"},
    )
    assert tampered.status_code == 401
    assert len(events(c)) == 1
    rotated = c.owner.post(f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.hook_id}/secret")
    assert rotated.status_code == 201
    new_secret = rotated.json()["signing_secret"]
    assert c.webhook(envelope(token)).status_code == 201
    assert c.webhook(envelope(token), secret=new_secret).status_code == 201
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(IngestionSourceSecret)
            .where(IngestionSourceSecret.version == 1)
            .values(retires_at=now_utc() - timedelta(seconds=1))
        )
    assert c.webhook(envelope(token)).status_code == 401
    assert c.webhook(envelope(token), secret=new_secret).status_code == 201
    stored = select_rows(c.db, select(IngestionSourceSecret.ciphertext))
    assert all(new_secret.encode() not in item and c.secret.encode() not in item for item in stored)
    actions = select_rows(
        c.db, select(AuditEvent.action).where(AuditEvent.resource_type == "source")
    )
    assert sorted(actions) == ["source.created", "source.created", "source.secret_rotated"]
    disabled = c.owner.patch(
        f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.hook_id}", json={"status": "disabled"}
    )
    assert disabled.status_code == 200
    assert c.webhook(envelope(token), secret=new_secret).status_code == 404


def test_erasure_removes_subject_data_and_tombstones_block_every_replay(c):
    token, keep = c.subject(), c.subject()
    first, second = (
        envelope(token),
        envelope(token, event_type="lead_signal", payload={"action": "x"}),
    )
    for body in (first, second, envelope(keep)):
        assert c.send(body).status_code == 201
    analyst = c.w.signed_in("analyst")
    denied = analyst.post(
        f"{c.base}/clients/{c.w.a1}/deletion-requests", json={"event_id": first["event_id"]}
    )
    assert denied.status_code == 403
    erased = c.owner.post(
        f"{c.base}/clients/{c.w.a1}/deletion-requests", json={"event_id": first["event_id"]}
    )
    assert erased.status_code == 201, erased.text
    request = erased.json()
    assert request["status"] == "completed" and request["requester_kind"] == "agency_admin"
    assert request["target_outcomes"] == {
        "collected_events": "done",
        "consent_records": "done",
        "collection_subjects": "done",
        "event_diagnostics": "not_applicable",
    }
    assert len(events(c)) == 1
    assert count_rows(c.db, CollectionSubject) == 1
    assert count_rows(c.db, StoredConsentRecord) == 2
    tombstones = select_rows(c.db, select(StoredTombstone))
    assert sorted(item.match_type for item in tombstones) == [
        "event_id",
        "event_id",
        "subject_token",
    ]
    keys = c.api.config.tombstone_keys()
    assert all(item.match_key_id == keys.active for item in tombstones)
    assert {bytes(item.match_key) for item in tombstones} == {
        keys.seal(c.w.a1, "subject_token", digest(token))[0],
        keys.seal(c.w.a1, "event_id", first["event_id"])[0],
        keys.seal(c.w.a1, "event_id", second["event_id"])[0],
    }
    assert c.send(envelope(token)).json() == {"error": "subject_deleted"}
    fresh = c.subject()
    replay = dict(first, subject_token=fresh)
    assert c.send(replay).json() == {"error": "replay_before_deletion"}
    assert c.collect(replay).status_code == 202
    assert c.webhook(dict(second, subject_token=fresh)).json() == {
        "error": "replay_before_deletion"
    }
    assert c.send(envelope(fresh)).status_code == 201
    assert len(events(c)) == 2
    audit = select_rows(
        c.db, select(AuditEvent.action).where(AuditEvent.resource_type == "deletion_request")
    )
    assert audit == ["deletion.requested"]
    self_erasure = c.public.post(
        f"/collect/v1/{c.public_key}/erasure", json={"subject_token": fresh}
    )
    assert (self_erasure.status_code, self_erasure.json()) == (202, {"status": "received"})
    [request_row] = select_rows(
        c.db,
        select(SubjectDeletionRequest).where(
            SubjectDeletionRequest.requester_kind == "data_subject"
        ),
    )
    assert request_row.requested_by_user_id is None and request_row.status == "completed"
    assert (
        c.public.post(
            f"/collect/v1/{c.public_key}/erasure", json={"subject_token": fresh}
        ).status_code
        == 202
    )
    assert len(events(c)) == 1


def wait_for_blocked_lock(db, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    with db.migration.connect() as connection:
        while time.monotonic() < deadline:
            waiting = connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                    "AND classid = :namespace AND NOT granted"
                ),
                {"namespace": LOCK_NAMESPACE},
            ).scalar_one()
            if waiting:
                return
            time.sleep(0.02)
    raise AssertionError("The request never waited for the client lock.")


def test_withdrawal_in_flight_serializes_before_a_concurrent_event(c):
    token = c.subject()
    with Session(c.db.runtime) as session:
        session.begin()
        record_consent(
            session,
            c.w.a,
            c.w.a1,
            source=ConsentSource.API,
            notice_sha256=NOTICE,
            choices={Purpose.ANALYTICS: ConsentState.WITHDRAWN},
            subject_token=token,
            captured_at=None,
            recheck=lambda: None,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(c.send, envelope(token))
            wait_for_blocked_lock(c.db)
            assert not pending.done()
            session.commit()
            response = pending.result(timeout=10)
    assert response.json() == {"error": "consent_withdrawn"}
    assert events(c) == []


def test_erasure_in_flight_wins_over_a_concurrent_event(c):
    token = c.subject()
    body = envelope(token)
    assert c.send(body).status_code == 201
    with Session(c.db.runtime) as session:
        session.begin()
        erase_subject(
            session,
            c.api.config,
            c.w.a,
            c.w.a1,
            requester=RequesterKind.DATA_SUBJECT,
            subject_token=token,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(c.send, envelope(token))
            wait_for_blocked_lock(c.db)
            session.commit()
            response = pending.result(timeout=10)
    assert response.json() == {"error": "subject_deleted"}
    assert events(c) == []


def test_concurrent_identical_retries_store_one_row(c):
    token = c.subject()
    body = envelope(token)
    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = sorted(executor.map(lambda _: c.send(body).status_code, range(4)))
    assert statuses == [200, 200, 200, 201]
    assert len(events(c)) == 1


def test_a_held_client_lock_times_out_as_retryable(c):
    token = c.subject()
    with c.db.migration.connect() as holder:
        holder.execute(select(func.pg_advisory_lock(LOCK_NAMESPACE, lock_key(c.w.a1))))
        try:
            response = c.send(envelope(token))
        finally:
            holder.execute(select(func.pg_advisory_unlock(LOCK_NAMESPACE, lock_key(c.w.a1))))
            holder.commit()
    assert response.status_code == 503 and response.headers["Retry-After"] == "1"
    assert events(c) == []


def test_lifecycle_expires_collected_data_but_never_tombstones(
    c, lifecycle_engine, lifecycle_settings
):
    token, idle = c.subject(), c.subject()
    old = envelope(token, occurred_at=now_utc() - timedelta(days=6))
    assert c.send(old).status_code == 201
    assert c.send(envelope(token)).status_code == 201
    erase_target = c.subject()
    assert c.send(envelope(erase_target)).status_code == 201
    assert (
        c.owner.post(
            f"{c.base}/clients/{c.w.a1}/deletion-requests", json={"subject_token": erase_target}
        ).status_code
        == 201
    )
    cutoff = now_utc()
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(CollectedEvent)
            .where(CollectedEvent.event_id == UUID(old["event_id"]))
            .values(expires_at=cutoff - timedelta(seconds=1))
        )
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.token_digest != "")
            .where(~CollectionSubject.id.in_(select(CollectedEvent.subject_id)))
            .values(last_activity_at=cutoff - timedelta(days=396))
        )
        session.execute(update(EventDiagnostic).values(day=(cutoff - timedelta(days=31)).date()))
    tombstones = count_rows(c.db, StoredTombstone)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings, cutoff=cutoff)
    assert result["status"] == "completed"
    assert result["deleted"]["collected_events"] == 1
    assert result["deleted"]["collection_subjects"] == 1
    assert result["deleted"]["consent_records"] == 2
    assert result["deleted"]["event_diagnostics"] >= 1
    assert count_rows(c.db, StoredTombstone) == tombstones
    assert count_rows(c.db, SubjectDeletionRequest) == 1
    assert len(events(c)) == 1
    retry = dict(old, occurred_at=(now_utc() - timedelta(days=8)).isoformat())
    assert c.send(retry).json() == {"error": "occurred_at_out_of_range"}
    assert c.send(envelope(idle)).json() == {"error": "unknown_subject"}


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM deletion_tombstones",
        "DELETE FROM deletion_requests",
        "UPDATE consent_records SET state = 'granted'",
        "UPDATE collected_events SET payload = '{}'::jsonb",
        "DELETE FROM ingestion_sources",
        "INSERT INTO collected_events (id) VALUES (gen_random_uuid())",
    ],
)
def test_lifecycle_role_cannot_reach_replay_protection(db, lifecycle_engine, statement):
    with pytest.raises(DBAPIError), lifecycle_engine.begin() as connection:
        connection.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE consent_records SET state = 'granted'",
        "UPDATE deletion_tombstones SET objected = true",
        "DELETE FROM deletion_tombstones",
        "DELETE FROM deletion_requests",
        "UPDATE service_credentials SET kind = 'ingest'",
        "UPDATE collected_events SET event_id = gen_random_uuid()",
        "UPDATE ingestion_sources SET public_key = 'pk_x'",
        "DELETE FROM event_diagnostics",
    ],
)
def test_runtime_role_cannot_rewrite_privacy_records(db, statement):
    with pytest.raises(DBAPIError), db.runtime.begin() as connection:
        connection.execute(text(statement))


def test_diagnostics_and_event_lookup_are_scoped_and_metadata_only(c):
    token = c.subject()
    body = envelope(
        token,
        event_type="purchase_signal",
        payload={"external_ref": "order-1", "amount_minor": 1999, "currency": "EGP"},
    )
    assert c.send(body).status_code == 201
    today = now_utc().date().isoformat()
    analyst = c.w.signed_in("analyst")
    path = f"{c.base}/clients/{c.w.a1}"
    rows = analyst.get(f"{path}/event-diagnostics", params={"start": today, "end": today})
    assert rows.status_code == 200
    assert {
        "channel": "server",
        "outcome": "accepted",
        "reason": "new",
        "count": 1,
        "day": today,
    } in rows.json()
    metadata = analyst.get(f"{path}/events/{body['event_id']}").json()
    assert metadata["event_type"] == "purchase_signal" and metadata["revision"] == 1
    assert not {"payload", "subject_id", "fingerprint", "amount_minor"} & set(metadata)
    assert analyst.get(f"{c.base}/clients/{c.w.a2}/events/{body['event_id']}").status_code == 403
    assert (
        c.ingest.get(f"{path}/event-diagnostics", params={"start": today, "end": today}).status_code
        == 401
    )
    wide = analyst.get(
        f"{path}/event-diagnostics", params={"start": "2030-01-01", "end": "2030-03-01"}
    )
    assert wide.status_code == 422
    assert c.w.signed_in("outsider").get(f"{path}/events/{body['event_id']}").status_code == 403


def test_administration_is_limited_to_managers_and_audited(c):
    analyst = c.w.signed_in("analyst")
    path = f"{c.base}/clients/{c.w.a1}"
    assert (
        analyst.post(
            f"{path}/ingestion-sources", json={"kind": "webhook", "name": "Denied"}
        ).status_code
        == 403
    )
    assert analyst.get(f"{path}/ingestion-sources").status_code == 403
    for invalid in [
        {"kind": "browser", "name": "No origin", "notice_sha256": NOTICE},
        {
            "kind": "browser",
            "name": "Wildcard",
            "allowed_origins": ["https://*.x.test"],
            "notice_sha256": NOTICE,
        },
        {"kind": "webhook", "name": "Origin", "allowed_origins": [ORIGIN]},
    ]:
        assert c.owner.post(f"{path}/ingestion-sources", json=invalid).status_code == 422
    listing = c.owner.get(f"{path}/ingestion-sources").json()
    assert sorted(item["kind"] for item in listing) == ["browser", "webhook"]
    assert all("secret" not in json.dumps(item) for item in listing)
    form = {"fields": [{"name": "plan", "data_class": "form.option", "options": ["a"]}]}
    assert c.owner.put(f"{path}/collection-forms/lead", json=form).json()["version"] == 1
    assert c.owner.put(f"{path}/collection-forms/lead", json=form).json()["version"] == 2
    bad = {"fields": [{"name": "email", "data_class": "contact.email"}]}
    assert c.owner.put(f"{path}/collection-forms/contact", json=bad).status_code == 422
    actions = select_rows(c.db, select(AuditEvent.action).where(AuditEvent.client_id == c.w.a1))
    assert actions.count("form.updated") == 2


def test_public_rate_limit_returns_retry_after(c):
    limited = c.api.config.model_copy(update={"ingest_public_per_minute": 2})
    client = c.api.new_client(limited)
    client.headers["Origin"] = ORIGIN
    token = c.subject()
    statuses = [c.collect(envelope(token), client=client).status_code for _ in range(3)]
    assert statuses == [202, 202, 429]


def test_downgrade_refuses_populated_collection_state(c):
    with pytest.raises(RuntimeError, match="event collection state"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0006_account_closure")
    with c.db.migration.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == expected_revision()
        )


# Review corrections of 2026-11-10 (R004-01 to R004-03 and the query-value observation).

STRANGER = "https://attacker.example.test"


def preflight(client, path, origin, *, method="POST", headers="content-type"):
    request_headers = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers is not None:
        request_headers["Access-Control-Request-Headers"] = headers
    return client.options(path, headers=request_headers)


def no_cors_grant(response) -> bool:
    return (
        "access-control-allow-origin" not in response.headers
        and "access-control-allow-credentials" not in response.headers
    )


def test_registered_origin_reads_the_consent_token_and_sends_events(c):
    base = f"/collect/v1/{c.public_key}"
    for route in ("consent", "events", "erasure"):
        allowed = preflight(c.public, f"{base}/{route}", ORIGIN)
        assert allowed.status_code == 204
        assert allowed.headers["access-control-allow-origin"] == ORIGIN
        assert allowed.headers["access-control-allow-methods"] == "POST"
        assert allowed.headers["access-control-allow-headers"] == "Content-Type"
        assert allowed.headers["access-control-max-age"] == "600"
        assert "access-control-allow-credentials" not in allowed.headers
    simple = c.public.post(
        f"{base}/consent",
        content=json.dumps({"choices": {ANALYTICS: "granted"}}),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )
    assert simple.status_code == 200
    assert simple.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in simple.headers
    assert "Origin" in simple.headers["vary"]
    token = simple.json()["subject_token"]
    assert token.startswith("sbj_")
    sent = c.public.post(f"{base}/events", json=envelope(token))
    assert (sent.status_code, sent.json()) == (202, {"status": "received"})
    assert sent.headers["access-control-allow-origin"] == ORIGIN
    changed = c.public.post(
        f"{base}/consent", json={"choices": {ATTRIBUTION: "granted"}, "subject_token": token}
    )
    assert changed.status_code == 200 and changed.json()["states"][ATTRIBUTION] == "granted"
    assert changed.headers["access-control-allow-origin"] == ORIGIN
    [row] = events(c)
    assert (row.channel, row.source_id) == ("browser", c.browser_id)
    for headers in ({"Content-Type": "application/x-www-form-urlencoded"}, {}):
        refused = c.public.post(
            f"{base}/events", content=json.dumps(envelope(token)), headers=headers
        )
        assert (refused.status_code, refused.json()) == (415, {"error": "unsupported_media_type"})
        assert refused.headers["access-control-allow-origin"] == ORIGIN
    assert len(events(c)) == 1


def test_unregistered_origins_and_requests_receive_no_cors_grant(c):
    base = f"/collect/v1/{c.public_key}"
    stranger = c.api.new_client()
    stranger.headers["Origin"] = STRANGER
    denied = preflight(stranger, f"{base}/consent", STRANGER)
    assert denied.status_code == 403 and no_cors_grant(denied)
    posted = stranger.post(
        f"{base}/consent",
        content=json.dumps({"choices": {ANALYTICS: "granted"}}),
        headers={"Content-Type": "text/plain"},
    )
    assert posted.status_code == 403 and no_cors_grant(posted)
    for response in (
        preflight(c.public, f"{base}/consent", ORIGIN, method="PUT"),
        preflight(c.public, f"{base}/consent", ORIGIN, headers="content-type, x-custom"),
        preflight(c.public, f"{base}/unknown", ORIGIN),
        preflight(c.public, f"/collect/v1/pk_{'x' * 43}/consent", ORIGIN),
        c.public.options(f"{base}/consent"),
    ):
        assert response.status_code == 403 and no_cors_grant(response)
    disabled = c.owner.patch(
        f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.browser_id}", json={"status": "disabled"}
    )
    assert disabled.status_code == 200
    assert preflight(c.public, f"{base}/consent", ORIGIN).status_code == 403
    assert count_rows(c.db, CollectionSubject) == 0


def test_platform_cors_cookie_and_csrf_boundaries_are_unchanged(c):
    platform = "http://localhost:8000"
    login = preflight(c.api.new_client(), "/auth/login", platform)
    assert login.status_code == 200
    assert login.headers["access-control-allow-origin"] == platform
    assert login.headers["access-control-allow-credentials"] == "true"
    # Starlette's unchanged platform rejection omits Allow-Origin, so no browser grants access.
    customer = preflight(c.public, "/auth/login", ORIGIN)
    assert customer.status_code == 400
    assert "access-control-allow-origin" not in customer.headers
    assert "access-control-allow-origin" not in c.public.get("/health/live").headers
    from_platform = c.api.new_client().post(
        f"/collect/v1/{c.public_key}/consent",
        content=json.dumps({"choices": {ANALYTICS: "granted"}}),
        headers={"Content-Type": "text/plain"},
    )
    assert from_platform.status_code == 403 and no_cors_grant(from_platform)
    csrf = c.owner.headers.pop("X-CSRF-Token")
    try:
        unprotected = c.owner.patch(
            f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.browser_id}",
            json={"status": "disabled"},
        )
        assert (unprotected.status_code, unprotected.json()) == (403, {"error": "csrf_failed"})
    finally:
        c.owner.headers["X-CSRF-Token"] = csrf
    foreign_origin = c.owner.patch(
        f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.browser_id}",
        json={"status": "disabled"},
        headers={"Origin": ORIGIN},
    )
    assert foreign_origin.status_code == 403
    assert "access-control-allow-origin" not in foreign_origin.headers
    [source] = c.owner.get(f"{c.base}/clients/{c.w.a1}/ingestion-sources").json()[:1]
    assert source["status"] == "active"


def idle_since(c, token: str, days: int) -> None:
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.token_digest == digest(token))
            .values(last_activity_at=now_utc() - timedelta(days=days))
        )


def assert_consent_evidence(c) -> None:
    with Session(c.db.migration) as session:
        basis = {
            item for row in session.scalars(select(CollectedEvent.consent_basis)) for item in row
        }
        present = set(session.scalars(select(StoredConsentRecord.id)))
    assert basis <= present


def retention(lifecycle_settings, days):
    if days is None:
        return lifecycle_settings
    return lifecycle_settings.model_copy(update={"subject_retention_days": days})


@pytest.mark.parametrize("days", [30, None], ids=["retention-30", "default-retention"])
def test_lifecycle_waits_for_an_in_flight_admission_and_keeps_its_consent(
    c, lifecycle_engine, lifecycle_settings, days
):
    settings = retention(lifecycle_settings, days)
    token = c.subject()
    idle_since(c, token, settings.subject_retention_days + 1)
    body = envelope(token)
    with Session(c.db.runtime) as session:
        session.begin()
        held = admit(
            session,
            c.api.config,
            c.w.a,
            c.w.a1,
            Channel("server", credential_id=c.credential_id),
            Envelope.model_validate(body),
            recheck=lambda: None,
        )
        assert held.outcome == "accepted"
        blocked = run_lifecycle(lifecycle_engine, settings)
        assert blocked["status"] == "partial"
        assert {"collected_events", "consent_records", "collection_subjects"} <= set(
            blocked["incomplete"]
        )
        assert blocked["deleted"]["consent_records"] == 0
        session.commit()
    assert count_rows(c.db, StoredConsentRecord) == 2
    after = run_lifecycle(lifecycle_engine, settings)
    assert after["status"] == "completed"
    assert after["deleted"]["consent_records"] == after["deleted"]["collection_subjects"] == 0
    assert count_rows(c.db, StoredConsentRecord) == 2
    assert c.send(body).json() == {"status": "duplicate", "revision": 1}
    assert_consent_evidence(c)


@pytest.mark.parametrize("days", [30, None], ids=["retention-30", "default-retention"])
def test_an_admission_behind_lifecycle_sees_the_expired_subject(
    c, lifecycle_engine, lifecycle_settings, days
):
    settings = retention(lifecycle_settings, days)
    token, active = c.subject(), c.subject()
    assert c.send(envelope(active)).status_code == 201
    idle_since(c, token, settings.subject_retention_days + 1)
    scoped = [target for target in targets(settings) if target.client_scoped]
    with lifecycle_engine.connect() as connection:
        counts = delete_client_batch(
            connection, scoped, c.w.a1, now_utc(), settings.lifecycle_batch_size
        )
        assert counts == {"collected_events": 0, "consent_records": 2, "collection_subjects": 1}
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(c.send, envelope(token))
            wait_for_blocked_lock(c.db)
            assert not pending.done()
            connection.commit()
            response = pending.result(timeout=10)
    assert response.json() == {"error": "unknown_subject"}
    [row] = events(c)
    assert count_rows(c.db, StoredConsentRecord) == 2
    assert count_rows(c.db, CollectionSubject) == 1
    assert row.consent_basis and c.send(envelope(active)).status_code == 201
    assert_consent_evidence(c)


def post_signed(c, source_id, secret: str, body) -> object:
    raw = json.dumps(body).encode()
    stamp = int(time.time())
    return c.api.new_client().post(
        f"/webhooks/v1/{source_id}/events",
        content=raw,
        headers={"X-Tracking-Signature": f"t={stamp},v1={sign_webhook(secret, stamp, raw)}"},
    )


def test_every_unexpired_webhook_secret_verifies_until_its_own_expiry(c):
    token = c.subject()
    rotate = f"{c.base}/clients/{c.w.a1}/ingestion-sources/{c.hook_id}/secret"
    issued = [c.secret]
    for _ in range(3):
        response = c.owner.post(rotate)
        assert response.status_code == 201
        issued.append(response.json()["signing_secret"])
    rows = select_rows(
        c.db,
        select(IngestionSourceSecret)
        .where(IngestionSourceSecret.source_id == c.hook_id)
        .order_by(IngestionSourceSecret.version),
    )
    assert [row.version for row in rows] == [1, 2, 3, 4]
    assert rows[3].retires_at is None
    assert rows[0].retires_at < rows[1].retires_at < rows[2].retires_at
    for secret in issued:
        assert c.webhook(envelope(token), secret=secret).status_code == 201
    for version in (1, 2, 3):
        with Session(c.db.migration) as session, session.begin():
            session.execute(
                update(IngestionSourceSecret)
                .where(
                    IngestionSourceSecret.source_id == c.hook_id,
                    IngestionSourceSecret.version == version,
                )
                .values(retires_at=now_utc() - timedelta(seconds=1))
            )
        expired = c.webhook(envelope(token), secret=issued[version - 1])
        assert expired.json() == {"error": "signature_invalid"}
        for secret in issued[version:]:
            assert c.webhook(envelope(token), secret=secret).status_code == 201
    sibling = c.owner.post(
        f"{c.base}/clients/{c.w.a1}/ingestion-sources", json={"kind": "webhook", "name": "Sibling"}
    ).json()
    other = c.owner.post(
        f"{c.base}/clients/{c.w.a2}/ingestion-sources", json={"kind": "webhook", "name": "Other"}
    ).json()
    for secret in (sibling["signing_secret"], other["signing_secret"], "whsec_" + "x" * 43):
        assert c.webhook(envelope(token), secret=secret).json() == {"error": "signature_invalid"}
    for target in (sibling, other):
        foreign = post_signed(c, target["source"]["id"], issued[3], envelope(token))
        assert foreign.json() == {"error": "signature_invalid"}
    assert len(events(c, c.w.a2)) == 0


def test_prohibited_query_values_are_removed_before_storage(c, capfd):
    token = c.subject()
    url = (
        "https://shop.example.test/offer?utm_campaign=4111111111111111"
        "&utm_source=spring_2030&utm_content=4111%201111%201111%201111"
        "&utm_term=someone%40example.test&gclid=Cj0KCQ-123"
        "&utm_medium=4111%25201111%25201111%25201111"
    )
    assert c.send(envelope(token, payload={"url": url})).status_code == 201
    link = envelope(
        token,
        event_type="link_click",
        payload={
            "url": "https://shop.example.test/",
            "link_url": "https://pay.example.test/go?utm_id=4111-1111-1111-1111&utm_source=ok",
        },
    )
    assert c.collect(link).status_code == 202
    stored = {row.event_type: row.payload for row in events(c)}
    assert stored["page_view"]["url"] == (
        "https://shop.example.test/offer?utm_source=spring_2030&gclid=Cj0KCQ-123"
    )
    assert stored["link_click"]["link_url"] == "https://pay.example.test/go?utm_source=ok"
    assert counters(c)[("server", "minimized", "sensitive_query_value")] == 4
    assert counters(c)[("browser", "minimized", "sensitive_query_value")] == 1
    with c.db.migration.connect() as connection:
        dump = connection.execute(
            text("SELECT coalesce(string_agg(t::text, ' '), '') FROM collected_events t")
        ).scalar_one()
    for value in ("4111111111111111", "4111 1111", "4111-1111", "%2520", "someone", "%40"):
        assert value not in dump
    output = capfd.readouterr()
    assert "4111" not in output.out + output.err and "someone" not in output.out + output.err


# Review finding R004-04: committed lifecycle batches must never let an older grant become the
# effective consent. The latest record of a subject and purpose is (received_at, id), as in
# app.privacy.consent.current_state.

EARLY_ID = UUID("00000000-0000-4000-8000-000000000001")
LATE_ID = UUID("00000000-0000-4000-8000-0000000000ff")


def issue_with_id(c, monkeypatch, record_id: UUID, choices, token: str) -> None:
    # Issue one consent record through the real endpoint with a fixed, valid record UUID. Only
    # the first identifier is fixed; every later uuid4 call (counters) stays random.
    issued = iter([record_id])
    original = collection_service.uuid4
    monkeypatch.setattr(collection_service, "uuid4", lambda: next(issued, None) or original())
    try:
        assert c.consent(choices, token=token)["receipts"] == [str(record_id)]
    finally:
        monkeypatch.setattr(collection_service, "uuid4", original)


def subject_id_of(c, token: str) -> UUID:
    [subject] = select_rows(
        c.db, select(CollectionSubject.id).where(CollectionSubject.token_digest == digest(token))
    )
    return subject


def add_grants(c, subject: UUID, purpose: str, received, count: int) -> None:
    # Older synthetic grants of one purpose, all received before the subject's later records.
    with Session(c.db.migration) as session, session.begin():
        session.add_all(
            StoredConsentRecord(
                id=uuid4(),
                agency_id=c.w.a,
                client_id=c.w.a1,
                subject_id=subject,
                purpose=purpose,
                state="granted",
                source="api",
                jurisdiction_profile="J1",
                policy_version="003-B.1",
                notice_sha256=NOTICE,
                received_at=received - timedelta(seconds=index + 1),
                expires_at=received + timedelta(days=365),
            )
            for index in range(count)
        )


def historical_subject(c, monkeypatch, latest: str, grants: int) -> tuple[str, UUID]:
    # The review reproduction: an analytics grant 33 days old (still valid), grants-1 further
    # older grants, then the newer latest record (withdrawn or denied) with the fixed UUID that
    # sorts before every grant UUID, received and last active 31 days ago.
    now = now_utc()
    token = c.subject({ANALYTICS: "granted"})
    subject = subject_id_of(c, token)
    issue_with_id(c, monkeypatch, EARLY_ID, {ANALYTICS: latest}, token)
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.subject_id == subject, StoredConsentRecord.id != EARLY_ID)
            .values(
                received_at=now - timedelta(days=33),
                expires_at=now - timedelta(days=33) + timedelta(days=365),
            )
        )
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.id == EARLY_ID)
            .values(received_at=now - timedelta(days=31))
        )
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.id == subject)
            .values(last_activity_at=now - timedelta(days=31))
        )
    add_grants(c, subject, ANALYTICS, now - timedelta(days=33), grants - 1)
    return token, subject


def effective_states(c, subject: UUID) -> dict[str, str] | None:
    # Evaluate the stored records exactly as admission does; None once the subject is gone.
    with Session(c.db.migration) as session:
        row = session.get(CollectionSubject, subject)
        if row is None:
            return None
        view = consent_view(session, row, now_utc())
    return {purpose.value: state.value for purpose, state in view.states.items()}


def consent_ids(c, subject: UUID) -> list[UUID]:
    return select_rows(
        c.db, select(StoredConsentRecord.id).where(StoredConsentRecord.subject_id == subject)
    )


@pytest.mark.parametrize("latest", ["withdrawn", "denied"])
@pytest.mark.parametrize(("size", "grants"), [(1, 1), (500, 500)], ids=["batch-1", "batch-500"])
def test_partial_lifecycle_never_resurrects_an_older_grant(
    c, monkeypatch, lifecycle_engine, lifecycle_settings, latest, size, grants
):
    settings = lifecycle_settings.model_copy(
        update={"subject_retention_days": 30, "lifecycle_batch_size": size}
    )
    token, subject = historical_subject(c, monkeypatch, latest, grants)
    refused = {"error": f"consent_{latest}"}
    assert len(consent_ids(c, subject)) == grants + 1
    assert c.send(envelope(token)).json() == refused
    first = run_lifecycle(lifecycle_engine, settings, max_batches=1)
    assert first["status"] == "partial"
    assert first["deleted"]["consent_records"] == size
    assert first["deleted"]["collection_subjects"] == 0
    assert consent_ids(c, subject) == [EARLY_ID]
    assert effective_states(c, subject)[ANALYTICS] == latest
    between = c.send(envelope(token))
    assert between.json() == refused
    assert events(c) == []
    resumed = run_lifecycle(lifecycle_engine, settings)
    assert resumed["status"] == "completed"
    assert resumed["deleted"]["consent_records"] == 1
    assert resumed["deleted"]["collection_subjects"] == 1
    assert effective_states(c, subject) is None
    assert c.send(envelope(token)).json() == {"error": "unknown_subject"}
    assert events(c) == []


def test_every_committed_batch_preserves_effective_consent_across_purposes(
    c, monkeypatch, lifecycle_engine, lifecycle_settings
):
    # Batch size 1 and one batch per run, so every single deletion is a committed boundary:
    # analytics granted then withdrawn (with older grants), attribution granted then denied,
    # and an active subject whose events and consent must stay untouched.
    settings = lifecycle_settings.model_copy(
        update={"subject_retention_days": 30, "lifecycle_batch_size": 1}
    )
    now = now_utc()
    active = c.subject()
    assert c.send(envelope(active)).status_code == 201
    token = c.subject({ANALYTICS: "granted", ATTRIBUTION: "granted"})
    subject = subject_id_of(c, token)
    issue_with_id(c, monkeypatch, EARLY_ID, {ANALYTICS: "withdrawn"}, token)
    issue_with_id(
        c, monkeypatch, UUID("00000000-0000-4000-8000-000000000002"), {ATTRIBUTION: "denied"}, token
    )
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(
                StoredConsentRecord.subject_id == subject, StoredConsentRecord.state == "granted"
            )
            .values(received_at=now - timedelta(days=33))
        )
        session.execute(
            update(StoredConsentRecord)
            .where(
                StoredConsentRecord.subject_id == subject, StoredConsentRecord.state != "granted"
            )
            .values(received_at=now - timedelta(days=31))
        )
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.id == subject)
            .values(last_activity_at=now - timedelta(days=31))
        )
    add_grants(c, subject, ANALYTICS, now - timedelta(days=33), 3)
    add_grants(c, subject, ATTRIBUTION, now - timedelta(days=33), 2)
    expected = {ANALYTICS: "withdrawn", ATTRIBUTION: "denied"}
    page = {"error": "consent_withdrawn"}
    lead = {"error": "consent_denied"}
    for run in range(1, 40):
        states = effective_states(c, subject)
        if states is None:
            break
        for purpose, state in expected.items():
            assert states[purpose] in {state, "unknown"}, (run, states)
            if states[purpose] == "unknown":
                expected[purpose] = "unknown"
        assert "granted" not in states.values(), (run, states)
        page_reply = c.send(envelope(token)).json()
        lead_reply = c.send(
            envelope(token, event_type="lead_signal", payload={"action": "book_call"})
        ).json()
        assert page_reply in (page, {"error": "consent_unknown"})
        assert lead_reply in (lead, {"error": "consent_unknown"})
        assert run_lifecycle(lifecycle_engine, settings, max_batches=1)["status"] in {
            "partial",
            "completed",
        }
    else:
        raise AssertionError("Cleanup did not finish within the bounded number of runs.")
    assert run > 2
    assert c.send(envelope(token)).json() == {"error": "unknown_subject"}
    assert [row.subject_id for row in events(c)] == [subject_id_of(c, active)]
    assert c.send(envelope(active)).status_code == 201
    assert_consent_evidence(c)


def test_receipt_time_ties_keep_the_record_the_evaluator_uses(
    c, monkeypatch, lifecycle_engine, lifecycle_settings
):
    # Same received_at: the evaluator's tie-break picks the higher UUID, here the withdrawal.
    settings = lifecycle_settings.model_copy(
        update={"subject_retention_days": 30, "lifecycle_batch_size": 1}
    )
    token = c.subject({ANALYTICS: "granted"})
    subject = subject_id_of(c, token)
    issue_with_id(c, monkeypatch, LATE_ID, {ANALYTICS: "withdrawn"}, token)
    tie = now_utc() - timedelta(days=31)
    with Session(c.db.migration) as session, session.begin():
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.subject_id == subject, StoredConsentRecord.id != LATE_ID)
            .values(id=EARLY_ID, received_at=tie)
        )
        session.execute(
            update(StoredConsentRecord)
            .where(StoredConsentRecord.id == LATE_ID)
            .values(received_at=tie)
        )
        session.execute(
            update(CollectionSubject)
            .where(CollectionSubject.id == subject)
            .values(last_activity_at=tie)
        )
    assert effective_states(c, subject)[ANALYTICS] == "withdrawn"
    assert c.send(envelope(token)).json() == {"error": "consent_withdrawn"}
    first = run_lifecycle(lifecycle_engine, settings, max_batches=1)
    assert first["deleted"]["consent_records"] == 1
    assert consent_ids(c, subject) == [LATE_ID]
    assert c.send(envelope(token)).json() == {"error": "consent_withdrawn"}
    assert run_lifecycle(lifecycle_engine, settings)["status"] == "completed"
    assert effective_states(c, subject) is None
    assert events(c) == []


def test_an_unbounded_run_removes_a_whole_history_in_one_pass(
    c, monkeypatch, lifecycle_engine, lifecycle_settings
):
    # Older history goes first and the effective record in a later batch of the same run, so a
    # run reported completed leaves nothing eligible behind (default batch size).
    settings = lifecycle_settings.model_copy(update={"subject_retention_days": 30})
    token, subject = historical_subject(c, monkeypatch, "withdrawn", 3)
    result = run_lifecycle(lifecycle_engine, settings)
    assert result["status"] == "completed"
    assert result["deleted"]["consent_records"] == 4
    assert result["deleted"]["collection_subjects"] == 1
    assert effective_states(c, subject) is None
    assert c.send(envelope(token)).json() == {"error": "unknown_subject"}
