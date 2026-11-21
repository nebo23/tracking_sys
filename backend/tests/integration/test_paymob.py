"""Paymob payment sources and signed callbacks on disposable PostgreSQL (specification 015-B).

D-067 decisions D3 to D7, D10, D12 to D14 and amendment A1; cases T-10 to T-21 of the entry
review section 7.2. Every callback comes from the synthetic sender of tests/paymob_callbacks.py,
signed by the documented algorithm with test secrets. No case contacts Paymob.
"""

import dataclasses
import itertools
import logging
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from paymob_callbacks import (
    CARD_LAST_FOUR,
    FORBIDDEN,
    MASKED_PAN,
    OTHER_SECRET,
    TEST_SECRET,
    authorization,
    capture,
    next_id,
    padded,
    refund,
    resent_parent,
    sale,
    signed,
    token,
    transaction,
    void,
)
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import (
    AuditEvent,
    PaymentCallbackDiagnostic,
    PaymentSource,
    PaymentSourceSecret,
    RevenueEvidence,
)
from app.privacy import providers
from app.services.lifecycle import run_lifecycle

pytestmark = pytest.mark.integration


@pytest.fixture
def pay(authenticated_world, api):
    w = authenticated_world
    config = api.config.model_copy(update={"payments_paymob_enabled": True})

    def browser(name, settings=None):
        client = api.new_client(settings or config)
        api.login(client, f"{name}@example.test")
        return client

    def create(name="owner_a", agency=None, client_id=None, secret=TEST_SECRET, settings=None):
        return browser(name, settings).post(
            f"/agencies/{agency or w.a}/clients/{client_id or w.a1}/payment-sources",
            json={
                "provider": "paymob",
                "region": "egypt",
                "name": "Synthetic Paymob",
                "hmac_secret": secret,
            },
        )

    lab = SimpleNamespace(w=w, api=api, config=config, browser=browser, create=create)
    created = create()
    assert created.status_code == 201, created.text
    lab.source = created.json()
    lab.path = lab.source["callback_path"]
    lab.public = api.new_client(config)

    def send(obj, secret=TEST_SECRET, path=None, client=None, kind="TRANSACTION"):
        body, query = signed(obj, secret, kind)
        return (client or lab.public).post(
            path or lab.path,
            content=body,
            params=query,
            headers={"Content-Type": "application/json"},
        )

    lab.send = send
    return lab


def _evidence(w, client_id=None):
    with Session(w.db.migration) as session:
        return list(
            session.scalars(
                select(RevenueEvidence)
                .where(RevenueEvidence.client_id == (client_id or w.a1))
                .order_by(RevenueEvidence.received_at, RevenueEvidence.sequence)
            )
        )


def _diagnostics(w):
    with Session(w.db.migration) as session:
        return [
            (row.outcome, row.reason)
            for row in session.scalars(
                select(PaymentCallbackDiagnostic).order_by(PaymentCallbackDiagnostic.received_at)
            )
        ]


def _revenue(pay, client_id=None):
    w = pay.w
    response = pay.browser("owner_a").get(f"/agencies/{w.a}/clients/{client_id or w.a1}/revenue")
    assert response.status_code == 200, response.text
    return response.json()


def _egp(report):
    (total,) = [item for item in report["verified"]["totals"] if item["currency"] == "EGP"]
    return total


def test_signed_callback_is_accepted(pay):
    # T-10: a callback signed as documented is accepted and posts one confirmed sale.
    paid = sale()
    response = pay.send(paid)
    assert response.status_code == 200 and response.json() == {"status": "received"}
    (row,) = _evidence(pay.w)
    assert (row.operation_id, row.kind, row.classification) == (
        str(paid["id"]),
        "sale",
        "confirmed_capture",
    )
    assert (row.amount_minor, row.currency, row.intake) == (100_000, "EGP", "paymob")
    assert str(row.intake_id) == pay.source["id"]
    assert row.effective_at == datetime(2026, 11, 10, 9, 33, 44, 592345, tzinfo=UTC)
    assert _diagnostics(pay.w) == [("stored", None)]
    assert _egp(_revenue(pay))["net"] == "1000.00"


