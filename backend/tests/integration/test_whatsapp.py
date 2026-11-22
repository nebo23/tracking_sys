"""WhatsApp Cloud API referrals on disposable PostgreSQL (specification 015-E, D-068 E7 to E11).

Cases T-60 to T-64, T-70 to T-72 of the second-round entry review. Every notification comes from
tests/whatsapp_sender.py and is signed with a test app secret. No case contacts Meta.
"""

import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from whatsapp_sender import (
    APP_SECRET,
    FORBIDDEN,
    VERIFY_TOKEN,
    message,
    notification,
    signed,
)

from app.models import AuditEvent, WhatsappMessage
from app.privacy import providers
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration
NUMBER = "106540352242922"
WEBHOOK = "/integrations/whatsapp/webhook"


@pytest.fixture
def wa(authenticated_world, api):
    w = authenticated_world
    config = api.config.model_copy(
        update={
            "whatsapp_enabled": True,
            "whatsapp_app_secret": SecretStr(APP_SECRET),
            "whatsapp_verify_token": SecretStr(VERIFY_TOKEN),
        }
    )

    def browser(name, settings=None):
        client = api.new_client(settings or config)
        api.login(client, f"{name}@example.test")
        return client

    def register(number=NUMBER, name="owner_a", client_id=None, settings=None):
        return browser(name, settings).post(
            f"/agencies/{w.a}/clients/{client_id or w.a1}/whatsapp-numbers",
            json={"phone_number_id": number, "name": "Synthetic number"},
        )

    lab = SimpleNamespace(w=w, api=api, config=config, browser=browser, register=register)
    created = register()
    assert created.status_code == 201, created.text
    lab.number = created.json()
    lab.public = api.new_client(config)

    def send(body, secret=APP_SECRET, client=None):
        raw, headers = signed(body, secret)
        return (client or lab.public).post(WEBHOOK, content=raw, headers=headers)

    lab.send = send
    return lab


def _messages(w, client_id=None):
    with Session(w.db.migration) as session:
        return list(
            session.scalars(
                select(WhatsappMessage).where(WhatsappMessage.client_id == (client_id or w.a1))
            )
        )


def _referrals(wa, name="analyst", client_id=None):
    w = wa.w
    return wa.browser(name).get(f"/agencies/{w.a}/clients/{client_id or w.a1}/whatsapp/referrals")


def test_signed_notifications_and_the_handshake(wa):
    # T-60 (M): a notification signed with the app secret is accepted; an invalid signature is
    # refused and stores nothing; the handshake answers the challenge only with the verify token.
    body = notification(NUMBER, message())
    raw, headers = signed(body)
    for sent in (
        {},
        {"x-hub-signature-256": "sha256=" + "0" * 64},
        signed(body, "OTHER-APP-SECRET-0000")[1],
    ):
        response = wa.public.post(WEBHOOK, content=raw, headers=sent)
        assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    assert _messages(wa.w) == []
    response = wa.send(body)
    assert response.status_code == 200 and response.json() == {"status": "received"}
    assert len(_messages(wa.w)) == 1
    good = {
        "hub.mode": "subscribe",
        "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "1158201444",
    }
    answer = wa.public.get(WEBHOOK, params=good)
    assert (answer.status_code, answer.text) == (200, "1158201444")
    for params in ({**good, "hub.verify_token": "wrong"}, {**good, "hub.mode": "unsubscribe"}, {}):
        assert wa.public.get(WEBHOOK, params=params).status_code == 403


def test_referrals_and_unknown_messages(wa):
    # T-61 (M): a referral keeps its source type and ad ID; a message without one is unknown;
    # status notifications store nothing.
    body = notification(
        NUMBER,
        message(),
        message(),
        message(referral=False),
        message(source_type="post", ad_id="120210000000999", click_id=False),
    )
    assert wa.send(body).status_code == 200
    assert wa.send(notification(NUMBER, statuses=True)).status_code == 200
    report = _referrals(wa)
    assert report.status_code == 200
    data = report.json()
    assert (data["total"], data["unknown"]) == (4, 1)
    assert data["sources"] == [
        {"source_type": "ad", "source_id": "120210000000853", "messages": 2, "with_click_id": 2},
        {"source_type": "post", "source_id": "120210000000999", "messages": 1, "with_click_id": 0},
    ]


