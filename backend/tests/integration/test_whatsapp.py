"""WhatsApp Cloud API referrals on disposable PostgreSQL (specification 015-E, D-068 E7 to E11).

Cases T-60 to T-64, T-70 to T-72 of the second-round entry review. Every notification comes from
tests/whatsapp_sender.py and is signed with a test app secret. No case contacts Meta.
"""

import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from whatsapp_sender import (
    APP_SECRET,
    FORBIDDEN,
    VERIFY_TOKEN,
    message,
    notification,
    signed,
)

from app.models import AuditEvent, WhatsappMessage, WhatsappNumber
from app.privacy import providers
from app.services.lifecycle import run_lifecycle
from app.services.whatsapp import WhatsappError, revoke_claim, verify_claim

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

    # The platform operator's verification of a claim (D-070); agencies cannot do it.
    def verify(claim_id):
        with Session(w.db.runtime) as session, session.begin():
            return verify_claim(session, UUID(str(claim_id))).status

    lab = SimpleNamespace(
        w=w, api=api, config=config, browser=browser, register=register, verify=verify
    )
    created = register()
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending" and created.json()["verified_at"] is None
    assert verify(created.json()["id"]) == "active"
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
    # T-64: numbers need an Owner or Admin and are audited; reads need client:read and are
    # isolated per client. Under D-070 (R004) a registration is a pending claim: another
    # client's claim of an already verified number is accepted as pending and routes nothing,
    # and only the same client's second claim conflicts.
    w = wa.w
    for name in ("analyst", "viewer", "owner_b"):
        assert wa.register("106540352242999", name).status_code == 403, name
    claim = wa.register("106540352242999", "admin", client_id=w.a2)
    assert claim.status_code == 201 and claim.json()["status"] == "pending"
    rival = wa.register(NUMBER, "admin", client_id=w.a2)
    assert rival.status_code == 201 and rival.json()["status"] == "pending"
    assert wa.register(NUMBER, "owner_a").status_code == 409  # the same client's second claim
    assert wa.register("+2010", "owner_a").status_code == 422
    assert wa.send(notification("106540352242999", message())).status_code == 200
    assert len(_messages(w)) == 0 and len(_messages(w, w.a2)) == 0  # pending routes nothing
    assert wa.verify(claim.json()["id"]) == "active"
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
    # The fixture's claim and the two claims of client a2; the refused claim left no event.
    assert actions == ["whatsapp_number.created"] * 3


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


# --- Review finding R004 (D-069, D-070): verified number bindings ---------------------------

VICTIM = "106540352242999"


def _claim_b(wa, number=VICTIM):
    w = wa.w
    return wa.browser("owner_b").post(
        f"/agencies/{w.b}/clients/{w.b1}/whatsapp-numbers",
        json={"phone_number_id": number, "name": "Unproven number claim"},
    )


def _number_path(wa, claim, agency=None, client_id=None):
    w = wa.w
    return f"/agencies/{agency or w.a}/clients/{client_id or w.a1}/whatsapp-numbers/{claim}"


def test_unproven_claims_route_nothing_and_cannot_block_the_owner(wa):
    # R004: another agency's first claim of a number stays pending and receives nothing; the
    # real owner can still claim it; neither agency can activate a claim itself; only the
    # operator's verification routes messages, and a second verification of the number fails.
    w = wa.w
    first = _claim_b(wa)
    assert first.status_code == 201 and first.json()["status"] == "pending"
    assert wa.send(notification(VICTIM, message())).status_code == 200
    assert _messages(w, w.b1) == [] and _messages(w) == []
    owner = wa.register(VICTIM)
    assert owner.status_code == 201 and owner.json()["status"] == "pending"
    for name, claim, agency, client_id in (
        ("owner_b", first.json()["id"], w.b, w.b1),
        ("owner_a", owner.json()["id"], None, None),
    ):
        refused = wa.browser(name).patch(
            _number_path(wa, claim, agency, client_id), json={"status": "active"}
        )
        assert (refused.status_code, refused.json()) == (409, {"error": "verification_required"})
    assert wa.send(notification(VICTIM, message())).status_code == 200
    assert _messages(w, w.b1) == [] and _messages(w) == []
    assert wa.verify(owner.json()["id"]) == "active"
    assert wa.send(notification(VICTIM, message())).status_code == 200
    assert len(_messages(w)) == 1 and _messages(w, w.b1) == []
    with pytest.raises(WhatsappError, match="number_already_bound"):
        wa.verify(first.json()["id"])
    listed = wa.browser("owner_b").get(f"/agencies/{w.b}/clients/{w.b1}/whatsapp-numbers")
    assert [(item["status"], item["verified_at"]) for item in listed.json()] == [("pending", None)]
    assert wa.send(notification(VICTIM, message())).status_code == 200
    assert len(_messages(w)) == 2 and _messages(w, w.b1) == []


