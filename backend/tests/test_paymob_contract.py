"""Paymob verification, minimization and mapping without a database (specification 015-B).

D-067 decisions D4 to D7 with amendment A1. The documented example of the HMAC transaction
callback page (read 2026-11-21) fixes the concatenated string; the synthetic sender of
tests/paymob_callbacks.py signs every other case. No case opens a network connection.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from paymob_callbacks import (
    FORBIDDEN,
    OTHER_SECRET,
    TEST_SECRET,
    authorization,
    capture,
    refund,
    resent_parent,
    sale,
    signed,
    token,
    transaction,
    void,
)

from app.ledger import EvidenceClass, OperationKind
from app.payments.paymob import (
    TRANSACTION_FIELDS,
    Unverifiable,
    effective_time,
    map_transaction,
    minimize,
    signed_string,
    verify,
)
from app.privacy import providers
from app.services.payments import paymob_allowed


def _documented_sample():
    # The values of Paymob's documented processed-callback sample that enter the signature.
    return {
        "amount_cents": 100000,
        "created_at": "2024-06-13T11:33:44.592345",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 192036465,
        "integration_id": 4097558,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": 217503754},
        "owner": 302852,
        "pending": False,
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
        "success": True,
    }


def test_documented_hmac_string():
    # T-10: the documented field order and formatting reproduce the documented example string.
    assert signed_string(_documented_sample(), TRANSACTION_FIELDS) == (
        "1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalsetrue"
        "false217503754302852false2346MasterCardcardtrue"
    )


def test_verify_accepts_current_and_previous_secrets_only():
    body, query = signed(sale())
    assert verify(body, query["hmac"], [TEST_SECRET]).kind == "TRANSACTION"
    assert verify(body, query["hmac"].upper(), [OTHER_SECRET, TEST_SECRET]).kind == "TRANSACTION"
    for secrets in ([OTHER_SECRET], []):
        with pytest.raises(Unverifiable):
            verify(body, query["hmac"], secrets)
    for received in (None, "", "ab" * 63, "zz" * 64):
        with pytest.raises(Unverifiable):
            verify(body, received, [TEST_SECRET])


def test_verify_refuses_altered_fields_and_unsupported_bodies():
    obj = sale()
    body, query = signed(obj)
    for field, value in (("amount_cents", 1), ("success", False), ("currency", "USD")):
        altered = dict(obj, **{field: value})
        with pytest.raises(Unverifiable):
            verify(signed(altered)[0], query["hmac"], [TEST_SECRET])
    for raw in (b"", b"[]", b'{"type": "TRANSACTION"}', b'{"type": "OTHER", "obj": {}}', b"\xff"):
        with pytest.raises(Unverifiable):
            verify(raw, query["hmac"], [TEST_SECRET])
    missing = dict(obj)
    del missing["owner"]
    with pytest.raises(Unverifiable):
        verify(signed(missing)[0], query["hmac"], [TEST_SECRET])
    floating = json.dumps({"type": "TRANSACTION", "obj": dict(obj, amount_cents=100000.0)})
    with pytest.raises(Unverifiable):
        verify(floating.encode(), query["hmac"], [TEST_SECRET])


def test_card_token_callback_is_verified_and_carries_nothing():
    body, query = signed(token(), kind="TOKEN")
    result = verify(body, query["hmac"], [TEST_SECRET])
    assert result.kind == "TOKEN" and result.transaction is None
    assert not any(value in repr(result) for value in FORBIDDEN)


def test_minimize_keeps_only_allowed_fields():
    # T-16: nothing of the card, billing, shipping, customer, items or token survives.
    kept = minimize(sale())
    assert set(kept) == {
        "id",
        "amount_cents",
        "currency",
        "created_at",
        "success",
        "pending",
        "error_occured",
        "is_auth",
        "is_capture",
        "is_standalone_payment",
        "has_parent_transaction",
        "is_refund",
        "is_void",
        "is_live",
        "parent_transaction",
        "integration_id",
        "order_id",
    }
    assert not any(value in repr(kept) for value in FORBIDDEN)


def _map(obj):
    return map_transaction(minimize(obj), "egypt")


def test_mapping_table():
    # T-14 (M) and A1: each state follows D5.
    paid = sale(id=1001)
    posted = _map(paid)
    assert posted.outcome == "stored" and posted.posting is not None
    assert posted.posting.kind is OperationKind.SALE
    assert posted.posting.classification is EvidenceClass.CONFIRMED_CAPTURE
    assert posted.posting.operation_id == "1001" and posted.posting.amount.minor == 100_000
    assert posted.posting.source_account_id == "paymob-egypt"
    assert posted.posting.source_reference == "paymob:4097558:810000001"
    captured = _map(capture(1002, 40_000, id=1003))
    assert captured.posting.kind is OperationKind.SALE and captured.posting.operation_id == "1003"
    partial = _map(refund(1001, 25_000, id=1004)).posting
    assert partial.kind is OperationKind.REFUND and partial.parent_operation_id == "1001"
    assert partial.classification is EvidenceClass.CONFIRMED_ADJUSTMENT and partial.reason is None
    voided = _map(void(1001, 100_000, id=1005)).posting
    assert voided.kind is OperationKind.REFUND and voided.reason == "void"
    assert (_map(authorization()).outcome, _map(authorization()).reason) == (
        "not_posted",
        "authorization",
    )
    assert _map(sale(success=False)).reason == "failed"
    assert _map(sale(error_occured=True)).reason == "failed"
    assert _map(sale(pending=True)).reason == "pending"
    assert _map(sale(is_live=False)).outcome == "test_mode"
    assert _map(refund(1001, 10, is_live=False)).outcome == "test_mode"


@pytest.mark.parametrize(
    ("obj", "reason"),
    [
        (transaction(is_standalone_payment=False), "unsupported_state"),
        (transaction(is_refund=True), "unsupported_state"),  # a refund flag without a parent
        (refund(1001, 10, is_void=True), "unsupported_state"),  # both refund and void
        (transaction(parent=1001, is_standalone_payment=False), "unsupported_state"),
        (refund(1001, 10, is_capture=True), "unsupported_state"),
        (refund(0, 10), "invalid_parent"),
        (sale(amount_cents=0), "invalid_amount"),
        (sale(currency="OMR"), "unsupported_currency"),
        (sale(currency="JPY"), "unsupported_currency"),
        (sale(created_at="yesterday"), "invalid_time"),
    ],
)
def test_unmapped_states(obj, reason):
    # T-15: a state the rules do not cover posts nothing and is counted, never guessed.
    mapped = _map(obj)
    assert (mapped.outcome, mapped.reason, mapped.posting) == ("unmapped", reason, None)


def test_refund_parent_must_differ_from_operation():
    assert _map(refund(2001, 10, id=2001)).reason == "invalid_parent"


def test_parent_resent_after_refund_or_void_repeats_its_delivery():
    # V-4: the parent's re-sent callback maps to the same sale and delivery ID.
    paid = sale(id=3001)
    first = _map(paid).posting
    assert _map(resent_parent(paid, refunded=25_000)).posting == first
    assert _map(resent_parent(paid, voided=True)).posting == first
    changed = _map(dict(paid, amount_cents=90_000)).posting
    assert changed.operation_id == first.operation_id
    assert changed.delivery_id != first.delivery_id


def test_effective_time_uses_offset_or_cairo_local_time():
    # V-7: no offset means Cairo local time (UTC+3 under summer time, UTC+2 in winter).
    assert effective_time("2024-06-13T11:33:44.592345", "egypt") == datetime(
        2024, 6, 13, 8, 33, 44, 592345, tzinfo=UTC
    )
    assert effective_time("2026-11-10T11:33:44", "egypt") == datetime(
        2026, 11, 10, 9, 33, 44, tzinfo=UTC
    )
    assert effective_time("2024-06-25T15:16:25.910710+04:00", "egypt") == datetime(
        2024, 6, 25, 11, 16, 25, 910710, tzinfo=UTC
    )
    # The repeated hour at the end of Cairo summer time resolves to its first occurrence.
    assert effective_time("2026-10-29T23:30:00", "egypt") == datetime(
        2026, 10, 29, 20, 30, tzinfo=UTC
    )
    for value in (None, 1, "", "not a time", "2026-13-01T00:00:00"):
        assert effective_time(value, "egypt") is None


def test_rules_gate(settings, monkeypatch):
    # T-20 (M), D12: the Paymob source type is off by default and needs both current rules.
    today = date(2026, 11, 21)
    assert settings.payments_paymob_enabled is False
    assert not paymob_allowed(settings, today)
    enabled = settings.model_copy(update={"payments_paymob_enabled": True})
    assert paymob_allowed(enabled, today)
    assert paymob_allowed(enabled, date(2027, 11, 21))
    assert not paymob_allowed(enabled, date(2027, 11, 22))  # past the review date
    for rule_id in ("payments.processor_records", "paymob.accept"):
        stale = tuple(
            replace(item, status=providers.RuleStatus.STALE) if item.rule_id == rule_id else item
            for item in providers.RULES
        )
        with monkeypatch.context() as patched:
            patched.setattr(providers, "RULES", stale)
            assert not paymob_allowed(enabled, today), rule_id
    for rule_id in ("payments.processor_records", "paymob.accept"):
        item = providers.rule(rule_id)
        assert item.status is providers.RuleStatus.CURRENT and item.data_class == "revenue.evidence"
        assert (item.verified_at, item.review_due_at) == (today, date(2027, 11, 21))
