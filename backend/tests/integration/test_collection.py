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

from app.collection.contract import sign_webhook
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
from app.security import now_utc
from app.services.collection import LOCK_NAMESPACE, erase_subject, record_consent
from app.services.lifecycle import run_lifecycle

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
    assert all(len(item.match_key) == 32 and item.match_key_id == "tomb1" for item in tombstones)
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