def test_invalid_signatures_store_nothing(pay):
    # T-10 (M): a missing signature, an altered field, a wrong secret or an unreadable body is
    # answered 401 and stores nothing.
    paid = sale()
    body, query = signed(paid)
    altered = body.replace(b'"amount_cents": 100000', b'"amount_cents": 900000', 1)
    assert altered != body
    attempts = [
        (body, {}),
        (body, {"hmac": "0" * 128}),
        (altered, query),
        (b"not json", query),
        (b"", query),
    ]
    attempts.append(signed(paid, OTHER_SECRET))
    for content, params in attempts:
        response = pay.public.post(pay.path, content=content, params=params)
        assert response.status_code == 401, content[:40]
        assert response.json() == {"error": "invalid_signature"}
    assert _evidence(pay.w) == [] and _diagnostics(pay.w) == []


def test_previous_secret_accepted_for_24_hours(pay):
    # T-11: after a replacement the previous secret is accepted for 24 hours, then refused.
    w = pay.w
    path = f"/agencies/{w.a}/clients/{w.a1}/payment-sources/{pay.source['id']}/secret"
    replaced = pay.browser("owner_a").put(path, json={"hmac_secret": OTHER_SECRET})
    assert replaced.status_code == 200 and OTHER_SECRET not in replaced.text
    assert TEST_SECRET not in replaced.text
    assert pay.send(sale(), OTHER_SECRET).status_code == 200
    assert pay.send(sale(), TEST_SECRET).status_code == 200
    with Session(w.db.migration) as session, session.begin():
        retires = session.scalars(
            select(PaymentSourceSecret.retires_at).where(PaymentSourceSecret.version == 1)
        ).one()
        assert timedelta(hours=23, minutes=59) < retires - datetime.now(UTC) <= timedelta(hours=24)
        session.execute(
            update(PaymentSourceSecret)
            .where(PaymentSourceSecret.version == 1)
            .values(retires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert pay.send(sale(), TEST_SECRET).status_code == 401
    assert pay.send(sale(), OTHER_SECRET).status_code == 200
    assert len(_evidence(w)) == 3


def test_repeated_callback_counts_once(pay):
    # T-12 (M): a repeated callback, and the parent re-sent after a refund, leave one record,
    # and the ledger counts the sale once.
    paid = sale()
    for _ in range(3):
        assert pay.send(paid).status_code == 200
    partial = refund(paid["id"], 30_000)
    assert pay.send(partial).status_code == 200
    assert pay.send(resent_parent(paid, refunded=30_000)).status_code == 200
    assert pay.send(partial).status_code == 200
    assert [row.kind for row in _evidence(pay.w)] == ["sale", "refund"]
    assert _diagnostics(pay.w) == [
        ("stored", None),
        ("duplicate", None),
        ("duplicate", None),
        ("stored", None),
        ("duplicate", None),
        ("duplicate", None),
    ]
    total = _egp(_revenue(pay))
    assert (total["captured"], total["refunded"], total["net"]) == ("1000.00", "300.00", "700.00")


def test_refund_before_sale_and_every_order(pay):
    # T-13: a refund received before its sale is pending, then posts when the sale arrives;
    # every delivery order of a sale and two refunds gives the same totals.
    first = sale()
    early = refund(first["id"], 10_000)
    assert pay.send(early).status_code == 200
    report = _revenue(pay)
    assert [(item["operation_id"], item["reason"]) for item in report["pending"]] == [
        (str(early["id"]), "parent_missing")
    ]
    assert report["verified"]["totals"] == []
    assert pay.send(first).status_code == 200
    report = _revenue(pay)
    assert report["pending"] == [] and _egp(report)["net"] == "900.00"
    nets = {}
    for order in itertools.permutations(range(3)):
        paid = sale()
        items = [paid, refund(paid["id"], 25_000), void(paid["id"], 5_000)]
        for index in order:
            assert pay.send(items[index]).status_code == 200
        nets[order] = paid["id"]
    report = _revenue(pay)
    by_id = {item["operation_id"]: item["net"] for item in report["verified"]["transactions"]}
    assert {by_id[str(identifier)] for identifier in nets.values()} == {"700.00"}
    assert report["pending"] == [] and report["reconciliation"] == []


def test_states_follow_the_mapping(pay):
    # T-14 (M: a failed or pending transaction never posts): partial refund, void of a captured
    # sale, capture of an authorization, authorization only, failed, pending and declined.
    paid = sale(amount_cents=50_000)
    held = authorization(amount_cents=40_000)
    cases = [
        (paid, ("stored", None)),
        (refund(paid["id"], 10_000), ("stored", None)),
        (void(paid["id"], 40_000), ("stored", None)),
        (held, ("not_posted", "authorization")),
        (capture(held["id"], 30_000), ("stored", None)),
        (sale(success=False), ("not_posted", "failed")),
        (sale(error_occured=True), ("not_posted", "failed")),
        (sale(pending=True), ("not_posted", "pending")),
        (sale(success=False, pending=True), ("not_posted", "failed")),
    ]
    for obj, _ in cases:
        assert pay.send(obj).status_code == 200
    assert _diagnostics(pay.w) == [expected for _, expected in cases]
    rows = _evidence(pay.w)
    assert [(row.kind, row.amount_minor, row.reason) for row in rows] == [
        ("sale", 50_000, None),
        ("refund", 10_000, None),
        ("refund", 40_000, "void"),
        ("sale", 30_000, None),
    ]
    total = _egp(_revenue(pay))
    assert (total["captured"], total["refunded"], total["net"]) == ("800.00", "500.00", "300.00")


def test_unmapped_state_is_counted_and_answered(pay):
    # T-15: unmapped states and card token callbacks post nothing, are counted and answered 200.
    for obj in (transaction(is_standalone_payment=False), sale(currency="OMR")):
        assert pay.send(obj).status_code == 200
    assert pay.send(token(), kind="TOKEN").status_code == 200
    assert _diagnostics(pay.w) == [
        ("unmapped", "unsupported_state"),
        ("unmapped", "unsupported_currency"),
        ("unmapped", "card_token"),
    ]
    assert _evidence(pay.w) == []


def test_test_mode_posts_nothing(pay):
    # A1: a callback whose is_live is not true is a test-mode transaction and posts nothing.
    paid = sale(is_live=False)
    assert pay.send(paid).status_code == 200
    assert pay.send(refund(paid["id"], 100, is_live=False)).status_code == 200
    assert _diagnostics(pay.w) == [("test_mode", None), ("test_mode", None)]
    assert _evidence(pay.w) == []


def test_no_card_or_customer_field_is_stored_logged_or_returned(pay, caplog):
    # T-16 (M): no PAN, masked PAN, brand, token, billing, shipping or customer field is stored,
    # logged or returned, and no raw payload is kept.
    caplog.set_level(logging.DEBUG)
    paid = sale()
    assert pay.send(paid).status_code == 200
    assert pay.send(refund(paid["id"], 1_000)).status_code == 200
    assert pay.send(token(), kind="TOKEN").status_code == 200
    w = pay.w
    answers = [
        pay.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/revenue").json(),
        pay.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/payment-sources").json(),
    ]
    # Every stored text value of the new tables and the audit log. Random identifiers, keys and
    # hexadecimal digests are compared with the long values only: the last four digits could
    # occur in them by chance (see the card-number rule and UUIDs).
    generated = {"delivery_id", "content_digest", "delivery_digest", "public_key"}
    with w.db.migration.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type IN ('text', 'character varying') "
                "AND table_name IN ('revenue_evidence', 'payment_callback_diagnostics', "
                "'payment_sources', 'payment_source_secrets', 'audit_events')"
            )
        ).all()
        stored = [
            (column, value)
            for table, column in columns
            for value in connection.execute(text(f"SELECT {column} FROM {table}")).scalars()
            if value is not None
        ]
        sealed = connection.execute(text("SELECT ciphertext FROM payment_source_secrets")).scalars()
        assert all(MASKED_PAN.encode() not in item for item in sealed)

    def values(item, key=""):
        if isinstance(item, dict):
            for name, value in item.items():
                yield from values(value, name)
        elif isinstance(item, list):
            for value in item:
                yield from values(value, key)
        elif item is not None:
            yield key, str(item)

    returned = [pair for answer in answers for pair in values(answer)]
    logged = [("log", record.getMessage() + str(record.__dict__)) for record in caplog.records]
    long_values = [value for value in FORBIDDEN if value != CARD_LAST_FOUR]
    for key, item in stored + returned + logged:
        for value in long_values:
            assert value not in item, (key, value)
    for key, item in stored + returned:
        if key not in generated and not key.endswith("id") and key != "callback_path":
            assert CARD_LAST_FOUR not in item, key
    for row in _evidence(w):
        assert row.source_reference == "paymob:4097558:810000001"
        assert MASKED_PAN not in (row.delivery_id + row.operation_id)