def test_no_person_field_is_stored_logged_or_returned(wa, caplog):
    # T-62 (M): no phone number, name, sender ID, text, ad copy, media URL or click ID is stored,
    # logged or returned.
    caplog.set_level(logging.DEBUG)
    assert wa.send(notification(NUMBER, message(), message(referral=False))).status_code == 200
    w = wa.w
    with w.db.migration.connect() as connection:
        stored = [
            str(tuple(row))
            for table in ("whatsapp_messages", "whatsapp_numbers")
            for row in connection.execute(text(f"SELECT * FROM {table}"))
        ]
    answers = [
        _referrals(wa, "owner_a").text,
        wa.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/whatsapp-numbers").text,
    ]
    logged = [record.getMessage() + str(record.__dict__) for record in caplog.records]
    for value in FORBIDDEN:
        for item in stored + answers + logged:
            assert value not in item, value


def test_repeats_and_unregistered_numbers(wa):
    # T-63: a repeated notification stores each message once; an unregistered phone number ID
    # stores nothing; a disabled number stops intake.
    body = notification(NUMBER, message(), message())
    for _ in range(3):
        assert wa.send(body).status_code == 200
    assert len(_messages(wa.w)) == 2
    assert wa.send(notification("999999999999", message())).status_code == 200
    assert len(_messages(wa.w)) == 2
    w = wa.w
    path = f"/agencies/{w.a}/clients/{w.a1}/whatsapp-numbers/{wa.number['id']}"
    assert wa.browser("owner_a").patch(path, json={"status": "disabled"}).status_code == 200
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert len(_messages(wa.w)) == 2


def test_numbers_permissions_audit_and_isolation(wa):
    # T-64: numbers need an Owner or Admin, are audited and unique; reads need client:read and
    # are isolated per client.
    w = wa.w
    for name in ("analyst", "viewer", "owner_b"):
        assert wa.register("106540352242999", name).status_code == 403, name
    assert wa.register("106540352242999", "admin", client_id=w.a2).status_code == 201
    assert wa.register(NUMBER, "admin", client_id=w.a2).status_code == 409
    assert wa.register("+2010", "owner_a").status_code == 422
    assert wa.send(notification("106540352242999", message())).status_code == 200
    assert len(_messages(w)) == 0 and len(_messages(w, w.a2)) == 1
    assert _referrals(wa).json()["total"] == 0
    assert _referrals(wa, "owner_a", w.a2).json()["total"] == 1
    assert _referrals(wa, "owner_b").status_code == 403
    assert _referrals(wa, "outsider").status_code == 403
    with Session(w.db.migration) as session:
        actions = sorted(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.resource_type == "whatsapp_number")
            )
        )
    assert actions == ["whatsapp_number.created", "whatsapp_number.created"]


def _stale(monkeypatch, **changes):
    rules = tuple(
        replace(item, **changes) if item.rule_id == "whatsapp.cloud_api" else item
        for item in providers.RULES
    )
    monkeypatch.setattr(providers, "RULES", rules)


def test_gates_and_rules(wa, monkeypatch):
    # T-70 (M): with the setting off or the rule stale or overdue, WhatsApp intake is refused.
    off = wa.config.model_copy(update={"whatsapp_enabled": False})
    closed = wa.api.new_client(off)
    assert wa.send(notification(NUMBER, message()), client=closed).status_code == 503
    assert wa.register("106540352242777", settings=off).status_code == 503
    for changes in ({"status": providers.RuleStatus.STALE}, {"review_due_at": date(2026, 1, 1)}):
        with monkeypatch.context() as patched:
            _stale(patched, **changes)
            assert wa.send(notification(NUMBER, message())).status_code == 503
            assert wa.public.get(WEBHOOK, params={"hub.mode": "subscribe"}).status_code == 503
    assert _messages(wa.w) == []


def test_body_bound(wa):
    # T-71: WhatsApp notifications may be up to 3 MiB.
    large = notification(NUMBER, *(message() for _ in range(2000)))
    raw, headers = signed(large)
    assert 1_048_576 < len(raw) < 3 * 1_048_576
    assert wa.public.post(WEBHOOK, content=raw, headers=headers).status_code == 200
    assert len(_messages(wa.w)) == 2000
    too_large = raw + b" " * (3 * 1_048_576 - len(raw) + 1)
    response = wa.public.post(WEBHOOK, content=too_large, headers=headers)
    assert response.status_code == 413


def test_lifecycle_deletes_messages_after_13_months(wa, lifecycle_engine, lifecycle_settings):
    # T-72: messages 395 days after receipt.
    assert wa.send(notification(NUMBER, message(), message())).status_code == 200
    w = wa.w
    with Session(w.db.migration) as session, session.begin():
        first = session.scalars(select(WhatsappMessage.id)).first()
        session.execute(
            update(WhatsappMessage)
            .where(WhatsappMessage.id == first)
            .values(received_at=datetime.now(UTC) - timedelta(days=396))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed" and result["deleted"]["whatsapp_messages"] == 1
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(WhatsappMessage)) == 1