def test_disabled_and_revoked_bindings_and_transfer(wa):
    # R004: a disabled binding routes nothing until re-activated; the operator's revocation
    # stops routing for good and frees the number, so another client's pending claim can then be
    # verified (transfer); messages already stored keep their client.
    w = wa.w
    path = _number_path(wa, wa.number["id"])
    owner = wa.browser("owner_a")
    assert owner.patch(path, json={"status": "disabled"}).json()["status"] == "disabled"
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert _messages(w) == []
    assert owner.patch(path, json={"status": "active"}).json()["status"] == "active"
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert len(_messages(w)) == 1
    successor = wa.register(NUMBER, "admin", client_id=w.a2).json()
    with pytest.raises(WhatsappError, match="number_already_bound"):
        wa.verify(successor["id"])
    with Session(w.db.runtime) as session, session.begin():
        assert revoke_claim(session, UUID(wa.number["id"])).status == "revoked"
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert len(_messages(w)) == 1 and _messages(w, w.a2) == []
    refused = owner.patch(path, json={"status": "active"})
    assert (refused.status_code, refused.json()) == (409, {"error": "claim_revoked"})
    assert wa.verify(successor["id"]) == "active"
    assert wa.send(notification(NUMBER, message())).status_code == 200
    assert len(_messages(w)) == 1 and len(_messages(w, w.a2)) == 1
    # Operator refusals: unknown, already verified and already revoked claims.
    for claim, code in (
        ("00000000-0000-0000-0000-000000000000", "claim_not_found"),
        (successor["id"], "claim_not_pending"),
    ):
        with pytest.raises(WhatsappError, match=code):
            wa.verify(claim)
    with pytest.raises(WhatsappError, match="claim_revoked"):
        with Session(w.db.runtime) as session, session.begin():
            revoke_claim(session, UUID(wa.number["id"]))
    # The previous owner may claim the number again; the claim waits for the operator.
    again = wa.register(NUMBER)
    assert again.status_code == 201 and again.json()["status"] == "pending"


def test_one_verified_binding_per_number_in_the_database(wa):
    # R004: the partial unique index keeps one verified binding per number and one unrevoked
    # claim per client and number, whatever path writes the rows.
    w = wa.w
    rival = wa.register(NUMBER, "admin", client_id=w.a2).json()
    with pytest.raises(IntegrityError, match="uq_whatsapp_numbers_verified"):
        with Session(w.db.migration) as session, session.begin():
            session.execute(
                update(WhatsappNumber)
                .where(WhatsappNumber.id == UUID(rival["id"]))
                .values(status="active", verified_at=datetime.now(UTC))
            )
    with pytest.raises(IntegrityError, match="ck_whatsapp_numbers_valid_verification"):
        with Session(w.db.migration) as session, session.begin():
            session.execute(
                update(WhatsappNumber)
                .where(WhatsappNumber.id == UUID(rival["id"]))
                .values(status="disabled")
            )