def test_response_redirect_is_never_evidence(pay):
    # T-17: the browser response redirect (GET with query parameters) is never accepted, and
    # its parameters sent without a JSON body are refused.
    paid = sale()
    body, query = signed(paid)
    redirect = {
        "id": str(paid["id"]),
        "success": "true",
        "amount_cents": "100000",
        "order": "810000001",
        **query,
    }
    assert pay.public.get(pay.path, params=redirect).status_code == 405
    assert pay.public.post(pay.path, params=redirect).status_code == 401
    assert _evidence(pay.w) == [] and _diagnostics(pay.w) == []


def test_body_bounds(pay):
    # T-18: a callback up to 64 KiB is accepted and a larger one is answered 413; every other
    # route keeps 16 KiB.
    body, query = padded(sale(), 65_536)
    assert pay.public.post(pay.path, content=body, params=query).status_code == 200
    body, query = padded(sale(), 65_537)
    response = pay.public.post(pay.path, content=body, params=query)
    assert response.status_code == 413 and response.json() == {"error": "request_too_large"}
    assert len(_evidence(pay.w)) == 1
    for path in ("/auth/login", f"/agencies/{pay.w.a}/clients/{pay.w.a1}/payment-sources"):
        assert pay.public.post(path, content=b"x" * 16_385).status_code == 413
    other = pay.public.post("/auth/login", content=b"x" * 16_000)
    assert other.status_code != 413


def test_unknown_and_disabled_sources_answer_like_invalid_signatures(pay):
    # T-19: an unknown, malformed or disabled source gets the same answer as an invalid
    # signature, so source keys cannot be enumerated.
    w = pay.w
    unknown = "/payments/paymob/callback/ppk_" + "A" * 43
    for path in (unknown, "/payments/paymob/callback/short", "/payments/paymob/callback/x" * 1):
        response = pay.send(sale(), path=path)
        assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    disabled = pay.browser("owner_a").patch(
        f"/agencies/{w.a}/clients/{w.a1}/payment-sources/{pay.source['id']}",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    response = pay.send(sale())
    assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    assert _evidence(w) == [] and _diagnostics(w) == []


def _stale(monkeypatch, rule_id, **changes):
    rules = tuple(
        dataclasses.replace(item, **changes) if item.rule_id == rule_id else item
        for item in providers.RULES
    )
    monkeypatch.setattr(providers, "RULES", rules)


def test_gate_and_rules(pay, monkeypatch):
    # T-20 (M): with the setting off, or a rule stale or past its review date, Paymob sources
    # cannot be created or re-activated and their callbacks are refused.
    w = pay.w
    off = pay.api.config.model_copy(update={"payments_paymob_enabled": False})
    assert pay.create(settings=off).status_code == 503
    closed = pay.api.new_client(off)
    response = pay.send(sale(), client=closed)
    assert (response.status_code, response.json()) == (503, {"error": "payments_unavailable"})
    for rule_id, changes in (
        ("payments.processor_records", {"status": providers.RuleStatus.STALE}),
        ("paymob.accept", {"status": providers.RuleStatus.STALE}),
        ("paymob.accept", {"review_due_at": date(2026, 1, 1)}),
    ):
        with monkeypatch.context() as patched:
            _stale(patched, rule_id, **changes)
            assert pay.create().status_code == 503, rule_id
            assert pay.send(sale()).status_code == 503, rule_id
    assert _evidence(w) == []
    source = f"/agencies/{w.a}/clients/{w.a1}/payment-sources/{pay.source['id']}"
    assert pay.browser("owner_a").patch(source, json={"status": "disabled"}).status_code == 200
    browser = pay.browser("owner_a", off)
    assert browser.patch(source, json={"status": "active"}).status_code == 503
    assert pay.browser("owner_a").patch(source, json={"status": "active"}).status_code == 200
    assert pay.send(sale()).status_code == 200


def test_rates_per_source_and_peer(pay):
    # T-21: the trusted intake rate applies per peer and per source key, known or not.
    config = pay.config.model_copy(update={"ingest_trusted_per_minute": 3})
    app = create_app(config)

    def peer(host):
        return (
            pay.api.new_client(config)
            if host is None
            else TestClient(app, base_url="http://localhost:8000", client=(host, 50000))
        )

    with peer("192.0.2.1") as first, peer("192.0.2.2") as second, peer("192.0.2.3") as third:
        for _ in range(3):
            assert pay.send(sale(), client=first).status_code == 200
        assert pay.send(sale(), client=first).status_code == 429  # peer and key exhausted
        assert pay.send(sale(), client=second).status_code == 429  # the key is exhausted
        unknown = "/payments/paymob/callback/ppk_" + "B" * 43
        for _ in range(3):
            assert pay.send(sale(), path=unknown, client=third).status_code == 401
        limited = pay.send(sale(), path=unknown, client=third)
        assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert len(_evidence(pay.w)) == 3


def test_source_routes_permissions_and_audit(pay):
    # D3, D10: Owner and Admin manage sources with audit events; the secret is sealed and never
    # returned; other roles and agencies are refused; sources are per client.
    w = pay.w
    assert TEST_SECRET not in str(pay.source) and pay.source["status"] == "active"
    assert pay.source["callback_path"].startswith("/payments/paymob/callback/ppk_")
    assert pay.create("admin").status_code == 201
    for name in ("analyst", "viewer", "owner_b"):
        assert pay.create(name).status_code == 403, name
    assert pay.create("owner_a", client_id=w.b1).status_code == 403
    listed = pay.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a1}/payment-sources")
    assert listed.status_code == 200 and len(listed.json()) == 2
    assert TEST_SECRET not in listed.text
    assert (
        pay.browser("analyst").get(f"/agencies/{w.a}/clients/{w.a1}/payment-sources").status_code
        == 403
    )
    other = pay.browser("owner_a").get(f"/agencies/{w.a}/clients/{w.a2}/payment-sources")
    assert other.json() == []
    invalid = pay.create(secret="short")
    assert invalid.status_code == 422 and "short" not in invalid.text
    base = f"/agencies/{w.a}/clients/{w.a1}/payment-sources/{pay.source['id']}"
    assert (
        pay.browser("owner_a").put(base + "/secret", json={"hmac_secret": OTHER_SECRET}).status_code
        == 200
    )
    assert pay.browser("owner_a").patch(base, json={"name": "Renamed"}).json()["name"] == "Renamed"
    with Session(w.db.migration) as session:
        actions = sorted(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.resource_type == "payment_source")
            )
        )
        sealed = session.scalars(select(PaymentSourceSecret.ciphertext)).all()
        keys = session.scalars(select(PaymentSource.public_key)).all()
    assert actions == [
        "payment_source.created",
        "payment_source.created",
        "payment_source.secret_replaced",
        "payment_source.updated",
    ]
    assert len(sealed) == 3 and all(TEST_SECRET.encode() not in item for item in sealed)
    assert len(set(keys)) == 2