def test_operator_command(wa):
    # R004: python -m app.whatsapp_binding lists pending claims and verifies or revokes one,
    # reporting closed error codes; it never prints a message.
    from app.whatsapp_binding import main, run

    w = wa.w
    claim = wa.register(VICTIM).json()
    code, listed = run(w.db.runtime, "list")
    assert code == 0 and [item["claim"] for item in listed] == [claim["id"]]
    assert listed[0]["phone_number_id"] == VICTIM and listed[0]["verified_at"] is None
    code, verified = run(w.db.runtime, "verify", claim=UUID(claim["id"]))
    assert code == 0 and verified["status"] == "active" and verified["verified_at"]
    assert run(w.db.runtime, "verify", claim=UUID(claim["id"])) == (
        1,
        {"error": "claim_not_pending"},
    )
    code, every = run(w.db.runtime, "list", status="all")
    assert code == 0 and len(every) == 2
    code, revoked = run(w.db.runtime, "revoke", claim=UUID(claim["id"]))
    assert code == 0 and revoked["status"] == "revoked"
    for argv in (
        ["verify", "--claim", claim["id"]],
        ["revoke", "--claim", claim["id"]],
        ["verify", "--claim", "not-a-uuid", "--confirm"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2, argv


# --- Review finding R009 (D-069): malformed messages stay confined to themselves -------------


def _post(wa, body, **changes):
    from fastapi.testclient import TestClient

    from app.main import create_app

    raw, headers = signed(body)
    with TestClient(create_app(wa.config), raise_server_exceptions=False) as client:
        return client.post(WEBHOOK, content=raw, headers=headers)


def test_malformed_messages_never_discard_valid_siblings(wa):
    # R009: through the real application without exception passthrough, malformed messages first
    # and last, unsupported shapes between changes, and extreme dates are read on their own: the
    # signed batch answers 200 and every readable message is stored once with its minimized
    # referral; unreadable items are skipped; a repeat stores nothing new.
    w = wa.w
    listed, objected = message(), message()
    listed["referral"]["source_type"] = []
    objected["referral"]["source_type"] = {"type": "ad"}
    far, near = message(timestamp=999_999_999_999), message(timestamp=1)
    valid = [message(), message(source_type="post"), message(referral=False)]
    anonymous = message()
    del anonymous["id"]
    body = notification(NUMBER, listed, valid[0], far, valid[1], "item", anonymous, near)
    body["entry"][0]["changes"].insert(0, "not a change")
    body["entry"].insert(0, ["not an entry"])
    body["entry"].append(
        {"id": "2", "changes": [{"field": "messages", "value": {"messages": "not a list"}}]}
    )
    second = notification(NUMBER, valid[2], objected)
    body["entry"].append(second["entry"][0])
    response = _post(wa, body)
    assert (response.status_code, response.json()) == (200, {"status": "received"})
    stored = _messages(w)
    assert len(stored) == 7
    assert sorted(row.source_type or "unknown" for row in stored) == [
        "ad",
        "ad",
        "ad",
        "other",
        "other",
        "post",
        "unknown",
    ]
    assert sum(1 for row in stored if row.message_at is None) == 2
    assert _post(wa, body).status_code == 200
    assert len(_messages(w)) == 7
    report = _referrals(wa).json()
    assert (report["total"], report["unknown"]) == (7, 1)


def test_unsigned_batches_and_storage_failures_are_never_acknowledged(wa, monkeypatch):
    # R009: the per-message reading never turns a refused signature or a storage failure into a
    # 200: an unsigned batch is 401, and a database error while storing is a server error,
    # so Meta retries it, with nothing stored.
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    from app.api import whatsapp as routes
    from app.main import create_app

    body = notification(NUMBER, message(), message())
    raw, _ = signed(body)
    with TestClient(create_app(wa.config), raise_server_exceptions=False) as client:
        refused = client.post(WEBHOOK, content=raw, headers={"content-type": "application/json"})
        assert refused.status_code == 401

        def failing(session, items):
            raise OperationalError("INSERT", {}, Exception("synthetic storage failure"))

        monkeypatch.setattr(routes, "receive_messages", failing)
        response = client.post(WEBHOOK, content=raw, headers=signed(body)[1])
        assert response.status_code >= 500
    assert _messages(wa.w) == []