def test_lifecycle_deletes_diagnostics_and_retired_secrets(
    pay, lifecycle_engine, lifecycle_settings
):
    # D14: diagnostics 30 days after receipt; replaced secrets once retired.
    w = pay.w
    assert pay.send(sale()).status_code == 200
    assert pay.send(sale()).status_code == 200
    path = f"/agencies/{w.a}/clients/{w.a1}/payment-sources/{pay.source['id']}/secret"
    assert pay.browser("owner_a").put(path, json={"hmac_secret": OTHER_SECRET}).status_code == 200
    now = datetime.now(UTC)
    with Session(w.db.migration) as session, session.begin():
        first = session.scalars(select(PaymentCallbackDiagnostic.id)).first()
        session.execute(
            update(PaymentCallbackDiagnostic)
            .where(PaymentCallbackDiagnostic.id == first)
            .values(received_at=now - timedelta(days=31))
        )
        session.execute(
            update(PaymentSourceSecret)
            .where(PaymentSourceSecret.version == 1)
            .values(retires_at=now - timedelta(minutes=1))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed"
    assert result["deleted"]["payment_callback_diagnostics"] == 1
    assert result["deleted"]["payment_source_secrets"] == 1
    with Session(w.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(PaymentCallbackDiagnostic)) == 1
        assert session.scalars(select(PaymentSourceSecret.version)).all() == [2]
        assert session.scalar(select(func.count()).select_from(RevenueEvidence)) == 2
    assert pay.send(sale(), OTHER_SECRET).status_code == 200
    assert next_id() > 0


def test_unreadable_bodies_and_a_missing_keyring_reveal_nothing(pay):
    # T-19: a deeply nested body gets the same 401 as any unverifiable callback, and without the
    # token keyring known and unknown keys alike answer 503 before any source lookup.
    nested = b'{"type": "TRANSACTION", "obj": ' + b"[" * 30_000 + b"]" * 30_000 + b"}"
    response = pay.public.post(pay.path, content=nested, params={"hmac": "ab" * 64})
    assert (response.status_code, response.json()) == (401, {"error": "invalid_signature"})
    unkeyed = pay.config.model_copy(
        update={"token_keyring": SecretStr(""), "token_keyring_active": ""}
    )
    client = pay.api.new_client(unkeyed)
    unknown = "/payments/paymob/callback/ppk_" + "C" * 43
    for path in (pay.path, unknown):
        response = pay.send(sale(), path=path, client=client)
        assert (response.status_code, response.json()) == (
            503,
            {"error": "collection_not_configured"},
        )
    assert _evidence(pay.w) == [] and _diagnostics(pay.w) == []
